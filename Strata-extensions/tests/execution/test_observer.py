"""Finite opt-in observer CPU tests: no native engine, listener or public write."""
import copy,hashlib,json,os,queue,struct,sys,tempfile,threading,types,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import mode_fixture as F

class BaseEngine:
 def __init__(self,*args,**kwargs):
  self.info={};self.unloaded=False;self.proc=types.SimpleNamespace(pid=os.getpid());self.lines=queue.Queue();self.ctl=threading.Lock();self.ctl_epoch=7;self.sent=[];self.closed=False;self.fail_send=False
 def _take_control(self,*args,**kwargs):
  self.ctl.acquire()
  if False:yield
  return True
 def _send(self,text):
  if self.fail_send:raise OSError('controlled flush failure')
  self.sent.append(text)
 def alive(self):return True
 def close(self):self.closed=True
class ObserverTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/('a'*64);self.root.mkdir();self.hook=F.hooks()
  self.copy=self.root/'Strata-extensions/models/deepseek41/server_hooks.py';self.copy.parent.mkdir(parents=True);self.copy.write_bytes((F.OWN/'models/deepseek41/server_hooks.py').read_bytes());self.hook.__file__=str(self.copy)
  manifest=self.root/'evidence/package-manifest.json';manifest.parent.mkdir();manifest.write_text(json.dumps(dict(schema='strata-t29-runtime-package/v1',id=self.root.name,files=[dict(path=str(self.copy),bytes=self.copy.stat().st_size,sha256=hashlib.sha256(self.copy.read_bytes()).hexdigest())])),encoding='utf8')
  self.cfg=dict(family='deepseek41',context=4096,bundle_id='b'*64,runtime_epoch=11,runtime_package=dict(id=self.root.name,manifest=str(manifest)))
  self.spec=dict(schema='strata-t46-observer-spec/v1',run_id=str(uuid.uuid4()),package_id=self.root.name,bundle_id='b'*64,mode='single',context=4096,input_ids=[0,128803,128804,128822],max_tokens=2,sampling=dict(temperature=0,top_k=0,top_p=1,min_p=0,seed=0,logprobs=True,top_logprobs=3),cancel_first_matching_begin=False,output=str(self.root/'capture.jsonl'))
  self.specpath=self.root/'spec.json';self.env=patch.dict(os.environ,{},clear=False);self.env.start();os.environ.pop('DEEPSEEK_T46_OBSERVER_SPEC',None)
 def tearDown(self):self.env.stop();self.temp.cleanup()
 def install(self):
  server=types.SimpleNamespace(StrataEngine=BaseEngine,Service=type('Service',(),{}),openai_to_messages=lambda req:([],[],{}),anthropic_to_messages=lambda req:None,responses_api=types.SimpleNamespace(),EngineDied=RuntimeError,EngineNonFinite=ArithmeticError,PP_CHUNK_MAX=1024,PP_FLOOR_TOK_S=1,ENGINE_STALL_S=0)
  frontend=types.ModuleType('serve.frontend');frontend.ToolCall=object
  with patch.dict(sys.modules,{'serve.frontend':frontend}):self.assertTrue(self.hook.install(server,self.cfg))
  return server.StrataEngine
 def engine(self,enabled=True):
  if enabled:self.specpath.write_text(json.dumps(self.spec),encoding='utf8');os.environ['DEEPSEEK_T46_OBSERVER_SPEC']=str(self.specpath)
  return self.install()()
 def rows(self):return [json.loads(line)for line in Path(self.spec['output']).read_text(encoding='utf8').splitlines()]
 def frames(self,request='7-1',epoch=11,finish='length',ids=(4482,55753)):
  dto=self.hook.codec._dto;context=dict(request_id=request,runtime_epoch=epoch,bundle_id='b'*64,asset_revision=dto.REVISION,model_family='deepseek41',tokenizer_identity=dto.TOKENIZER_SHA,tokenizer_model='gpt2',tokenizer_pre='joyai-llm',vocab_size=129280)
  common=dict(schema='strata-generation/v1',request_id=request,runtime_epoch=epoch)
  return [json.dumps(dict(common,kind='begin',**{k:v for k,v in context.items()if k not in ('request_id','runtime_epoch')})),json.dumps(dict(common,kind='token_batch',sequence=0,origin='native-generated',ids=list(ids))),json.dumps(dict(common,kind='finish',sequence=1,generated_count=len(ids),finish=finish,ids_sha256=hashlib.sha256(struct.pack('<'+'I'*len(ids),*ids)).hexdigest())),'INFO '+json.dumps(dict(core_position=5)),'DONE '+str(len(ids))]
 def run_request(self,e,rows=None,ids=None,cancel=None):
  for row in self.frames()if rows is None else rows:e.lines.put(row)
  cancel=cancel or threading.Event();out=list(e.frames(self.spec['input_ids']if ids is None else ids,2,self.spec['sampling'],cancel,{}));return out,cancel
 def test_disabled_no_additional_io_or_clock_and_same_transport(self):
  for value in (None,''):
   if value is None:os.environ.pop('DEEPSEEK_T46_OBSERVER_SPEC',None)
   else:os.environ['DEEPSEEK_T46_OBSERVER_SPEC']=value
   cls=self.install()
   with patch.object(self.hook,'Path',side_effect=AssertionError('additional Path')),patch.object(self.hook.json,'dumps',side_effect=AssertionError('additional encoding')),patch.object(self.hook.time,'monotonic_ns',side_effect=AssertionError('additional clock')):
    e=cls();self.run_request(e,['PP 1 4','DONE 0']);e.close()
   self.assertIsNone(e.trial_observer);self.assertEqual(len(e.sent),1);self.assertTrue(e.closed)
 def test_normal_raw_lines_dto_and_flush_order(self):
  e=self.engine();raw=self.frames();original=e.trial_observer.emit
  def emit(event,**fields):
   if event=='send':self.assertIn(fields['line'],e.sent)
   return original(event,**fields)
  e.trial_observer.emit=emit;out,_=self.run_request(e,raw);e.close();rows=self.rows()
  self.assertEqual([r['line']for r in rows if r['event']=='receive'],raw)
  dto=None
  for line in out:
   if line is None:continue
   frame=json.loads(line)
   if dto is None:dto=self.hook.codec._dto.GenerationDTO({k:frame[k]for k in self.hook.codec._dto.CONTEXT})
   dto.feed(line)
  self.assertEqual(dto.result()['original_token_ids'],(4482,55753));self.assertEqual([r['sequence']for r in rows],list(range(len(rows))));self.assertEqual(rows[-1]['event'],'summary');self.assertEqual(rows[0]['owner']['engine']['pid'],os.getpid())
 def test_cancel_only_first_matching_begin_and_fresh_cookie(self):
  self.spec['cancel_first_matching_begin']=True;e=self.engine();_,cancel=self.run_request(e);self.assertTrue(cancel.is_set());self.assertIn('STOP request_id=7-1 epoch=11 reason=user_cancel',e.sent)
  _,second=self.run_request(e,self.frames('7-2'));self.assertFalse(second.is_set());e.close();self.assertEqual(sum(r['event']=='cancel_fixture'for r in self.rows()),1)
 def test_nonmatching_prompt_is_not_recorded_or_cancelled(self):
  self.spec['cancel_first_matching_begin']=True;e=self.engine();_,cancel=self.run_request(e,['DONE 0'],ids=[999999]);self.assertFalse(cancel.is_set());e.close();text=Path(self.spec['output']).read_text();self.assertNotIn('999999',text);self.assertFalse(any(r['event']in ('request','receive','send')for r in self.rows()))
 def test_drain_preserves_raw_terminal_and_releases(self):
  e=self.engine();raw=self.frames();[e.lines.put(x)for x in raw];g=e.frames(self.spec['input_ids'],2,self.spec['sampling'],threading.Event(),{});next(g);g.close();self.assertFalse(e.ctl.locked());e.close();self.assertEqual([r['line']for r in self.rows()if r['event']=='receive'],raw);self.assertTrue(any(r.get('phase')=='drain'for r in self.rows()))
 def test_mismatched_cookie_or_epoch_fails_capture(self):
  for epoch in (11,12):
   self.spec['output']=str(self.root/('capture'+str(epoch)+'.jsonl'));e=self.engine();self.run_request(e,self.frames('foreign',epoch));self.assertEqual(e.trial_observer.error,'frame_cookie_mismatch');e.close();self.assertNotEqual(self.rows()[-1]['event'],'summary')
 def test_log_failure_does_not_prevent_stop_drain_release_close(self):
  e=self.engine();observer=e.trial_observer
  class Broken:
   def write(self,*a):raise OSError('disk')
   def close(self):pass
  observer.stream.close();observer.stream=Broken();raw=self.frames();[e.lines.put(x)for x in raw];g=e.frames(self.spec['input_ids'],2,self.spec['sampling'],threading.Event(),{});next(g);g.close();e.close();self.assertTrue(e.closed);self.assertFalse(e.ctl.locked());self.assertEqual(observer.error,'OSError');self.assertTrue(any(x.startswith('STOP ')for x in e.sent));self.assertTrue(observer.closed)
 def test_fixture_event_save_failure_never_sets_cancel(self):
  for failure in ('write','flush'):
   self.spec['cancel_first_matching_begin']=True;self.spec['output']=str(self.root/(failure+'.jsonl'));e=self.engine();o=e.trial_observer;stream=o.stream
   class FailFixture:
    fixture=False
    def write(self,text):
     self.fixture='"event":"cancel_fixture"'in text
     if self.fixture and failure=='write':raise OSError('fixture event write failed')
     return stream.write(text)
    def flush(self):
     if self.fixture and failure=='flush':raise OSError('fixture event flush failed')
     return stream.flush()
    def close(self):return stream.close()
   o.stream=FailFixture();_,cancel=self.run_request(e);self.assertFalse(cancel.is_set());self.assertTrue(o.cancel_pending)
   self.assertEqual(o.error,'OSError');self.assertFalse(any(x.startswith('STOP ')for x in e.sent));e.close()
   self.assertNotEqual(self.rows()[-1]['event'],'summary');self.assertTrue(e.closed);self.assertFalse(e.ctl.locked())
 def test_failed_or_closed_observer_has_no_request_or_cancel_side_effect(self):
  self.spec['cancel_first_matching_begin']=True;e=self.engine();o=e.trial_observer
  class Broken:
   def write(self,*a):raise OSError('controlled receive write')
   def close(self):pass
  o.request(e,self.spec['input_ids'],2,self.spec['sampling'],('7-1',11));o.stream.close();o.stream=Broken();cancel=threading.Event()
  o.line(self.frames()[0],'normal',cancel)
  self.assertFalse(cancel.is_set());self.assertEqual(o.error,'OSError')
  before=list(o.cookies)
  with patch.object(o,'identity',side_effect=AssertionError('disabled identity lookup')),patch.object(self.hook.json,'loads',side_effect=AssertionError('disabled parse')):
   o.request(e,self.spec['input_ids'],2,self.spec['sampling'],('7-2',11));o.line('not-json','normal',cancel)
   self.assertEqual(o.cookies,before);self.assertFalse(cancel.is_set())
   o.error=None;o.closed=True;o.request(e,self.spec['input_ids'],2,self.spec['sampling'],('7-3',11));o.line('not-json','normal',cancel)
   self.assertEqual(o.cookies,before);self.assertFalse(cancel.is_set())
  e.close();self.assertTrue(e.closed)
 def test_send_failure_preserves_exception_and_cleanup(self):
  e=self.engine();original=OSError('original GEN failure')
  def fail(engine,text):
   if text.startswith('GEN '):raise original
   raise RuntimeError('secondary STOP failure')
  with patch.object(BaseEngine,'_send',fail):
   with self.assertRaises(OSError)as caught:self.run_request(e,['DONE 0'])
  self.assertIs(caught.exception,original);self.assertFalse(e.ctl.locked())
  e.close();self.assertTrue(e.closed);self.assertTrue(any(r['event']=='send_error'for r in self.rows()))
 def test_close_exception_is_preserved_and_sink_closed(self):
  e=self.engine();original=RuntimeError('engine close')
  with patch.object(BaseEngine,'close',side_effect=original):
   with self.assertRaises(RuntimeError)as caught:e.close()
  self.assertIs(caught.exception,original);self.assertTrue(e.trial_observer.closed);self.assertEqual(self.rows()[-1]['close_error'],'RuntimeError')
 def test_spec_error_precedes_engine_constructor(self):
  self.spec['mode']='foreign'
  with patch.object(BaseEngine,'__init__',side_effect=AssertionError('must not spawn')):
   with self.assertRaises(ValueError):self.engine()
 def test_explicit_bad_spec_rejected_before_engine(self):
  for field,value in (('schema','bad'),('context',32),('package_id','foreign'),('output','relative.jsonl'),('cancel_first_matching_begin',1)):
   original=self.spec[field];self.spec[field]=value
   with self.assertRaises(ValueError,msg=field):self.engine()
   self.spec[field]=original
 def test_existing_output_create_only(self):
  Path(self.spec['output']).write_text('keep',encoding='utf8')
  with self.assertRaises(FileExistsError):self.engine()
  self.assertEqual(Path(self.spec['output']).read_text(),'keep')
 def test_relative_spec_rejected(self):
  os.environ['DEEPSEEK_T46_OBSERVER_SPEC']='relative.json';cls=self.install()
  with self.assertRaises(ValueError):cls()
 def test_eof_err_nonfinite_preserved_and_summary_closed(self):
  for index,raw in enumerate(([None,'DONE 0'],['ERR controlled','DONE 0'],self.frames(finish='nonfinite',ids=()))):
   self.spec['output']=str(self.root/('failure'+str(index)+'.jsonl'));e=self.engine()
   if index==0:
    with self.assertRaises(RuntimeError):self.run_request(e,raw)
   else:self.run_request(e,raw)
   e.close();self.assertTrue(e.closed);self.assertFalse(e.ctl.locked());self.assertEqual(self.rows()[-1]['event'],'summary')


