import copy
import importlib.util
from pathlib import Path
import unittest
P=Path(__file__).resolve().parents[2]/'clients/runtime_identity.py'
spec=importlib.util.spec_from_file_location('t33_identity',P);I=importlib.util.module_from_spec(spec);spec.loader.exec_module(I)

def tag():return dict(schema='strata-runtime-identity/v1',family='deepseek41',bundle_id='a'*64,package_id='b'*64,runtime_epoch='1792568209599735400',model='deepseek-v4.1',context=4096)

class IdentityTests(unittest.TestCase):
 def test_lossless_same_and_adjacent(self):
  t=tag();self.assertEqual(I.normalize(t),t);self.assertTrue(I.same(t,copy.deepcopy(t)))
  other=tag();other['runtime_epoch']='1792568209599735401';self.assertFalse(I.same(t,other))
  other=tag();other['package_id']='c'*64;self.assertFalse(I.same(t,other))
 def test_strict_domain_unknown_and_copy(self):
  for field,values in dict(runtime_epoch=[True,1,1.0,'01','0','-1','18446744073709551616'],context=[True,4096.0,0,1048577],bundle_id=['x'*64,None],family=['huihui'],model=['',None]).items():
   for value in values:
    bad=tag();bad[field]=value
    with self.assertRaises(ValueError,msg=(field,value)):I.normalize(bad)
  self.assertFalse(I.same(tag(),None));self.assertFalse(I.same(None,None))
  original=tag();result=I.normalize(original);result['model']='changed';self.assertEqual(original['model'],'deepseek-v4.1')
 def test_completed_old_history_not_invalidated(self):
  old=[dict(role='assistant',content='old')];self.assertEqual(I.history_for_context(old),old)
  current=old+[dict(role='assistant',content='partial',strata_runtime=tag(),strata_incomplete=True)]
  self.assertEqual(I.history_for_context(current),old);self.assertEqual(len(current),2)
  completed=old+[dict(role='assistant',content='complete',strata_runtime=tag())]
  self.assertEqual(I.history_for_context(completed),completed)

class ServiceIdentityTests(unittest.TestCase):
 def config(self):return dict(family='deepseek41',bundle_id='a'*64,runtime_package=dict(id='b'*64),runtime_epoch=1792568209599735400,model_name='deepseek-v4.1',context=4096)
 def test_launch_exact_epoch_and_cache_path_not_identity(self):
  cfg=self.config();self.assertEqual(I.from_config(cfg),tag())
  cfg['artifact_root']='changed-cache-path';self.assertEqual(I.from_config(cfg),tag())
  for epoch in (True,1.0,'1792568209599735400',0,2**64):
   cfg=self.config();cfg['runtime_epoch']=epoch
   with self.assertRaises(ValueError):I.from_config(cfg)
 def test_family_metadata_and_every_object_chunk_keep_original_fields(self):
  from types import SimpleNamespace
  original=dict(engine=dict(bundle_id=None,runtime_epoch=None),value=1)
  class Service:
   def metrics(self,*args,**kwargs):return original
  data=[None,dict(choices=[dict(delta=dict(reasoning_content='think'),finish_reason=None)]),dict(choices=[dict(delta={},finish_reason='tool_calls')],strata_mcp=dict(type='tool'),usage=dict(completion_tokens=1))]
  def chunks(*args,**kwargs):yield from data
  server=SimpleNamespace(Service=Service,openai_chunks=chunks)
  I.install(server,self.config());self.assertEqual(server.Service().metrics(all_requests=True),dict(original,strata_runtime=tag()));self.assertNotIn('strata_runtime',original)
  result=list(server.openai_chunks('original-args',run='original-run'))
  self.assertIsNone(result[0]);self.assertEqual(result[1],dict(data[1],strata_runtime=tag()));self.assertEqual(result[2],dict(data[2],strata_runtime=tag()));self.assertNotIn('strata_runtime',data[1])
  current=server.openai_chunks;I.install(server,self.config());self.assertIs(server.openai_chunks,current)
  wrong=self.config();wrong['runtime_epoch']+=1
  with self.assertRaises(ValueError):I.install(server,wrong)
 def test_nonfamily_server_functions_are_unchanged(self):
  from types import SimpleNamespace
  class Service:
   def metrics(self):return {'legacy':True}
  def chunks():yield None
  server=SimpleNamespace(Service=Service,openai_chunks=chunks);I.install(server,dict(family='legacy'))
  self.assertIs(server.openai_chunks,chunks);self.assertNotIn('strata_runtime',server.Service().metrics())

