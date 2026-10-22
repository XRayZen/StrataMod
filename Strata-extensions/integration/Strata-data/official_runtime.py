"""Use Strata's unchanged official MCP management implementation with validated profiles.

This adapter does not run setup/update, download models, or edit Strata source.
The public Python CLI retains the local model/context and ownership checks.
"""
import contextlib
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid
import psutil
from profile_defaults import approved_hashes
import startup_progress

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent / 'Strata'
REGISTRY = ROOT / 'records' / 'official-profile-registry.json'
MCP_SHA256 = '94fd8f9fe475de23da14ae4ef48598755e4ebbe09821b1c421e47ec93c0533df'
SETUP_SHA256 = '907788af312d1657350076188be6c696b839cfa8f5073a55a1e7e3c3e49dc88c'
SERVER_SHA256 = '1d50a9ad02608254f391a73db96a23c49f9a1620200cbd92ea830275825e8816'
BASELINE = ROOT / 'records/official-migration-20261017T002153Z/baseline.json'
BASELINE_SHA256 = 'ef01a6819caabe437755370ff9372f2ce96ded0795d284fb37825236857b1818'
_native = None
_native_lock = threading.RLock()


def directory_writable_once(directory):
    """Same non-secret TEMP test, without Windows tempfile's name-retry loop."""
    path = Path(directory) / ('.strata-write-probe-' + uuid.uuid4().hex)
    created = False
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, 'O_BINARY', 0)
                     | getattr(os, 'O_TEMPORARY', 0), 0o600)
        created = True
        os.close(fd)
        path.unlink(missing_ok=True)
        return True
    except OSError:
        if created:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        return False


@contextlib.contextmanager
def windows_temp_probe(server, selected_config=None):
    """Only replace the pinned official guard's filesystem probe, then restore it.

    hip_env_guard still chooses and logs the fallback. No ACLs, path selection,
    inherited credentials, model options, or GPU settings are changed here.
    """
    original = getattr(server, '_dir_writable', None)
    if os.name != 'nt' or original is None:
        yield
        return
    expected_path,expected_sha=REPO/'serve/server.py',SERVER_SHA256
    if selected_config is not None:
        if selected_config.get('family')!='deepseek41':raise RuntimeError('Unknown selected TEMP family')
        package=selected_config['runtime_package']
        manifest_path=Path(package['manifest'])
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        expected_path=Path(selected_config['exe']).parent/'server/serve/server.py'
        if (manifest.get('id')!=package['id'] or manifest_path.parent.parent.name!=package['id']
                or manifest.get('native_manifest_sha256')!=selected_config['bundle_id']
                or not expected_path.resolve().is_relative_to(manifest_path.parent.parent.resolve())):
            raise RuntimeError('Selected TEMP runtime package binding mismatch')
        matches=[item['copy'] for item in manifest['copies'] if Path(item['copy']['path']).resolve()==expected_path.resolve()]
        if len(matches)!=1:raise RuntimeError('Selected prepared server is not uniquely package-bound')
        expected_sha=matches[0]['sha256']
    if (Path(getattr(server, '__file__', '')).resolve() != expected_path.resolve()
            or digest(expected_path) != expected_sha):
        raise RuntimeError('Official server changed; review the Windows TEMP compatibility probe.')
    with _native_lock:
        server._dir_writable = directory_writable_once
        try:
            yield
        finally:
            server._dir_writable = original


class LaunchFailure(RuntimeError):
    def __init__(self, error, process, tracking, observation, startup=None):
        super().__init__(f'Official start failed: {type(error).__name__}: {error}')
        self.process = process
        self.tracking = tracking
        self.observation = observation
        self.startup = startup


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def native():
    global _native
    path = REPO / 'tools' / 'strata_mcp.py'
    if digest(path) != MCP_SHA256:
        raise RuntimeError('Official MCP changed; review the integration before starting/stopping.')
    if digest(REPO / 'setup.py') != SETUP_SHA256:
        raise RuntimeError('Official setup source changed; review the integration.')
    if _native is None:
        spec = importlib.util.spec_from_file_location('strata_official_management', path)
        module = importlib.util.module_from_spec(spec)
        prior = sys.dont_write_bytecode
        try:
            sys.dont_write_bytecode = True
            spec.loader.exec_module(module)
        finally:
            sys.dont_write_bytecode = prior
        _native = module
    return _native