class PublicInfoTests(unittest.TestCase):
 def setUp(self):
  ObserverTests.setUp(self)
  self.cfg['placement']={'mode':'cache-only'}
  self.spec['mode']='cache-only';self.specpath.write_text(json.dumps(self.spec),encoding='utf8')
  os.environ['DEEPSEEK_T46_OBSERVER_SPEC']=str(self.specpath)
  class Service:
   def metrics(self,*args,**kwargs):
    self.calls.append((args,kwargs))
    if self.original_error:raise self.original_error
    return self.return_value if self.return_value is not None else {'engine':dict(self.engine.info)}
  server=types.SimpleNamespace(StrataEngine=BaseEngine,Service=Service,openai_to_messages=lambda req:([],[],{}),anthropic_to_messages=lambda req:None,responses_api=types.SimpleNamespace(),EngineDied=RuntimeError,EngineNonFinite=ArithmeticError,PP_CHUNK_MAX=1024,PP_FLOOR_TOK_S=1,ENGINE_STALL_S=0)
  frontend=types.ModuleType('serve.frontend');frontend.ToolCall=object
  with patch.dict(sys.modules,{'serve.frontend':frontend}):self.hook.install(server,self.cfg)
  self.engine=server.StrataEngine();self.engine.gen=1;self.engine.active_cookie=None
  self.service=server.Service.__new__(server.Service);self.service.engine=self.engine;self.service.calls=[];self.service.original_error=None;self.service.return_value=None
  self.observer=self.engine.trial_observer
 def tearDown(self):
  self.engine.trial_observer.finish();ObserverTests.tearDown(self)
 def boundary(self):
  e=self.engine;o=self.observer
  for cookie in [('1-1',11),('1-2',11)]:
   o.request(e,self.spec['input_ids'],2,self.spec['sampling'],cookie)
   o.emit('receive',cookie=cookie,phase='normal',line='DONE '+('0'if cookie[0]=='1-1'else'2')+'\n')
  o.active=None;e.active_cookie=None
  rows=[json.loads(line)for line in Path(self.spec['output']).read_text().splitlines()]
  end=self.hook.time.monotonic_ns()
  values={'config.json':self.cfg,'complete-http.json':{'HTTP_DONE':True},'complete-clock.json':{'end_ns':end},'complete-sse.json':['[DONE]']}
  for name,value in values.items():(self.root/name).write_text(json.dumps(value),encoding='utf8')
  boundary=dict(binding=dict(owner=o.owner,hook_sha256=o.hook_sha256,runtime_epoch=11),cookies=o.cookies,cookie=o.cookies[1],native_DONE=rows[-1],HTTP=self.hook._trial_row(self.root/'complete-http.json'),HTTP_clock=self.hook._trial_row(self.root/'complete-clock.json'),HTTP_end_ns=end)
  wrapper=dict(schema='strata-t46-public-INFO-boundary/v1',boundary=boundary,config=self.hook._trial_row(self.root/'config.json'),spec=self.hook._trial_row(self.specpath))
  (self.root/'fresh-INFO-boundary.json').write_text(json.dumps(wrapper),encoding='utf8')
  return wrapper
 def sender(self,line='INFO {"core_position":5,"extra":null}'):
  def send(text):
   self.engine.sent.append(text);self.assertEqual(text,'INFO')
   self.engine.lines.put(line)
  self.engine._send=send
 def receipt(self):return json.loads((self.root/'fresh-INFO-receipt.json').read_text())
 def test_actual_metrics_success_once_and_off_delegation(self):
  self.boundary();self.sender()
  self.assertEqual(self.service.metrics(all_requests=True)['engine']['core_position'],5)
  first=(self.root/'fresh-INFO-receipt.json').read_bytes()
  self.assertEqual(self.service.metrics()['engine']['core_position'],5)
  self.assertEqual(self.engine.sent,['INFO']);self.assertEqual(first,(self.root/'fresh-INFO-receipt.json').read_bytes())
  self.assertTrue(self.receipt()['ok']);self.assertIsNone(self.receipt()['parsed']['extra']);self.assertFalse(self.engine.ctl.locked())
  self.assertEqual(self.service.calls[0],((),{'all_requests':True}))
  # Ordinary route and accepted direct-single route retain exact delegation.
  marker=object();failure=RuntimeError('original metrics failure');self.service.return_value=marker
  for off in ('disabled','single'):
   if off=='disabled':self.engine.trial_observer=None
   else:self.engine.trial_observer=self.observer;self.cfg['placement']['mode']='single'
   with patch.object(self.hook,'_trial_public_INFO',side_effect=AssertionError('off refresh')),patch.object(self.hook.time,'monotonic_ns',side_effect=AssertionError('extra clock')),patch.object(self.hook,'_trial_row',side_effect=AssertionError('extra file I/O')):
    self.assertIs(self.service.metrics('opaque',all_requests=True),marker)
    # Existing selected-location probe deliberately invokes an unbound method.
    probe=types.SimpleNamespace(engine=self.engine,calls=[],original_error=None,return_value=marker)
    self.assertIs(type(self.service).metrics(probe,'probe',all_requests=True),marker)
    self.assertEqual(probe.calls,[(('probe',),{'all_requests':True})])
    self.service.original_error=failure
    with self.assertRaises(RuntimeError)as got:self.service.metrics()
    self.assertIs(got.exception,failure);self.service.original_error=None
  self.engine.trial_observer=self.observer
 def test_no_HTTP_boundary_is_cached_without_INFO(self):
  self.sender();self.assertEqual(self.service.metrics(),{'engine':dict(self.engine.info)});self.assertEqual(self.engine.sent,[])
  self.assertFalse((self.root/'fresh-INFO-receipt.json').exists())
 def test_response_faults_preserve_raw_release_and_no_retry(self):
  for line in [None,'ERR broken','INFO {bad','INFO {"core_position":5,"extra":{"x":NaN}}','INFO {"core_position":5,"extra":[Infinity]}','INFO {"core_position":true}']:
   with self.subTest(line=line):
    # Each is a distinct finite fixture; no external native retry.
    self.boundary();self.sender(line)
    with self.assertRaises((ValueError,TypeError)):self.service.metrics()
    receipt=self.receipt();self.assertFalse(receipt['ok']);self.assertIsNone(receipt['parsed'])
    self.assertEqual(receipt['responses'][0]['line'],line);self.assertFalse(self.engine.ctl.locked())
    with self.assertRaises((ValueError,TypeError)):self.service.metrics()
    self.assertEqual(self.engine.sent,['INFO'])
    (self.root/'fresh-INFO-receipt.json').unlink()
    self.engine._trial_public_info_state=None;self.engine.sent=[];self.observer.cookies=[]
    self.observer.stream.close();Path(self.spec['output']).write_text('',encoding='utf8');self.observer.stream=Path(self.spec['output']).open('a',encoding='utf8');self.observer.sequence=0;self.observer.start(self.engine)
 def test_authority_active_queue_send_and_save_faults(self):
  self.boundary();self.sender()
  self.engine.active_cookie=('active',11)
  with self.assertRaises(ValueError):self.service.metrics()
  self.assertEqual(self.engine.sent,[]);self.assertFalse(self.engine.ctl.locked())
  self.assertFalse(self.receipt()['ok'])
 def test_boundary_owner_generation_queue_and_send_faults(self):
  cases=('foreign-owner','epoch','cookie','header','sequence','HTTP-DONE','HTTP-clock','dirty-queue','send','generation-change','epoch-change')
  for case in cases:
   with self.subTest(case=case):
    wrapper=self.boundary();self.sender()
    if case=='foreign-owner':self.observer.owner['engine']['birth']+=1
    elif case=='epoch':wrapper['boundary']['binding']['runtime_epoch']+=1
    elif case=='cookie':wrapper['boundary']['cookies'][1][0]='foreign'
    elif case in('header','sequence'):
     path=Path(self.spec['output']);rows=[json.loads(line)for line in path.read_text().splitlines()]
     if case=='header':rows[0]['owner']['engine']['birth']+=1
     else:rows[0]['sequence']=False
     path.write_text(''.join(json.dumps(row)+'\n'for row in rows),encoding='utf8')
    elif case=='HTTP-DONE':(self.root/'complete-http.json').write_text('{"HTTP_DONE":false}',encoding='utf8')
    elif case=='HTTP-clock':wrapper['boundary']['HTTP_end_ns']+=1
    elif case=='dirty-queue':self.engine.lines.put('PP unexpected')
    elif case=='send':
     def send(text):self.engine.sent.append(text);raise OSError('original send failure')
     self.engine._send=send
    else:
     def send(text):
      self.engine.sent.append(text)
      if case=='epoch-change':self.cfg['runtime_epoch']+=1
      else:self.engine.gen+=1
     self.engine._send=send
    (self.root/'fresh-INFO-boundary.json').write_text(json.dumps(wrapper),encoding='utf8')
    with self.assertRaises((ValueError,OSError)):self.service.metrics()
    self.assertFalse(self.receipt()['ok']);self.assertFalse(self.engine.ctl.locked())
    if case not in('send','generation-change','epoch-change'):self.assertEqual(self.engine.sent,[])
    # Reset only this CPU fixture; every failure remains in its test result.
    (self.root/'fresh-INFO-receipt.json').unlink()
    self.engine._trial_public_info_state=None;self.engine.sent=[];self.engine.gen=1;self.cfg['runtime_epoch']=11
    while not self.engine.lines.empty():self.engine.lines.get_nowait()
    self.observer.cookies=[];self.observer.active=None
    self.observer.owner=self.observer.identity(self.engine)
    self.observer.stream.close();Path(self.spec['output']).write_text('',encoding='utf8');self.observer.stream=Path(self.spec['output']).open('a',encoding='utf8');self.observer.sequence=0;self.observer.start(self.engine)
 def test_partial_error_priority_save_failure(self):
  self.boundary();self.sender('INFO {bad')
  with patch.object(self.hook,'_trial_save',side_effect=OSError('disk failure')),self.assertRaises(ValueError)as error:self.service.metrics()
  self.assertIn('fresh INFO receipt save failed',str(error.exception.__notes__))
  self.assertFalse(self.engine.ctl.locked());self.assertEqual(self.engine.sent,['INFO'])
 def test_save_failure_never_reports_success(self):
  self.boundary();self.sender()
  with patch.object(self.hook,'_trial_save',side_effect=OSError('disk failure')),self.assertRaises(OSError):self.service.metrics()
  self.assertEqual(self.engine._trial_public_info_state,'failed');self.assertFalse(self.engine.ctl.locked())
 def test_concurrent_metrics_share_one_original_reader(self):
  self.boundary();entered=threading.Event();release=threading.Event();results=[]
  def send(text):
   self.engine.sent.append(text);entered.set();self.assertTrue(release.wait(3));self.engine.lines.put('INFO {"core_position":5}')
  self.engine._send=send
  def call():
   try:results.append(self.service.metrics())
   except BaseException as error:results.append(error)
  a=threading.Thread(target=call);b=threading.Thread(target=call);a.start();self.assertTrue(entered.wait(3));b.start();release.set();a.join(3);b.join(3)
  self.assertFalse(a.is_alive()or b.is_alive());self.assertEqual(self.engine.sent,['INFO'])
  self.assertEqual(len(results),2);self.assertTrue(all(isinstance(v,dict)and v['engine']['core_position']==5 for v in results))

 def test_actual_DONE_line_endings_and_invalid_terminals(self):
  for line,valid in [('DONE 2\n',True),('DONE 2\r\n',True),('DONE 2 extra\n',False),('DONE 1\n',False),(None,False),(2,False)]:
   fixture=PublicInfoTests();fixture.setUp()
   try:
    wrapper=fixture.boundary();fixture.sender()
    path=Path(fixture.spec['output']);rows=[json.loads(x)for x in path.read_text().splitlines()]
    rows[-1]['line']=line;wrapper['boundary']['native_DONE']=rows[-1]
    path.write_text(''.join(json.dumps(row)+'\n'for row in rows),encoding='utf8')
    (fixture.root/'fresh-INFO-boundary.json').write_text(json.dumps(wrapper),encoding='utf8')
    with self.subTest(line=line):
     if valid:self.assertEqual(fixture.service.metrics()['engine']['core_position'],5);self.assertEqual(fixture.engine.sent,['INFO'])
     else:
      with self.assertRaises(ValueError):fixture.service.metrics()
      self.assertEqual(fixture.engine.sent,[]);self.assertFalse(fixture.receipt()['ok'])
     self.assertEqual(rows[-1]['line'],line);self.assertFalse(fixture.engine.ctl.locked())
   finally:fixture.tearDown()

if __name__=='__main__':unittest.main()
