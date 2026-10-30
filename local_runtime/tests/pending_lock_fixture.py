"""CPU-only LCR proof process. Never load a native engine or send HTTP."""
import _thread
import contextlib
import importlib.util
import json
import msvcrt
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from unittest.mock import Mock,patch

from local_runtime import evaluate_r9700 as runner,manifest


def probe(path):
    with Path(path).open('r+b') as stream:
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            print('blocked')
            return
        msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
        print('acquired')


def hold(root,data):
    runner.safety.STATE = root/'state.json'  # Only fixture-owned tracking.
    config = root/'config.json'
    config.write_text(json.dumps(dict(exe=sys.executable)),encoding='utf-8')
    child = subprocess.Popen([sys.executable,'-B','-c',
        'import pathlib,sys,time; p=pathlib.Path(sys.argv[1]);\nwhile not p.exists(): time.sleep(.05)',str(root/'child-exit')])
    process = runner.psutil.Process(child.pid)
    identity = dict(pid=child.pid,created=process.create_time(),exe=process.exe())
    state = dict(pid=child.pid,config=str(config),created=identity['created'],owned_identities=[identity],
                 cleanup_pending=True,spawn_observation=dict(created=identity['created'],identities=[identity],unknown=[],errors=[]))
    retained = dict(spawn_possible=True,process=child,state=state)
    result = dict(status='failed',error_type='RuntimeError',reason='fixture cleanup failed',post_count=0)
    signal.signal(signal.SIGINT,signal.default_int_handler)
    def send_signals():
        for index in (1,2):
            while not (root/f'signal-{index}').exists(): time.sleep(.02)
            _thread.interrupt_main(signal.SIGINT)
    threading.Thread(target=send_signals,daemon=True).start()
    with runner.shared_operation(data=data):
        (root/'holding').write_text(json.dumps(identity),encoding='utf-8')
        runner.hold_pending_cleanup(retained,result,root)
        if child.wait(timeout=5) != 0:
            raise RuntimeError('CPU child did not exit voluntarily')
    (root/'released').write_text(json.dumps(dict(signals=retained.get('deferred_signals',[]),result=result)),encoding='utf-8')
    raise SystemExit(42)  # Original evaluation failure stays a failure.


def old_boundary(root):
    """Execute unmodified old start + locks; stub preflight/assets, not boundary."""
    sys.path.insert(0,str(manifest.DATA))
    import strata_cli as cli
    import manage_runtime as manager
    import huihui_authority as authority
    manager.ROOT = cli.ROOT = root
    manager.STATE = root/'records/owned-runtime.json'
    profile = root/'profiles/fixture-262144.json'
    class Marker(RuntimeError): pass
    def marker(*args,**kwargs):
        print('START-MARKER',flush=True)
        raise Marker('CPU-only stop before native launch')
    env = dict(HIP_VISIBLE_DEVICES='0',TEMP=str(root),TMP=str(root))
    server = Mock()
    server.child_env.return_value = env
    real_import = __import__('importlib').import_module
    def import_module(name,*args):
        return server if name == 'serve.server' else real_import(name,*args)
    rt = Mock()
    rt.state.side_effect = manager.read_state
    rt.active.side_effect = manager.runtime_active
    rt.start.side_effect = manager.start
    with patch.object(authority,'require_context'),patch.object(authority,'check_monitor'), \
            patch.object(manager,'require_ready',return_value=root/'fixture.bin'), \
            patch.object(manager,'validate_profile'),patch.object(manager,'validate_layout'), \
            patch.object(manager,'source_receipts',return_value=[]), \
            patch.object(manager.official_runtime,'require_registration',return_value=profile), \
            patch.object(manager.runtime_temp_probe,'probe_temporary_environment',return_value=({},{})), \
            patch.object(manager.official_runtime,'windows_temp_probe',return_value=contextlib.nullcontext()), \
            patch('importlib.import_module',side_effect=import_module), \
            patch.object(manager.official_runtime,'start',side_effect=marker):
        try:
            cli.start_selected(rt,'fixture',262144)
        except Marker:
            return
        except (RuntimeError,OSError) as error:
            print('BOUNDARY-BLOCKED '+str(error),flush=True)
            return
    raise RuntimeError('Old start did not reach an identified boundary')


if __name__ == '__main__':
    action = sys.argv[1]
    if action == 'probe': probe(sys.argv[2])
    elif action == 'hold': hold(Path(sys.argv[2]),Path(sys.argv[3]))
    elif action == 'old-boundary': old_boundary(Path(sys.argv[2]))
