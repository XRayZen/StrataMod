"""Fixed Huihui 256K profile authority and explicit private validation scopes."""
import contextlib
import contextvars
import hashlib
import json
import os
from pathlib import Path
import psutil

ROOT = Path(__file__).resolve().parent
MODEL = 'huihui-ud-iq4_xs'
CONTEXT = 262144
AUTHORITY_SHA256 = 'b6c57ac90500b75504d752dd6fdec519a64cb34a00374ae26442bf99bea0e390'
VALIDATOR_SHA256 = '13794c1f7e8a8ab6958fca67cc15429031adf66cd99fca652c4bd240f600e3e5'
_scope = contextvars.ContextVar('huihui_validation_scope', default=None)
_monitor = contextvars.ContextVar('huihui_validation_monitor', default=None)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(root=ROOT):
    root = Path(root)
    path = root / 'records/huihui-256k-authority.json'
    if path.resolve() != path.absolute() or sha(path) != AUTHORITY_SHA256:
        raise RuntimeError('Fixed Huihui authority changed or linked.')
    data = json.loads(path.read_text(encoding='utf-8'))
    source = root / f'profiles/{MODEL}-{CONTEXT}.json'
    target = root.parent / 'Strata' / f'strata-{MODEL}-{CONTEXT}.json'
    if (data.get('schema_version') != 1 or data.get('model') != MODEL or data.get('context') != CONTEXT
            or data.get('revision') != '43b4c1a8871afcc27e37bf996a431528b3d957e5'
            or data.get('source') != str(source) or data.get('official_config') != str(target)
            or source.resolve() != source.absolute() or target.resolve() != target.absolute()
            or sha(source) != data.get('profile_sha256')
            or sha(root / f'records/ready-{MODEL}.json') != data.get('asset_ready_sha256')
            or sha(root / f'records/verified-pack-{MODEL}.json') != data.get('verified_pack_sha256')):
        raise RuntimeError('Huihui authority profile/asset/pack/path binding failed.')
    return data


@contextlib.contextmanager
def validation_scope(monitor=None):
    verify()
    token = _scope.set('start')
    monitor_token = _monitor.set(monitor)
    try:
        yield
    finally:
        _monitor.reset(monitor_token)
        _scope.reset(token)


def check_monitor():
    callback = _monitor.get()
    if callback is not None:
        callback()


@contextlib.contextmanager
def inspection_scope(model, context, config):
    data = verify()
    if model != MODEL or context != CONTEXT or str(config) != data['official_config']:
        raise RuntimeError('Inspection is restricted to the fixed Huihui configuration')
    token = _scope.set('inspect')
    try:
        yield
    finally:
        _scope.reset(token)


def launcher_identity(process=None):
    process = process or psutil.Process()
    return dict(pid=process.pid,created=process.create_time(),exe=process.exe())


def journal_path(verify_only=False):
    return (ROOT/'records/huihui-256k-activation-20261017T225750Z/bootstrap-preflight-v5-journal.json'
            if verify_only else ROOT/f'records/{MODEL}-{CONTEXT}-attempt5-final-result.json')


def check_launcher(identity, verify_only):
    from startup_progress import BASE_PYTHON
    process = psutil.Process(identity['pid'])
    actual = launcher_identity(process)
    script = ROOT/'validate_huihui.py'
    expected = [str(BASE_PYTHON),'-E','-s','-B','-X','utf8',str(script),
                'preflight' if verify_only else 'validate']
    command = process.cmdline()
    if (abs(actual['created']-identity['created']) > .00001
            or Path(actual['exe']).resolve() != Path(identity['exe']).resolve()
            or Path(actual['exe']).resolve() != BASE_PYTHON.resolve()
            or len(command) != len(expected) or command[1:] != expected[1:]
            or Path(command[0]).resolve() != BASE_PYTHON.resolve()
            or script.resolve() != script.absolute() or sha(script) != VALIDATOR_SHA256):
        raise RuntimeError('Private bootstrap parent identity/command/source mismatch')


def issue_bootstrap(attempt, stage, config, verify_only=False):
    from startup_progress import stage_path
    data = verify()
    if _scope.get() != 'start' or str(config) != data['official_config'] or Path(stage) != stage_path(attempt):
        raise RuntimeError('Bootstrap issuance is restricted to this private launch')
    path = journal_path(verify_only)
    journal = json.loads(path.read_text(encoding='utf-8'))
    parent = launcher_identity()
    check_launcher(parent,verify_only)
    if (journal.get('status') != 'running' or journal.get('post_count') != 0
            or journal.get('launcher_identity') != parent or journal.get('bootstrap')):
        raise RuntimeError('Private validation journal is not a fresh single launch')
    journal['bootstrap'] = dict(attempt=attempt,stage=str(stage),config=str(config),
        config_sha256=data['profile_sha256'],authority_sha256=AUTHORITY_SHA256,
        validator_sha256=VALIDATOR_SHA256,parent=parent,verify_only=verify_only)
    temporary = path.with_suffix('.bootstrap.tmp')
    temporary.write_text(json.dumps(journal,indent=2)+'\n',encoding='utf-8');temporary.replace(path)


@contextlib.contextmanager
def bootstrap_scope(model, context, config, attempt, stage, verify_only=False):
    import model_catalog as catalog
    from startup_progress import stage_path
    if model != MODEL or catalog.CATALOG[MODEL].get('selectable'):
        yield
        return
    data = verify()
    path = journal_path(verify_only)
    journal = json.loads(path.read_text(encoding='utf-8'))
    binding = journal.get('bootstrap',{})
    parent = launcher_identity(psutil.Process(os.getppid()))
    check_launcher(parent,verify_only)
    if (journal.get('status') != 'running' or journal.get('post_count') != 0
            or journal.get('launcher_identity') != parent
            or binding != dict(attempt=attempt,stage=str(stage),config=str(config),
                config_sha256=data['profile_sha256'],authority_sha256=AUTHORITY_SHA256,
                validator_sha256=VALIDATOR_SHA256,parent=parent,verify_only=verify_only)
            or Path(stage) != stage_path(attempt) or Path(stage).resolve() != Path(stage).absolute()):
        raise RuntimeError('Private bootstrap journal/config/stage/parent binding failed')
    claim = ROOT/'records'/f'huihui-bootstrap-{attempt}-claim.json'
    with claim.open('x',encoding='utf-8') as stream:
        json.dump(dict(binding=binding,child=launcher_identity()),stream)
    with inspection_scope(model,context,config):
        yield


def private_state(state):
    data = verify()
    if (state.get('model') != MODEL or state.get('context') != CONTEXT
            or state.get('runtime_provider') != 'official_mcp'
            or state.get('config') != data['official_config']):
        raise RuntimeError('Private Huihui persisted model/context/config binding failed.')


@contextlib.contextmanager
def cleanup_scope(state):
    private_state(state)
    token = _scope.set('cleanup')
    try:
        yield
    finally:
        _scope.reset(token)


def require_context(model, context, root=ROOT, *, for_start=False):
    import model_catalog as catalog
    if model == MODEL and context == CONTEXT and _scope.get() in (('start',) if for_start else ('start','cleanup','inspect')):
        verify(root)
        return
    catalog.require_public_context(model, context, root)


def registration_sha(model, context, root=ROOT):
    require_context(model, context, root)
    if model != MODEL or context != CONTEXT:
        raise RuntimeError('Only fixed Huihui 256K has extension authority.')
    return verify(root)['profile_sha256']
