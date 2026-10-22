"""Remove local tuning caps while retaining the chosen hardware and model assets."""
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / 'records/custom-limits-removal-20261017/before/profiles'


def official_defaults(profile, context):
    profile = copy.deepcopy(profile)
    args = profile['args']
    for flag in ('--resident-budget-gib', '--prefill', '--kv'):
        if flag in args:
            index = args.index(flag)
            del args[index:index + 2]
    if '--resident-experts' not in args:
        args.append('--resident-experts')
    args.extend(['--prefill', 'auto'])
    # setup.py leaves the engine's fp16 default at <=8K, selects int8 above it.
    if context > 8192:
        args.extend(['--kv', 'int8'])
    profile.pop('reasoning_effort', None)
    return profile


def serialize(profile):
    return (json.dumps(profile, indent=2) + '\n').encode('utf-8')


def approved_hashes(source, original_sha):
    """Accept the original receipt or exactly its reviewed defaults transform.

    The archived original must match the immutable historical baseline first.
    This does not turn an edited profile or an arbitrary new SHA into authority.
    """
    allowed = {original_sha}
    archived = ARCHIVE / Path(source).name
    if Path(source).parent.resolve() == (ROOT / 'profiles').resolve() and archived.is_file():
        content = archived.read_bytes()
        if hashlib.sha256(content).hexdigest() != original_sha:
            raise RuntimeError('Archived original profile differs from its historical receipt.')
        context = int(Path(source).stem.rsplit('-', 1)[1])
        candidate = official_defaults(json.loads(content.decode('utf-8-sig')), context)
        allowed.add(hashlib.sha256(serialize(candidate)).hexdigest())
    return allowed
