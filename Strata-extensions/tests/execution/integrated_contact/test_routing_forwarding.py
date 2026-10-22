import copy,importlib.util,json,math,queue,sys,threading,types,unittest
from pathlib import Path
from unittest.mock import patch
W=Path(__file__).resolve().parents[3]
def load(name,p):
 spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
L=load('routing_candidate_launch',W/'control/deepseek_launch.py')
H=load('routing_candidate_hook',W/'models/deepseek41/server_hooks.py')
KEYS=('routing_primary_bonus','routing_secondary_bonus','routing_ssd_penalty')
class RoutingForwarding(unittest.TestCase):
 def cfg(self):return dict(family='deepseek41',exe='CPU-no-launch.exe',artifact_root='CPU',primary_pci='0000:07:00.0',context=32768,bundle_id='b'*64,runtime_epoch=1,native_paths=[],args=[])
 def test_startup_real_overlay_and_argv_forward_all_three(self):
  cfg=L.overlay(self.cfg(),dict(zip(KEYS,(.05,0.,.03))))
  args=H.native_args(cfg)
  self.assertEqual(args,L.native_command(cfg)[2:])
  for key,v in zip(KEYS,('0.05','0','0.03')):
   flag='--'+key.replace('_','-');self.assertEqual(args[args.index(flag)+1],v)
 def test_missing_and_signed_zero_do_not_change_existing_fields(self):
  cfg=self.cfg();old=H.native_args(cfg)
  self.assertFalse(any('routing-'in x for x in old))
  sample=dict(temperature=0,seed=0,logprobs=True)
  expected=' temperature=0 seed=0 logprobs=1'
  self.assertEqual(H.sampling_keys(sample),expected)
  with_zero=dict(sample,**dict.fromkeys(KEYS,-0.0))
  tail=H.sampling_keys(with_zero)
  for key in KEYS:self.assertIn(' '+key+'=0',tail)
  self.assertEqual(sample,dict(temperature=0,seed=0,logprobs=True))
 def test_invalid_bounds_types_are_rejected_before_GEN(self):
  for key in KEYS:
   for value in (True,False,float('nan'),float('inf'),-float('inf'),-.01,1.01,'0.05',None):
    with self.subTest(key=key,value=value):
     with self.assertRaises(ValueError):H.validate_options({key:value})
     with self.assertRaises(ValueError):L.overlay(self.cfg(),{key:value})
 def test_actual_cli_parser_forwards_only_explicit_fields(self):
  sys.path.insert(0,r'C:\Develop\AI\Strata-data')
  cli=load('routing_candidate_cli',W/'control/strata_cli.py')
  args=cli.parser().parse_args(['start','--model','deepseek-v4.1-flash-1017-ud-q4_k_xl','--routing-primary-bonus','0.05','--routing-secondary-bonus','0','--routing-ssd-penalty','0.03'])
  self.assertEqual([getattr(args,k)for k in KEYS],[.05,0.,.03])
  rt=types.SimpleNamespace()
  with patch.object(cli,'start_selected',side_effect=lambda *a:None):
   cli.main(['start','--model','deepseek-v4.1-flash-1017-ud-q4_k_xl','--routing-primary-bonus','0.05'],rt=rt)
  self.assertEqual(rt.launch_options,dict(routing_primary_bonus=.05))
 def test_real_Service_prepare_run_request_override_and_missing_preserve_startup(self):
  package=Path(r'C:\Develop\AI\Strata-extensions\runtime\deepseek41\fe366a793c63a636a54ead1865c3dc9d0e0f3b79a4493c7f9d70f1baa82aa14d')
  sys.path[:0]=[str(package/'base'),str(package/'base/tools')]
  server=load('serve.server',package/'native/server/serve/server.py')
  cfg=L.overlay(self.cfg(),dict(zip(KEYS,(.05,.06,.07))));H.install(server,cfg)
  sent=[]
  def frames(ids,maximum,sampling,cancel,transport):
   sent.append((copy.deepcopy(sampling),'GEN '+str(maximum)+H.sampling_keys(sampling)+' request_id=CPU epoch=1 '+','.join(map(str,ids))))
   yield None
  shell=types.SimpleNamespace(frames=frames,max_context=32768,info={},batch=0,alive=lambda:True)
  tok=types.SimpleNamespace(recipe=object(),control_tokens=(),encode=lambda *a,**k:[])
  svc=server.Service(shell,tok,None,sampling_defaults={});svc.ensure_loaded=lambda:None
  prepared=dict(input_ids=[0,128803,128804,128822],max_tokens=2,inference_options=types.SimpleNamespace())
  with patch.object(H.codec,'prepare_chat',return_value=prepared)as recipe_prepare:
   for request in ({},dict(zip(KEYS,(.1,.2,.3))),dict.fromkeys(KEYS,0)):
    ids,thinking,maximum=svc.prepare([dict(role='user',content='CPU')],None,{},req=request)
    run=svc._run(ids,thinking,None,maximum,{},threading.Event())
    self.assertEqual(next(run),('ping',None));run.close()
    self.assertEqual({k:v for k,v in sent[-1][0].items()if k in KEYS},request)
    for key,value in request.items():self.assertIn(' '+key+'='+str(value),sent[-1][1])
    self.assertEqual(svc.sampling_defaults,{})
    self.assertFalse(svc.status['busy']);self.assertTrue(svc.fifo.acquire(False));svc.fifo.release()
   for key in KEYS:
    for value in (None,True,float('nan'),float('inf'),-.1,1.1):
     with self.subTest(key=key,value=value),self.assertRaises(ValueError):
      svc.prepare([dict(role='user',content='CPU')],None,{},req={key:value})
  self.assertEqual(recipe_prepare.call_count,3)
  self.assertEqual(len(sent),3)
  svc.shared=dict(temperature=.7,**dict.fromkeys(KEYS,.2))
  self.assertEqual(svc.with_shared({'temperature':None},'openai')['temperature'],.7)
  for key in KEYS:
   for value in (None,True,float('nan'),float('inf'),-.1,1.1):
    with self.subTest(shared_key=key,value=value),self.assertRaises(ValueError):
     req=svc.with_shared({key:value},'openai')
  for key in KEYS:self.assertEqual(svc.with_shared({key:0},'openai')[key],0)
  # Missing request keys emit no GEN override, preserving native startup defaults.
  self.assertFalse(any(key+'='in sent[0][1]for key in KEYS))
 def test_existing_single_reader_INFO_routing_passes_to_original_metrics(self):
  package=Path(r'C:\Develop\AI\Strata-extensions\runtime\deepseek41\fe366a793c63a636a54ead1865c3dc9d0e0f3b79a4493c7f9d70f1baa82aa14d')
  sys.path[:0]=[str(package/'base'),str(package/'base/tools')]
  server=load('serve.server',package/'native/server/serve/server.py');H.install(server,self.cfg())
  routing=dict(version=1,phase='target_decode',primary_bonus=.05,secondary_bonus=0,ssd_penalty=.03,effective='cache_aware',reason='request_snapshot',snapshot_digest='a'*64,coverage_counts=[1,2,3,4,5,6],coverage_order=['primary','secondary','ram','partial','none','unknown'])
  engine=server.StrataEngine.__new__(server.StrataEngine)
  engine.info={};engine.ctl=threading.Lock();engine.transport_counter=0;engine.ctl_epoch=7;engine.trial_observer=None;engine.silence_s=0;engine.batch=0;engine.max_context=32768
  engine.lines=queue.Queue();engine.alive=lambda:True;sent=[];engine._send=sent.append
  def take_control(*a,**k):
   engine.ctl.acquire()
   if False:yield None
   return True
  engine._take_control=take_control
  for observed in (routing,dict(routing,effective='exact',snapshot_digest=None)):
   engine.lines.put('INFO '+json.dumps(dict(routing=observed,legal_extra=None)))
   engine.lines.put('DONE 0')
   self.assertEqual(list(engine.frames([0],1,{},threading.Event(),{})),[])
   svc=server.Service(engine,types.SimpleNamespace(control_tokens=(),encode=lambda *a,**k:[]),None)
   svc.loaded=lambda:True
   self.assertEqual(svc.metrics()['engine']['routing'],observed)
   self.assertIsNone(svc.metrics()['engine']['legal_extra'])
  # The original reader consumes existing native frames, without extra INFO sends.
  self.assertEqual(len(sent),2);self.assertTrue(all(line.startswith('GEN ')for line in sent))
  self.assertTrue(engine.ctl.acquire(False));engine.ctl.release()
if __name__=='__main__':unittest.main(verbosity=2)