def management():
    module = native()
    strata = module.Strata(REPO)
    return strata, module.Tools(strata)


def tag(model, context):
    return f'{model}-{context}'


def registered_path(model, context):
    return REPO / f'strata-{tag(model, context)}.json'


def require_registration(model, context):
    """Mirror the prepared profile beside setup.py for official management.

    No receipt, registry row or content hash is consulted.
    """
    import model_catalog as catalog
    catalog.require_public_context(model, context, ROOT)
    source = ROOT / 'profiles' / f'{tag(model, context)}.json'
    if not source.is_file():
        raise RuntimeError('Prepared profile is missing: ' + str(source))
    target = registered_path(model, context)
    if not target.is_file() or target.read_bytes() != source.read_bytes():
        target.write_bytes(source.read_bytes())
    native()
    return target


@contextlib.contextmanager
def native_hooks(module, **changes):
    """Scoped observation/safety hooks; always delegate or explicitly fail closed."""
    with _native_lock:
        previous = {name: getattr(module, name) for name in changes}
        try:
            for name, value in changes.items():
                setattr(module, name, value)
            yield
        finally:
            for name, value in previous.items():
                setattr(module, name, value)


def observe_spawn(process, config):
    """Capture exact identities while the newly returned Popen still identifies its root."""
    import manage_runtime as manager
    observation = dict(identities=[], unknown=[], errors=[])
    try:
        parent = psutil.Process(process.pid)
        command = parent.cmdline()
        if (manager.server_command(command, str(config))
                and (not startup_progress.is_bootstrap_command(command, str(config))
                     or Path(parent.exe()).resolve() == startup_progress.BASE_PYTHON.resolve())):
            observation['created'] = parent.create_time()
            observation['identities'].append(dict(pid=parent.pid, created=observation['created'], exe=parent.exe()))
            errors, unknown = [], []
            children = manager.descendants(parent, str(config), strict=False, unrecognized=unknown, errors=errors)
            observation['errors'].extend(errors)
            observation['unknown'].extend(dict(pid=child.pid) for child in unknown)
            for child in children:
                try:
                    observation['identities'].append(dict(pid=child.pid, created=child.create_time(), exe=child.exe()))
                except psutil.Error as error:
                    observation['errors'].append(dict(pid=child.pid, error_type=type(error).__name__))
        else:
            observation['errors'].append(dict(pid=parent.pid, error_type='UnexpectedSpawnCommand'))
    except psutil.Error as error:
        observation['errors'].append(dict(pid=process.pid, error_type=type(error).__name__))
    return observation


def register_profiles():
    """Register the validated public combinations; never overwrite another configuration."""
    import model_catalog as catalog
    rows = {}
    candidates = []
    for model, item in catalog.CATALOG.items():
        if not item.get('selectable', True):
            continue
        catalog.require_ready(model, ROOT)
        for context in catalog.public_contexts(model):
            catalog.require_public_context(model, context, ROOT)
            source = ROOT / 'profiles' / f'{tag(model, context)}.json'
            target = registered_path(model, context)
            content = source.read_bytes()
            if target.exists() and target.read_bytes() != content:
                raise RuntimeError('Existing official configuration differs: ' + str(target))
            candidates.append((source, target, content, model, context))
    native()
    for source, target, content, model, context in candidates:
        if not target.exists():
            with target.open('xb') as stream:
                stream.write(content)
        rows[tag(model, context)] = dict(model=model, context=context, source=str(source),
                                        official_config=str(target), sha256=digest(source))
    data = dict(schema_version=1, official_mcp_sha256=MCP_SHA256, profiles=rows,
                note='Generated runtime configuration only; source profiles and official code unchanged.')
    temporary = REGISTRY.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temporary.replace(REGISTRY)
    return data


@contextlib.contextmanager
def launch_environment(environment):
    # Manager commands run in their own single-threaded Python process. Restore its
    # environment after the official routine has captured the server's environment.
    original = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(environment)
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


