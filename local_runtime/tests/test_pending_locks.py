"""LCR-01: failure ownership stays inside the production lock lifetime."""
import contextlib
import copy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock,patch

from local_runtime import evaluate_r9700 as runner,official_runtime as official,manifest


class RetainedLaunchTests(unittest.TestCase):
    def test_spawn_constructor_begin_and_save_failures_keep_original_handle(self):
        for kind in ('constructor','cancel','begin','save','uncertain_spawn'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as folder:
                config = Path(folder)/'strata-baseline.json'
                cfg = dict(log=str(Path(folder)/'engine.log'))
                value = dict(config=str(config),arm='baseline',environment={})
                process,observer,module,strata,tools = Mock(pid=100),Mock(),Mock(),Mock(),Mock()
                module.spawn_detached.return_value = process
                strata.state.return_value = {}
                if kind == 'uncertain_spawn':
                    module.spawn_detached.side_effect = KeyboardInterrupt('spawn uncertain')
                if kind == 'begin':
                    observer.begin.side_effect = RuntimeError('begin failed')
                constructor = KeyboardInterrupt('cancel') if kind == 'cancel' else RuntimeError('constructor failed')
                def start(**kwargs):
                    return kwargs['launcher']([str(manifest.PYTHON),str(manifest.ROOT/'serve/server.py'),
                        '--engine','strata','--config',str(config),'--port','18080'],
                        manifest.ROOT,config.parent/'native/server.log',os.environ)
                tools.strata_start.side_effect = start
                def save(state):
                    if kind == 'save' and state.get('pid'):
                        raise OSError('save failed')
                retained = {}
                with patch.object(manifest,'verify',return_value=value),patch.object(manifest,'read_json',return_value=cfg), \
                        patch.object(official,'management',return_value=(strata,tools)), \
                        patch.object(official,'native',return_value=module), \
                        patch.object(official,'clean_environment',return_value={}), \
                        patch.object(official,'SpawnObserver',side_effect=constructor if kind in ('constructor','cancel') else None,return_value=observer), \
                        patch.object(runner.safety,'save',side_effect=save):
                    with self.assertRaises(official.LaunchFailure) as caught:
                        official.start_candidate(Path('manifest.json'),'approved',retained=retained)
                self.assertTrue(retained['spawn_possible'])
                self.assertIs(retained['process'],None if kind == 'uncertain_spawn' else process)
                self.assertIs(caught.exception.process,retained['process'])


class PendingBarrierTests(unittest.TestCase):
    def test_signal_handler_restores_and_first_work_cancel_uses_monitor(self):
        import _thread
        previous = signal.getsignal(signal.SIGINT)
        retained = dict(spawn_possible=True)
        monitor = runner.MemoryMonitor('unused')
        monitor.cancel_requested = lambda:retained.get('cancel_requested',False)
        with runner.candidate_interrupts(retained):
            _thread.interrupt_main(signal.SIGINT)
            with self.assertRaisesRegex(KeyboardInterrupt,'cancel requested'):
                monitor.check()
        self.assertIs(signal.getsignal(signal.SIGINT),previous)
        with runner.candidate_interrupts({}):
            with self.assertRaises(KeyboardInterrupt):
                _thread.interrupt_main(signal.SIGINT)
        self.assertIs(signal.getsignal(signal.SIGINT),previous)

    def test_synchronous_systemexit_in_hold_persistence_stays_pending_until_proof(self):
        retained = dict(spawn_possible=True,state=dict(cleanup_pending=True))
        result = dict(status='failed',reason='original')
        checks = []
        def proof(context):
            checks.append(True)
            return dict(complete=len(checks)>=3)
        with tempfile.TemporaryDirectory() as folder,patch.object(runner,'pending_exit_proof',side_effect=proof), \
                patch.object(runner.time,'sleep'),patch.object(runner.safety,'save',side_effect=[SystemExit('save cancelled'),None,None]):
            runner.hold_pending_cleanup(retained,result,Path(folder))
        self.assertEqual(len(checks),3)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['lock_hold_errors'][0]['error_type'],'SystemExit')
        self.assertTrue(result['cleanup']['lock_hold_proof']['complete'])

    def test_repeated_real_sigint_at_except_to_barrier_boundary_is_deferred(self):
        import _thread
        with tempfile.TemporaryDirectory() as folder:
            value = dict(arm='baseline',config=str(Path(folder)/'strata-baseline.json'),suite='smoke',max_tokens=32)
            state = dict(pid=100,startup_seconds=1,cleanup_pending=True)
            locked = []
            @contextlib.contextmanager
            def operation():
                locked.append(True)
                try: yield
                finally: locked.pop()
            def barrier(retained,result,directory):
                _thread.interrupt_main(signal.SIGINT)
                _thread.interrupt_main(signal.SIGINT)
                self.assertEqual(locked,[True])
                self.assertEqual(len(retained['deferred_signals']),2)
                state['cleanup_pending'] = False
            with patch.object(manifest,'_verify_document',return_value=value),patch.object(manifest,'verify',return_value=value),patch.object(runner,'shared_operation',side_effect=operation), \
                    patch.object(runner,'production_inactive'),patch.object(runner,'preflight_budget',return_value={}), \
                    patch.object(runner,'MemoryMonitor'),patch.object(runner,'start_session',return_value=state), \
                    patch.object(runner,'stream_smoke',side_effect=ValueError('original')), \
                    patch.object(runner,'wait_request_release',side_effect=RuntimeError('cleanup')), \
                    patch.object(runner.safety,'save'),patch.object(runner,'hold_pending_cleanup',side_effect=barrier):
                with self.assertRaisesRegex(ValueError,'original'):
                    runner.run(Path(folder)/'manifest.json','approved')

    def test_pre_ready_handle_context_survives_observer_and_persistence_failure(self):
        process = Mock(pid=100)
        retained = {}
        def launch(*args,**kwargs):
            kwargs['retained'].update(spawn_possible=True,process=process,observer=None)
            raise official.LaunchFailure(KeyboardInterrupt('observer constructor cancel'),process,None,{})
        with patch.object(manifest,'verify',return_value=dict(config='fixture.json')), \
                patch.object(manifest,'read_json',return_value=dict(log='fixture.log')), \
                patch.object(official,'start_candidate',side_effect=launch), \
                patch.object(runner.safety,'save',side_effect=OSError('persistence failed')):
            with self.assertRaises(official.LaunchFailure):
                runner.start_session(Path('manifest.json'),'approved',Mock(),retained=retained)
        self.assertIs(retained['process'],process)
        self.assertTrue(retained['spawn_possible'])
        self.assertTrue(retained['state']['cleanup_pending'])
        self.assertFalse(retained['state']['spawn_observation']['identities'])

    def test_cleanup_failure_waits_inside_shared_lock_and_keeps_original_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            value = dict(arm='baseline',config=str(root/'strata-baseline.json'),suite='smoke',max_tokens=32)
            state = dict(pid=100,startup_seconds=1,cleanup_pending=True)
            locked = []
            @contextlib.contextmanager
            def operation():
                locked.append(True)
                try: yield
                finally: locked.pop()
            def barrier(retained,result,directory):
                self.assertEqual(locked,[True])
                self.assertIs(retained['state'],state)
                self.assertEqual(result['status'],'failed')
                state['cleanup_pending'] = False
                result['cleanup'] = dict(status='passed')
            with patch.object(runner.manifest,'_verify_document',return_value=value),patch.object(runner.manifest,'verify',return_value=value), \
                    patch.object(runner,'shared_operation',side_effect=operation), \
                    patch.object(runner,'production_inactive'),patch.object(runner,'preflight_budget',return_value={}), \
                    patch.object(runner,'MemoryMonitor'),patch.object(runner,'start_session',return_value=state), \
                    patch.object(runner,'stream_smoke',side_effect=ValueError('original request failure')), \
                    patch.object(runner,'wait_request_release',side_effect=RuntimeError('cleanup failure')), \
                    patch.object(runner.safety,'save'),patch.object(runner,'hold_pending_cleanup',side_effect=barrier) as hold:
                with self.assertRaisesRegex(ValueError,'original request failure'):
                    runner.run(root/'manifest.json','approved')
            hold.assert_called_once()
            self.assertFalse(locked)

    def test_incomplete_unknown_error_and_unverifiable_never_prove_exit(self):
        row = dict(pid=100,created=1.,exe='python.exe')
        for kind in ('missing','unknown','error','unverifiable','presence'):
            with self.subTest(kind=kind):
                observation = dict(created=1.,identities=[row],unknown=[],errors=[])
                if kind == 'missing': observation.pop('created')
                if kind == 'unknown': observation['unknown'] = [dict(pid=101)]
                if kind == 'error': observation['errors'] = [dict(action='observe')]
                state = dict(config='fixture.json',owned_identities=[row],spawn_observation=observation)
                retained = dict(spawn_possible=True,state=state,process=None)
                with patch.object(runner.safety,'process_identity_status',return_value=runner.safety.IdentityStatus(
                        'unverifiable' if kind == 'unverifiable' else 'gone')), \
                        patch.object(runner.safety,'process_presence',return_value='present' if kind == 'presence' else 'gone'), \
                        patch.object(runner.safety,'check_port_available'):
                    self.assertFalse(runner.pending_exit_proof(retained)['complete'])

    def test_zero_spawn_preflight_failure_does_not_wait(self):
        with tempfile.TemporaryDirectory() as folder:
            value = dict(arm='baseline',config=str(Path(folder)/'strata-baseline.json'),suite='smoke')
            with patch.object(runner.manifest,'_verify_document',return_value=value),patch.object(runner.manifest,'verify',return_value=value), \
                    patch.object(runner,'shared_operation',return_value=contextlib.nullcontext()), \
                    patch.object(runner,'production_inactive',side_effect=RuntimeError('inactive gate')), \
                    patch.object(runner,'hold_pending_cleanup') as hold:
                with self.assertRaisesRegex(RuntimeError,'inactive gate'):
                    runner.run(Path(folder)/'manifest.json','approved')
            hold.assert_not_called()

    def test_retained_observer_late_unknown_cannot_be_lost_after_finish_cancel(self):
        row = dict(pid=100,created=1.,exe='python.exe')
        initial = dict(created=1.,identities=[row],unknown=[],errors=[])
        watcher = Mock()
        watcher.snapshot.return_value = dict(initial,unknown=[dict(pid=101)],errors=[dict(action='late')])
        state = dict(config='fixture.json',owned_identities=[row],spawn_observation=initial)
        retained = dict(spawn_possible=True,state=state,observer=watcher)
        with patch.object(runner.safety,'process_identity_status',return_value=runner.safety.IdentityStatus('gone')), \
                patch.object(runner.safety,'process_presence',return_value='gone'),patch.object(runner.safety,'check_port_available'):
            proof = runner.pending_exit_proof(retained)
        self.assertFalse(proof['complete'])
        self.assertEqual(proof['unknown'],[dict(pid=101)])
        self.assertEqual(state['spawn_observation']['errors'],[dict(action='late')])


