import unittest
from unittest.mock import patch,Mock
from local_runtime import release_trial as t


class Trial(unittest.TestCase):
    def test_read_only_client_rejects_changed_state_before_zero_post_and_has_no_job_rights(self):
        from pathlib import Path
        from types import SimpleNamespace
        import tempfile
        from local_runtime import evaluate_r9700 as runner
        with tempfile.TemporaryDirectory() as td:
            log=Path(td)/'engine.log';log.write_text('',encoding='utf-8')
            state=dict(phase='ready',pid=1,engine_log=str(log))
            normal=SimpleNamespace(runner=runner,status=lambda:dict(running=True,state=dict(state,pid=2)))
            with patch.object(runner,'ready',side_effect=AssertionError('client has no foreground Job')),\
                 patch.object(runner.http.client,'HTTPConnection') as connection:
                with self.assertRaisesRegex(RuntimeError,'identity/state'):
                    t.request(normal,state,Mock(),'fixture')
            connection.assert_not_called()

    def test_read_only_release_gate_is_checked_each_poll_without_foreground_job_handle(self):
        from local_runtime import evaluate_r9700 as runner
        gate=Mock()
        with patch.object(runner.official_runtime,'require_tracking',side_effect=AssertionError('client must not claim Job handle')),\
             patch.object(runner.safety,'require_owned_listener'),patch.object(runner.time,'sleep'),\
             patch.object(runner.safety,'get_json',side_effect=[dict(busy=True,queued=0),dict(busy=False,queued=0)]):
            runner.wait_request_release({},ready_check=gate)
        self.assertEqual(gate.call_count,2)

    def test_status_and_post_generation_release_timeouts_are_not_generation_deadline(self):
        from pathlib import Path
        from types import SimpleNamespace
        import tempfile
        for phase in ('status','release'):
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as td:
                log=Path(td)/'engine.log';log.write_text('',encoding='utf-8')
                runner=Mock();normal=SimpleNamespace(runner=runner)
                def completed(*args,partial,**kwargs):partial.update(text='answer',finish_reason='stop')
                runner.stream_request.side_effect=TimeoutError('status probe') if phase=='status' else completed
                runner.wait_request_release.side_effect=TimeoutError('release proof not complete')
                sample=t.request(normal,dict(engine_log=str(log)),Mock(),'fixture')
                self.assertFalse(sample['censored'])
                self.assertEqual(sample['status'],'failed' if phase=='status' else 'cleanup_failed')
                self.assertEqual(sample['generation_status'],'failed' if phase=='status' else 'completed')

    def test_request_cannot_borrow_same_arm_from_other_manifest_or_round(self):
        from pathlib import Path
        import tempfile,json
        from types import SimpleNamespace
        from local_runtime import normal_runtime
        with tempfile.TemporaryDirectory() as td:
            directory=Path(td);other=directory/'other';other.mkdir()
            for folder,index in ((directory,0),(directory,9),(other,0)):
                (folder/f'start-{index}.claim').write_text('reserved',encoding='utf-8')
            actual=dict(manifest=str(directory/'manifest.json'),sha256='fixed',index=0)
            cfg=dict(args=['--prompt-cache','6'],env={},log=str(directory/'engine.log'),vision=dict(temp_dir=str(directory/'tmp')))
            profile=directory/'profile.json';profile.write_text(json.dumps(cfg),encoding='utf-8')
            snapshot=dict(cfg,args=['--prompt-cache','0'])
            normal=SimpleNamespace(selected=lambda:({},dict(profile=str(profile))),
                                   authority=lambda state:dict(trial=actual,snapshot_config=snapshot),cal=normal_runtime.cal)
            for wrong in (dict(actual,index=9),dict(actual,manifest=str(other/'manifest.json')),dict(actual,sha256='other')):
                fixed=dict(warmup='warm',fixture=[dict(content='four'),dict(content='twenty')])
                with patch.object(t,'validate',return_value=fixed),self.assertRaisesRegex(RuntimeError,'launch'):
                    t.reserve_request(normal,{},wrong)

    def test_deadline_sse_eof_or_late_terminal_is_timeout_censored_through_wrapper(self):
        import http.client,json,threading,tempfile
        from pathlib import Path
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from local_runtime import evaluate_r9700 as runner
        for late in (False,True):
            with self.subTest(late=late),tempfile.TemporaryDirectory() as td:
                released=threading.Event()
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self,*args):pass
                    def do_POST(self):
                        self.rfile.read(int(self.headers['Content-Length']));self.send_response(200)
                        self.send_header('Content-Type','text/event-stream');self.end_headers()
                        self.wfile.write(b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n');self.wfile.flush()
                        self.connection.settimeout(3);self.connection.recv(1)
                        if late:
                            try:
                                self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n');self.wfile.flush()
                            except OSError:pass
                        released.set()
                server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
                worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
                real_connection=http.client.HTTPConnection;real_stream=runner.stream_request
                def short_fixture(*args,**kwargs):
                    self.assertEqual(kwargs['deadline_s'],120);kwargs['deadline_s']=.2
                    return real_stream(*args,**kwargs)
                log=Path(td)/'engine.log';log.write_text('',encoding='utf-8')
                normal=Mock();normal.runner=runner
                try:
                    with patch.object(t,'client_ready'),patch.object(runner,'ready'),patch.object(runner,'wait_request_release'),\
                         patch.object(runner.safety,'get_json',return_value=dict(busy=False,queued=0)),\
                         patch.object(runner.http.client,'HTTPConnection',side_effect=lambda *a,**k:real_connection('127.0.0.1',server.server_port,timeout=3)),\
                         patch.object(runner,'stream_request',side_effect=short_fixture):
                        sample=t.request(normal,dict(engine_log=str(log)),Mock(),'fixture')
                    self.assertEqual(sample['status'],'timeout');self.assertTrue(sample['censored'])
                    self.assertEqual(sample['text'],'partial');self.assertTrue(sample['reader_stopped'])
                    self.assertTrue(released.wait(2));self.assertIn('client_terminal_at',sample)
                finally:server.shutdown();server.server_close();worker.join(2)

    def test_independent_watchdog_cuts_stalled_sse_and_preserves_partial_and_terminal_times(self):
        import http.client
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from local_runtime import evaluate_r9700 as runner
        released=threading.Event();active=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                self.wfile.write(b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n');self.wfile.flush()
                active.set()
                try:
                    self.connection.settimeout(3);self.connection.recv(1)
                finally:released.set()
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        real=http.client.HTTPConnection;sample={}
        monitor=Mock()
        def slow_monitor():
            if active.is_set():released.wait(.8)
        monitor.check.side_effect=slow_monitor
        try:
            with patch.object(runner,'ready'),patch.object(runner.safety,'get_json',return_value=dict(busy=False,queued=0)),\
                 patch.object(runner.http.client,'HTTPConnection',side_effect=lambda *a,**k:real('127.0.0.1',server.server_port,timeout=3)):
                with self.assertRaises((RuntimeError,TimeoutError,OSError)):
                    runner.stream_request({},monitor,'fixture',deadline_s=.2,partial=sample)
            self.assertTrue(released.wait(2))
            self.assertEqual(sample['text'],'partial')
            self.assertTrue(sample['reader_stopped'])
            self.assertGreaterEqual(sample['timeout_requested_monotonic'],sample['transport_started_monotonic']+.15)
            self.assertLess(sample['timeout_requested_monotonic']-sample['transport_started_monotonic'],.6)
            self.assertIn('transport_terminal_at',sample)
        finally:
            server.shutdown();server.server_close();worker.join(2)

    def test_only_finite_flag_pairs_and_all_rounds_are_predeclared(self):
        self.assertEqual(list(t.ARMS),['U','00','10','01','11'])
        self.assertEqual(len(t.ORDER)*len(t.ORDER[0]),15)
        self.assertEqual(t.LIMITS,dict(starts=15,requests=45,request_seconds=120,max_tokens=128,rounds=3))
        for env in t.ARMS.values():
            self.assertFalse(set(env)-set(t.FLAGS))
            self.assertFalse(set(env.values())-{'0','1'})

    def test_normal_body_preserves_output_thinking_and_retry_defaults(self):
        body=t.body('task')
        for key in ('max_tokens','reasoning_effort','thinking','retry'):
            self.assertNotIn(key,body)
        fixed=t.body('fixture',quantitative=True)
        self.assertEqual(fixed['max_tokens'],128)
        self.assertEqual(fixed['temperature'],0)
        self.assertNotIn('reasoning_effort',fixed)

    def test_cold_checker_accepts_reasoning_but_rejects_cached_or_incomplete(self):
        case=dict(prompt_tokens=4096)
        sample=dict(status='completed',reasoning='actual thinking',text='',censored=False,
                    first_token_seconds=1,wall_seconds=2,
                    usage=dict(prompt_tokens=4096,completion_tokens=128,prompt_tokens_details=dict(cached_tokens=0)),
                    timings=dict(prompt_n=4096,cache_n=0,predicted_n=128,prompt_ms=1,prompt_per_second=1,predicted_ms=1,predicted_per_second=1))
        log='prompt 4096 tokens = 0 reused + 4096 read'
        self.assertEqual(t.cold_errors(sample,case,log),[])
        sample['usage']['prompt_tokens_details']['cached_tokens']=1
        self.assertTrue(t.cold_errors(sample,case,log))
        sample['usage']['prompt_tokens_details']['cached_tokens']=0;sample['censored']=True
        self.assertTrue(t.cold_errors(sample,case,log))

    def test_quantitative_request_cannot_bypass_manifest_and_request_budget(self):
        with self.assertRaisesRegex(RuntimeError,'authority'):
            t.request(None,None,None,'arbitrary',quantitative=True)


if __name__=='__main__':unittest.main()
