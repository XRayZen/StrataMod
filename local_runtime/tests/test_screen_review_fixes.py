"""SCR01..03: exact engine loss, critical loader gate, and failed sample evidence."""
import contextlib
import copy
import http.client
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch

from local_runtime import manifest,benchmark,evaluate_r9700 as runner


class ScreenReviewFixes(unittest.TestCase):
    def test_active_engine_loss_cancels_real_sse_and_retains_partial_text(self):
        active,released = threading.Event(),threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):
                pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200)
                self.send_header('Content-Type','text/event-stream')
                self.end_headers()
                self.wfile.write(b'data: {"choices":[{"delta":{"content":"partial text"}}]}\n\n')
                self.wfile.flush()
                active.set()
                try:
                    self.connection.settimeout(5)
                    self.connection.recv(1)
                finally:
                    released.set()
        server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        worker = threading.Thread(target=server.serve_forever,daemon=True)
        worker.start()
        monitor = runner.MemoryMonitor('unused')
        monitor.engine = dict(pid=100,created=10.)
        real_connection = http.client.HTTPConnection
        def connect(*args,**kwargs):
            return real_connection('127.0.0.1',server.server_port,timeout=kwargs['timeout'])
        def identity(*args):
            return runner.safety.IdentityStatus('gone' if active.is_set() else 'verified',Mock())
        partial = {}
        try:
            with patch.object(runner,'ready'), \
                    patch.object(runner.safety,'get_json',return_value=dict(busy=False,queued=0)), \
                    patch.object(runner.safety,'process_identity_status',side_effect=identity), \
                    patch.object(runner.http.client,'HTTPConnection',side_effect=connect):
                with self.assertRaisesRegex(RuntimeError,'engine'):
                    runner.stream_request({},monitor,'fixture',deadline_s=5,partial=partial)
            self.assertTrue(released.wait(2))
            self.assertEqual(partial['text'],'partial text')
            self.assertTrue(monitor.abort.is_set())
        finally:
            server.shutdown()
            server.server_close()
            worker.join(2)

    def test_engine_gone_reused_or_unverifiable_aborts_but_expected_stop_exit_does_not(self):
        for status in ('gone','unverifiable'):
            with self.subTest(status=status):
                monitor = runner.MemoryMonitor('unused')
                monitor.engine = dict(pid=100,created=10.)
                with patch.object(runner.safety,'process_identity_status',return_value=runner.safety.IdentityStatus(status)), \
                        self.assertRaisesRegex(RuntimeError,'engine'):
                    monitor.check()
                self.assertTrue(monitor.abort.is_set())
        monitor = runner.MemoryMonitor('unused')
        monitor.engine = dict(pid=100,created=10.)
        monitor.expect_engine_exit()
        with patch.object(runner.safety,'process_identity_status') as inspect:
            monitor.check()
        inspect.assert_not_called()

    def test_engine_loss_before_post_prevents_http(self):
        monitor = runner.MemoryMonitor('unused')
        monitor.engine = dict(pid=100,created=10.)
        with patch.object(runner.safety,'process_identity_status',return_value=runner.safety.IdentityStatus('gone')), \
                patch.object(runner,'ready'),patch.object(runner.safety,'get_json',return_value=dict(busy=False,queued=0)), \
                patch.object(runner.http.client,'HTTPConnection') as connection:
            with self.assertRaisesRegex(RuntimeError,'engine'):
                runner.stream_request({},monitor,'fixture')
        connection.assert_not_called()

    def test_missing_foreign_or_mismatched_critical_module_is_not_comparison_eligible(self):
        fixed = {str(manifest.ORIGINAL/'engine'/name):'a'*64 for name in manifest.CRITICAL_DLLS}
        build = dict(rocm='fixed',hipblaslt_version=100500)
        good = dict(build=build,modules=[dict(path=path,sha256=sha,manifest_sha256=sha,matched=True)
                                       for path,sha in fixed.items()])
        with patch.object(manifest,'read_json',return_value=build):
            manifest.require_loader_binding(good,fixed)
            for kind in ('missing','foreign','mismatch','version'):
                changed = copy.deepcopy(good)
                if kind == 'missing':
                    changed['modules'].pop()
                if kind == 'foreign':
                    changed['modules'][0]['path'] = str(Path('C:/foreign')/Path(changed['modules'][0]['path']).name)
                if kind == 'mismatch':
                    changed['modules'][0]['sha256'] = 'b'*64
                if kind == 'version':
                    changed['build']['rocm'] = 'other'
                with self.subTest(kind=kind),self.assertRaisesRegex(RuntimeError,'loader'):
                    manifest.require_loader_binding(changed,fixed)

    def test_stream_or_release_failure_saves_partial_and_original_error_then_no_more_posts(self):
        cases = [dict(name=name,prompt_tokens=n,initial_deadline_seconds=d,content='input',
                      input_sha256='input',token_sha256='tokens') for name,n,d in benchmark.LENGTHS]
        for kind in ('stream','release','ctrlc'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as folder:
                directory = Path(folder)
                log = directory/'engine.log'
                log.write_text('',encoding='utf-8')
                state,value,result = dict(engine_log=str(log)),dict(config=str(directory/'config.json'),
                    suite='screen',arm='baseline',protocol=benchmark.protocol(cases),max_posts=12,max_tokens=128),dict(post_count=0)
                original = KeyboardInterrupt('original ctrlc') if kind == 'ctrlc' else TimeoutError('original '+kind)
                def stream(*args,partial=None):
                    partial.update(text='partial answer',reasoning='',first_sse_seconds=.1)
                    log.write_text('partial engine progress\n',encoding='utf-8')
                    if kind != 'release':
                        raise original
                    return dict(partial)
                release = Mock(side_effect=[None,original] if kind == 'release' else None)
                with patch.object(manifest,'read_json',return_value=dict(tokenizer='fixture')), \
                        patch.object(manifest,'baseline_reference',return_value=None), \
                        patch.object(benchmark,'prompts',return_value=cases), \
                        patch.object(runner,'wait_request_release',release), \
                        patch.object(runner,'stream_request',side_effect=stream) as request:
                    with self.assertRaises(type(original)) as caught:
                        runner.screen(state,Mock(),value,result)
                self.assertIs(caught.exception,original)
                self.assertEqual(request.call_count,1)
                row = json.loads((directory/'samples.jsonl').read_text(encoding='utf-8'))
                self.assertFalse(row['valid'])
                self.assertEqual(row['sample']['text'],'partial answer')
                self.assertEqual(row['error_type'],type(original).__name__)
                self.assertEqual(row['case'],'short')
                self.assertEqual(row['deadline_seconds'],120)
                self.assertIn('partial engine progress',row['engine_log_delta'])

    def test_bad_loader_is_saved_before_no_post_and_normal_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            log = directory/'engine.log'
            log.write_text('',encoding='utf-8')
            value = dict(suite='screen',arm='baseline',config=str(directory/'config.json'),dependencies={})
            state = dict(startup_seconds=1,engine_log=str(log))
            observation = dict(build={},modules=[])
            with patch.object(manifest,'_verify_document',return_value=value),patch.object(manifest,'verify',return_value=value), \
                    patch.object(runner,'shared_operation',return_value=contextlib.nullcontext()), \
                    patch.object(runner,'production_inactive'),patch.object(runner,'preflight_budget',return_value={}), \
                    patch.object(runner,'MemoryMonitor'),patch.object(runner,'start_session',return_value=state), \
                    patch.object(runner,'loader_observation',return_value=(observation,{})), \
                    patch.object(manifest,'read_json',return_value=dict(rocm='test-build')), \
                    patch.object(runner,'screen') as screen,patch.object(runner,'wait_request_release'), \
                    patch.object(runner.safety,'save'),patch.object(runner.safety,'check_port_available'), \
                    patch.object(runner.safety,'stop_owned',return_value=[]) as stop:
                with self.assertRaisesRegex(RuntimeError,'loader'):
                    runner.run(directory/'manifest.json','approved')
            screen.assert_not_called()
            stop.assert_called_once()
            self.assertEqual(json.loads((directory/'loader-observation.json').read_text(encoding='utf-8')),observation)
            result = json.loads((directory/'result.json').read_text(encoding='utf-8'))
            self.assertFalse(result['comparison_eligible'])
            self.assertEqual(result['post_count'],0)
            self.assertEqual(result['cleanup']['status'],'passed')


if __name__ == '__main__':
    unittest.main()