class SpawnObserver:
    """Read-only descendant observation until official readiness ends or is cancelled."""
    def __init__(self, process, config):
        self.process, self.config = process, config
        self.data = dict(identities=[], unknown=[], errors=[])
        self.lock, self.done, self.thread = threading.Lock(), threading.Event(), None

    def capture(self):
        latest = observe_spawn(self.process, self.config)
        with self.lock:
            if 'created' in self.data and latest.get('created') != self.data['created']:
                raise RuntimeError('Spawn root identity lost/changed during descendant observation.')
            if 'created' in latest:
                self.data['created'] = latest['created']
            for key in ('identities', 'unknown', 'errors'):
                for row in latest[key]:
                    if row not in self.data[key]:
                        self.data[key].append(row)

    def fail(self, error):
        with self.lock:
            self.data['errors'].append(dict(pid=self.process.pid, error_type=type(error).__name__, reason=str(error)))

    def begin(self):
        self.capture()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        try:
            while not self.done.wait(.01):
                if self.process.poll() is not None:
                    raise RuntimeError('Spawn root ended before readiness observation completed; descendants not fully verified.')
                self.capture()
        except BaseException as error:
            self.fail(error)

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.data)

    def finish(self):
        self.done.set()
        if self.thread is not None:
            try:
                self.thread.join(timeout=3)
                if self.thread.is_alive():
                    raise RuntimeError('Spawn observer did not join.')
            except RuntimeError as error:
                self.fail(error)
        if self.process.poll() is not None:
            self.fail(RuntimeError('Early root exit; unobserved descendants cannot be ruled out.'))
        return self.snapshot()


def start(model, context, environment, launch=None):
    import huihui_authority
    huihui_authority.require_context(model, context, ROOT, for_start=True)
    source_config = require_registration(model, context)
    source_sha256 = digest(source_config)
    config = Path(launch['config']) if launch else source_config
    if launch:
        family = startup_progress.family_launch(config)
        if not family or family[2] != launch:
            raise RuntimeError('Selected family launch binding mismatch')
    config_sha256 = digest(config)
    strata, tools = management()
    before = strata.tracked_server()
    if before and not before.get('ended'):
        raise RuntimeError('Official management already owns a running server; do not launch another.')
    module = native()
    spawn = module.spawn_detached
    captured = []

    def capture(command, cwd, logfile, env):
        expected = [str(strata.venv_python()), str(REPO / 'serve/server.py'),
                    '--engine', 'strata', '--config', str(source_config), '--port', '18080']
        # Recheck at the mutation boundary, after official management has resolved
        # its command. Only this one pinned server invocation may be substituted.
        if (captured or command != expected or cwd != REPO
                or logfile != REPO / '.strata-mcp/server.log'
                or require_registration(model, context) != source_config
                or digest(source_config) != source_sha256
                or digest(config) != config_sha256
                or digest(REPO / 'serve/server.py') != SERVER_SHA256):
            raise RuntimeError('Official launch command/config/source changed; no spawn.')
        current = strata.tracked_server()
        if current and not current.get('ended'):
            raise RuntimeError('Official owner appeared before spawn; no replacement launch.')
        attempt = launch['attempt'] if launch else str(uuid.uuid4())
        stage = startup_progress.stage_path(attempt)
        with stage.open('x', encoding='utf-8'):
            pass
        if model == huihui_authority.MODEL:
            import model_catalog as catalog
            if not catalog.CATALOG[model].get('selectable'):
                huihui_authority.issue_bootstrap(attempt,stage,config)
        python = family[1]['python'] if launch else str(startup_progress.VENV_PYTHON)
        child_environment = dict(env, __PYVENV_LAUNCHER__=python)
        process = spawn(startup_progress.bootstrap_command(config, attempt), cwd, logfile, child_environment)
        watcher = SpawnObserver(process, config)
        watcher.startup = dict(attempt=attempt, stage=str(stage), config_sha256=config_sha256)
        if launch:
            watcher.startup['launch_binding'] = launch
        # Retain the Popen BEFORE inspection and continue observations across the
        # native start's0.1s and our own manager's readiness loop.
        captured.append((process, watcher))
        try:
            watcher.begin()
        except BaseException as error:
            watcher.fail(error)
            raise
        return process

    try:
        with native_hooks(module, spawn_detached=capture), launch_environment(environment):
            result = tools.strata_start(model=tag(model, context), port=18080, wait_seconds=0)
        if len(captured) != 1 or len(strata.children) != 1:
            raise RuntimeError('Official management did not create exactly one new server.')
        process, watcher = captured[0]
        observation = watcher.snapshot()
        tracking = strata.state('server')
        if (tracking.get('pid') != process.pid or tracking.get('config') != source_config.name
                or tracking.get('model') != tag(model, context) or tracking.get('port') != 18080
                or not module.proc_alive(process.pid, tracking.get('ident'))):
            raise RuntimeError('Official management ownership record does not match the new server.')
        if observation['errors'] or observation['unknown'] or 'created' not in observation:
            raise RuntimeError('Spawn identity/descendants could not be completely verified.')
        return process, tracking, result, observation, watcher
    except BaseException as error:
        if captured:
            process, watcher = captured[0]
            observation = watcher.finish()
            try:
                tracking = strata.state('server')
            except BaseException:
                tracking = {}
            raise LaunchFailure(error, process, tracking, observation, getattr(watcher, 'startup', None)) from error
        raise


