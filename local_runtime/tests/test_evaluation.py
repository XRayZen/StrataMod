import contextlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

from local_runtime import evaluate_r9700 as runner,official_runtime as official


class SharedLockTests(unittest.TestCase):
    def test_old_cli_byte_lock_conflicts_without_changing_old_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            records = root/'records'
            records.mkdir()
            for name in ('cli-operation.lock','runtime.lock'):
                (records/name).write_bytes(b'unchanged fixture payload')
            code = ('import msvcrt,sys; f=open(sys.argv[1],"r+b"); '
                    'msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1); '
                    'print("locked",flush=True); sys.stdin.readline()')
            for name in ('cli-operation.lock','runtime.lock'):
                process = subprocess.Popen([sys.executable,'-B','-c',code,str(records/name)],
                                           stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
                try:
                    self.assertEqual(process.stdout.readline().strip(),'locked')
                    with self.assertRaisesRegex(RuntimeError,'shared lock'):
                        with runner.shared_operation(data=root):
                            self.fail('Conflicting production lock was ignored')
                finally:
                    process.communicate('\n',timeout=5)
            with runner.shared_operation(data=root):
                pass
            for path in records.iterdir():
                self.assertEqual(path.read_bytes(),b'unchanged fixture payload')

    def test_missing_production_lock_is_not_created(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'records').mkdir()
            with self.assertRaises(FileNotFoundError):
                with runner.shared_operation(data=root):
                    pass
            self.assertEqual(list((root/'records').iterdir()),[])


class MemoryTests(unittest.TestCase):
    def test_low_memory_requires_three_consecutive_samples(self):
        monitor = runner.MemoryMonitor('unused')
        low = dict(available_bytes=3*runner.GIB,commit_margin_bytes=20*runner.GIB)
        high = dict(available_bytes=8*runner.GIB,commit_margin_bytes=20*runner.GIB)
        monitor.observe(low)
        monitor.observe(low)
        monitor.check()
        monitor.observe(high)
        monitor.observe(low)
        monitor.observe(low)
        monitor.check()
        monitor.observe(low)
        with self.assertRaisesRegex(RuntimeError,'Memory guard'):
            monitor.check()

    def test_commit_emergency_is_immediate(self):
        monitor = runner.MemoryMonitor('unused')
        monitor.observe(dict(available_bytes=8*runner.GIB,commit_margin_bytes=runner.GIB))
        with self.assertRaisesRegex(RuntimeError,'2 GiB'):
            monitor.check()


class StopGuardTests(unittest.TestCase):
    def setUp(self):
        self.state = dict(pid=100,model='huihui-ud-iq4_xs',context=262144,
                          official_tracking=dict(ident='birth'))
        self.module = Mock()
        self.module.http_json.side_effect = [(200,dict(busy=False,queued=0)),(200,dict(status='unloaded'))]
        self.tools = Mock()
        def stop(**kwargs):
            kwargs['request']('http://127.0.0.1:18080/status')
            kwargs['request']('http://127.0.0.1:18080/unload','POST')
            kwargs['terminate'](100,'birth')
            return dict(ended_cleanly=True,engine_unloaded='unloaded')
        self.tools.strata_stop.side_effect = stop
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(official,'native',return_value=self.module))
        self.tracking = stack.enter_context(patch.object(official,'require_tracking',return_value=(None,self.tools)))
        stack.enter_context(patch.object(runner.safety,'require_owned_listener',return_value=True))
        stack.enter_context(patch.object(runner.safety,'get_json',return_value=dict(
            service='strata',model=self.state['model'],max_context=262144,loaded=True)))

    def test_normal_stop_delegates_after_confirmed_unload(self):
        self.assertTrue(official.stop(self.state)['ended_cleanly'])
        self.module.proc_terminate.assert_called_once_with(100,'birth')

    def test_busy_queued_or_unreadable_status_does_not_unload(self):
        for response in [(200,dict(busy=True,queued=0)),(200,dict(busy=False,queued=1)),
                         (200,dict(busy=False,queued=False)),(500,{})]:
            with self.subTest(response=response):
                self.module.reset_mock()
                self.module.http_json.side_effect = [response]
                with self.assertRaises(RuntimeError):
                    official.stop(self.state)
                self.module.proc_terminate.assert_not_called()
                self.assertEqual(self.module.http_json.call_count,1)

    def test_failed_unload_does_not_terminate(self):
        self.module.http_json.side_effect = [(200,dict(busy=False,queued=0)),(500,dict(status='unloaded'))]
        with self.assertRaises(RuntimeError):
            official.stop(self.state)
        self.module.proc_terminate.assert_not_called()

    def test_changed_owner_does_not_send_http(self):
        self.tracking.side_effect = RuntimeError('owner changed')
        with self.assertRaises(RuntimeError):
            official.stop(self.state)
        self.module.http_json.assert_not_called()

    def test_unexpected_tree_kill_is_refused(self):
        def stop(**kwargs):
            return kwargs['tree_kill'](100,'birth')
        self.tools.strata_stop.side_effect = stop
        with self.assertRaisesRegex(RuntimeError,'tree kill'):
            official.stop(self.state)
        self.module.proc_kill_tree.assert_not_called()


