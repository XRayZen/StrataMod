"""T32 pure family contract tests; no runtime, settings, network, or credentials."""
from pathlib import Path
import unittest,importlib.util,copy
P=Path(__file__).resolve().parents[2]/'clients/runtime_binding.py'
class FamilyTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  s=importlib.util.spec_from_file_location('t32_family',P);cls.m=importlib.util.module_from_spec(s);s.loader.exec_module(cls.m)
 def test_domain_presets_and_boolean(self):
  descriptor=self.m.descriptor('model',{'family':'deepseek41'},[4096,262144])
  for c in (1,4096,524289,1048576):self.assertTrue(self.m.supports_context(c,descriptor,[4096,262144]))
  for c in (True,0,-1,1048577,1.2,None):self.assertFalse(self.m.supports_context(c,descriptor,[4096,262144]))
  self.assertIsNone(self.m.descriptor('legacy',{},[262144]));self.assertFalse(self.m.supports_context(4096,None,[262144]));self.assertTrue(self.m.supports_context(262144,None,[262144]))
 def test_canonical_alias_and_foreign_or_duplicate_rejection(self):
  rows=[{'id':'model','meta':{'n_ctx':524289},'status':{'value':'loaded'}},{'id':'alias','alias_of':'model','meta':{'n_ctx':524289},'status':{'value':'loaded'}}]
  self.m.validate_models(rows,'model',524289,['alias'])
  for bad in (True,1.0):
   invalid=[dict(id='model',meta={'n_ctx':bad},status={'value':'loaded'})]
   with self.assertRaises(ValueError):self.m.validate_models(invalid,'model',1,[])
  for mutation in ('canonical','foreign','context','alias_of','status'):
   values=copy.deepcopy(rows)
   if mutation=='canonical':values.append(copy.deepcopy(rows[0]))
   elif mutation=='foreign':values[1]['id']='foreign'
   elif mutation=='context':values[1]['meta']['n_ctx']=4096
   elif mutation=='alias_of':values[1]['alias_of']='foreign'
   else:values[1]['status']['value']='unloaded'
   with self.assertRaises(ValueError):self.m.validate_models(values,'model',524289,['alias'])
 def test_observed_authority_and_unknown_INFO_identity(self):
  cfg='C:/owned/config.json';native={'pid':7,'created':1.25,'exe':'C:/owned/native.exe'}
  state={'family':'deepseek41','phase':'ready','config':cfg,'model':'model','context':524289,'pid':3,'created':1.0,'owned_identities':[native], 'launch_binding':{'runtime_epoch':1,'bundle_id':'a'*64,'config':cfg,'config_sha256':'b'*64,'runtime_package':{'id':'c'*64}}}
  observation={'runtime_epoch':1,'bundle_id':'a'*64,'primary_pci':'0000:07:00.0','identity_source':'fresh owned native exact argv','native':{'identity':native,'command':['C:/owned/native.exe','--serve','--runtime-epoch','1']},'native_INFO_identity_fields':{'bundle_id':None,'runtime_epoch':None,'primary_pci':None},'native_info':{'device_slots':3}}
  binding=self.m.observed_authority(state,observation);self.assertIsNone(binding['native_INFO_identity_fields']['runtime_epoch']);self.assertEqual(binding['runtime_epoch'],'1')
  large=1792568209599735400;bigstate=copy.deepcopy(state);bigstate['launch_binding']['runtime_epoch']=large;bigobs=copy.deepcopy(observation);bigobs['runtime_epoch']=large;bigobs['native']['command'][-1]=str(large);self.assertEqual(self.m.observed_authority(bigstate,bigobs)['runtime_epoch'],str(large))
  for wrong in (str(large+1),str(large-1)):
   bad=copy.deepcopy(bigobs);bad['native']['command'][-1]=wrong
   with self.assertRaises(ValueError):self.m.observed_authority(bigstate,bad)
  for axis in ('runtime_epoch','bundle_id','identity_source'):
   bad=copy.deepcopy(observation);bad[axis]=None
   with self.assertRaises(ValueError):self.m.observed_authority(state,bad)
  for epoch in (True,1.0):
   bad=copy.deepcopy(observation);bad['runtime_epoch']=epoch
   with self.assertRaises(ValueError):self.m.observed_authority(state,bad)
  bad=copy.deepcopy(state);bad['launch_binding']['runtime_epoch']=True
  with self.assertRaises(ValueError):self.m.observed_authority(bad,observation)
  for axis in ('config_sha256','bundle_id'):
   bad=copy.deepcopy(state);bad['launch_binding'][axis]='unknown'
   with self.assertRaises(ValueError):self.m.observed_authority(bad,observation)

