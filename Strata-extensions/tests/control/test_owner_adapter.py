"""T24 isolated tests: existing manager/CLI helpers, exclusively owned fixtures."""
import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
import uuid

EXT=Path(__file__).resolve().parents[2]
DATA=Path('C:/Develop/AI/Strata-data')
sys.path.insert(0,str(DATA))
import psutil
import manage_runtime as manager
import strata_cli as cli

def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

binding=load('t24_bootstrap',EXT/'control/bootstrap_binding.py')
adapter=load('t24_owner',EXT/'control/owner_adapter.py')
BUILD=None
EVIDENCE=[]

class OwnerTests(unittest.TestCase):
    def setUp(self):
        self.root=BUILD/('case-'+self._testMethodName+'-'+uuid.uuid4().hex)
        self.assertTrue(self.root.resolve().is_relative_to(BUILD.resolve()))
        (self.root/'records').mkdir(parents=True)
        self.old=(manager.ROOT,manager.STATE,manager.PORT,cli.ROOT)
        manager.ROOT=self.root;manager.STATE=self.root/'records/owned-runtime.json';manager.PORT=0;cli.ROOT=self.root
        self.children=[]
    def tearDown(self):
        for process,release,ready in reversed(self.children):
            release.write_text('release',encoding='utf-8')
            try:process.wait(timeout=8)
            except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=8)
            out,err=process.communicate()
            if err:EVIDENCE.append(dict(case=self._testMethodName,fixture_stderr=err))
        manager.ROOT,manager.STATE,manager.PORT,cli.ROOT=self.old
    def launch(self,*,unknown=False,publish=True,fault=None):
        case=self.root/('spawn-'+str(len(self.children)));(case/'repo/serve').mkdir(parents=True)
        profile=case/'profile.json';profile.write_text('{"model":"deepseek-owner-fixture","context":128}',encoding='utf-8')
        wrapper=case/'repo/serve/server.py'
        wrapper.write_text('import runpy\nrunpy.run_path('+repr(str(Path(__file__).with_name('owned_child.py')))+',run_name="__main__")\n',encoding='utf-8')
        ready=case/'ready.json';release=case/'release';snapshot_path=case/'snapshot.json'
        executable=str(Path(sys._base_executable).resolve())
        command=[executable,'-B','-m','serve.server','--config',str(profile),'--snapshot',str(snapshot_path),'--ready',str(ready),'--release',str(release)]
        if unknown:command.append('--unknown-child')
        target=dict(model_id='deepseek-owner-fixture',context=128,bundle_id='b'*64,tokenizer_identity='1'*64,
                    asset_revision='f924b94f19c1fea02c06a65c8475b0a45e2b88b1',runtime_epoch=7,
                    placement=dict(mode='single',primary='fixture-device',secondary=None),binary=executable,
                    profile=str(profile),cwd=str(case/'repo'),argv=command)
        parent=manager.captured_identity(psutil.Process())
        snapshot=binding.freeze_launch(target,str(uuid.uuid4()),parent)
        snapshot_path.write_text(json.dumps(snapshot),encoding='utf-8')
        environment=dict(os.environ,PYTHONUTF8='1',PYTHONPATH=str(Path(psutil.__file__).parent.parent))
        def spawn():
            if publish and not unknown:
                intent=manager.read_state();self.assertEqual(intent['phase'],'starting');self.assertEqual(intent['attempt'],snapshot['attempt'])
                self.assertNotIn('pid',intent)
            process=subprocess.Popen(command,cwd=target['cwd'],env=environment,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                     text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
            self.children.append((process,release,ready));return process
        def observe(process):
            root=manager.captured_identity(psutil.Process(process.pid));unknowns=[];errors=[]
            cohort=[psutil.Process(process.pid)]+manager.descendants(psutil.Process(process.pid),str(profile),False,unknowns,errors)
            return root,dict(created=root['created'],identities=[manager.captured_identity(p) for p in cohort],unknown=[dict(pid=p.pid) for p in unknowns],errors=errors)
        def await_hello(process,state):
            if publish and not unknown:
                saved=manager.read_state();self.assertEqual(saved['phase'],'loading');self.assertEqual(saved['pid'],process.pid)
            if fault=='crash':process.terminate();process.wait(timeout=8);raise RuntimeError('fixture crash before READY')
            if fault in ('cancel','cleanup_failure'):raise RuntimeError('fixture cancel before READY')
            until=time.monotonic()+8
            while True:
                try:
                    if ready.exists():hello=json.loads(ready.read_text(encoding='utf-8'));break
                except PermissionError:pass # Test-owned atomic publication may still hold rename handle.
                if process.poll() is not None:
                    out,err=process.communicate();raise AssertionError('owned fixture failed: '+out+err)
                if time.monotonic()>until:raise AssertionError('owned fixture startup timeout (test only)')
                time.sleep(.01)
            manager.PORT=hello['port']
            # Re-observe full cohort after child creation, before readiness.
            root,observation=observe(process);state.update(root,owned_identities=observation['identities'],spawn_observation=observation)
            return hello
        if publish and not unknown:
            with cli.operation_lock():state,hello,process=adapter.start_fixture(manager,snapshot,spawn,observe,await_hello)
        else:
            process=spawn();root,observation=observe(process)
            state=dict(root,config=str(profile),owned_identities=observation['identities'])
            hello=await_hello(process,state)
            state.update(model=target['model_id'],context=128,runtime_epoch=7,bundle_id=target['bundle_id'],snapshot_id=snapshot['snapshot_id'],attempt=snapshot['attempt'],runtime_provider='t24_fixture',phase='loading')
            if publish:manager.save(state)
        EVIDENCE.append(dict(case=self._testMethodName,root={k:state[k] for k in ('pid','created','exe')},cohort=state['owned_identities'],port=hello['port'],unknown=state['spawn_observation']['unknown'],generation_qualified=False))
        return state,snapshot,hello,process
    def test_owned_cohort_ready_stop_and_port_reuse(self):
        state,snapshot,hello,process=self.launch()
        with cli.operation_lock(),manager.state_lock():adapter.check_confirmed(state,manager.read_state());adapter.check_handshake(state,snapshot,hello,manager)
        stopped=adapter.stop_confirmed(manager,state,snapshot)
        process.wait(timeout=8);self.assertIn(process.pid,stopped)
        self.assertEqual(manager.read_state()['phase'],'stopped');manager.check_port_available(manager.PORT)
        next_state,next_snapshot,next_hello,_=self.launch()
        adapter.check_handshake(next_state,next_snapshot,next_hello,manager)
    def test_pid_birth_and_executable_mismatch_do_not_stop(self):
        state,snapshot,_,process=self.launch()
        wrong=dict(state,created=state['created']+1)
        self.assertEqual(manager.process_identity_status(wrong).status,'gone')
        wrong=dict(state,exe=str(self.root/'different.exe'))
        self.assertEqual(manager.process_identity_status(wrong).status,'unverifiable')
        self.assertIsNone(process.poll())
    def test_confirmed_race_preserves_process(self):
        state,snapshot,_,process=self.launch();changed=dict(state,runtime_epoch=8);manager.save(changed)
        with self.assertRaises(ValueError):adapter.stop_confirmed(manager,state,snapshot)
        self.assertIsNone(process.poll())
    def test_target_profile_change_before_mutation(self):
        state,snapshot,_,process=self.launch();Path(state['config']).write_text('changed target',encoding='utf-8')
        with cli.operation_lock(),self.assertRaises(ValueError):adapter.stop_confirmed(manager,state,snapshot)
        self.assertIsNone(process.poll())
    def test_bootstrap_parent_argv_attempt_and_half_json(self):
        _,snapshot,_,process=self.launch();parents=[manager.captured_identity(psutil.Process())]
        binding.verify_bootstrap(snapshot,snapshot['target']['argv'],parents)
        for field,value in [('attempt','wrong'),('snapshot_id','0'*64)]:
            wrong=dict(snapshot,**{field:value})
            with self.assertRaises(ValueError):binding.verify_bootstrap(wrong,snapshot['target']['argv'],parents)
        with self.assertRaises(ValueError):binding.verify_bootstrap(snapshot,snapshot['target']['argv']+['changed'],parents)
        with self.assertRaises(ValueError):binding.verify_bootstrap(snapshot,snapshot['target']['argv'],[])
        manager.STATE.write_text('{"pid":',encoding='utf-8')
        with self.assertRaises(json.JSONDecodeError):adapter.stop_confirmed(manager,{'pid':process.pid},snapshot)
        self.assertIsNone(process.poll())
    def test_handshake_epoch_and_stage_do_not_grant_ready(self):
        state,snapshot,hello,_=self.launch()
        for key,value in [('runtime_epoch',8),('snapshot_id','0'*64),('attempt',str(uuid.uuid4())),('scope','official-runtime')]:
            with self.subTest(key=key),self.assertRaises(ValueError):adapter.check_handshake(state,snapshot,dict(hello,**{key:value}),manager)
        with self.assertRaises(ValueError):adapter.check_handshake(state,snapshot,{'phase':'engine_ready'},manager)
    def test_unknown_child_preflight_no_termination(self):
        state,snapshot,_,process=self.launch(unknown=True)
        with self.assertRaises(Exception):adapter.stop_confirmed(manager,state,snapshot)
        saved=manager.read_state();self.assertEqual(saved['phase'],'cleanup_pending');self.assertIsNone(process.poll())
        self.assertTrue(state['spawn_observation']['unknown'])
        for row in state['spawn_observation']['unknown']:self.assertTrue(psutil.pid_exists(row['pid']))
    def test_foreign_listener_rejected_and_survives(self):
        state,snapshot,hello,process=self.launch();original_port=manager.PORT
        _,_,foreign,other=self.launch(publish=False)
        with self.assertRaises(manager.OwnershipUnverifiable):adapter.stop_confirmed(manager,state,snapshot)
        with self.assertRaises(RuntimeError):manager.check_port_available(foreign['port'])
        self.assertIsNone(process.poll());self.assertIsNone(other.poll());manager.PORT=original_port
        adapter.check_handshake(state,snapshot,hello,manager)
    def test_unverifiable_inspection_cleanup_pending(self):
        state,snapshot,_,process=self.launch()
        with patch.object(manager,'process_identity_status',return_value=manager.IdentityStatus('unverifiable',reason='fixture denied')):
            with self.assertRaises(manager.OwnershipUnverifiable):adapter.stop_confirmed(manager,state,snapshot)
        self.assertEqual(manager.read_state()['phase'],'cleanup_pending');self.assertIsNone(process.poll())
    def test_cleanup_failure_not_stopped_or_ready(self):
        state,snapshot,_,process=self.launch()
        with patch.object(manager,'stop_owned',side_effect=RuntimeError('injected cleanup failure')):
            with self.assertRaises(RuntimeError):adapter.stop_confirmed(manager,state,snapshot)
        self.assertEqual(manager.read_state()['phase'],'cleanup_pending');self.assertIsNone(process.poll())
    def test_retained_popen_cleanup_only_our_spawn(self):
        # No child tree, no model/GPU: exact Popen handle is existing manager's
        # narrow fallback when inspection has no trustworthy birth record yet.
        process=subprocess.Popen([sys._base_executable,'-B','-c','import time;time.sleep(30)'],creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            report=manager.cleanup_spawn_handle(process,dict(identities=[],unknown=[],errors=[]),self.root/'unused.json',include_identities=False)
            self.assertEqual(report['status'],'completed');self.assertIsNotNone(process.poll())
        finally:
            if process.poll() is None:process.terminate();process.wait(timeout=8)
    def test_gone_root_saved_child_cleanup_and_foreign_unknown(self):
        for mode in ('foreign','unknown','success'):
            state,snapshot,_,process=self.launch()
            saved=[row for row in state['owned_identities'] if row['pid']!=process.pid and Path(row['exe']).name.lower()=='python.exe']
            self.assertTrue(saved)
            process.terminate();process.wait(timeout=8)
            self.assertEqual(manager.process_presence(process.pid),'gone')
            self.assertTrue(psutil.pid_exists(saved[0]['pid']))
            if mode=='foreign':
                _,_,_,foreign=self.launch(publish=False)
                with self.assertRaises(manager.OwnershipUnverifiable):adapter.stop_confirmed(manager,state,snapshot)
                self.assertIsNone(foreign.poll());self.assertTrue(psutil.pid_exists(saved[0]['pid']))
                # Release only our foreign fixture and retry old cleanup later.
                self.children[-1][1].write_text('release',encoding='utf-8');foreign.wait(timeout=8)
            elif mode=='unknown':
                original=manager.process_identity_status
                def denied(row,**kwargs):
                    return manager.IdentityStatus('unverifiable',reason='fixture child denied') if row.get('pid')==saved[0]['pid'] else original(row,**kwargs)
                with patch.object(manager,'process_identity_status',side_effect=denied):
                    with self.assertRaises(manager.OwnershipUnverifiable):adapter.stop_confirmed(manager,state,snapshot)
                self.assertTrue(psutil.pid_exists(saved[0]['pid']))
            manager.PORT=0 # Gone-root listener is absent; explicit ephemeral reuse probe.
            stopped=adapter.stop_confirmed(manager,state,snapshot)
            self.assertIn(saved[0]['pid'],stopped);self.assertEqual(manager.read_state()['phase'],'stopped')

    def test_new_attempt_does_not_overwrite_live_owner(self):
        state,_,_,process=self.launch()
        with self.assertRaises(RuntimeError):self.launch()
        self.assertEqual(manager.read_state()['attempt'],state['attempt']);self.assertIsNone(process.poll())

    def test_pre_ready_crash_cancel_and_cleanup_failure(self):
        for fault in ('crash','cancel','cleanup_failure'):
            old=subprocess.Popen([sys._base_executable,'-B','-c','import time;time.sleep(30)'],creationflags=subprocess.CREATE_NO_WINDOW)
            old_identity=manager.captured_identity(psutil.Process(old.pid));old.terminate();old.wait(timeout=8)
            manager.save(dict(old_identity,phase='ready',attempt='old-ready'))
            if fault=='cleanup_failure':
                with patch.object(manager,'cleanup_spawn_handle',return_value=dict(status='failed',error='fixture cleanup denied')):
                    with self.assertRaises(RuntimeError):self.launch(fault=fault)
            else:
                with self.assertRaises(RuntimeError):self.launch(fault=fault)
            state=manager.read_state();self.assertNotEqual(state['attempt'],'old-ready')
            self.assertIn(state['phase'],('failed','cleanup_pending'))
            if fault=='cleanup_failure':self.assertEqual(state['phase'],'cleanup_pending')
            self.assertIn('pid',state)
            if fault!='cleanup_failure':self.assertIsNotNone(self.children[-1][0].poll())

    def test_real_lock_contention_and_order(self):
        script='''import sys,pathlib
sys.path.insert(0,r'C:\\Develop\\AI\\Strata-data')
import manage_runtime as m,strata_cli as c
m.ROOT=c.ROOT=pathlib.Path(sys.argv[1]);m.STATE=m.ROOT/'records/owned-runtime.json'
try:
 with (c.operation_lock() if sys.argv[2]=='cli' else m.state_lock()):print('acquired')
except RuntimeError as e:print(e);sys.exit(3)
'''
        for label,lock in [('cli',cli.operation_lock),('manager',manager.state_lock)]:
            with lock():
                result=subprocess.run([sys.executable,'-B','-c',script,str(self.root),label],capture_output=True,text=True,encoding='utf-8',errors='replace')
                self.assertEqual(result.returncode,3);self.assertNotIn('acquired',result.stdout)
        order=[];original_cli=cli.operation_lock;original_manager=manager.state_lock
        @contextlib.contextmanager
        def outer():
            with original_cli():order.append('cli');yield
        @contextlib.contextmanager
        def inner():
            with original_manager():order.append('manager');yield
        with outer(),inner():pass
        self.assertEqual(order,['cli','manager'])

def main():
    global BUILD
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    output=Path(args.output).resolve();BUILD=EXT.parent/'build-deepseek-t24'
    if not output.is_relative_to(BUILD.resolve()):raise ValueError('test output must remain in T24 generated root')
    stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(OwnerTests))
    report=dict(scope='test-owned process/port fixtures only; not official DeepSeek startup',tests=result.testsRun,
                failures=len(result.failures),errors=len(result.errors),successful=result.wasSuccessful(),evidence=EVIDENCE,log=stream.getvalue())
    output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(stream.getvalue())
    return 0 if result.wasSuccessful() else 1

if __name__=='__main__':raise SystemExit(main())


