"""CPU-only normal observer/positive cleanup contracts; no live GPU/API."""
import contextlib,copy,ctypes,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from local_runtime import normal_runtime as n,official_runtime as o,runtime_safety as s,checked_job as j
class NormalObserverRepairTests(unittest.TestCase):
 def fixture(self):
  config=str(n.RUNS/'unit/strata-StrataMod.json')
  cfg={'exe':str(n.m.ROOT/'engine-unit.exe'),'vision':{'exe':str(n.m.ROOT/'vision-unit.exe')}}
  command=[str(n.m.PYTHON),str(n.m.ROOT/'serve/server.py'),'--config',config]
  state={'kind':n.KIND,'config':config,'authority':str(n.RUNS/'unit/authority.json'),'owned_identities':[{'pid':7,'created':1,'exe':'root.exe'}],'spawn_observation':{'created':1,'identities':[{'pid':7,'created':1,'exe':'root.exe'}],'unknown':[],'errors':[]}}
  return state,cfg,command
 def test_normal_snapshot_avoids_state_reads_and_keeps_expected_child_argv(self):
  state,cfg,command=self.fixture();parent=Mock(pid=7);parent.cmdline.return_value=command;parent.exe.return_value='root.exe';parent.create_time.return_value=1
  child=Mock(pid=8);child.exe.return_value=cfg['exe'];child.cmdline.return_value=['exact-engine'];child.create_time.return_value=2;parent.children.return_value=[child]
  fixed={'snapshot_config':cfg,'command':command,'snapshot':'snapshot.json','receipt':'receipt.json'}
  with patch.object(n,'authority',return_value=fixed),patch.object(n,'expected_child_commands',return_value={str(Path(cfg['exe']).resolve()):['exact-engine']}):
   watcher=o.SpawnObserver.for_normal(Mock(pid=7),state)
  cfg['exe']='foreign.exe'
  with patch.object(o.psutil,'Process',return_value=parent),patch.object(s,'read_state',side_effect=AssertionError('mutable STATE reopened')):
   watcher.capture();self.assertEqual([x['pid'] for x in watcher.snapshot()['identities']],[7,8]);self.assertFalse(watcher.snapshot()['unknown'])
   child.cmdline.return_value=['same-exe-foreign-arguments']
   with self.assertRaises(RuntimeError):watcher.capture()
 def test_default_observer_keeps_existing_descendant_path(self):
  state,cfg,command=self.fixture();parent=Mock(pid=7);parent.cmdline.return_value=command;parent.exe.return_value='root';parent.create_time.return_value=1
  with patch.object(o.psutil,'Process',return_value=parent),patch.object(s,'descendants',return_value=[]) as descendants:
   o.SpawnObserver(Mock(pid=7),state['config']).capture();descendants.assert_called_once()
 def test_error_metadata_never_includes_payload_or_exception_text(self):
  err=PermissionError(13,'secret payload',str(n.RUNS/'unit/authority.json'));err.winerror=5
  row=o.observation_error(err,'normal_authority_read',allowed_paths=[err.filename])
  self.assertEqual(row['operation'],'normal_authority_read');self.assertEqual(row['winerror'],5);self.assertEqual(row['errno'],13);self.assertNotIn('secret',str(row));self.assertNotIn('reason',row)
 def test_checked_job_members_requires_original_handle(self):
  with patch.object(j,'_parent_job',None):
   with self.assertRaises(RuntimeError):j.active_members()
 def proof_fixture(self):
  state,cfg,command=self.fixture();state['spawn_observation']['errors']=[{'action':'observe','operation':'normal_authority_read','error_type':'PermissionError','filename':state['authority']}]
  process=Mock(pid=7);process.poll.return_value=1
  return {'state':state,'process':process,'observer':None}
 def test_typed_io_history_is_retained_but_positive_job_exit_can_complete(self):
  retained=self.proof_fixture();before=copy.deepcopy(retained['state'])
  with patch.object(n,'authority',return_value={}),patch.object(j,'active_members',return_value={os.getpid()}),patch.object(s,'process_identity_status',return_value=s.IdentityStatus('gone')),patch.object(s,'process_presence',return_value='gone'),patch.object(j,'original_birth_exit',return_value={'original_gone':True,'windows':{'status':'absent'}}),patch.object(s,'check_port_available'):
   proof=n.positive_failed_cleanup_proof(retained);self.assertTrue(proof['complete']);self.assertEqual(proof['historical_errors'],before['spawn_observation']['errors']);self.assertEqual(retained['state'],before)
 def test_actual_unknown_metadata_or_job_error_never_becomes_clean(self):
  for fault in ('unknown','metadata','job_member','job_query','identity','persisted_error'):
   with self.subTest(fault=fault):
    retained=self.proof_fixture()
    if fault=='unknown':retained['state']['spawn_observation']['unknown']=[{'pid':99}]
    if fault=='metadata':retained['state']['spawn_observation']['errors'][0]['operation']='capture_child_metadata'
    if fault=='persisted_error':retained['state']['cleanup_observation']={'errors':[{'action':'incomplete_exit_proof'}]}
    with patch.object(n,'authority',return_value={}),patch.object(j,'active_members',side_effect=OSError() if fault=='job_query' else None,return_value={os.getpid(),99} if fault=='job_member' else {os.getpid()}),patch.object(s,'process_identity_status',return_value=s.IdentityStatus('unverifiable' if fault=='identity' else 'gone')),patch.object(s,'process_presence',return_value='gone'),patch.object(j,'original_birth_exit',return_value={'original_gone':fault!='identity','windows':{'status':'unverifiable' if fault=='identity' else 'absent'}}),patch.object(s,'check_port_available'):
     self.assertFalse(n.positive_failed_cleanup_proof(retained)['complete'])
 def test_job_member_list_rejects_incomplete_reply_and_queries_only_original_job(self):
  class Kernel:
   def QueryInformationJobObject(self,handle,kind,buffer,size,returned):
    self.called=(handle,kind);ctypes.c_ulong.from_buffer(buffer,0).value=2;ctypes.c_ulong.from_buffer(buffer,4).value=1;(ctypes.c_size_t*1).from_buffer(buffer,8)[0]=os.getpid();return 1
  k=Kernel()
  with patch.object(j,'_parent_job',123),patch.object(j,'_api',return_value=k):
   with self.assertRaises(RuntimeError):j.active_members()
  self.assertEqual(k.called,(123,3))
 def test_real_isolated_cpu_parent_job_reports_its_only_member(self):
  code='import os,json;from local_runtime import checked_job as j;j.ensure_parent_job();print(json.dumps(dict(pid=os.getpid(),members=sorted(j.active_members()))))'
  result=subprocess.run([sys.executable,'-B','-X','utf8','-c',code],cwd=n.m.ROOT,capture_output=True,text=True,timeout=10)
  self.assertEqual(result.returncode,0,result.stderr);value=json.loads(result.stdout);self.assertEqual(value['members'],[value['pid']])
 def test_positive_proof_persistence_failure_keeps_original_failure_and_locks(self):
  for fail_save in (False,True):
   with self.subTest(fail_save=fail_save),tempfile.TemporaryDirectory() as tmp,contextlib.ExitStack() as stack:
    directory=Path(tmp);retained_data=self.proof_fixture();retained_data['state']['config']=str(directory/'strata-StrataMod.json');held=[False];events=[]
    original=RuntimeError('original startup failure')
    @contextlib.contextmanager
    def locks():
     held[0]=True
     try:yield
     finally:held[0]=False
    def start(pointer,value,monitor,retained):retained.update(retained_data,spawn_possible=True);raise original
    def barrier(*args):self.assertTrue(held[0]);events.append('hold')
    monitor=Mock();monitor.__enter__=Mock(return_value=Mock());monitor.__exit__=Mock(return_value=False)
    proof={'complete':True,'port_free':True,'historical_errors':retained_data['state']['spawn_observation']['errors']}
    for target,name,kwargs in ((n,'selected',{'return_value':({}, {})}),(n,'validate_assets',{}),(n.runner,'shared_operation',{'side_effect':locks}),(n.runner,'production_inactive',{}),(n,'NormalMonitor',{'return_value':monitor}),(n,'start',{'side_effect':start}),(n.runner,'cleanup_failed_start',{}),(n.runner,'pending_exit_proof',{'return_value':{'complete':False}}),(n,'positive_failed_cleanup_proof',{'return_value':proof}),(s,'save',{'side_effect':OSError('diskfull') if fail_save else None}),(n.runner,'hold_pending_cleanup',{'side_effect':barrier})):
     stack.enter_context(patch.object(target,name,**kwargs))
    with self.assertRaisesRegex(RuntimeError,'original startup'):n.serve()
    result=json.loads((directory/'result.json').read_text(encoding='utf-8'));self.assertEqual(result['status'],'failed');self.assertEqual(events,['hold'] if fail_save else []);self.assertFalse(held[0])
 @unittest.skipUnless((n.m.LOCAL/'records/qwen_direct_trial_stop120.py').is_file(),'private historical records operator not distributed')
 def test_records_timeout_revision_preserves_get_and_uses_official_unload_timeout(self):
  import importlib.util
  path=n.m.LOCAL/'records/qwen_direct_trial_stop120.py';spec=importlib.util.spec_from_file_location('fixed_stop120_cpu',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  ops=module.Backend('binding','green');ops.native=Mock();ops.native.http_json.return_value=(200,{})
  with patch.object(s,'require_owned_listener'):
   ops.request({},'/unload','POST');self.assertEqual(ops.native.http_json.call_args.kwargs['timeout'],120)
   ops.request({},'/health');self.assertEqual(ops.native.http_json.call_args.kwargs['timeout'],3)
 def test_three_immutable_reader_failures_in_actual_launcher_are_before_spawn(self):
  from local_runtime.tests.test_normal_runtime import NormalEntryTests
  for target,operation in (('authority','normal_authority_read'),('snapshot','normal_snapshot_read'),('receipt','normal_receipt_read')):
   with self.subTest(target=target),tempfile.TemporaryDirectory() as tmp,contextlib.ExitStack() as stack:
    stack.enter_context(patch.object(n.m,'local_path',side_effect=Path))
    state,fixed,cfg=NormalEntryTests.authority(self,Path(tmp));directory=Path(state['config']).parent;tools=Mock();strata=Mock();calls=[0]
    path=Path(state['authority'] if target=='authority' else fixed[target]);real_digest=n.m.digest
    def digest(p):
     if Path(p)==path:
      calls[0]+=1
      if calls[0]==3:
       error=PermissionError(13,'immutable read temporarily denied',str(path));error.winerror=5;raise error
     return real_digest(p)
    tools.strata_start.side_effect=lambda **kw:kw['launcher'](fixed['command'],n.m.ROOT,directory/'native/server.log',{})
    for obj,key,kw in ((n,'new_run',{'return_value':(directory,state,cfg)}),(n,'manager',{'return_value':(strata,tools)}),(n,'read_receipt',{}),(n,'validate_assets',{}),(o,'clean_environment',{'return_value':{}}),(j,'ensure_parent_job',{}),(j,'require_child',{}),(n,'startup_forecast',{}),(s,'save',{})):
     stack.enter_context(patch.object(obj,key,**kw))
    stack.enter_context(patch.object(n.m,'digest',side_effect=digest));retained={}
    with patch.object(o.native(),'spawn_detached') as spawn:
     with self.assertRaises(PermissionError) as caught:n.start({'receipt':'receipt'},{},Mock(),retained)
     spawn.assert_not_called();self.assertFalse(retained.get('spawn_possible',False))
    self.assertEqual(caught.exception.normal_observation['operation'],operation);self.assertEqual(caught.exception.normal_observation['filename'],str(path))
 def test_reused_pid_is_not_the_original_birth_and_alive_unknown_never_complete(self):
  for status in ('different_birth','alive','unverifiable'):
   with self.subTest(status=status):
    retained=self.proof_fixture()
    with patch.object(n,'authority',return_value={}),patch.object(j,'active_members',return_value={os.getpid()}),patch.object(j,'original_birth_exit',return_value={'original_gone':status=='different_birth','windows':{'status':status}}),patch.object(s,'process_presence',return_value='present'),patch.object(s,'check_port_available'):
     self.assertEqual(n.positive_failed_cleanup_proof(retained)['complete'],status=='different_birth')
 def test_production_birth_proof_keeps_same_birth_alive_unknown_and_foreign_control_zero(self):
  for identity,status,expected in (('gone','different_birth',True),('verified','exited',True),('gone','exited',True),('verified','alive',False),('unverifiable','exited',False)):
   with self.subTest(identity=identity,status=status),patch.object(s,'process_identity_status',return_value=s.IdentityStatus(identity)),patch.object(j,'_birth_windows',return_value={'status':status}):
    self.assertEqual(j.original_birth_exit({'pid':7,'created':1})['original_gone'],expected)
 def test_authority_actual_json_read_failure_after_digest_keeps_safe_operation(self):
  from local_runtime.tests.test_normal_runtime import NormalEntryTests
  with tempfile.TemporaryDirectory() as tmp,patch.object(n.m,'local_path',side_effect=Path):
   state,fixed,cfg=NormalEntryTests.authority(self,Path(tmp));path=Path(state['authority']);real=n.m.read_json
   def read(p):
    if Path(p)==path:
     error=PermissionError(13,'secret exception text',str(path));error.winerror=5;raise error
    return real(p)
   with patch.object(n.m,'read_json',side_effect=read):
    with self.assertRaises(PermissionError) as caught:n.authority(state)
   self.assertEqual(caught.exception.normal_observation['operation'],'normal_authority_read');self.assertEqual(caught.exception.normal_observation['filename'],str(path));self.assertNotIn('secret',str(caught.exception.normal_observation))
if __name__=='__main__':unittest.main()