class StreamIdentityTests(unittest.TestCase):
 def stream_module(self):
  import sys
  sys.path.insert(0,str(Path(__file__).resolve().parents[2]));from clients import stream_contract
  return stream_contract
 def data(self,identity):
  import json
  value=dict(choices=[dict(index=0,delta=dict(content='answer'),finish_reason='stop')])
  if identity is not None:value['strata_runtime']=identity
  return ('data: '+json.dumps(value)+'\n\ndata: [DONE]\n\n').encode()
 def test_optional_expected_and_fresh_commit(self):
  S=self.stream_module();t=S.Turn([dict(role='assistant',content='old')],dict(role='user',content='next'),expected_identity=tag());t.feed(self.data(tag()));r=t.commit(observed_identity=tag())
  self.assertEqual(r['choices'][0]['message']['content'],'answer');self.assertEqual(t.history[-1]['strata_runtime'],tag());self.assertEqual(t.history[0],dict(role='assistant',content='old'))
  legacy=S.CompletionStream();legacy.feed(self.data(None));self.assertEqual(legacy.finish()['choices'][0]['message'],dict(role='assistant',content='answer'))
 def test_stream_missing_changed_or_commit_stale_not_completed(self):
  S=self.stream_module()
  for observed in (None,dict(tag(),runtime_epoch='1792568209599735401')):
   t=S.Turn([],dict(role='user',content='next'),expected_identity=tag())
   with self.assertRaises(S.StreamError):t.feed(self.data(observed))
   self.assertFalse(t.committed);self.assertEqual(t.history,[])
  t=S.Turn([],dict(role='user',content='next'),expected_identity=tag());t.feed(self.data(tag()))
  with self.assertRaises(S.StreamError):t.commit(observed_identity=dict(tag(),runtime_epoch='1792568209599735401'))
  self.assertFalse(t.committed);self.assertEqual(t.history,[])