class LifecycleTests(unittest.TestCase):
    def test_nonready_memory_abort_preserves_exact_spawn_cleanup(self):
        observation = dict(created=10.,identities=[dict(pid=100,created=10.,exe='python.exe')],unknown=[],errors=[])
        process,observer,monitor = Mock(pid=100),Mock(),Mock()
        observer.snapshot.return_value = observation
        observer.finish.return_value = observation
        process.poll.return_value = None
        monitor.check.side_effect = RuntimeError('memory abort before READY')
        with patch.object(runner.manifest,'verify',return_value=dict(config='fixture.json')), \
                patch.object(runner.manifest,'read_json',return_value=dict(log='engine.log')), \
                patch.object(runner.official_runtime,'start_candidate',return_value=(process,observer,{},{})), \
                patch.object(runner.safety,'save'), \
                patch.object(runner.safety,'check_port_available'), \
                patch.object(runner.safety,'stop_owned') as cleanup:
            with self.assertRaisesRegex(RuntimeError,'memory abort'):
                runner.start_session(Path('manifest.json'),'approved',monitor)
        cleanup.assert_called_once()
        self.assertFalse(cleanup.call_args.kwargs['official_first'])
        self.assertEqual(cleanup.call_args.args[0]['owned_identities'],observation['identities'])
        process.terminate.assert_not_called()

    def test_generation_failure_still_stops_candidate_and_checks_port(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder)/'strata-baseline.json'
            value = dict(arm='baseline',config=str(config),suite='smoke',max_tokens=32)
            state = dict(pid=100,startup_seconds=1)
            with patch.object(runner.manifest,'_verify_document',return_value=value), \
                    patch.object(runner.manifest,'verify',return_value=value), \
                    patch.object(runner,'shared_operation',return_value=contextlib.nullcontext()), \
                    patch.object(runner,'production_inactive'),patch.object(runner,'preflight_budget',return_value={}), \
                    patch.object(runner,'MemoryMonitor'), \
                    patch.object(runner,'start_session',return_value=state), \
                    patch.object(runner,'wait_request_release'), \
                    patch.object(runner,'stream_smoke',side_effect=RuntimeError('generation failed')), \
                    patch.object(runner.safety,'stop_owned',return_value=[100]) as stop, \
                    patch.object(runner.safety,'check_port_available') as port,patch.object(runner.safety,'save'):
                with self.assertRaisesRegex(RuntimeError,'generation failed'):
                    runner.run(Path('manifest.json'),'approved')
            stop.assert_called_once_with(state)
            port.assert_called_once()
            result = json.loads((Path(folder)/'result.json').read_text(encoding='utf-8'))
            self.assertEqual(result['status'],'failed')
            self.assertEqual(result['cleanup']['status'],'passed')


if __name__ == '__main__':
    unittest.main()
