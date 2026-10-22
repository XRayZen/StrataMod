"""One guarded WebUI upload; the caller retains the server and both old locks."""
import base64
import hashlib
import json
from pathlib import Path
import time

from tools.vision.encode_io import EncodeIO
from tools.vision.image_api_cases import parse_sse
from . import official_runtime
from . import evaluate_r9700 as runner
from . import runtime_safety as safety

REFERENCE_IMAGE = Path(__file__).resolve().parents[2]/'RefImage/48463779.jpeg'
REFERENCE_SHA = '1806c40d735545d6852e1d1a90dba9c22f4501e79e9cb5784f93268e2331d699'


def _require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON key')
        value[key] = item
    return value


def _json(text):
    return json.loads(text, object_pairs_hook=_unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def _sha(value):
    return hashlib.sha256(value).hexdigest()


class WebUIIO(EncodeIO):
    """Reuse the existing bounded raw tee/queue/join, adapting only JSONL parsing.

    Selected JPEG base64 is 170340 bytes, duplicated in generation_request.
    A 4 MiB raw SSE plus JSON escaping/decoded/UI text fits 32 MiB per line.
    Accepted raw JSONL totals at most 40 MiB. As in the existing line guard,
    the rejecting line is retained before parsing (capture <= total+line+1).
    Overflow/truncation is sticky and cannot authorize another send.
    """
    MAX_LINE_BYTES = 32 * 1024 * 1024
    MAX_TOTAL_BYTES = 40 * 1024 * 1024

    def _parse(self, line):
        if self._raw.tell() > self.MAX_TOTAL_BYTES:
            raise ValueError('WebUI JSONL total byte limit exceeded')
        value = _json(line)
        if not isinstance(value, dict) or value.get('type') not in (
                'attachment', 'generation_request', 'final_answer', 'error', 'closed'):
            raise ValueError('Unexpected WebUI JSONL event')
        return dict(kind='webui', event=value)


def _observe(aux, row, persist, label=None):
    observation = aux['observer'].snapshot()
    state = aux['state']
    state.update(owned_identities=observation['identities'], spawn_observation=observation)
    identities = row.setdefault('auxiliary_identities', [])
    for identity in observation['identities']:
        if identity not in identities:
            identities.append(dict(identity))
    row['physical_aux_process_starts'] = len(identities)
    persist(state)
    _require(observation.get('created') == state.get('created') and bool(identities)
             and not observation['unknown'] and not observation['errors'], 'WebUI birth/cohort is unconfirmed')
    memory = []
    sample = label is not None or time.monotonic() >= aux.get('next_memory_sample_at', 0)
    for identity in observation['identities']:
        presence = safety.process_identity_status(identity)
        if presence.status == 'gone':
            continue
        _require(presence.status == 'verified'
                 and official_runtime.checked_job.membership_pid(identity['pid']), 'WebUI cohort Job membership is unconfirmed')
        if sample:
            counters = dict(identity, rss_bytes=None, private_bytes=None)
            try:
                info = presence.process.memory_info()
                for field, attribute in (('rss_bytes', 'rss'), ('private_bytes', 'private')):
                    measured = getattr(info, attribute, None)
                    if type(measured) is int and measured >= 0:
                        counters[field] = measured
                if any(counters[field] is None for field in ('rss_bytes', 'private_bytes')):
                    counters['error_type'] = 'UnavailableMemoryCounter'
            except Exception as error:
                counters.update(error_type=type(error).__name__, reason=str(error))
            memory.append(counters)
    if sample:
        now = time.monotonic()
        row.setdefault('auxiliary_memory_samples', []).append(dict(at_monotonic=now, label=label or 'periodic', processes=memory))
        aux['next_memory_sample_at'] = now + 1


def _event(event, row, config):
    """Validate actual helper evidence, without inferring image recognition."""
    if event['type'] == 'error':
        row['helper_error'] = event
        raise RuntimeError('WebUI helper: ' + str(event.get('message', 'unknown error')))
    expected = ('attachment', 'generation_request', 'final_answer', 'closed')
    index = len(row['events']) - 1
    _require(index < len(expected) and event['type'] == expected[index], 'WebUI event order/count mismatch')
    if index == 0:
        preview = event.get('preview', {})
        _require(event.get('file_input') == '#file' and event.get('set_input_files_returned') is True
                 and type(event.get('selected_files')) is int and event['selected_files'] == 1
                 and event.get('image_path') == config['image_path']
                 and event.get('image_sha256') == config['image_sha256']
                 and preview.get('kind') == 'filename_chip'
                 and Path(config['image_path']).name in preview.get('text', ''), 'WebUI attachment evidence mismatch')
    elif index == 1:
        wire = event['post_data_utf8'].encode('utf-8')
        body = _json(event['post_data_utf8'])
        _require(event.get('url') == config['url'] + 'v1/chat/completions' and event.get('method') == 'POST'
                 and type(event.get('count')) is int and event['count'] == 1
                 and _sha(wire) == event.get('full_wire_sha256') and body == event['post_data_json'],
                 'WebUI actual request wire mismatch')
        _require(type(body.get('max_tokens')) is int and body['max_tokens'] == 128 and body.get('stream') is True
                 and body.get('reasoning_effort') == 'none' and type(body.get('temperature')) in (int, float)
                 and body['temperature'] == 0 and type(body.get('seed')) is int and body['seed'] == 42
                 and not body.get('strata_mcp') and not body.get('tools')
                 and type(body.get('n', 1)) is int and body.get('n', 1) == 1,
                 'WebUI actual request bounds differ')
        messages = body['messages']
        _require(isinstance(messages, list) and len(messages) == 1 and messages[0]['role'] == 'user', 'WebUI fresh chat mismatch')
        content = messages[0]['content']
        _require(isinstance(content, list) and len(content) == 2 and content[0] == dict(type='text', text=config['prompt'])
                 and content[1]['type'] == 'image_url', 'WebUI actual prompt/image mismatch')
        url = content[1]['image_url']['url']
        _require(isinstance(url, str) and url.startswith('data:image/jpeg;base64,'), 'WebUI selected inline JPEG missing')
        _require(_sha(base64.b64decode(url.split(',', 1)[1], validate=True)) == config['image_sha256'], 'WebUI actual image hash mismatch')
        row['generation_request'] = event
        row['actual_generation_count'] = 1
    elif index == 2:
        evidence = event['api_response']
        raw = evidence['response_utf8']
        protocol = parse_sse('openai', raw)
        usage = protocol['usage'] or {}
        _require(event.get('api_status') == 200 and type(event.get('generation_count')) is int
                 and event['generation_count'] == 1 and event.get('user_image_preview_sha256') == config['image_sha256']
                 and isinstance(event.get('text'), str) and bool(event['text'].strip())
                 and protocol['normal_terminal'] and _sha(raw.encode('utf-8')) == evidence.get('response_sha256')
                 and protocol['text'] == evidence['content'] and protocol['finish_reason'] == evidence['finish_reason']
                 and usage == evidence['usage'] and type(usage.get('prompt_tokens')) is int and usage['prompt_tokens'] > 0
                 and type(protocol['output_tokens']) is int and 0 < protocol['output_tokens'] <= 128,
                 'WebUI final API response evidence mismatch')
        row.update(final_answer=event, protocol=protocol)
    else:
        _require(event.get('context_close_returned') is True and event.get('cleanup_verified') is False
                 and event.get('process_proof_owner') == 'runtime' and type(event.get('generation_count')) is int
                 and event['generation_count'] == 1, 'WebUI context close evidence mismatch')


def _cleanup(aux, row, persist, failed):
    """Always try cohort and reader proof, even after secondary exceptions."""
    errors = row.setdefault('cleanup_errors', [])
    state = aux.setdefault('state', dict(cleanup_pending=True))
    state['cleanup_pending'] = True

    def attempt(action, function):
        try:
            return function()
        except BaseException as error:
            errors.append(dict(action=action, error_type=type(error).__name__, reason=str(error)))
            return None

    observer, process = aux.get('observer'), aux.get('process')
    if observer is not None:
        observation = attempt('finish_observer', observer.finish_standalone)
        if observation is not None:
            attempt('bind_final_observation', lambda: state.update(
                owned_identities=observation['identities'], spawn_observation=observation))
    stop_attempted = failed
    if failed:
        attempt('stop_owned_auxiliary', lambda: safety.stop_owned(state, official_first=False))
    reader = aux.get('reader')
    joined = reader is None or attempt('close_reader', lambda: reader.close_reader(2)) is True
    if not joined:
        state['reader_cleanup_pending'] = True
    # Pipe cleanup errors cannot prevent the independent full-cohort proof.
    if process is not None:
        for name in ('stdin', 'stdout'):
            stream = getattr(process, name, None)
            if stream is not None and (name == 'stdin' or joined):
                attempt('close_' + name, stream.close)
    if not stop_attempted and (not joined or errors):
        stop_attempted = True
        attempt('stop_owned_auxiliary', lambda: safety.stop_owned(state, official_first=False))
    deadline = time.monotonic() + 15
    proof = dict(complete=False)
    while True:
        observed = attempt('cohort_exit_proof', lambda: runner.pending_exit_proof(aux, require_port=False))
        if observed is not None:
            proof = observed
        evidence = state.get('spawn_observation', {})
        if not proof.get('complete') and not stop_attempted:
            stop_attempted = True
            attempt('stop_owned_auxiliary', lambda: safety.stop_owned(state, official_first=False))
            continue
        if proof.get('complete') or errors or evidence.get('unknown') or evidence.get('errors'):
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(.05)
    complete = proof.get('complete') is True and joined and not errors and not (
        state.get('spawn_observation', {}).get('unknown') or state.get('spawn_observation', {}).get('errors'))
    state.update(cleanup_pending=not complete, phase='stopped' if complete else 'cleanup-pending')
    row['cleanup'] = dict(proof, complete=complete, reader_joined=joined)
    attempt('persist_auxiliary', lambda: persist(state))
    if errors:
        state.update(cleanup_pending=True, phase='cleanup-pending')
        row['cleanup']['complete'] = False


def run(state, monitor, value, result, retained):
    """One WebUI slot, called while the parent server and shared locks remain held."""
    _require(not retained.get('auxiliary'), 'Existing auxiliary evidence must be retained')
    aux = retained.setdefault('auxiliary', {})  # Before any possible CreateProcess.
    row = dict(status='unverified', events=[], actual_generation_count=0, physical_aux_process_starts=0,
               cleanup=dict(complete=False))
    result['webui'] = row
    deadline = time.monotonic() + 120

    def persist(auxstate):
        state['webui_auxiliary'] = auxstate
        safety.save(state)  # Never replace the server's global owner with Node.

    error = None
    try:
        config = value['webui_input']
        _require(config['max_tokens'] == 128 and config['deadline_seconds'] == 120, 'Fixed WebUI limits required')
        _require(Path(config['image_path']).resolve() == REFERENCE_IMAGE.resolve()
                 and config['image_sha256'] == REFERENCE_SHA, 'Exact selected RefImage path/hash required')
        _require(value['max_posts'] == 7 and type(result.get('post_count')) is int and result['post_count'] == 4
                 and result.get('browser_start_count', 0) == 0, 'WebUI POST/start slot unavailable')
        monitor.check()
        runner.ready(state)
        status = safety.get_json('/status')
        _require(status.get('busy') is False and type(status.get('queued')) is int and status['queued'] == 0,
                 'Candidate is busy/queued; WebUI not started')
        result.update(post_count=5, browser_start_count=1)  # Reserve before the only possible launch/send.
        row['post_slot_reserved'] = True
        def before_spawn():
            monitor.check()
            _require(time.monotonic() < deadline, 'Fixed WebUI 120-second deadline exceeded before spawn')
        process, observer, auxstate = official_runtime.start_webui(
            state['manifest'], state['manifest_sha256'], parent_state=state, retained=aux,
            before_spawn=before_spawn, persist_aux=persist)
        row['physical_aux_root_starts'] = 1
        reader = WebUIIO(process.stdin, process.stdout, Path(value['config']).parent/'webui.stdout')
        aux['reader'] = reader
        _observe(aux, row, persist, 'before-input')
        monitor.check()
        safety.require_owned_listener(state)
        _require(time.monotonic() < deadline, 'Fixed WebUI 120-second deadline exceeded before input')
        source = (json.dumps(config, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
        _require(process.stdin.write(source) == len(source), 'Short WebUI stdin write; no retry')
        process.stdin.flush()
        process.stdin.close()
        while True:
            monitor.check()
            safety.require_owned_listener(state)
            _observe(aux, row, persist)
            _require(time.monotonic() < deadline, 'Fixed WebUI 120-second deadline exceeded')
            event = reader.read_event(.05)
            if event is None:
                continue
            if event['kind'] == 'error':
                raise RuntimeError('WebUI JSONL reader: ' + event['reason'])
            if event['kind'] == 'eof':
                row['reader_eof'] = True
                _require(len(row['events']) == 4, 'WebUI EOF before complete event sequence')
                break
            _require(event['kind'] == 'webui', 'Unexpected WebUI reader event')
            row['events'].append(event['event'])
            _event(event['event'], row, config)
            _observe(aux, row, persist, event['event']['type'])
        while process.poll() is None:
            monitor.check()
            safety.require_owned_listener(state)
            _observe(aux, row, persist)
            _require(time.monotonic() < deadline, 'WebUI root did not exit by deadline')
            time.sleep(.05)
        process.wait(timeout=0)
        _require(process.returncode == 0, 'WebUI Node exited unsuccessfully')
        row['exit_code'] = process.returncode
    except BaseException as cause:
        error = cause
        row.update(status='failed', error_type=type(cause).__name__, reason=str(cause))
    finally:
        row['physical_aux_root_starts'] = int(aux.get('process') is not None)
        if aux.get('spawn_possible'):
            try:
                _cleanup(aux, row, persist, failed=error is not None)
            except BaseException as cleanup_error:
                # An unexpected secondary failure still preserves the exact
                # auxiliary for the parent's compound lock-held barrier.
                aux.setdefault('state', {})['cleanup_pending'] = True
                row.setdefault('cleanup_errors', []).append(dict(action='cleanup',
                    error_type=type(cleanup_error).__name__, reason=str(cleanup_error)))
                row['cleanup'] = dict(complete=False)
                if error is None:
                    error = cleanup_error
                    row.update(status='failed', error_type=type(error).__name__, reason=str(error))
        else:
            row['cleanup'] = dict(complete=True, zero_spawn=True)
        identities = row.setdefault('auxiliary_identities', [])
        # The final observer/proof may discover another saved birth after the
        # last stdout event. Include it without inventing absent metadata.
        for identity in aux.get('state', {}).get('owned_identities', []):
            if identity not in identities:
                identities.append(dict(identity))
        row['physical_aux_process_starts'] = len(identities)
        result['physical_aux_process_starts'] = row['physical_aux_process_starts']
    if error is None and not row['cleanup']['complete']:
        error = RuntimeError('WebUI auxiliary cleanup remains pending')
        row.update(status='failed', error_type=type(error).__name__, reason=str(error))
    if error is not None:
        raise error
    row['status'] = 'passed'
    return row