class ChatIdentityTests(unittest.TestCase):
 def test_bound_chat_fresh_metrics_before_and_commit(self):
  import sys,json
  from unittest.mock import patch
  sys.path.insert(0,str(Path(__file__).resolve().parents[2]));from clients import chat_adapter as C
  class Response:
   def __init__(self,data):self.data=data;self.closed=False
   def __enter__(self):return self
   def __exit__(self,*args):self.closed=True
   def read(self):return self.data
   def read1(self,n):out=self.data;self.data=b'';return out
  raw=StreamIdentityTests().data(tag())
  for stale in (False,True):
   responses=[Response(json.dumps(dict(strata_runtime=tag())).encode()),Response(raw),Response(json.dumps(dict(strata_runtime=dict(tag(),runtime_epoch='1792568209599735401')if stale else tag())).encode())];calls=[]
   def open_(request,**kwargs):calls.append(request.full_url if hasattr(request,'full_url')else request);return responses[len(calls)-1]
   with patch.object(C.urllib.request,'urlopen',side_effect=open_):
    turn=C.bound_stream('http://127.0.0.1:9/v1/chat/completions',[dict(role='user',content='next')],None,None)
    if stale:
     with self.assertRaises(C.StreamError):list(turn)
     self.assertIsNone(turn.message)
    else:
     self.assertEqual(list(turn),[('', 'answer')]);self.assertEqual(turn.message['strata_runtime'],tag())
   self.assertEqual(calls,['http://127.0.0.1:9/metrics','http://127.0.0.1:9/v1/chat/completions','http://127.0.0.1:9/metrics']);self.assertTrue(all(r.closed for r in responses))
 def test_unknown_metrics_uses_existing_oserror_path_without_generation(self):
  import sys
  from unittest.mock import patch
  sys.path.insert(0,str(Path(__file__).resolve().parents[2]));from clients import chat_adapter as C
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def read(self):return b'{}'
  with patch.object(C.urllib.request,'urlopen',return_value=Response())as opened:
   turn=C.bound_stream('http://127.0.0.1:9/v1/chat/completions',[],None,None)
   with self.assertRaises(C.StreamError):list(turn)
   self.assertEqual(opened.call_count,1);self.assertIsNone(turn.message)
 def test_actual_derived_chat_switch_does_not_commit_but_old_complete_history_stays(self):
  import sys,json,tempfile,threading,subprocess,hashlib,shutil
  from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
  sys.path.insert(0,str(Path(__file__).resolve().parents[2]));from clients import chat_adapter as C
  requests=[];current=[tag()]
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):
    data=json.dumps(dict(strata_runtime=current[0])).encode();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
   def do_POST(self):
    requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))));index=len(requests)
    payload=dict(choices=[dict(index=0,delta=dict(content='answer'+str(index)),finish_reason='stop')],strata_runtime=current[0])
    data=('data: '+json.dumps(payload)+'\n\ndata: [DONE]\n\n').encode()
    if index==2:current[0]=dict(tag(),runtime_epoch='1792568209599735401')
    self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);worker=threading.Thread(target=server.serve_forever);worker.start()
  try:
   with tempfile.TemporaryDirectory()as folder:
    root=Path(folder);(root/'clients').mkdir();target=root/'clients/chat.py';raw=Path('C:/Develop/AI/Strata/chat.py').read_bytes();target.write_text(C.derive_chat(raw,hashlib.sha256(raw).hexdigest(),bind_identity=True),encoding='utf8')
    dest=root/'Strata-extensions/clients';dest.mkdir(parents=True)
    for name in ('runtime_identity.py','stream_contract.py','chat_adapter.py'):shutil.copyfile(Path(__file__).resolve().parents[2]/'clients'/name,dest/name)
    result=subprocess.run([sys.executable,'-X','utf8','-B',str(target),'--port',str(server.server_port)],input='first\nsecond\nthird\n/quit\n',capture_output=True,text=True,encoding='utf8',timeout=15)
    self.assertEqual(result.returncode,0,result.stderr);self.assertIn('runtime identity changed before chat commit',result.stdout)
   self.assertEqual(len(requests),3);history=requests[2]['messages'];self.assertEqual([m['content']for m in history],['first','answer1','third']);self.assertEqual(history[1]['strata_runtime'],tag())
  finally:server.shutdown();worker.join();server.server_close()
 def test_chat_derivative_identity_is_explicit_extension(self):
  import sys,hashlib
  sys.path.insert(0,str(Path(__file__).resolve().parents[2]));from clients import chat_adapter as C
  raw=Path('C:/Develop/AI/Strata/chat.py').read_bytes();sha=hashlib.sha256(raw).hexdigest()
  self.assertIn('stream as selected_stream',C.derive_chat(raw,sha));self.assertIn('bound_stream as selected_stream',C.derive_chat(raw,sha,bind_identity=True))

class WebIdentityTests(unittest.TestCase):
 def test_bound_derivative_explicit_identity_and_default_compatibility(self):
  import sys,hashlib
  sys.path.insert(0,str(Path(__file__).resolve().parents[2]));from clients import package_clients as C
  raw=Path('C:/Develop/AI/Strata/serve/web/app.js').read_bytes();sha=hashlib.sha256(raw).hexdigest();folder=Path(__file__).resolve().parents[2]/'clients';parser=(folder/'web_stream.js').read_bytes()
  legacy=C.derive_web(raw,sha,parser);self.assertNotIn('T33Identity',legacy)
  bound=C.derive_web(raw,sha,parser,identity_raw=(folder/'runtime_identity.js').read_bytes());self.assertIn('t33FreshIdentity',bound);self.assertIn('strata_incomplete',bound);self.assertIn('await t33FreshIdentity(controller.signal)',bound)

