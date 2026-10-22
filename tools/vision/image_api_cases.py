"""Fixed image requests and pure scoring; runtime owns HTTP, raw files and recovery.

Protocol terminal, natural completion and semantic correctness are separate.
Usage/timings are server reports, not proof of native work or request ownership.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math

PROMPT = ('画像を観察し、人物の人数、髪の色、上着の色、室内の種類、人物が手や腕を触れさせている家具とその画像内の位置を、'
          'people/hair/top/scene/object/positionを持つ短いJSONで答えてください。'
          '位置は人物の身体の左右ではなく画像内の大まかな領域で表してください。'
          'JSON以外は出力せず、peopleは整数、他は短い文字列にしてください。')


def fixed_cases(image_base64, model, max_tokens=128, image_mime='image/png'):
    """Build exactly three cases from original PNG/JPEG bytes, without IO."""
    if type(max_tokens) is not int or max_tokens != 128:
        raise ValueError('This fixed phase requires max_tokens=128')
    if not isinstance(model, str) or not model.strip():
        raise ValueError('A model ID is required')
    try:
        image = base64.b64decode(image_base64, validate=True)
    except (ValueError, TypeError, binascii.Error):
        raise ValueError('Expected base64 image bytes') from None
    signatures = {'image/png': b'\x89PNG\r\n\x1a\n', 'image/jpeg': b'\xff\xd8\xff'}
    if image_mime not in signatures or not image.startswith(signatures[image_mime]):
        raise ValueError('PNG/JPEG MIME and image signature must agree')
    image_sha256 = hashlib.sha256(image).hexdigest()
    encoded = base64.b64encode(image).decode('ascii')
    url = 'data:' + image_mime + ';base64,' + encoded
    common = dict(model=model, stream=True, temperature=0, seed=42, top_k=1, top_p=1, min_p=0)
    images = [dict(type='image_url', image_url=dict(url=url)),
              dict(type='image', source=dict(type='base64', media_type=image_mime, data=encoded)),
              dict(type='input_image', image_url=url)]
    cases = []
    for api, pathname, image in zip(('openai', 'anthropic', 'responses'),
                                  ('/v1/chat/completions', '/v1/messages', '/v1/responses'), images):
        body = dict(common)
        content = [dict(type='input_text' if api == 'responses' else 'text', text=PROMPT), image]
        if api == 'responses':
            body.update(input=[dict(role='user', content=content)], max_output_tokens=128,
                        reasoning=dict(effort='none'))
        else:
            body.update(messages=[dict(role='user', content=content)], max_tokens=128)
            if api == 'anthropic':
                body['thinking'] = dict(type='disabled')
            else:
                body['reasoning_effort'] = 'none'
        cases.append(dict(api=api, pathname=pathname, body=body, image_sha256=image_sha256))
    return cases


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _json(text):
    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('nonfinite JSON')
        return number
    return json.loads(text, object_pairs_hook=_unique,
                      parse_float=finite,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def _frames(raw):
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8', errors='strict')
    if not isinstance(raw, str):
        raise ValueError('Expected complete raw SSE body as str or bytes')
    raw = raw.replace('\r\n', '\n').replace('\r', '\n')
    # An incomplete frame, even one whose JSON is parseable, is not dispatched.
    parts = raw.split('\n\n')
    tail = parts.pop()
    if tail.strip() and any(not line.startswith(':') for line in tail.split('\n') if line):
        raise ValueError('truncated SSE frame')
    for part in parts:
        name, data = None, []
        for line in part.split('\n'):
            if not line or line.startswith(':'):
                continue
            key, _, value = line.partition(':')
            value = value[1:] if value.startswith(' ') else value
            if key == 'event':
                if name is not None:
                    raise ValueError('duplicate SSE event field')
                name = value
            elif key == 'data':
                data.append(value)
            elif key not in ('id', 'retry'):
                raise ValueError('unexpected SSE field')
        if data:
            yield name, '\n'.join(data)


def parse_sse(api, raw_events):
    """Parse one complete wire body; never infer tokens from text or expected input.

    normal_terminal includes an explicit token-limit terminal. completed is true
    only for natural completion. Neither field certifies transport/owner/cleanup.
    usage_sources identifies the zero-based *data event* index of each report.
    """
    if api not in ('openai', 'anthropic', 'responses'):
        raise ValueError('Unknown image API')
    result = dict(text='', usage=None, usage_sources=[], output_tokens=None, timings=None,
                  finish_reason=None, terminal=False, normal_terminal=False, completed=False, errors=[])
    pieces, start, finish, blocks = [], False, None, set()

    def usage(value, index, output_key, final=False):
        if not isinstance(value, dict) or any(type(v) is not int or v < 0 for v in value.values()
                                             if not isinstance(v, dict)):
            raise ValueError('invalid usage report')
        result['usage_sources'].append(dict(event_index=index, usage=value))
        result['usage'] = dict(result['usage'] or {}, **value)
        # Anthropic message_start's output_tokens=0 is provisional, not final.
        if final and output_key in value:
            if type(value[output_key]) is not int or value[output_key] < 0:
                raise ValueError('invalid output token count')
            result['output_tokens'] = value[output_key]

    try:
        for index, (name, data) in enumerate(_frames(raw_events)):
            if result['terminal']:
                raise ValueError('event after terminal')
            if data == '[DONE]':
                if api != 'openai' or finish is None:
                    raise ValueError('unexpected DONE marker')
                result['terminal'] = True
                continue
            event = _json(data)
            if not isinstance(event, dict) or event.get('error'):
                raise ValueError('invalid event or server error')
            kind = event.get('type')
            if api != 'openai' and (not isinstance(kind, str) or name != kind):
                raise ValueError('SSE event/type mismatch')
            if api == 'openai':
                if finish is not None:
                    raise ValueError('event after finish')
                choices = event['choices']
                if not isinstance(choices, list) or len(choices) != 1:
                    raise ValueError('expected one choice')
                choice = choices[0]
                if choice.get('index', 0) != 0:
                    raise ValueError('unexpected choice index')
                delta = choice['delta']
                text = delta.get('content')
                if text is not None:
                    if not isinstance(text, str):
                        raise ValueError('invalid text delta')
                    pieces.append(text)
                if choice.get('finish_reason') is not None:
                    finish = choice['finish_reason']
                if 'usage' in event:
                    usage(event['usage'], index, 'completion_tokens', final=finish is not None)
                if 'timings' in event:
                    if not isinstance(event['timings'], dict):
                        raise ValueError('invalid timings report')
                    result['timings'] = event['timings']
            elif api == 'anthropic':
                if kind == 'message_start':
                    if start or finish is not None:
                        raise ValueError('duplicate message start')
                    start = True
                    if 'usage' in event['message']:
                        usage(event['message']['usage'], index, 'output_tokens')
                elif not start:
                    raise ValueError('message start missing')
                elif kind == 'content_block_start':
                    if finish is not None or event['index'] in blocks:
                        raise ValueError('invalid block start')
                    blocks.add(event['index'])
                    block = event['content_block']
                    if block['type'] == 'text' and block.get('text'):
                        pieces.append(block['text'])
                elif kind == 'content_block_delta':
                    if finish is not None or event['index'] not in blocks:
                        raise ValueError('delta outside open block')
                    delta = event['delta']
                    if delta['type'] == 'text_delta':
                        pieces.append(delta['text'])
                elif kind == 'content_block_stop':
                    blocks.remove(event['index'])
                elif kind == 'message_delta':
                    if finish is not None or blocks:
                        raise ValueError('invalid message finish')
                    finish = event['delta']['stop_reason']
                    if 'usage' in event:
                        usage(event['usage'], index, 'output_tokens', final=True)
                elif kind == 'message_stop':
                    if finish is None or blocks:
                        raise ValueError('message finish missing')
                    result['terminal'] = True
                elif kind != 'ping':
                    raise ValueError('unexpected Anthropic event')
            else:
                if kind == 'response.created':
                    if start:
                        raise ValueError('duplicate response start')
                    start = True
                elif not start:
                    raise ValueError('response start missing')
                elif kind == 'response.output_text.delta':
                    pieces.append(event['delta'])
                elif kind in ('response.completed', 'response.incomplete', 'response.failed'):
                    response = event['response']
                    status = kind.rsplit('.', 1)[1]
                    if response.get('status') != status:
                        raise ValueError('response status mismatch')
                    result['terminal'] = True
                    if response.get('error') or status == 'failed':
                        raise ValueError('response failed')
                    if status == 'incomplete' and (response.get('incomplete_details') or {}).get('reason') != 'max_output_tokens':
                        raise ValueError('unexpected incomplete reason')
                    finish = 'stop' if status == 'completed' else 'length'
                    if response.get('usage') is not None:
                        usage(response['usage'], index, 'output_tokens', final=True)
                elif kind not in ('response.in_progress', 'response.output_item.added', 'response.output_item.done',
                                   'response.content_part.added', 'response.content_part.done', 'response.output_text.done',
                                   'response.reasoning_text.delta', 'response.reasoning_text.done'):
                    raise ValueError('unexpected Responses event')
        if not result['terminal']:
            raise ValueError('terminal marker missing')
        allowed = ('end_turn', 'max_tokens') if api == 'anthropic' else ('stop', 'length')
        if finish not in allowed:
            raise ValueError('unexpected finish reason')
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, UnicodeError) as error:
        result['errors'].append(str(error))
    if not all(isinstance(piece, str) for piece in pieces):
        result['errors'].append('invalid text delta')
    else:
        result['text'] = ''.join(pieces)
    result['finish_reason'] = {'end_turn': 'stop', 'max_tokens': 'length'}.get(finish, finish)
    result['normal_terminal'] = result['terminal'] and not result['errors']
    result['completed'] = result['normal_terminal'] and result['finish_reason'] == 'stop'
    return result


def score_known_answer(text, expected):
    """Score the five required RefImage facts against a pre-bound finite rubric.

    Hair is auxiliary only. Exact normalized phrase membership rejects unknown,
    negated or contradictory required facts; no free-text judge or inference.
    """
    keys = ('people', 'top', 'scene', 'object', 'position')
    items = dict.fromkeys(keys, False)
    auxiliary = dict(hair=dict(matched=False, observed=None))
    try:
        actual = _json(text)
        if not isinstance(actual, dict) or set(actual) != {*keys, 'hair'}:
            raise ValueError('expected exactly six observation keys')
        def norm(value):
            if not isinstance(value, str) or not value.strip():
                raise ValueError('observation must be nonempty text')
            return ' '.join(value.lower().replace('-', ' ').split())
        items['people'] = type(actual['people']) is int and actual['people'] == expected['people']
        for key in (*keys[1:], 'hair'):
            if not isinstance(expected[key], list) or not expected[key]:
                raise ValueError('finite accepted phrases are required')
            matched = norm(actual[key]) in {norm(value) for value in expected[key]}
            if key == 'hair':
                auxiliary['hair'] = dict(matched=matched, observed=actual[key])
            else:
                items[key] = matched
    except (ValueError, TypeError, KeyError, AttributeError):
        return dict(passed=False, items=items, auxiliary=auxiliary, error='invalid observation JSON or rubric')
    return dict(passed=all(items.values()), items=items, auxiliary=auxiliary, observed=actual)
