"""Assigned integrated contact: reuse the original parent and supplier owners."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

# Strong roots survive an interrupted wait in this same original parent.
HELD = []
CONTEXTS = []


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bounded_guard(guard):
    previous = list(sys.path)
    try:
        return guard.accepted_guard()
    finally:
        sys.path[:] = previous


def close_retained(supplier, owner, errors):
    """Wait only the already registered original objects, then close them."""
    for held in supplier.RETAINED:
        if not any(value is held for value in HELD):
            HELD.append(held)
    # The supplier's wait helper does not close either engine or native handle.
    while True:
        try:
            supplier.wait_retained_originals()
            break
        except KeyboardInterrupt as error:
            errors.append(dict(stage='retained_wait_interrupt', error=repr(error)))
            # Same objects and same wait; never another diagnostic/native launch.
    observations = []
    for held in HELD:
        engine = held['engine']
        for process in held['processes']:
            value = dict(wait_completed=False, exit=None, engine_closed=False,
                         handle_closed=False, error=None)
            try:
                code = process.wait()
                if code is None:
                    raise RuntimeError('original wait remains unknown')
                value.update(wait_completed=True, exit=code)
                engine.close()
                value['engine_closed'] = True
                handle = getattr(process, '_handle', None)
                if handle is None:
                    raise RuntimeError('original handle unavailable')
                if not handle.closed:
                    owner.close_original(process)
                value['handle_closed'] = handle.closed is True
                if not value['handle_closed']:
                    raise RuntimeError('original handle close remains unknown')
            except BaseException as error:
                value['error'] = repr(error)
                errors.append(dict(stage='retained_close', error=repr(error)))
            observations.append(value)
    return observations


def run(callspec_path, window_path):
    # read_record below binds all later source/data before any factory invocation.
    callspec_path, window_path = Path(callspec_path), Path(window_path)
    spec = json.loads(callspec_path.read_text(encoding='utf-8-sig'))
    parent_record = spec['refs']['parent_entry']
    # Parent source is pinned by the reviewed assignment; do not trust a path alone.
    window = json.loads(window_path.read_text(encoding='utf-8-sig'))
    import hashlib
    def row(path):
        path = Path(path).resolve()
        return dict(path=str(path), bytes=path.stat().st_size,
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    if (window.get('execution_go') is not True or window.get('do_not_execute') is not False
            or window.get('callspec') != row(callspec_path)
            or window.get('parent_entry') != parent_record
            or row(parent_record['path']) != parent_record
            or window.get('window_id') != spec['window_id']
            or not window.get('formal_assignment')):
        raise ValueError('exact reviewed callspec/original parent/Root window required')
    parent = load('integrated_original_parent', parent_record['path'])
    for record in spec['refs'].values():
        parent.V.require(row(record['path']) == record, 'callspec immutable reference')
    guard, owner = parent.primitives()
    caller = load('integrated_selected_caller', spec['refs']['caller']['path'])
    # The caller remains authority for its selected expected/recipe/argv/environment.
    expected, value = caller.selected()
    parent.V.require(expected == spec['refs']['expected']
                     and value['recipe'] == spec['refs']['recipe']
                     and row(caller.P/'native-command.json') == spec['refs']['native_command']
                     and row(caller.P/'environment-template.json') == spec['refs']['environment'], 'caller data/callspec binding')
    out = Path(spec['output'])
    parent.V.require(window['output'] == str(out), 'assigned create-only output')
    out.mkdir(parents=True, exist_ok=False)
    parent.save(out/'window.json', dict(source=row(window_path), value=window,
                                      callspec=row(callspec_path)))
    parent.save(out/'pre-guard.json', bounded_guard(guard))
    errors, result, primary = [], None, None
    factory = caller.make_factory(out/'native.log')
    # Retain the factory before its register-before-constructor native contact.
    context = dict(factory=factory, supplier=caller.S, result=None)
    CONTEXTS.append(context)
    def persist(event):
        import os
        with (out/'raw-events.jsonl').open('a', encoding='utf8', newline='\n') as stream:
            stream.write(json.dumps(event, allow_nan=False)+'\n')
            stream.flush()
            os.fsync(stream.fileno())
    def save(name, value):
        try:
            parent.save(out/name, value)
            return True
        except BaseException as error:
            errors.append(dict(stage='save:'+name, error=repr(error)))
            return False
    try:
        result = caller.run_diagnostic(factory, owner.WinObservation, persist,
                                       lambda identity: parent.save(out/'original-owner.json', identity))
        context['result'] = result
        primary = result.get('error')
        saved_result = dict(result, retained_owner=result.get('retained_owner') is not None)
        save('result.json', saved_result)
    except BaseException as error:
        primary = repr(error)
    finally:
        try:
            retained = close_retained(caller.S, owner, errors)
        except BaseException as error:
            retained = []
            errors.append(dict(stage='retained_wait', error=repr(error)))
        cleanup = (result or {}).get('cleanup', {})
        initial_known = (cleanup.get('wait_completed') is True
                         and cleanup.get('close_called') is True
                         and cleanup.get('original_handle_closed') is True)
        retained_known = bool(retained) and all(x['wait_completed'] and x['engine_closed']
                                               and x['handle_closed'] for x in retained)
        known = retained_known if caller.S.RETAINED else initial_known
        save('retained-close.json', dict(observations=retained, original_owner_closed=known))
        post = None
        if known:
            try:
                post = bounded_guard(guard)
                save('post-guard.json', post)
            except BaseException as error:
                errors.append(dict(stage='post_guard', error=repr(error)))
        outcome = dict(error=primary, secondary_errors=errors, cleanup=cleanup,
                       original_owner_closed=known, post_guard=post,
                       resource_return_ready=known and post is not None and not errors,
                       outer_termination='operator must bind actual outer exec/wait/exit separately',
                       success=primary is None and known and not errors)
        if not save('outcome.json', outcome):
            outcome['success'] = False
            outcome['resource_return_ready'] = False
        # Do not discard unknown originals when this function is used by a held parent.
        if not known:
            context['result'] = result
            context['retained'] = True
    return outcome


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--callspec', required=True)
    parser.add_argument('--window', required=True)
    args = parser.parse_args(argv)
    result = run(args.callspec, args.window)
    if not result['original_owner_closed']:
        # No normal CLI termination while the original native owner is unknown.
        supplier = CONTEXTS[-1]['supplier']
        _, owner = load('integrated_held_parent', json.loads(Path(args.callspec).read_text())['refs']['parent_entry']['path']).primitives()
        while not result['original_owner_closed']:
            observations = close_retained(supplier, owner, result['secondary_errors'])
            result['original_owner_closed'] = bool(observations) and all(x['wait_completed'] and x['engine_closed'] and x['handle_closed'] for x in observations)
    return 0 if result['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