class PackageIdentityTests(unittest.TestCase):
 def test_identity_candidate_is_finite_parent_extension_and_native_unchanged(self):
  import sys,tempfile,json
  sys.path.insert(0,str(Path(__file__).resolve().parents[2]));from clients import package_clients as C
  parent=Path('C:/Develop/AI/Strata-extensions/runtime/deepseek41/15cb03c082dc18f1dc57f39a6dbc4a036575b1a5b83e670e493396abc1db95dc/evidence/package-manifest.json')
  with tempfile.TemporaryDirectory()as folder:
   result=C.identity_candidate_inputs(parent,Path(folder)/'candidate');value=json.loads(Path(result['path']).read_text(encoding='utf8'))
   self.assertEqual(value['schema'],'strata-t33-identity-package-input/v1');self.assertEqual(len(value['selected_files']),62);self.assertEqual(value['expected_copy_count'],62)
   self.assertEqual(value['native_manifest']['sha256'],'b3d7d28015b2b7b288a2fcf8919bebc2f36259f6d042bdeacd67ad49e4f822fa');self.assertFalse(value['public_write_executed']);self.assertEqual(value['parent_id'],parent.parent.parent.name)
   entries={r['relative_destination']:r for r in value['selected_files']};self.assertIn('Strata-extensions/clients/runtime_identity.py',entries);self.assertIn('Strata-extensions/clients/runtime_identity.js',entries)
   entry=Path(entries['Strata-extensions/control/deepseek_serve.py']['source']).read_text(encoding='utf8');self.assertIn('identity.install(server,config)',entry)

 def test_identity_input_validation_and_meaningful_mutations(self):
  import sys,tempfile,json,copy,hashlib,importlib.util
  sys.path.insert(0,str(Path(__file__).resolve().parents[2]));from clients import package_clients as C
  path=Path(__file__).resolve().parents[2]/'tests/providers/runtime_stage.py';spec=importlib.util.spec_from_file_location('t33_stage',path);stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)
  parent=Path('C:/Develop/AI/Strata-extensions/runtime/deepseek41/15cb03c082dc18f1dc57f39a6dbc4a036575b1a5b83e670e493396abc1db95dc/evidence/package-manifest.json')
  with tempfile.TemporaryDirectory()as folder:
   root=Path(folder);r=C.identity_candidate_inputs(parent,root/'candidate');value=json.loads(Path(r['path']).read_text(encoding='utf8'));self.assertEqual(stage.selected_inputs(r['path'])['expected_copy_count'],62)
   for mode in ('extra','duplicate','protected','parent','sum','schema','native','public'):
    changed=copy.deepcopy(value)
    if mode=='extra':changed['selected_files'][-1]['relative_destination']='unexpected.py'
    elif mode=='duplicate':changed['selected_files'][-1]['relative_destination']=changed['selected_files'][0]['relative_destination']
    elif mode=='protected':
     old=next(x for x in changed['selected_files']if x['relative_destination']=='native/Strata-deepseek.exe');other=changed['selected_files'][-1];old.update({k:other[k]for k in ('source','bytes','sha256')})
    elif mode=='parent':changed['parent_id']='0'*64
    elif mode=='sum':changed['copy_payload_bytes']+=1
    elif mode=='schema':changed['schema']='strata-t31-client-package-input/v1'
    elif mode=='native':changed['native_manifest'].update(source=str(parent),bytes=parent.stat().st_size,sha256=hashlib.sha256(parent.read_bytes()).hexdigest())
    else:changed['public_write_executed']=True
    changed.pop('candidate_package_id');changed['candidate_package_id']=hashlib.sha256(json.dumps(changed,sort_keys=True,separators=(',',':')).encode()).hexdigest();out=root/(mode+'.json');out.write_text(json.dumps(changed),encoding='utf8')
    with self.assertRaises(ValueError,msg=mode):stage.selected_inputs(out)

 def test_declared_identity_chat_dependency_exact_and_legacy_kept(self):
  import sys,tempfile,json,hashlib,importlib.util
  from unittest import mock
  data=Path('C:/Develop/AI/Strata-data');previous=list(sys.path)
  try:
   sys.path.insert(0,str(data));spec=importlib.util.spec_from_file_location('t33_actual_cli',data/'strata_cli.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
  finally:sys.path[:]=previous
  with tempfile.TemporaryDirectory()as folder:
   root=Path(folder);files=[]
   for relative in ('clients/chat.py','Strata-extensions/clients/chat_adapter.py','Strata-extensions/clients/stream_contract.py'):
    p=root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('# fixture',encoding='utf8');files.append(dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
   manifest=root/'evidence/package-manifest.json';manifest.parent.mkdir();body=dict(id='a'*64,client_extension={},identity_extension=dict(schema='strata-runtime-identity/v1'),files=files);manifest.write_text(json.dumps(body),encoding='utf8')
   cfg=dict(family='deepseek41',python=str(root/'venv/Scripts/python.exe'),runtime_package=dict(id='a'*64,manifest=str(manifest)));rt=mock.Mock();rt.state.return_value=dict(config='selected.json')
   with mock.patch.object(cli.runtime.startup_progress,'family_launch',return_value=(None,cfg,{})),mock.patch.object(cli,'run_client',return_value=0)as run:
    with self.assertRaises(RuntimeError):cli.use_ready(rt,'chat')
    run.assert_not_called()
    p=root/'Strata-extensions/clients/runtime_identity.py';p.write_text('# identity fixture',encoding='utf8');body['files'].append(dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()));manifest.write_text(json.dumps(body),encoding='utf8')
    self.assertEqual(cli.use_ready(rt,'chat'),0);self.assertEqual(run.call_count,1);run.reset_mock()
    p.write_text('# modified identity fixture',encoding='utf8')
    with self.assertRaises(RuntimeError):cli.use_ready(rt,'chat')
    run.assert_not_called()
    body.pop('identity_extension');manifest.write_text(json.dumps(body),encoding='utf8');self.assertEqual(cli.use_ready(rt,'chat'),0)

class IdentityPublicationTests(unittest.TestCase):
 def setup_recipe(self):
  path=Path(__file__).resolve().parents[1]/'providers/runtime_stage.py';spec=importlib.util.spec_from_file_location('t33_publication_tests',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  root=Path(__file__).resolve().parents[3]
  return module,root/'build-deepseek-t33/identity-candidate-r1/verification.json',root/'build-deepseek-t31/actual-sse-attempt-1/cpu-revalidation-r1/verification.json'
 def test_same_native_parent_is_explicit_not_new_model_success(self):
  R,candidate,numeric=self.setup_recipe();value,manifest=R.identity_publication_inputs(candidate,numeric)
  self.assertNotEqual(manifest['id'],manifest['identity_extension']['parent_id']);self.assertFalse(value['public_profiles_updated']);self.assertFalse(value['native_or_listener_started'])
  self.assertEqual(manifest['native_manifest_sha256'],'b3d7d28015b2b7b288a2fcf8919bebc2f36259f6d042bdeacd67ad49e4f822fa')
 def test_numeric_version_executable_or_changed_profile_refused(self):
  from unittest.mock import patch
  R,candidate,numeric=self.setup_recipe();saved=R.numeric_config(R.load(R.load(numeric)['manifest']['path']))
  for field in ('parent','bundle'):
   wrong=copy.deepcopy(saved)
   if field=='parent':wrong['runtime_package']['id']='f'*64
   else:wrong['bundle_id']='f'*64
   with patch.object(R,'numeric_config',return_value=wrong):
    with self.assertRaises(ValueError,msg=field):R.identity_publication_inputs(candidate,numeric)
  with patch.object(R,'digest',return_value='f'*64):
   with self.assertRaises(ValueError):R.identity_publication_inputs(candidate,numeric)
  with patch.object(R,'protected',return_value={}):
   with self.assertRaises(ValueError):R.identity_publication_inputs(candidate,numeric)

if __name__=='__main__':unittest.main()