class PiMetadataTests(unittest.TestCase):
 def test_actual_Pi_metadata_alias_and_arbitrary_context(self):
  import tempfile,json,hashlib,sys
  from unittest.mock import patch
  ai=Path(__file__).resolve().parents[6]
  old=list(sys.path)
  try:
   sys.path.insert(0,str(ai/'Strata-data'));spec=importlib.util.spec_from_file_location('t32_actual_Pi',ai/'Pi/runtime_check.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  finally:sys.path[:]=old
  saved=json.loads((ai/'Strata-data/build/deepseek-v41/build-deepseek-t31/normal-client-entry-attempt-1/ready.json').read_text(encoding='utf-8'))['state']
  model='deepseek-v4.1-flash-1017-ud-q4_k_xl';caps={k:True for k in ('supports_tools','supports_tool_calls','supports_system_role')}
  for context in (4096,524289):
   with self.subTest(context=context),tempfile.TemporaryDirectory()as directory:
    state=copy.deepcopy(saved);state['context']=context;cfg={'family':'deepseek41','context':context,'aliases':['family-alias']};path=Path(directory)/'config.json';path.write_text(json.dumps(cfg),encoding='utf-8');state['config']=str(path);state['launch_binding']['config']=str(path);state['launch_binding']['config_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    observation=copy.deepcopy(saved['family_ready_observation'])
    rows=[dict(id=model,meta={'n_ctx':context},status={'value':'loaded'}),dict(id='family-alias',alias_of=model,meta={'n_ctx':context},status={'value':'loaded'})]
    values={'/health':dict(status='ok',loaded=True,model=model,max_context=context,api_key=False),'/v1/models':{'data':rows},'/props':dict(chat_template_caps=caps,default_generation_settings={'n_ctx':context},total_slots=1)}
    with patch.object(m.manager,'read_state',side_effect=lambda:copy.deepcopy(state)),patch.object(m.manager,'require_owned_listener'),patch.object(m.manager,'validate_profile'),patch.object(m.manager,'require_family_ready',return_value=observation),patch.object(m.manager,'get_json',side_effect=lambda key:copy.deepcopy(values[key])):
     result=m._validate_original(model,context);self.assertEqual(result['context'],context);self.assertEqual(result['familyAuthority']['runtime_epoch'],str(state['launch_binding']['runtime_epoch']))


class ExistingBindingTests(unittest.TestCase):
 def test_family_epoch_changes_fingerprint_and_legacy_algorithm_unchanged(self):
  import sys
  ai=Path(__file__).resolve().parents[6];prior=list(sys.path)
  try:
   sys.path.insert(0,str(ai/'Strata-data'));import client_runtime as current
   old_path=ai/'Strata-data/build/deepseek-v41/build-deepseek-t32/before-source/Strata-data/client_runtime.py';spec=importlib.util.spec_from_file_location('t32_legacy_fingerprint',old_path);old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
  finally:sys.path[:]=prior
  value=dict(model='legacy',context=262144,pid=3,created=1.25,runtimeKind='strata',inputModalities=['text'])
  self.assertEqual(current._fingerprint(value),old._fingerprint(value))
  first=dict(value,familyAuthority=dict(runtime_epoch=1,bundle_id='a'*64));second=copy.deepcopy(first);second['familyAuthority']['runtime_epoch']=2
  self.assertNotEqual(current._fingerprint(first),current._fingerprint(second))
 def test_actual_Harness_overlay_preserves_legacy_and_exposes_SDK_levels(self):
  import subprocess,os,json
  ai=Path(__file__).resolve().parents[6];base=Path('C:/Users/yaruo/AppData/Local/Programs/Python/Python312/python.exe')
  code="import sys,json;sys.path.insert(0,'C:/Develop/AI/Harness');import runtime_binding as r;b=dict(model='model',context=262144,baseURL='http://127.0.0.1:18080/v1');print(json.dumps([r.make_overlay(b),r.make_overlay(dict(b,familyAuthority={'family':'deepseek41'}))]))"
  env={k:v for k,v in os.environ.items()if not k.upper().startswith('PYTHON')and k.upper()!='__PYVENV_LAUNCHER__'};env['__PYVENV_LAUNCHER__']=str(ai/'Strata/.venv/Scripts/python.exe')
  result=subprocess.run([str(base),'-I','-B','-X','utf8','-c',code],env=env,capture_output=True,text=True,encoding='utf-8');self.assertEqual(result.returncode,0,result.stderr);old,new=json.loads(result.stdout)
  get=lambda overlay:overlay[1]['config']['providers']['strata-local']['models'][0]['reasoningEfforts']
  self.assertEqual(get(old),dict(off='none',low='low',medium='medium',high='xhigh'))
  self.assertEqual(get(new),dict(off='none',minimal='minimal',low='low',medium='medium',high='high',xhigh='xhigh',max='max'))
  self.assertEqual(old[2]['insert'][0]['name'],new[2]['insert'][0]['name'])


class ContextSelectionTests(unittest.TestCase):
 def test_actual_selection_arbitrary_current_and_official_default(self):
  import sys
  from unittest.mock import patch
  ai=Path(__file__).resolve().parents[6];old=list(sys.path)
  try:
   sys.path.insert(0,str(ai/'Strata-data'));import client_selection as selected
  finally:sys.path[:]=old
  model='deepseek-v4.1-flash-1017-ud-q4_k_xl';index=str(list(selected.cli.catalog.CATALOG).index(model)+1)
  with patch.object(selected.cli,'show_models'),patch.object(selected.cli,'choose',side_effect=[index,'c']),patch('builtins.input',return_value='524289'):
   self.assertEqual(selected._target({}),(model,524289))
  defaults=[]
  def choose(_prompt,_choices,default):
   defaults.append(default);return index if len(defaults)==1 else default
  with patch.object(selected.cli,'show_models'),patch.object(selected.cli,'choose',side_effect=choose):
   self.assertEqual(selected._target({}),(model,262144));self.assertEqual(defaults[-1],'4')
  with patch.object(selected.cli,'show_models'),patch.object(selected.cli,'choose',side_effect=[index,'c']),patch('builtins.input',return_value=''):
   self.assertEqual(selected._target(dict(model=model,context=524289)),(model,524289))


class HarnessProbeTests(unittest.TestCase):
 def test_actual_probe_attaches_owned_family_and_rejects_foreign_alias(self):
  import sys,json,hashlib,tempfile
  from unittest.mock import patch
  ai=Path(__file__).resolve().parents[6];old=list(sys.path)
  try:
   sys.path.insert(0,str(ai/'Strata-data'));import client_runtime as clients;import manage_runtime as manager
   spec=importlib.util.spec_from_file_location('t32_actual_Harness_probe',ai/'Harness/runtime_probe.py');probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)
  finally:sys.path[:]=old
  saved=json.loads((ai/'Strata-data/build/deepseek-v41/build-deepseek-t31/normal-client-entry-attempt-1/ready.json').read_text(encoding='utf-8'))['state'];model=saved['model'];context=saved['context'];caps={k:True for k in ('supports_tools','supports_tool_calls','supports_system_role')}
  with tempfile.TemporaryDirectory()as directory:
   state=copy.deepcopy(saved);path=Path(directory)/'config.json';path.write_text(json.dumps(dict(aliases=['alias'])),encoding='utf-8');state['config']=str(path);state['launch_binding']['config']=str(path);state['launch_binding']['config_sha256']=hashlib.sha256(path.read_bytes()).hexdigest();candidate=dict(runtimeKind='strata',state=state)
   canonical=dict(id=model,meta={'n_ctx':context},status={'value':'loaded'},architecture={'input_modalities':['text']});alias=dict(copy.deepcopy(canonical),id='alias',alias_of=model)
   values={'/health':dict(service='strata',status='ok',loaded=True,model=model,max_context=context,api_key=False,images=False),'/v1/models':dict(data=[canonical,alias]),'/props':dict(chat_template_caps=caps,default_generation_settings={'n_ctx':context})}
   with patch.object(clients,'inspect_runtime',side_effect=lambda:copy.deepcopy(candidate)),patch.object(manager,'read_state',side_effect=lambda:copy.deepcopy(state)),patch.object(manager,'require_owned_listener'),patch.object(manager,'require_family_ready',return_value=copy.deepcopy(saved['family_ready_observation'])),patch.object(probe,'read_api',side_effect=lambda key:copy.deepcopy(values[key])):
    result=probe.probe();self.assertEqual(result['runtimeKind'],'strata');self.assertEqual(result['familyAuthority']['runtime_epoch'],str(state['launch_binding']['runtime_epoch']));self.assertIsNone(result['familyAuthority']['native_INFO_identity_fields']['runtime_epoch'])
    values['/v1/models']['data'][1]['id']='foreign'
    with self.assertRaises(probe.ProbeError):probe.probe()

if __name__=='__main__':unittest.main()
