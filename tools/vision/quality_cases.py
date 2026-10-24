"""The fixed R9700 80-case quality set. Materializing/scoring never spawns.

Runtime owns API calls, late tool-call IDs, CPU worker launch/deadline/Job/cohort.
The --code-check mode processes one case's four small vectors, then exits.
"""
from __future__ import annotations

import ast
import copy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
DIALECT = 'https://json-schema.org/draft/2020-12/schema'
GROUPS = dict(japanese=20, strict_json=20, tool=10, stream=5, cancel=5, code=10, long_recall=10)


def object_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON key: ' + key)
        value[key] = item
    return value


def _json(text, *, exact_numbers=False):
    return json.loads(text, object_pairs_hook=_unique,
                      parse_float=Decimal if exact_numbers else float,
                      parse_constant=lambda s: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def _same(actual, expected, *, json_numbers=False):
    if json_numbers and type(actual) in (int, float, Decimal) and type(expected) in (int, float, Decimal):
        actual, expected = Decimal(str(actual)), Decimal(str(expected))
        return actual.is_finite() and expected.is_finite() and actual == expected
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(_same(actual[k], v, json_numbers=json_numbers)
                                                       for k, v in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(_same(a, b, json_numbers=json_numbers)
                                                   for a, b in zip(actual, expected))
    return actual == expected


def _load_tokenizer(directory):
    from tools.strata_tokenizer import Tokenizer
    from serve.frontend import ChatTemplate
    directory = Path(directory)
    vocab = _json((directory / 'vocab.json').read_text(encoding='utf-8'))
    tokens = [None] * len(vocab)
    for token, index in vocab.items():
        tokens[index] = token
    return (Tokenizer(tokens, (directory / 'merges.txt').read_text(encoding='utf-8').split('\n'),
                      _json((directory / 'token_type.json').read_text(encoding='utf-8'))),
            ChatTemplate(directory / 'chat_template.jinja'))


def _render(payload, tokenizer, template):
    from serve.frontend import openai_to_messages, forced_call
    messages, tools, kwargs = openai_to_messages(payload)
    rendered = template.render(messages, tools=tools, **kwargs)
    ids = tokenizer.encode(rendered, parse_special=True)
    force = forced_call(payload.get('tool_choice'), tools)
    if force and kwargs.get('enable_thinking', True) is False:
        rendered += force
        ids += tokenizer.encode(force, parse_special=True)
    return rendered, ids


def _payload(prompt, cap, stream=False):
    return dict(model='huihui-ud-iq4_xs', messages=[dict(role='user', content=prompt)],
                max_tokens=cap, stream=stream, seed=42, temperature=0, top_k=1, top_p=1,
                min_p=0, reasoning_effort='none')


def _fill(target, measure, unit, tokenizer):
    """Finite adjustment using the tokenizer's single-digit pre-tokenization."""
    empty = measure('')
    if empty > target:
        raise ValueError('Fixed long template exceeds its target')
    size = max(1, len(tokenizer.encode(unit)))
    units = max(0, (target - empty) // size)
    for _ in range(8):
        text = unit * units
        count = measure(text)
        if count > target:
            units = max(0, units - max(1, (count - target + size - 1) // size))
            continue
        padding = target - count
        for _ in range(4):
            padded = text + '0' * padding
            measured = measure(padded)
            if measured == target:
                return padded
            padding += target - measured
            if padding < 0:
                break
        units = max(0, units - 1)
    raise ValueError('Fixed long input could not reach its exact target')


def _long_payload(case, tokenizer, template):
    body = case['body']
    target = body['target_rendered_input_tokens']
    position = body['fact_token_position_target']
    wanted = target * position['numerator'] // position['denominator']
    def make(before='', after=''):
        return _payload(body['template'].format(filler_before=before, fact=body['fact'],
                                               filler_after=after), case['max_tokens_per_post'])
    def offset(before):
        rendered, _ = _render(make(before), tokenizer, template)
        return len(tokenizer.encode(rendered[:rendered.index(body['fact'])], parse_special=True))
    before = _fill(wanted, offset, body['filler_unit'], tokenizer)
    after = _fill(target, lambda text: len(_render(make(before, text), tokenizer, template)[1]),
                  body['filler_unit'], tokenizer)
    payload = make(before, after)
    rendered, ids = _render(payload, tokenizer, template)
    prefix = tokenizer.encode(rendered[:rendered.index(body['fact'])], parse_special=True)
    if len(ids) != target or len(prefix) != wanted or ids[:wanted] != prefix:
        raise ValueError('Long input/fact token boundary mismatch')
    return payload, wanted


def _turn(payload, tokenizer, template, *, pending_id=False):
    _, ids = _render(payload, tokenizer, template)
    if len(ids) + payload['max_tokens'] > 262144:
        raise ValueError('Quality input exceeds fixed context')
    return dict(endpoint='/v1/chat/completions', body=payload, input_tokens=len(ids), token_ids=ids,
                token_sha256=hashlib.sha256(json.dumps(ids, separators=(',', ':')).encode('ascii')).hexdigest(),
                payload_sha256=None if pending_id else object_sha(payload),
                payload_template_sha256=object_sha(payload),
                wire_bindings_pending=['returned_tool_call_id'] if pending_id else [])


def materialize_cases(draft_path, tokenizer_dir, output_dir, *, image_receipt=None):
    output = Path(output_dir)
    if not output.is_absolute() or not output.resolve().is_relative_to(ROOT) or output.resolve() != output.absolute():
        raise ValueError('Quality output must stay in StrataMod without links')
    value = _json(Path(draft_path).read_text(encoding='utf-8'))
    if value.get('json_schema_dialect') != DIALECT:
        raise ValueError('Fixed JSON schema dialect mismatch')
    cases = value['cases']
    if len(cases) != 80 or len({c['id'] for c in cases}) != 80:
        raise ValueError('Fixed 80 unique cases required')
    counts = {group: sum(c['group'] == group for c in cases) for group in GROUPS}
    if counts != GROUPS or sum(c['max_posts'] for c in cases) != 100:
        raise ValueError('Quality case/post inventory changed')
    for case in cases:
        checked = dict(case); expected = checked.pop('case_spec_sha256')
        if object_sha(checked) != expected:
            raise ValueError('Quality case hash changed: ' + case['id'])
    tokenizer, template = _load_tokenizer(tokenizer_dir)
    result = []
    for original in cases:
        case = copy.deepcopy(original)
        body, group, cap = case['body'], case['group'], case['max_tokens_per_post']
        if group == 'long_recall':
            first, case['fact_token_position'] = _long_payload(case, tokenizer, template)
        else:
            first = _payload(body.get('prompt', body.get('first_prompt')), cap,
                             group in ('stream', 'cancel'))
        if group == 'tool':
            first.update(tools=[body['tool_definition']], tool_choice=body['tool_choice'])
        case['turns'] = [_turn(first, tokenizer, template)]
        if case['max_posts'] == 2:
            second = _payload(body.get('second_prompt', body.get('continuation_prompt')), cap,
                              body.get('second_stream', False))
            if group == 'tool':
                call = case['scoring']['first']
                second['messages'] = first['messages'] + [
                    dict(role='assistant', content=None, tool_calls=[dict(id='${returned_tool_call_id}', type='function',
                         function=dict(name=call['tool_name'], arguments=json.dumps(call['arguments'], ensure_ascii=False)))]),
                    dict(role='tool', tool_call_id='${returned_tool_call_id}',
                         content=json.dumps(body['fixed_tool_result'], ensure_ascii=False)),
                    second['messages'][0]]
            elif group == 'stream':
                second['messages'] = first['messages'] + [dict(role='assistant', content=case['scoring']['first']['expected']),
                                                         second['messages'][0]]
            case['turns'].append(_turn(second, tokenizer, template, pending_id=group == 'tool'))
        case['readiness'] = 'materialized; tool follow-up ID must be bound and wire hash recorded before POST2' if group == 'tool' else 'materialized'
        result.append(case)
    output.mkdir(parents=True, exist_ok=False)
    path = output / 'quality-cases.json'
    ready = dict(version=1, json_schema_dialect=DIALECT, draft_sha256=hashlib.sha256(Path(draft_path).read_bytes()).hexdigest(),
                 source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), cases=result,
                 tokenizer_files={name: hashlib.sha256((Path(tokenizer_dir) / name).read_bytes()).hexdigest()
                                  if (Path(tokenizer_dir) / name).is_file() else None
                                  for name in ('vocab.json', 'merges.txt', 'token_type.json', 'chat_template.jinja')},
                 max_posts=100, max_cpu_code_starts=10, vectors_per_code_worker=4,
                 image_dependent_inputs='pending until actual image receipt; these 80 cases are text-only',
                 image_receipt_sha256=None if image_receipt is None else object_sha(image_receipt))
    path.write_text(json.dumps(ready, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    return path


def _evidence(response, expected_input, cap):
    """Only actual response/native facts normalized by runtime; never expected copies."""
    if not isinstance(response.get('usage'), dict) or not isinstance(response.get('timings'), dict):
        return False
    usage, timings = response['usage'], response['timings']
    return (type(expected_input) is int and expected_input > 0
            and type(usage.get('prompt_tokens')) is int and usage['prompt_tokens'] == expected_input
            and type(cap) is int and cap > 0
            and type(usage.get('completion_tokens')) is int and 0 < usage['completion_tokens'] <= cap
            and type(timings.get('prompt_n')) is int and type(timings.get('predicted_n')) is int
            and timings.get('prompt_n') == usage['prompt_tokens']
            and timings.get('predicted_n') == usage['completion_tokens']
            and all(type(x) not in (float, int) or math.isfinite(x) for x in timings.values()))


def _cancel_input(proof, expected_input):
    # Runtime associates one new /metrics history row with the owned request.
    # prompt_tokens/prompt_total can fall back to len(ids); only native read+reuse count.
    evidence = proof.get('native_input_evidence')
    if not isinstance(evidence, dict) or not isinstance(evidence.get('history_row'), dict):
        return False
    row = evidence['history_row']
    read, reused = evidence.get('prompt_read'), evidence.get('reused')
    started, at = evidence.get('request_started_at'), row.get('time')
    return (evidence.get('source') == 'metrics.requests.prompt_read+reused'
            and evidence.get('owner_verified') is True
            and type(expected_input) is int and expected_input > 0
            and type(read) is int and read >= 0 and type(reused) is int and reused >= 0
            and type(row.get('prompt_read')) is int and row['prompt_read'] == read
            and type(row.get('reused')) is int and row['reused'] == reused
            and read + reused == expected_input and row.get('finish') in ('cancel', 'disconnect')
            and type(started) in (float, int) and math.isfinite(started) and started > 0
            and type(at) in (float, int) and math.isfinite(at) and at >= started)


def score_case(case, response):
    """Score one normalized request; runtime combines both turns and owns recovery."""
    reasons = []
    turn = response.get('turn_index', 0)
    score = case['scoring']
    if type(turn) is not int or turn not in range(case['max_posts']):
        return dict(passed=False, reasons=['invalid turn index'])
    try:
        expected_input = case['turns'][turn]['input_tokens']
        cap = case['turns'][turn]['body']['max_tokens']
    except (KeyError, IndexError, TypeError):
        expected_input, cap = None, None
    if case['max_posts'] == 2:
        score = score['first' if turn == 0 else 'second']
    method = score['method']
    if method == 'intentional_cancel_recovery_contract':
        proof = response.get('cancel_proof') or {}
        if not isinstance(proof, dict):
            return dict(passed=False, reasons=['invalid cancel proof shape'])
        good = (type(proof.get('trigger_events')) is int and proof['trigger_events'] == 1 and proof.get('preclose_busy') is True
                and proof.get('owner_verified') is True and proof.get('terminal_before_cut') is False
                and proof.get('reader_exited') is True and proof.get('same_cohort') is True
                and proof.get('busy') is False and type(proof.get('queued')) is int and proof['queued'] == 0
                and proof.get('posthoc_cancelled') is True and proof.get('normal_finish') is False
                and type(proof.get('release_seconds')) in (int, float)
                and math.isfinite(proof['release_seconds']) and 0 <= proof['release_seconds'] <= 30)
        input_proved = _cancel_input(proof, expected_input)
        reasons = [] if good else ['cancel/recovery proof missing or failed']
        if not input_proved:
            reasons.append('cancel native input evidence missing or materialized input mismatch')
        # A recovery proof alone cannot certify which input reached the native engine.
        return dict(passed=good and input_proved, recovery_passed=good, input_verified=input_proved, reasons=reasons)
    if not _evidence(response, expected_input, cap):
        reasons.append('usage/timing evidence missing, nonfinite or materialized input mismatch')
    expected_finish = 'tool_calls' if method == 'exact_tool_name_and_parsed_argument_object' else 'stop'
    if response.get('finish_reason') != expected_finish:
        reasons.append('terminal finish reason missing or unexpected')
    text = response.get('text')
    try:
        if method == 'exact_tool_name_and_parsed_argument_object':
            calls = response.get('tool_calls')
            if not isinstance(calls, list) or len(calls) != score['tool_call_count']:
                raise ValueError('tool call count')
            function = calls[0]['function']
            arguments = function['arguments']
            arguments = _json(arguments) if isinstance(arguments, str) else arguments
            good = function['name'] == score['tool_name'] and _same(arguments, score['arguments'])
        elif method == 'single_json_document_no_duplicate_keys_schema_and_expected_value':
            # Preserve JSON decimal values before comparing (no binary-float rounding).
            # Other groups and CPU code vectors retain strict Python types.
            good = isinstance(text, str) and _same(_json(text, exact_numbers=True), score['expected'], json_numbers=True)
        elif method == 'SSE_reassemble_content_exact_text_and_valid_terminal':
            events = response.get('stream_events')
            good = (isinstance(events, list) and bool(events) and all(isinstance(e, dict) for e in events)
                    and events[-1].get('done') is True
                    and sum(e.get('done') is True for e in events) == 1
                    and ''.join(e.get('text') or '' for e in events) == score['expected']
                    and text == score['expected'])
        elif method == 'parse_python_function_then_run_fixed_CPU_vectors_in_bounded_newroot_subprocess':
            result = response.get('code_check') or {}
            good = (result.get('passed') is True and result.get('vectors_passed') == 4
                    and result.get('case_id') == case['id'] and isinstance(text, str)
                    and result.get('code_sha256') == hashlib.sha256(text.encode()).hexdigest()
                    and result.get('vectors_sha256') == object_sha(score['vectors']))
        elif method == 'exact_text_after_outer_whitespace_strip':
            good = isinstance(text, str) and text.strip() == score['expected']
        else:
            good = False
        if not good:
            reasons.append('fixed expected value/protocol did not match')
    except (ValueError, TypeError, KeyError, IndexError, InvalidOperation):
        reasons.append('invalid response value/shape')
    return dict(passed=not reasons, reasons=reasons)


def code_check_tasks(case, response):
    if case['group'] != 'code':
        return []
    vectors = case['scoring']['vectors']
    if not isinstance(response.get('text'), str):
        raise ValueError('Missing code text; no worker descriptor')
    if len(vectors) != 4:
        raise ValueError('Exactly four fixed code vectors required')
    return [dict(command_args=[str(Path(__file__).resolve()), '--code-check'],
                 stdin_json=dict(case_id=case['id'], code=response.get('text'), vectors=vectors),
                 timeout_seconds=2, vectors_count=4, memory_limit_bytes=268435456, max_child_processes=0,
                 expected_schema=dict(type='object', required=['case_id', 'passed', 'vectors_passed', 'errors',
                                                               'code_sha256', 'vectors_sha256'],
                                      properties=dict(case_id=dict(const=case['id']), passed=dict(type='boolean'),
                                                      vectors_passed=dict(type='integer'), errors=dict(type='array'),
                                                      code_sha256=dict(const=hashlib.sha256(response['text'].encode()).hexdigest()),
                                                      vectors_sha256=dict(const=object_sha(vectors)))))]


def check_code_input(value):
    """One small function, no imports/IO; runtime's process/Job is the outer bound."""
    result = dict(case_id=value.get('case_id'), passed=False, vectors_passed=0, errors=[],
                  code_sha256=hashlib.sha256(value['code'].encode()).hexdigest() if isinstance(value.get('code'), str) else None,
                  vectors_sha256=object_sha(value.get('vectors')))
    safe = dict(abs=abs, all=all, any=any, bool=bool, dict=dict, divmod=divmod, enumerate=enumerate,
                int=int, len=len, list=list, max=max, min=min, range=range, reversed=reversed,
                set=set, sorted=sorted, str=str, sum=sum, tuple=tuple, zip=zip)
    methods = {'append', 'extend', 'pop', 'sort', 'lower', 'upper', 'count', 'index', 'items', 'keys', 'values', 'join'}
    previous = sys.gettrace()
    try:
        code, vectors = value.get('code'), value['vectors']
        if not isinstance(code, str) or len(code.encode()) > 8192 or len(vectors) != 4:
            raise ValueError('Code/vector size invalid')
        tree = ast.parse(code)
        if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef) or tree.body[0].name != 'solve':
            raise ValueError('Only one solve function allowed')
        if tree.body[0].decorator_list:
            raise ValueError('Decorators not allowed')
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef, ast.Global, ast.Nonlocal, ast.With,
                                 ast.AsyncFunctionDef, ast.Await, ast.Yield, ast.YieldFrom)):
                raise ValueError('External/unsupported code operation')
            if isinstance(node, ast.Attribute) and node.attr not in methods:
                raise ValueError('Unsupported attribute')
            if isinstance(node, ast.Name) and node.id.startswith('__'):
                raise ValueError('Dunder names not allowed')
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id not in {*safe, 'solve'}:
                raise ValueError('Unsupported function call')
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
                raise ValueError('Exponentiation unnecessary for fixed algorithms')
        deadline = time.monotonic() + 1.5
        def trace(frame, event, arg):
            if time.monotonic() > deadline:
                raise TimeoutError('Code execution budget')
            return trace
        sys.settrace(trace)
        env = {'__builtins__': safe}
        exec(compile(tree, '<quality-solve>', 'exec'), env)
        for vector in vectors:
            actual = env['solve'](*copy.deepcopy(vector['args']))
            if not _same(actual, vector['expected']):
                raise ValueError('Code vector mismatch')
            result['vectors_passed'] += 1
        result['passed'] = True
    except Exception as error:
        result['errors'].append(type(error).__name__ + ': ' + str(error))
    finally:
        sys.settrace(previous)
    return result


if __name__ == '__main__':
    if sys.argv[1:] != ['--code-check']:
        raise SystemExit('Only --code-check is supported; runtime owns launches')
    source = sys.stdin.buffer.read(65537)
    if len(source) > 65536:
        raise SystemExit('Code worker input too large')
    print(json.dumps(check_code_input(_json(source)), ensure_ascii=False, allow_nan=False))
