from pathlib import Path
from types import SimpleNamespace
import copy,json,tempfile,unittest
from contextlib import ExitStack,contextmanager
from unittest.mock import Mock,patch

from local_runtime import pilot_authority as a,prefill_timing_pilot as p,manifest as m
from local_runtime import runtime_safety as s,official_runtime as official


class PilotRuntime(unittest.TestCase):
    def runtime(self,root):
        ctx=a.PilotContext(m.ROOT,root/'pilot',root/'normal',root/'original',root/'data')
        for path in (ctx.pilot,ctx.normal,ctx.original,ctx.data,ctx.runs):path.mkdir(parents=True,exist_ok=True)
        ctx.authority.write_text('{}',encoding='utf-8')
        obj=p.PilotRuntime.__new__(p.PilotRuntime);obj.ctx=ctx;obj.approved=m.digest(ctx.authority)
        obj.fixed=dict(parent_data_proof=dict(profile=dict(cwd='old',log='old',env={},args=['--prompt-cache','6'],
                     exe='C:/stock/strata.exe',vision=dict(exe='C:/stock/vision.exe',cpu_exe='C:/stock/vision-cpu.exe',temp_dir='old'))))
        return obj

    @contextmanager
    def request_fixture(self,root):
        pilot=self.runtime(root);directory,state,cfg=pilot.new_run(0)
        pilot.fixed['warmup']='fixture';pilot.fixed['fixture']=[]
        state.update(loader=dict(reader_backend='hip'),owned_identities=[dict(exe=cfg['exe']),dict(exe=cfg['vision']['exe'])])
        log=Path(cfg['log']);log.write_text('',encoding='utf-8');state['engine_log']=str(log)
        client=dict(pid=901,created=10.0,exe=str(pilot.ctx.python),argv=pilot.client_command(0,0))
        count=[0]
        def get_json(path):
            if path=='/metrics':
                value=dict(totals=dict(requests=count[0]));count[0]+=1;return value
            return dict(busy=False,queued=0)
        with ExitStack() as stack:
            for target,name,kwargs in (
                    (a,'load',{}),(pilot,'read_state',dict(return_value=state)),(pilot,'client_ready',{}),
                    (pilot,'actual_environment',dict(return_value=[])),(pilot,'actual_loader',dict(return_value={})),
                    (pilot,'authority',dict(return_value=dict(snapshot_config=cfg))),
                    (pilot,'capture_client',dict(return_value=client)),
                    (p.normal,'NormalMonitor',dict(return_value=Mock())),
                    (p.runner.safety,'get_json',dict(side_effect=get_json))):
                stack.enter_context(patch.object(target,name,**kwargs))
            yield pilot,state

    def test_midrun_authority_replacement_rejected_before_any_operation(self):
        with tempfile.TemporaryDirectory() as td:
            pilot=self.runtime(Path(td))
            with patch.object(a,'context_for_state',return_value=pilot.ctx):
                directory,state,cfg=pilot.new_run(0)
                self.assertEqual(pilot.authority(state)['snapshot_config'],cfg)
                pilot.ctx.authority.write_text('{"changed":true}',encoding='utf-8')
                with self.assertRaises(RuntimeError):pilot.authority(state)

    def test_canonical_two_old_locks_block_an_independent_cpu_process_without_byte_changes(self):
        import subprocess,sys,time,msvcrt
        data=a.NORMAL.parent/'Strata-data'
        paths=[data/'records'/name for name in ('cli-operation.lock','runtime.lock')]
        if not all(path.is_file() for path in paths):self.skipTest('canonical existing lock files unavailable')
        before=[(path.read_bytes(),path.stat().st_mtime_ns) for path in paths]
        site=a.NORMAL.parent/'Strata/.venv/Lib/site-packages'
        code='''import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1]);sys.path.insert(0,sys.argv[2])
from local_runtime import evaluate_r9700 as r
with r.shared_operation(data=Path(sys.argv[3])):
 Path(sys.argv[4]).write_text('holding',encoding='utf-8')
 sys.stdin.readline()
'''
        with tempfile.TemporaryDirectory() as td:
            ready=Path(td)/'ready'
            child=subprocess.Popen([sys._base_executable,'-I','-B','-X','utf8','-c',code,str(m.ROOT),str(site),str(data),str(ready)],
                                   stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                end=time.monotonic()+10
                while not ready.exists():
                    if child.poll() is not None:self.fail(str(child.communicate()))
                    self.assertLess(time.monotonic(),end);time.sleep(.02)
                for path in paths:
                    with path.open('r+b') as stream:
                        stream.seek(0)
                        with self.assertRaises(OSError):msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                child.communicate('\n',timeout=10);self.assertEqual(child.returncode,0)
            finally:
                if child.poll() is None:child.terminate();child.communicate(timeout=10)
        self.assertEqual(before,[(path.read_bytes(),path.stat().st_mtime_ns) for path in paths])

    def test_newkind_family_classifier_uses_immutable_snapshot_not_mutable_file(self):
        with tempfile.TemporaryDirectory() as td:
            pilot=self.runtime(Path(td));directory,state,cfg=pilot.new_run(0)
            (pilot.ctx.pilot/'records').mkdir();a.write(pilot.ctx.state,state)
            a.write(Path(state['config']),dict(exe='foreign.exe'))
            with patch.object(a,'production_context',return_value=pilot.ctx),patch.object(p.PilotRuntime,'attach',return_value=pilot),\
                 patch.object(pilot,'authority',return_value=dict(snapshot_config=cfg)):
                self.assertEqual(s.family_config(state['config']),cfg)

    def test_newkind_saves_only_private_state_and_foreign_root_rejects(self):
        with tempfile.TemporaryDirectory() as td:
            pilot=self.runtime(Path(td));(pilot.ctx.pilot/'records').mkdir()
            state=dict(kind=a.KIND,pilot_root=str(pilot.ctx.pilot),phase='cleanup-pending',cleanup_pending=True)
            old=Path(td)/'old-state.json'
            with patch.object(a,'production_context',return_value=pilot.ctx),patch.object(s,'STATE',old):
                s.save(state);self.assertTrue(pilot.ctx.state.is_file());self.assertFalse(old.exists())
                with self.assertRaises(RuntimeError):s.save(dict(state,pilot_root=str(pilot.ctx.normal)))

    def test_all_three_runtime_authorities_are_checked_and_pending_refuses(self):
        with tempfile.TemporaryDirectory() as td:
            pilot=self.runtime(Path(td))
            for path in (pilot.ctx.data/'records/owned-runtime.json',pilot.ctx.normal/'local_runtime/records/owned-runtime.json',pilot.ctx.state):
                path.parent.mkdir(parents=True,exist_ok=True);a.write(path,dict(cleanup_pending=False))
            with patch.object(s,'check_port_available') as port:
                proof=pilot.production_inactive();self.assertEqual(len(proof['states']),3);port.assert_called_once()
            a.write(pilot.ctx.normal/'local_runtime/records/owned-runtime.json',dict(cleanup_pending=True))
            with patch.object(s,'check_port_available') as port,self.assertRaisesRegex(RuntimeError,'normal'):
                pilot.production_inactive()
            port.assert_not_called()

    def test_unknown_or_alive_saved_birth_never_means_inactive(self):
        with tempfile.TemporaryDirectory() as td:
            pilot=self.runtime(Path(td))
            for path in (pilot.ctx.data/'records/owned-runtime.json',pilot.ctx.normal/'local_runtime/records/owned-runtime.json'):
                path.parent.mkdir(parents=True,exist_ok=True);a.write(path,dict(pid=1,created=1,cleanup_pending=False))
            for identity in (s.IdentityStatus('unverifiable',reason='denied'),s.IdentityStatus('verified',process=Mock())):
                with patch.object(s,'process_identity_status',return_value=identity),self.assertRaises(RuntimeError):pilot.production_inactive()

    def test_explicit_python_environment_cannot_inherit_parent_performance_flags(self):
        with tempfile.TemporaryDirectory() as td:
            pilot=self.runtime(Path(td));cfg=dict(exe='C:/stock/strata.exe',log=str(pilot.ctx.pilot/'run/engine.log'),vision=dict(reader_mode='official-bundle'))
            env=pilot.environment(cfg,dict(STRATA_PREFILL_TIMING='0',STRATA_HIPBLASLT_TUNING='foreign',PYTHONPATH='foreign',HIP_VISIBLE_DEVICES='0'))
            self.assertFalse(any(k.startswith('STRATA_') for k in env));self.assertNotIn('PYTHONPATH',env)
            self.assertEqual(env['__PYVENV_LAUNCHER__'],str(pilot.ctx.venv))
            self.assertEqual(Path(env['TEMP']),pilot.ctx.pilot/'run/tmp')
            self.assertEqual(Path(env['LOCALAPPDATA']),pilot.ctx.pilot/'run/user/AppData/Local')

    def test_readonly_client_never_uses_foreground_job_handle_and_checks_every_release_poll(self):
        from local_runtime import evaluate_r9700 as runner
        gate=Mock()
        with patch.object(runner.official_runtime,'require_tracking',side_effect=AssertionError('client has no Job handle')),\
             patch.object(runner.safety,'require_owned_listener'),patch.object(runner.time,'sleep'),\
             patch.object(runner.safety,'get_json',side_effect=[dict(busy=True,queued=0),dict(busy=False,queued=0)]):
            runner.wait_request_release({},ready_check=gate)
        self.assertEqual(gate.call_count,2)

    def test_client_request_refuses_other_index_with_zero_post_and_zero_claim(self):
        with tempfile.TemporaryDirectory() as td:
            pilot=self.runtime(Path(td))
            with patch.object(a,'load'),patch.object(pilot,'read_state',return_value=dict(pilot_index=0)),\
                 patch.object(p.runner.http.client,'HTTPConnection') as connection,patch.object(a,'reserve_request') as claim:
                with self.assertRaisesRegex(RuntimeError,'index'):pilot.request(1,0)
            connection.assert_not_called();claim.assert_not_called()

    def test_original_normal_and_oldtrial_kind_dispatches_are_not_replaced(self):
        normal_state=dict(kind='stratamod-normal-v1')
        with patch.object(p.normal,'require_tracking',return_value=('normal','tools')) as normal_call,\
             patch.object(p.PilotRuntime,'attach',side_effect=AssertionError('wrong dispatcher')):
            self.assertEqual(official.require_tracking(normal_state),('normal','tools'))
        normal_call.assert_called_once_with(normal_state)

    def test_wrong_newkind_root_rejects_before_tracking_or_stop(self):
        with tempfile.TemporaryDirectory() as td:
            pilot=self.runtime(Path(td));state=dict(kind=a.KIND,pilot_root=str(pilot.ctx.normal),pilot_authority_sha256=pilot.approved)
            with patch.object(a,'production_context',return_value=pilot.ctx),patch.object(official,'native') as native:
                with self.assertRaises(RuntimeError):official.require_tracking(state)
            native.assert_not_called()

    def test_distinct_owner_cannot_clear_client_reader_pending_when_native_gone(self):
        with tempfile.TemporaryDirectory() as td:
            pilot=self.runtime(Path(td));index=0
            (pilot.ctx.runs/'0').mkdir()
            (pilot.ctx.pilot/'start-0.claim').write_text('claim',encoding='utf-8')
            client=dict(pid=901,created=10.0,exe=str(pilot.ctx.python),argv=pilot.client_command(0,0))
            with patch.object(pilot,'authority',return_value={}),patch.object(pilot,'capture_client',return_value=client):
                registration=pilot.register_client(dict(pilot_index=index,authority_sha256='runsha'),0)
            a.reserve_request(pilot.ctx.pilot,0,0)
            local_client_state=dict(request_cleanup_pending=True)
            pilot.publish_reader(registration,local_client_state,dict(transport_started_at=1))
            # Another owner has a different state object and every native birth gone.
            owner=dict(owned_identities=[dict(pid=1,created=1)],spawn_observation=dict(created=1,identities=[],unknown=[],errors=[]))
            guard=p.ClientReaders(pilot,dict(pilot_index=0,authority_sha256='runsha'))
            with patch.object(s,'process_identity_status',side_effect=lambda row:s.IdentityStatus('verified',Mock()) if row['pid']==901 else s.IdentityStatus('gone')),\
                 patch.object(s,'process_presence',return_value='gone'),patch.object(s,'check_port_available'):
                proof=p.runner.pending_exit_proof(dict(state=owner,reader=guard))
            self.assertFalse(proof['complete']);self.assertTrue(proof['reader_cleanup_pending'])
            self.assertNotIn('request_cleanup_pending',owner)
            with patch.object(s,'process_identity_status',return_value=s.IdentityStatus('unverifiable')),\
                 patch.object(s,'process_presence',return_value='gone'):
                self.assertFalse(guard.close_reader(.05))
            with patch.object(s,'process_identity_status',return_value=s.IdentityStatus('gone')),\
                 patch.object(s,'process_presence',return_value='gone'):
                self.assertTrue(guard.close_reader(.05))
            self.assertEqual(guard.proof['members'][0]['proof'],'original_client_birth_and_presence_gone')

    def test_reader_positive_close_requires_exact_run_and_registration_binding(self):
        with tempfile.TemporaryDirectory() as td:
            pilot=self.runtime(Path(td));state=dict(pilot_index=0,authority_sha256='runsha')
            (pilot.ctx.runs/'0').mkdir()
            client=dict(pid=901,created=10.0,exe=str(pilot.ctx.python),argv=pilot.client_command(0,0))
            with patch.object(pilot,'authority',return_value={}),patch.object(pilot,'capture_client',return_value=client):
                registration=pilot.register_client(state,0)
            (pilot.ctx.pilot/'start-0.claim').write_text('claim',encoding='utf-8');a.reserve_request(pilot.ctx.pilot,0,0)
            pilot.publish_reader(registration,{},dict(transport_started_at=1,reader_stopped=True))
            guard=p.ClientReaders(pilot,state)
            self.assertTrue(guard.close_reader(.05))
            path=pilot.ctx.pilot/'request-0-0.reader.json';value=m.read_json(path)
            a.write(path,dict(value,registration_sha256='other'))
            self.assertFalse(guard.close_reader(.05))

    def test_status_or_release_timeout_never_becomes_generation_deadline(self):
        for phase in ('status','release'):
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as td,self.request_fixture(Path(td)) as (pilot,state):
                def completed(*args,partial,**kwargs):
                    partial.update(transport_started_at=1,reader_stopped=True,usage=dict(prompt_tokens=63),finish_reason='stop',text='answer')
                with patch.object(p.runner,'stream_request',side_effect=TimeoutError('status') if phase=='status' else completed),\
                     patch.object(p.runner,'wait_request_release',side_effect=TimeoutError('release')):
                    value=pilot.request(0,0)
                self.assertFalse(value['censored']);self.assertFalse(value['valid'])
                self.assertEqual(value['status'],'failed' if phase=='status' else 'cleanup_failed')
                self.assertTrue((pilot.ctx.pilot/'aborted.json').is_file())
                self.assertTrue(p.ClientReaders(pilot,state).close_reader(.05))

    def test_watchdog_eof_or_buffered_terminal_through_private_request_is_censored(self):
        import http.client,threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        for late in (False,True):
            with self.subTest(late=late),tempfile.TemporaryDirectory() as td,self.request_fixture(Path(td)) as (pilot,state):
                stopped=threading.Event()
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self,*args):pass
                    def do_POST(self):
                        self.rfile.read(int(self.headers['Content-Length']));self.send_response(200)
                        self.end_headers();self.wfile.write(b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n');self.wfile.flush()
                        self.connection.settimeout(3);self.connection.recv(1)
                        if late:
                            try:self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n');self.wfile.flush()
                            except OSError:pass
                        stopped.set()
                server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
                worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
                real_connection=http.client.HTTPConnection;real_stream=p.runner.stream_request
                def short(*args,**kwargs):
                    self.assertEqual(kwargs['deadline_s'],120);kwargs['deadline_s']=.2
                    return real_stream(*args,**kwargs)
                try:
                    with patch.object(p.runner.http.client,'HTTPConnection',side_effect=lambda *args,**kwargs:real_connection('127.0.0.1',server.server_port,timeout=3)),\
                         patch.object(p.runner,'stream_request',side_effect=short):
                        value=pilot.request(0,0)
                    self.assertEqual(value['status'],'timeout');self.assertTrue(value['censored']);self.assertFalse(value['valid'])
                    self.assertTrue(value['reader_stopped']);self.assertEqual(value['text'],'partial');self.assertTrue(stopped.wait(2))
                finally:server.shutdown();server.server_close();worker.join(2)

    def test_actual_text_environment_rejects_timing0_extra_flags_reader_leak_or_private_root_drift(self):
        for bad in ('timing0','extra','reader','userroot','stock'):
            with self.subTest(bad=bad),tempfile.TemporaryDirectory() as td:
                pilot=self.runtime(Path(td));directory,state,cfg=pilot.new_run(0)
                state.update(loader=dict(reader_backend='hip'),owned_identities=[dict(exe=cfg['exe'],created=1),dict(exe=cfg['vision']['exe'],created=2)])
                env={**pilot.environment(cfg,{}),'HIP_VISIBLE_DEVICES':'1'}
                text={**env,**a.ARMS['00-unset'],**p.DEFAULTS};reader=dict(env)
                if bad=='timing0':text['STRATA_PREFILL_TIMING']='0'
                elif bad=='extra':text['STRATA_UNKNOWN']='1'
                elif bad=='reader':reader['STRATA_HIP_WMMA']='0'
                elif bad=='userroot':text['USERPROFILE']='foreign'
                else:text['STRATA_GDN_PP']='3'
                proc1=Mock();proc1.environ.return_value=text;proc2=Mock();proc2.environ.return_value=reader
                def status(row):return s.IdentityStatus('verified',proc1 if row['exe']==cfg['exe'] else proc2)
                with patch.object(pilot,'authority',return_value=dict(snapshot_config=cfg)),patch.object(s,'process_identity_status',side_effect=status),\
                     patch.object(pilot,'require_child_command'),self.assertRaises(RuntimeError):pilot.actual_environment(state)

    def test_changed_stock_default_observation_across_arms_refuses(self):
        with tempfile.TemporaryDirectory() as td:
            pilot=self.runtime(Path(td));directory,state,cfg=pilot.new_run(0)
            state.update(loader=dict(reader_backend='hip'),owned_identities=[dict(exe=cfg['exe'],created=1),dict(exe=cfg['vision']['exe'],created=2)])
            a.write(directory/'ready.json',dict(actual_environment=[dict(observed_stock_defaults=p.DEFAULTS),dict(observed_stock_defaults={})]))
            env={**pilot.environment(cfg,{}),'HIP_VISIBLE_DEVICES':'1'}
            proc1=Mock();proc1.environ.return_value={**env,**a.ARMS['00-unset']};proc2=Mock();proc2.environ.return_value=env
            def status(row):return s.IdentityStatus('verified',proc1 if row['exe']==cfg['exe'] else proc2)
            with patch.object(pilot,'authority',return_value=dict(snapshot_config=cfg)),patch.object(s,'process_identity_status',side_effect=status),\
                 patch.object(pilot,'require_child_command'),self.assertRaisesRegex(RuntimeError,'across'):pilot.actual_environment(state)