def require_tracking(state):
    strata, tools = management()
    record = strata.state('server')
    expected = state.get('official_tracking', {})
    if (not expected or not isinstance(record.get('ident'), str) or not record['ident']
            or any(record.get(k) != expected.get(k) for k in ('pid', 'ident', 'config', 'model', 'port'))
            or record.get('pid') != state.get('pid')
            or record.get('config') != registered_path(state['model'], state['context']).name
            or not native().proc_alive(record['pid'], record.get('ident'))):
        raise RuntimeError('Official owner changed; no unload/stop request was sent.')
    return strata, tools


def stop(state):
    import huihui_authority as authority
    if state.get('model') == authority.MODEL:
        with authority.cleanup_scope(state):
            return _stop(state)
    return _stop(state)


def _stop(state):
    if state.get('family') == 'deepseek41':
        family = startup_progress.family_launch(state['config'])
        if not family or family[2] != state.get('launch_binding'):
            raise RuntimeError('Saved family launch changed; no stop request')
    else:
        require_registration(state['model'], state['context'])
    _, tools = require_tracking(state)
    import manage_runtime as manager
    module = native()
    http, terminate = module.http_json, module.proc_terminate
    unloaded = False

    def validate_owner(stage='before status/unload'):
        try:
            require_tracking(state)
            manager.require_owned_listener(state)
        except (RuntimeError, psutil.Error) as error:
            raise RuntimeError(f'Official stop ownership check [{stage}]: {error}') from error

    def guarded_http(url, method='GET', **kwargs):
        nonlocal unloaded
        validate_owner('before unload' if url.endswith('/unload') else 'before status')
        if url not in ('http://127.0.0.1:18080/status', 'http://127.0.0.1:18080/unload'):
            raise RuntimeError('Unexpected official stop HTTP target.')
        status, body = http(url, method, **kwargs)
        if status != 200 or not isinstance(body, dict):
            raise RuntimeError(f'Official stop HTTP failed: status {status}; no termination.')
        if url.endswith('/status'):
            if method != 'GET' or body.get('busy') is not False or type(body.get('queued')) is not int or body['queued'] != 0:
                raise RuntimeError('Official stop is busy/queued; no unload or termination.')
        elif method != 'POST' or body.get('status') not in ('unloaded', 'not loaded'):
            raise RuntimeError('Official unload was not confirmed; no termination.')
        else:
            if body['status'] == 'not loaded':
                health = manager.get_json('/health')
                if (health.get('service') != 'strata' or health.get('status') != 'ok'
                        or health.get('model') != state['model']
                        or health.get('max_context') != state['context']
                        or health.get('loaded') is not False):
                    raise RuntimeError('Already-unloaded health was not confirmed; no termination.')
            unloaded = True
        return status, body

    def guarded_terminate(pid, ident):
        if not unloaded:
            raise RuntimeError('No successful official unload; termination prohibited.')
        validate_owner('after unload, before termination')
        if pid != state['pid'] or ident != state['official_tracking']['ident']:
            raise RuntimeError('Official termination identity changed.')
        return terminate(pid, ident)

    def no_tree_kill(*args, **kwargs):
        raise RuntimeError('Official process did not exit; tree-kill prohibited. Review exact ownership.')

    # Reject unknown/busy HTTP status before the native method can POST /unload.
    validate_owner()
    health = manager.get_json('/health')
    if health.get('service') != 'strata' or health.get('model') != state['model'] or health.get('max_context') != state['context']:
        raise RuntimeError('Official stop health identity mismatch.')
    with native_hooks(module, http_json=guarded_http, proc_terminate=guarded_terminate, proc_kill_tree=no_tree_kill):
        result = tools.strata_stop(port=18080, force=False)
    if not unloaded or result.get('engine_unloaded') not in ('unloaded', 'not loaded') or result.get('ended_cleanly') is not True:
        raise RuntimeError('Official graceful stop not confirmed; no descendant fallback.')
    return result


