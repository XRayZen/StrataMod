"""SR-01..06: environment, persistent cleanup, cancellation, assets, and baseline gate."""
import contextlib
import copy
import http.client
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch

from local_runtime import manifest,official_runtime as official,evaluate_r9700 as runner


class ReviewFixTests(unittest.TestCase):
    def test_sdk_python_path_and_tuning_pollution_are_deterministically_removed(self):
        cfg = dict(log=str(manifest.LOCAL/'runs/fixture/engine.log'),env={})
        clean = dict(SystemRoot='C:\\Windows',USERPROFILE='C:\\Users\\fixture')
        polluted = dict(clean,HIP_PATH='C:/foreign-sdk',HIP_DEVICE_LIB_PATH='C:/foreign-device',
                        LLVM_PATH='C:/foreign-llvm',ROCM_PATH='C:/other-rocm',PATH='C:/foreign-bin',
                        PYTHONPATH='C:/injected',PYTHONHOME='C:/injected-python',PYTHONSTARTUP='evil.py',
                        STRATA_HIPBLASLT_TUNING='foreign-table',HIP_VISIBLE_DEVICES='0',
                        CUDA_VISIBLE_DEVICES='0',OMP_NUM_THREADS='1')
        expected = manifest.normalized_environment(cfg,clean)
        self.assertEqual(manifest.normalized_environment(cfg,polluted),expected)
        self.assertNotIn('PYTHONPATH',expected)
        self.assertNotIn('HIP_DEVICE_LIB_PATH',expected)
        self.assertEqual(expected['HIP_PATH'],str(manifest.ORIGINAL/'engine/rocm'))

    def test_changed_prepared_environment_refuses_spawn(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = dict(log=str(Path(folder)/'engine.log'))
            env = manifest.normalized_environment(cfg,os.environ)
            env['PATH'] += ';changed'
            with self.assertRaisesRegex(RuntimeError,'environment'):
                official.clean_environment(cfg,os.environ,env)

    def test_cleanup_pending_blocks_even_when_no_pid_or_listener_remains(self):
        with patch.object(runner.safety,'read_state',return_value=dict(cleanup_pending=True)), \
                patch.object(runner.safety,'runtime_active',return_value=False), \
                self.assertRaisesRegex(RuntimeError,'cleanup'):
            runner.require_candidate_inactive()

    def test_birth_collection_failure_was_persisted_before_native_spawn(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder)/'strata-baseline.json'
            cfg = dict(log=str(Path(folder)/'engine.log'))
            value = dict(config=str(config),arm='baseline',environment=manifest.normalized_environment(cfg,os.environ))
            saved = []
            process,observer,module,strata,tools = Mock(pid=100),Mock(),Mock(),Mock(),Mock()
            observer.begin.side_effect = RuntimeError('birth unavailable')
            strata.state.return_value = {}
            def spawn(*args):
                self.assertTrue(saved[-1]['cleanup_pending'])
                self.assertEqual(saved[-1]['phase'],'spawning')
                return process
            module.spawn_detached.side_effect = spawn
            def start(**kwargs):
                command = [str(manifest.PYTHON),str(manifest.ROOT/'serve/server.py'),'--engine','strata',
                           '--config',str(config),'--port','18080']
                return kwargs['launcher'](command,manifest.ROOT,config.parent/'native/server.log',os.environ)
            tools.strata_start.side_effect = start
            with patch.object(manifest,'verify',return_value=value),patch.object(manifest,'read_json',return_value=cfg), \
                    patch.object(official,'management',return_value=(strata,tools)),patch.object(official,'native',return_value=module), \
                    patch.object(official,'SpawnObserver',return_value=observer), \
                    patch.object(runner.safety,'save',side_effect=lambda value:saved.append(copy.deepcopy(value))):
                with self.assertRaises(official.LaunchFailure):
                    official.start_candidate(Path('manifest.json'),'approved')
            self.assertEqual(saved[-1]['pid'],100)
            self.assertTrue(saved[-1]['cleanup_pending'])

    def test_missing_birth_unknown_child_or_cleanup_error_remains_pending(self):
        for kind in ('missing_birth','unknown_child','cleanup_error'):
            with self.subTest(kind=kind):
                observed = dict(identities=[],unknown=[],errors=[])
                if kind != 'missing_birth':
                    observed.update(created=10.,identities=[dict(pid=100,created=10.,exe='python.exe')])
                if kind == 'unknown_child':
                    observed['unknown'] = [dict(pid=101)]
                process,observer = Mock(pid=100),Mock()
                process.poll.return_value = None
                observer.finish.return_value = observed
                observer.snapshot.return_value = observed
                failed = dict(config='fixture.json',manifest='manifest.json',manifest_sha256='bound',cleanup_pending=True)
                with patch.object(runner.safety,'read_state',return_value=failed), \
                        patch.object(runner.safety,'save') as save, \
                        patch.object(runner.safety,'stop_owned',side_effect=RuntimeError('not proven')) as cleanup, \
                        patch.object(runner.safety,'check_port_available'):
                    runner.cleanup_failed_start(process,observer,failed)
                    self.assertTrue(save.call_args.args[0]['cleanup_pending'])
                    if kind != 'cleanup_error':
                        cleanup.assert_not_called()
                with patch.object(runner.safety,'read_state',return_value=save.call_args.args[0]):
                    with self.assertRaisesRegex(RuntimeError,'cleanup'):
                        runner.require_candidate_inactive()

    def test_mtp_four_files_and_expert_profile_are_bound(self):
        cfg = dict(exe=str(manifest.ORIGINAL/'engine/strata.exe'),args=[
            '--mtp',str(manifest.DATA/'mtp/rt'),'--expert-profile',str(manifest.ORIGINAL/'data/expert-profile.bin')])
        paths = manifest.dependency_paths(cfg,'baseline')
        for name in ('experts.bin','dense.bin','dense.txt','draft_vocab.bin'):
            self.assertIn(manifest.DATA/'mtp/rt'/name,paths)
        self.assertIn(manifest.ORIGINAL/'data/expert-profile.bin',paths)

    def test_same_size_mtp_or_profile_content_replacement_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ('experts.bin','dense.bin','dense.txt','draft_vocab.bin','expert-profile.bin'):
                path = Path(folder)/name
                path.write_bytes(b'original')
                fixed = {str(path):manifest.digest(path)}
                manifest.verify_dependencies([path],fixed)
                path.write_bytes(b'replaced')
                with self.subTest(name=name),self.assertRaisesRegex(RuntimeError,'dependency'):
                    manifest.verify_dependencies([path],fixed)

    def test_nonbaseline_smoke_is_refused_before_claim_or_start(self):
        for arm in manifest.ARMS[1:]:
            with self.subTest(arm=arm),patch.object(manifest,'_verify_document',return_value=dict(arm=arm,suite='smoke')), \
                    patch.object(manifest,'verify',return_value=dict(arm=arm,suite='smoke')), \
                    patch.object(runner,'start_session') as start:
                with self.assertRaisesRegex(RuntimeError,'baseline'):
                    runner.run(Path('unused'),'approved')
                start.assert_not_called()

    def test_budget_is_smaller_than_historical_resident_and_keeps_floors(self):
        self.assertEqual(manifest.RESIDENT_GIB,16)
        row = dict(available_bytes=68*runner.GIB,commit_margin_bytes=67*runner.GIB)
        with patch.object(runner,'memory_sample',return_value=row):
            self.assertEqual(runner.preflight_budget()['resident_gib'],16)
        with patch.object(runner,'memory_sample',return_value=dict(row,available_bytes=68*runner.GIB-1)):
            advisory=runner.preflight_budget()
            self.assertFalse(advisory['predicted_fits'])
            self.assertTrue(advisory['startup_prediction_advisory'])


class CancellationTransportTests(unittest.TestCase):
    def test_timeout_guard_and_ctrlc_close_transport_then_wait_for_idle_before_stop(self):
        for kind in ('timeout','guard','ctrlc'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as folder:
                active,released = threading.Event(),threading.Event()
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self,*args):
                        pass
                    def do_POST(self):
                        self.rfile.read(int(self.headers['Content-Length']))
                        active.set()
                        self.send_response(200)
                        self.send_header('Content-Type','text/event-stream')
                        self.end_headers()
                        self.wfile.flush()
                        try:
                            self.connection.settimeout(5)
                            self.connection.recv(1)
                        finally:
                            released.set()
                server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
                worker = threading.Thread(target=server.serve_forever,daemon=True)
                worker.start()
                real_connection = http.client.HTTPConnection
                def connect(*args,**kwargs):
                    return real_connection('127.0.0.1',server.server_port,timeout=kwargs['timeout'])
                monitor = Mock()
                if kind == 'guard':
                    def guard_check():
                        if active.is_set():
                            raise RuntimeError('guard abort')
                    monitor.check.side_effect = guard_check
                elif kind == 'ctrlc':
                    def cancel_check():
                        if active.is_set():
                            raise KeyboardInterrupt('user cancel')
                    monitor.check.side_effect = cancel_check
                def status(path):
                    return dict(busy=active.is_set() and not released.is_set(),queued=0)
                state = dict(pid=100,startup_seconds=1,cleanup_pending=True)
                value = dict(arm='baseline',suite='smoke',config=str(Path(folder)/'strata-baseline.json'),max_tokens=32)
                original_stream = runner.stream_smoke
                def stream(*args,**kwargs):
                    return original_stream(*args,**kwargs,deadline_s=.05 if kind == 'timeout' else 5)
                try:
                    with patch.object(manifest,'_verify_document',return_value=value),patch.object(manifest,'verify',return_value=value), \
                            patch.object(runner,'shared_operation',return_value=contextlib.nullcontext()), \
                            patch.object(runner,'production_inactive'),patch.object(runner,'preflight_budget',return_value={}), \
                            patch.object(runner,'MemoryMonitor') as monitor_class, \
                            patch.object(runner,'start_session',return_value=state),patch.object(runner,'ready'), \
                            patch.object(runner,'stream_smoke',side_effect=stream), \
                            patch.object(runner.http.client,'HTTPConnection',side_effect=connect), \
                            patch.object(runner.safety,'get_json',side_effect=status), \
                            patch.object(official,'require_tracking'),patch.object(runner.safety,'require_owned_listener'), \
                            patch.object(runner.safety,'save'),patch.object(runner.safety,'check_port_available'), \
                            patch.object(runner.safety,'stop_owned',side_effect=lambda state: [100] if released.is_set() else self.fail('stop before release')) as stop:
                        monitor_class.return_value.__enter__.return_value = monitor
                        expected_error = TimeoutError if kind == 'timeout' else KeyboardInterrupt if kind == 'ctrlc' else RuntimeError
                        with self.assertRaises(expected_error):
                            runner.run(Path('manifest.json'),'approved')
                    self.assertTrue(active.is_set())
                    self.assertTrue(released.is_set())
                    stop.assert_called_once()
                    result = json.loads((Path(folder)/'result.json').read_text(encoding='utf-8'))
                    self.assertEqual(result['cleanup']['status'],'passed')
                finally:
                    server.shutdown()
                    server.server_close()
                    worker.join(2)

    def test_unknown_owner_during_idle_wait_refuses_http_and_preserves_pending(self):
        with patch.object(official,'require_tracking',side_effect=RuntimeError('owner unknown')), \
                patch.object(runner.safety,'get_json') as get, \
                self.assertRaisesRegex(RuntimeError,'owner unknown'):
            runner.wait_request_release(dict(cleanup_pending=True),timeout_s=.01)
        get.assert_not_called()

    def test_busy_request_release_deadline_remains_pending(self):
        state = dict(cleanup_pending=True)
        with patch.object(official,'require_tracking'),patch.object(runner.safety,'require_owned_listener'), \
                patch.object(runner.safety,'get_json',return_value=dict(busy=True,queued=1)), \
                self.assertRaisesRegex(TimeoutError,'pending'):
            runner.wait_request_release(state,timeout_s=0)
        self.assertTrue(state['cleanup_pending'])


if __name__ == '__main__':
    unittest.main()
