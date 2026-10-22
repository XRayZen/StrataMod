"""Independent literal policy model; no model/GPU imports or output-derived Q."""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Key:
    asset: str
    bundle: str
    epoch: int
    context: int
    mode: str
    primary: str
    secondary: str | None
    assignment: tuple
    cut: int | None
    math: str


def decide(*, processed, mask, prompt, incoming_mask, previous, incoming,
           position, valid, logits, full_logits, reset):
    for ids in [processed, prompt]:
        if any(type(x) is not int or not 0 <= x < 129280 for x in ids):
            raise ValueError('original token domain')
    if len(mask) != len(processed) or len(incoming_mask) != len(prompt):
        raise ValueError('explicit mask geometry')
    if any(type(x) is not int or x not in [0, 1] for x in mask + incoming_mask):
        raise ValueError('mask domain')
    if type(position) is not int or position < 0:
        raise ValueError('cursor domain')
    if not (0 < incoming.epoch < 2**64 and 0 < incoming.context <= 1048576):
        raise ValueError('request capacity/epoch')
    if len(prompt) > incoming.context:
        raise ValueError('prompt capacity')
    n = len(processed)
    eligible = (valid and logits and not full_logits and not reset and n > 0
                and position == n and previous == incoming and incoming.math == 'canonical'
                and len(prompt) >= n and prompt[:n] == processed
                and incoming_mask[:n] == mask)
    if not eligible:
        return 'fresh', 0
    return ('logits' if len(prompt) == n else 'append'), n