class CpuLockProofTests(unittest.TestCase):
    def command(self,*args):
        # Run the base interpreter directly: Windows venv redirectors introduce
        # an extra live process, which is intentionally not an unknown resolver.
        bootstrap = ('import sys,runpy; sys.path.insert(0,sys.argv.pop(1)); '
                     'runpy.run_module("local_runtime.tests.pending_lock_fixture",run_name="__main__")')
        return [str(Path(sys.base_prefix)/'python.exe'),'-B','-X','utf8','-c',bootstrap,
                str(Path(sys.prefix)/'Lib/site-packages'),*map(str,args)]

    def wait_file(self,path,process):
        end = time.monotonic()+12
        while not path.exists():
            if process.poll() is not None or time.monotonic()>end:
                self.fail('CPU fixture stopped/timed out: '+str(path))
            time.sleep(.05)

    def fixture_root(self,root):
        (root/'records').mkdir()
        (root/'profiles').mkdir()
        (root/'tokenizer').mkdir()
        (root/'mtp/rt').mkdir(parents=True)
        for path in ('records/cli-operation.lock','records/runtime.lock','records/verified-hip.json',
                     'fixture.bin','tokenizer/vocab.json','mtp/rt/experts.bin'):
            (root/path).write_bytes(b'0')
        (root/'profiles/fixture-262144.json').write_text(json.dumps(dict(
            exe=str(root/'fixture.bin'),tokenizer=str(root/'tokenizer'),hip_ordinal=0,log='unused')),encoding='utf-8')

    @unittest.skipUnless(all((manifest.DATA/n).is_file() for n in ('strata_cli.py','manage_runtime.py','records/cli-operation.lock','records/runtime.lock','records/owned-runtime.json')),'private original manager/shared-lock boundary prerequisites not distributed')
    def test_real_old_paths_and_isolated_unmodified_callgraph_two_layer_proof(self):
        receipt = dict(first_layer=[],second_layer=[],signal_delivery='Two actual CPython SIGINT events via interrupt_main are deferred throughout failure cleanup; synchronous SystemExit separately covered')
        for real in (True,False):
            with self.subTest(real=real),tempfile.TemporaryDirectory(dir=manifest.LOCAL/'records') as folder:
                root = Path(folder)
                self.fixture_root(root)
                data = manifest.DATA if real else root
                paths = [data/'records'/name for name in ('cli-operation.lock','runtime.lock')]
                before = {str(path):path.read_bytes().hex() for path in paths}
                old_state = manifest.DATA/'records/owned-runtime.json'
                old_state_before = manifest.digest(old_state)
                parent = subprocess.Popen(self.command('hold',root,data),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
                try:
                    self.wait_file(root/'holding',parent)
                    self.wait_file(root/'result.json',parent)
                    identity = json.loads((root/'holding').read_text(encoding='utf-8'))
                    checks = []
                    for stage in ('initial','SIGINT-1','SIGINT-2'):
                        if stage != 'initial':
                            (root/('signal-1' if stage=='SIGINT-1' else 'signal-2')).touch()
                            end = time.monotonic()+8
                            while True:
                                try:
                                    result = json.loads((root/'result.json').read_text(encoding='utf-8'))
                                except (OSError,json.JSONDecodeError): result = {}
                                if len(result.get('deferred_signals',[])) >= (1 if stage=='SIGINT-1' else 2): break
                                self.assertLess(time.monotonic(),end,'Repeated signal not persisted')
                                time.sleep(.05)
                        for path in paths:
                            output = subprocess.check_output(self.command('probe',path),text=True,encoding='utf-8').strip()
                            self.assertEqual(output,'blocked')
                            checks.append(dict(stage=stage,path=str(path),offset=0,length=1,result=output))
                        self.assertIsNone(parent.poll())
                        if not real:
                            output = subprocess.check_output(self.command('old-boundary',root),text=True,encoding='utf-8')
                            self.assertIn('BOUNDARY-BLOCKED',output)
                            self.assertNotIn('START-MARKER',output)
                    (root/'child-exit').touch()
                    stdout,stderr = parent.communicate(timeout=15)
                    self.assertEqual(parent.returncode,42,(stdout,stderr))
                    released = json.loads((root/'released').read_text(encoding='utf-8'))
                    self.assertEqual(len(released['signals']),2)
                    self.assertEqual(released['result']['status'],'failed')
                    proof = released['result']['cleanup']['lock_hold_proof']
                    self.assertTrue(proof['complete'])
                    self.assertTrue(all(row['identity_status']=='gone' and row['presence']=='gone' for row in proof['members']))
                    for path in paths:
                        self.assertEqual(subprocess.check_output(self.command('probe',path),text=True,encoding='utf-8').strip(),'acquired')
                    if real:
                        self.assertEqual(before,{str(path):path.read_bytes().hex() for path in paths})
                        self.assertEqual(old_state_before,manifest.digest(old_state))
                    else:
                        output = subprocess.check_output(self.command('old-boundary',root),text=True,encoding='utf-8')
                        self.assertIn('START-MARKER',output)
                    receipt['first_layer' if real else 'second_layer'].append(dict(
                        paths=[str(path) for path in paths],checks=checks,identity=identity,proof=proof,
                        bytes_before=before,bytes_after={str(path):path.read_bytes().hex() for path in paths},
                        original_failure_exit=42,old_callgraph='start_selected -> operation_lock -> manager.start -> _start -> state_lock -> CPU-only official.start marker' if not real else None))
                    if real:
                        receipt['old_state_sha256_before'] = old_state_before
                        receipt['old_state_sha256_after'] = manifest.digest(old_state)
                finally:
                    (root/'child-exit').touch()
                    if parent.poll() is None:
                        parent.communicate(timeout=15)
        version = manifest.digest(Path(runner.safety.__file__))[:16]
        (manifest.LOCAL/f'records/pending-lock-cpu-proof-{version}.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
