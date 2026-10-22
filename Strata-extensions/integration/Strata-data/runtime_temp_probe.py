"""Select official TEMP fallbacks with a bounded Low helper before server spawn."""
import json
import math
from pathlib import Path
import subprocess
import uuid

import official_runtime as official
import startup_progress
from runtime_permissions import handle_identity

ROOT = Path(__file__).resolve().parent
HELPER = ROOT / 'temp_probe_child.py'
TEMP_KEYS = {'TEMP', 'TMP', 'TMPDIR'}
RESULT_KEYS = {'version', 'attempt', 'config_sha256', 'server_sha256', 'mcp_sha256', 'setup_sha256',
               'helper_sha256', 'identity', 'parent_identity', 'sys_executable', 'prefix',
               'integrity_rid', 'temporary_environment'}


def same_identity(left, right):
    def valid(row):
        return (isinstance(row, dict) and set(row) == {'pid', 'created', 'exe'}
                and type(row['pid']) is int and row['pid'] > 0
                and type(row['created']) in (int, float) and math.isfinite(row['created'])
                and isinstance(row['exe'], str) and Path(row['exe']).is_absolute())
    return (valid(left) and valid(right) and left['pid'] == right['pid']
            and abs(left['created'] - right['created']) < .00001
            and Path(left['exe']).resolve() == Path(right['exe']).resolve())


def validate_result(result, root_identity, attempt, config_sha256, helper_sha256, family=None):
    cfg = family[1] if family else None
    python = Path(cfg['python']) if cfg else startup_progress.VENV_PYTHON
    prefix = python.parent.parent
    server_sha = official.digest(Path(cfg['exe']).parent / 'server/serve/server.py') if cfg else official.SERVER_SHA256
    if (not isinstance(result, dict) or set(result) != RESULT_KEYS
            or type(result.get('version')) is not int or result['version'] != 1
            or result['attempt'] != attempt or result['config_sha256'] != config_sha256
            or result['server_sha256'] != server_sha
            or result['mcp_sha256'] != official.MCP_SHA256 or result['setup_sha256'] != official.SETUP_SHA256
            or result['helper_sha256'] != helper_sha256
            or type(result['integrity_rid']) is not int or result['integrity_rid'] != 4096
            or not isinstance(result['sys_executable'], str) or not isinstance(result['prefix'], str)
            or Path(result['sys_executable']).resolve() != python.resolve()
            or Path(result['prefix']).resolve() != prefix.resolve()):
        raise RuntimeError('Low TEMP probe result authority/schema/token mismatch')
    identity = result['identity']
    if (not same_identity(identity, identity)
            or not same_identity(result['parent_identity'], result['parent_identity'])
            or Path(identity['exe']).resolve() != startup_progress.BASE_PYTHON.resolve()
            or not same_identity(root_identity, root_identity)
            or Path(root_identity['exe']).resolve() not in (python.resolve(), startup_progress.BASE_PYTHON.resolve())
            or not (same_identity(identity, root_identity)
                    or (identity['pid'] != root_identity['pid'] and same_identity(result['parent_identity'], root_identity)))):
        raise RuntimeError('Low TEMP probe redirector/helper identity binding failed')
    environment = result['temporary_environment']
    if (not isinstance(environment, dict) or not set(environment).issubset(TEMP_KEYS)
            or not all(isinstance(value, str) and value and '\0' not in value and Path(value).is_absolute()
                       for value in environment.values())):
        raise RuntimeError('Low TEMP probe returned invalid temporary environment')
    return dict(environment)


def require_exited(identity):
    import manage_runtime as manager
    if manager.process_identity_status(identity).status != 'gone':
        raise RuntimeError('Low TEMP helper exit is unverified; server spawn prohibited')


def probe_temporary_environment(model, context, config, environment, timeout=20):
    attempt, config = str(uuid.uuid4()), Path(config)
    config_sha256, helper_sha256 = official.digest(config), official.digest(HELPER)
    family = startup_progress.family_launch(config)
    if family and not family[2]:
        raise RuntimeError('Low TEMP family probe requires resolved launch binding')
    if not family and official.require_registration(model, context) != config:
        raise RuntimeError('Low TEMP probe configuration mismatch')
    python = family[1]['python'] if family else str(startup_progress.VENV_PYTHON)
    command = [python, '-E', '-s', '-B', '-X', 'utf8', str(HELPER),
               '--model', model, '--context', str(context), '--config', str(config),
               '--config-sha256', config_sha256, '--attempt', attempt]
    process, root_identity = None, None
    receipt = dict(version=1, attempt=attempt, command=command, status='unverified')
    record = ROOT / 'records' / f'startup-temp-probe-{attempt}.json'
    try:
        process = subprocess.Popen(command, cwd=official.REPO, env=dict(environment),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding='utf-8')
        root_identity = handle_identity(process._handle)
        receipt['root_identity'] = root_identity
        output, errors = process.communicate(timeout=timeout)
        receipt['helper_stdout'] = output
        receipt['helper_stderr'] = errors
        if process.returncode != 0:
            raise RuntimeError(f'Low TEMP probe exited {process.returncode}; server spawn prohibited')
        result = json.loads(output)
        selected = validate_result(result, root_identity, attempt, config_sha256, helper_sha256, family)
        if official.digest(config) != config_sha256 or official.digest(HELPER) != helper_sha256:
            raise RuntimeError('Low TEMP probe source/config changed before acceptance')
        require_exited(root_identity)
        require_exited(result['identity'])
        receipt.update(status='completed', result=result, root_and_helper_exited=True)
        record.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        print(f'[起動] Low権限の公式TEMP検査完了（RID {result["integrity_rid"]}）\n記録: {record}', flush=True)
        return selected, receipt
    except BaseException as error:
        receipt.update(status='failed', error_type=type(error).__name__, reason=str(error),
                       root_and_helper_exited=False)
        if process is not None and process.poll() is None:
            try:
                process.terminate()  # Retained redirector handle only; self-report never authorizes a kill.
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired) as cleanup_error:
                receipt['root_cleanup_error'] = type(cleanup_error).__name__
        # If identity or protocol collection failed we cannot claim the actual
        # helper ended. Its first-instruction self deadline is an additional guard.
        receipt['cleanup'] = 'root-handle-only; actual helper exit unverified'
        try:
            record.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        except OSError:
            pass
        raise