def adopt_current():
    """Hand over exact known ownership metadata without restarting or unloading."""
    import manage_runtime as manager
    import strata_cli as cli
    with cli.operation_lock(), manager.state_lock():
        state = manager.read_state()
        strata, _ = management()
        transaction_path = ROOT / 'records' / f'official-adoption-{state["pid"]}-{int(state["created"] * 1e6)}.json'
        official_path = strata.state_dir / 'server.json'
        if state.get('runtime_provider') == 'official_mcp' and strata.state('server') != state.get('official_tracking'):
            # Reverse partial rollback: local publication remains, but native
            # tracking was restored/deleted. Recover the proven old local bytes
            # BEFORE ready() consults the currently absent native tracking.
            prior = json.loads(transaction_path.read_text(encoding='utf-8')) if transaction_path.exists() else {}
            before = bytes.fromhex(prior.get('before_owned_hex', ''))
            previous_native = prior.get('before_official_hex')
            previous_native = bytes.fromhex(previous_native) if previous_native is not None else None
            old = json.loads(before.decode('utf-8')) if before else {}
            expected_tracking = state.get('official_tracking', {})
            current_owned = manager.STATE.read_bytes()
            if (prior.get('status') not in ('prepared', 'rollback_incomplete')
                    or prior.get('pid') != state['pid'] or prior.get('created') != state['created']
                    or prior.get('tracking') != expected_tracking
                    or prior.get('published_owned_sha256') != hashlib.sha256(current_owned).hexdigest()
                    or json.loads(current_owned.decode('utf-8')) != state
                    or prior.get('before_owned_sha256') != hashlib.sha256(before).hexdigest()
                    or any(state.get(key) != value for key, value in old.items())
                    or set(state) - set(old) != {'runtime_provider', 'official_tracking', 'official_adopted_utc'}
                    or (official_path.read_bytes() if official_path.exists() else None) != previous_native
                    or not manager.owned(state)
                    or native().proc_identity(state['pid']) != expected_tracking.get('ident')):
                raise RuntimeError('Incomplete adoption does not match our exact journal; metadata preserved.')
            restored = restore_if_equal(manager.STATE, current_owned, before)
            if not restored['restored']:
                raise RuntimeError('Exact local adoption rollback failed; live process unchanged.')
            state = manager.read_state()
        cli.Runtime().ready(state)
        target = require_registration(state['model'], state['context'])
        process = manager.owned(state)
        if process is None:
            raise RuntimeError('The known running server disappeared before handover.')
        ident = native().proc_identity(process.pid)
        if not ident:
            raise RuntimeError('Cannot obtain the official process identity.')
        tracking = dict(pid=process.pid, ident=ident, model=tag(state['model'], state['context']),
                        config=target.name, port=18080, log=state['log'],
                        started=state.get('started_utc'), adopted_from='owned-runtime.json',
                        actual_launch_config=state['config'])
        current = strata.tracked_server()
        recovering_forward_partial = False
        if current and not current.get('ended'):
            if state.get('runtime_provider') == 'official_mcp':
                require_tracking(state)
                return state
            # Recover ONLY our exact recorded partial adoption. Another owner is
            # never overwritten just because it happens to use the same port.
            prior = json.loads(transaction_path.read_text(encoding='utf-8')) if transaction_path.exists() else {}
            if (current != tracking or prior.get('tracking') != tracking
                    or prior.get('before_owned_sha256') != digest(manager.STATE)
                    or prior.get('pid') != state['pid'] or prior.get('created') != state['created']
                    or 'before_official_hex' not in prior
                    or prior.get('status') not in ('prepared', 'rollback_incomplete')):
                raise RuntimeError('Another official owner is present; adoption was not performed.')
            recovering_forward_partial = True
        before_owned = manager.STATE.read_bytes()
        before_official = official_path.read_bytes() if official_path.exists() else None
        # A second save failure during recovery must restore the ORIGINAL native
        # metadata, not the partial publication that we observed on this retry.
        rollback_official = before_official
        if recovering_forward_partial:
            rollback_official = bytes.fromhex(prior['before_official_hex']) if prior['before_official_hex'] is not None else None
        updated = dict(state, runtime_provider='official_mcp', official_tracking=tracking,
                       official_adopted_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
        published_owned = json.dumps(updated, indent=2).replace('\n', os.linesep).encode('utf-8')
        transaction = dict(status='prepared', pid=state['pid'], created=state['created'], tracking=tracking,
                           before_owned_sha256=hashlib.sha256(before_owned).hexdigest(),
                           before_owned_hex=before_owned.hex(), before_official_hex=rollback_official.hex() if rollback_official is not None else None,
                           published_owned_sha256=hashlib.sha256(published_owned).hexdigest())
        write_json(transaction_path, transaction)
        expected_owned = None
        try:
            if manager.read_state() != state or not manager.owned(state):
                raise RuntimeError('Owned runtime changed before handover; no metadata publication.')
            if (official_path.read_bytes() if official_path.exists() else None) != before_official:
                raise RuntimeError('Official tracking changed before publication; preserved.')
            # Delegate tracking publication to the unchanged official writer.
            strata.save_state('server', tracking)
            if strata.state('server') != tracking or manager.read_state() != state or not manager.owned(state):
                raise RuntimeError('Ownership changed during handover.')
            expected_owned = published_owned
            manager.save(updated)
            if manager.read_state() != updated or strata.state('server') != tracking or not manager.owned(updated):
                raise RuntimeError('Ownership changed before handover confirmation.')
            write_json(transaction_path, dict(transaction, status='completed', official_restart=False))
            return updated
        except BaseException as error:
            rollback = []
            # Compare exact publication bytes before restoring either file. A
            # newer owner's metadata is preserved and reported, never replaced.
            if expected_owned is not None:
                rollback.append(restore_if_equal(manager.STATE, expected_owned, before_owned))
            published = json.dumps(tracking, indent=1).replace('\n', os.linesep).encode('utf-8')
            rollback.append(restore_if_equal(official_path, published, rollback_official))
            transaction.update(status='rolled_back' if all(row['restored'] for row in rollback) else 'rollback_incomplete',
                               error_type=type(error).__name__, reason=str(error), rollback=rollback)
            try:
                write_json(transaction_path, transaction)
            except OSError as record_error:
                error.add_note('Adoption record failed: ' + type(record_error).__name__)
            raise


def write_json(path, value):
    temporary = path.with_name(path.name + f'.{time.time_ns()}.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.replace(path)


def restore_if_equal(path, published, original):
    try:
        current = path.read_bytes() if path.exists() else None
        if current == original:
            return dict(path=str(path), restored=True, unchanged=True)
        if current != published:
            return dict(path=str(path), restored=False, reason='newer_or_unknown_metadata_preserved')
        if original is None:
            path.unlink()
        else:
            temporary = path.with_name(path.name + f'.rollback.{time.time_ns()}.tmp')
            temporary.write_bytes(original)
            temporary.replace(path)
        return dict(path=str(path), restored=True)
    except OSError as error:
        return dict(path=str(path), restored=False, error_type=type(error).__name__)


def overview():
    import model_catalog as catalog
    strata, _ = management()
    configurations = []
    for model, item in catalog.CATALOG.items():
        if not item.get('selectable', True):
            continue
        for context in catalog.public_contexts(model):
            path = require_registration(model, context)
            configurations.append(strata.describe_config(path))
    return dict(provider='official Strata MCP (unchanged)', configurations=configurations,
                tracked=strata.tracked_server(), live=strata.probe(18080, deep=False))


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('register', 'adopt-current', 'status'))
    args = parser.parse_args()
    result = register_profiles() if args.action == 'register' else adopt_current() if args.action == 'adopt-current' else overview()
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
