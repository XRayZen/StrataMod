import unittest,importlib.util,sys,copy
from pathlib import Path
OWN=Path(__file__).resolve().parents[2]
def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
L=module('t46_launch',OWN/'control/deepseek_launch.py')
class ExecutionPackageTests(unittest.TestCase):
 def test_finite_execution_input_and_native_parent_binding(self):
  import mode_fixture as F,json
  stage=F.load('t46_package_input',OWN/'tests/providers/runtime_stage.py');path=OWN.parent/'build-deepseek-t46/package-input-r1/inputs.json';value=stage.selected_inputs(path)
  self.assertEqual(value['expected_copy_count'],63);self.assertEqual(value['execution_abi'],'strata-deepseek-execution/v1')
  seen={r['relative_destination']for r in value['selected_files']}
  for change in ('ABI','parent','count','native','DLL','protected'):
   bad=copy.deepcopy(value)
   if change=='ABI':bad['execution_abi']='unknown'
   elif change=='parent':bad['parent_id']='0'*64
   elif change=='count':bad['expected_copy_count']=62
   elif change=='native':bad['native_compiled_source_id']='0'*64
   elif change=='DLL':bad['native_bundle_dlls'][0]['sha256']='0'*64
   else:next(r for r in bad['selected_files']if r['relative_destination']=='clients/chat.py')['sha256']='0'*64
   with self.assertRaises(ValueError,msg=change):stage.validate_execution_extension(bad,seen)
  bad=copy.deepcopy(value);bad['selected_files']=[r for r in bad['selected_files']if r['relative_destination']!='Strata-extensions/control/contracts.py']
  with self.assertRaises(ValueError):stage.validate_execution_extension(bad,{r['relative_destination']for r in bad['selected_files']})
class ModeOverlayTests(unittest.TestCase):
 def profile(self):return dict(family='deepseek41',primary_pci='0000:07:00.0')
 def test_explicit_modes_and_single_restore(self):
  p=self.profile();expert=L.overlay(p,dict(mode='expert-assist',secondary_pci='0000:03:00.0',assignment=[0,37,383]))
  self.assertEqual(expert['placement'],dict(mode='expert-assist',primary=p['primary_pci'],secondary='0000:03:00.0',assignment=[0,37,383]))
  split=L.overlay(expert,dict(mode='layer-split',cut=24));self.assertEqual(split['placement']['cut'],24);self.assertNotIn('assignment',split['placement'])
  single=L.overlay(split,dict(mode='single'));self.assertEqual(single['placement'],dict(mode='single',primary=p['primary_pci'],secondary=None))
  self.assertEqual(p,self.profile());self.assertEqual(L.overlay(p,{}),p)
 def test_type_domain_and_cross_mode_options(self):
  for opts in (dict(mode='expert-assist',secondary_pci='0000:03:00.0',assignment=[True]),dict(mode='expert-assist',secondary_pci='0000:03:00.0',assignment=[1,1]),dict(mode='layer-split',secondary_pci='0000:03:00.0',cut=True),dict(mode='single',assignment=[1]),dict(mode='cache-only',secondary_pci='0000:07:00.0'),dict(mode='unknown')):
   with self.assertRaises(ValueError,msg=opts):L.overlay(self.profile(),opts)
 def test_single_on_previous_secondary_and_role_swap(self):
  expert=L.overlay(self.profile(),dict(mode='expert-assist',secondary_pci='0000:03:00.0',assignment=[1]))
  selected=L.overlay(expert,dict(mode='single',primary_pci='0000:03:00.0'))
  self.assertEqual(selected['placement'],dict(mode='single',primary='0000:03:00.0',secondary=None))
  swapped=L.overlay(expert,dict(primary_pci='0000:03:00.0',secondary_pci='0000:07:00.0'))
  self.assertEqual(swapped['placement']['secondary'],'0000:07:00.0')
 def test_old_cache_options_equal_before_implementation(self):
  before=OWN.parents[0]/'build-deepseek-t46/CPU-component-1/before/deepseek_launch.py'
  old=module('t46_before_launch',before)
  for opts in ({},dict(ram_cache_payload_bytes=123456,auto_cache_fraction=0,auto_row_fraction=0),dict(primary_pci='0000:03:00.0')):
   self.assertEqual(L.overlay(self.profile(),opts),old.overlay(self.profile(),opts))
 def test_mode_only_uses_saved_recommendations_and_manual_is_optional(self):
  p=dict(self.profile(),execution_defaults=dict(devices=['0000:07:00.0','0000:03:00.0'],assignment=list(range(1,384,2)),cut=24))
  expert=L.overlay(p,dict(mode='expert-assist'));self.assertEqual(len(expert['placement']['assignment']),192);self.assertEqual(expert['placement']['secondary'],'0000:03:00.0')
  split=L.overlay(expert,dict(mode='layer-split'));self.assertEqual(split['placement']['cut'],24)
  previous=L.overlay(p,dict(mode='expert-assist',assignment=[7],secondary_pci='0000:09:00.0'))
  self.assertEqual(L.overlay(previous,dict(mode='expert-assist'))['placement']['assignment'],[7]);self.assertEqual(L.overlay(previous,dict(primary_pci='0000:08:00.0',mode='expert-assist'))['placement']['secondary'],'0000:09:00.0')
  manual=L.overlay(p,dict(primary_pci='0000:08:00.0',mode='layer-split',secondary_pci='0000:09:00.0',cut=1));self.assertEqual(manual['placement']['cut'],1)
  with self.assertRaises(ValueError):L.overlay(p,dict(primary_pci='0000:08:00.0',mode='cache-only'))
 def test_defaults_are_declared_values_not_runtime_presence(self):
  for defaults in (None,dict(devices=['0000:07:00.0']*2,assignment=[1],cut=24),dict(devices=['0000:07:00.0','0000:03:00.0'],assignment=[True],cut=24)):
   with self.assertRaises(ValueError):L.execution_defaults(defaults)
class ModeReadyInfoTests(unittest.TestCase):
 def compute(self,cut=None):
  import mode_fixture as F
  cfg=dict(family='deepseek41',context=4096,primary_pci='0000:07:00.0',secondary='0000:03:00.0',placement=dict(mode='expert-assist',primary='0000:07:00.0',secondary='0000:03:00.0',assignment=[1,3]))
  if cut is not None:cfg['placement']=dict(mode='layer-split',primary=cfg['primary_pci'],secondary=cfg['secondary'],cut=cut)
  pr=1 if cut is None or cut>1 else 0;sr=1 if cut is not None and cut<=14 else 0;w=2097152;pp=w+pr*264;sp=w+sr*264
  info=dict(family='deepseek41',context=4096,configured_mode=cfg['placement']['mode'],effective_mode=cfg['placement']['mode'],primary_pci=cfg['primary_pci'],requested_secondary_pci=cfg['secondary'],actual_secondary_pci=cfg['secondary'],secondary_experts=[1,3]if cut is None else None,layer_cut=cut,head_role='primary'if cut is None else'secondary',device_slots=1,row_device_slots=pr,ram_slots=1,row_ram_slots=pr,secondary_device_slots=1,secondary_row_device_slots=sr,secondary_ram_slots=1,secondary_row_ram_slots=sr,device_cache_payload_bytes=pp,secondary_device_cache_payload_bytes=sp,ram_cache_payload_bytes=pp+sp,declared_device_cache_payload_bytes=None,declared_ram_cache_payload_bytes=None,auto_cache_fraction=.5,auto_row_fraction=1/64,weight_tile_bytes=w,working_minimum_payload_bytes=pp+sp,mode_ram_target_bytes=pp+sp,mode_ram_minimum_payload_bytes=pp+sp,mode_ram_extra_primary_bytes=0,mode_ram_extra_secondary_bytes=0,mode_ram_unused_bytes=0,mode_primary_ram_payload_bytes=pp,mode_secondary_ram_payload_bytes=sp,actual_device_owned=100,actual_primary_device_owned=100,actual_secondary_device_owned=200,actual_all_role_device_owned=300)
  return cfg,info
 def test_compute_absent_rows_are_zero_and_roles_are_observed(self):
  import mode_fixture as F
  for cut in (None,1,2,14,15,24,39):
   cfg,info=self.compute(cut)
   with F.declared_mode_package(cfg)as declared:self.assertEqual(L.validate_ready_info(declared,info),info)
 def test_compute_mismatch_cannot_be_saved_as_ready(self):
  import mode_fixture as F
  cfg,info=self.compute(1)
  for key,bad in (('row_ram_slots',1),('secondary_row_ram_slots',0),('configured_mode','single'),('actual_secondary_pci',None),('layer_cut',True),('ram_cache_payload_bytes',1),('mode_ram_minimum_payload_bytes',1),('actual_all_role_device_owned',100),('declared_device_cache_payload_bytes',1)):
   value=copy.deepcopy(info);value[key]=bad
   with F.declared_mode_package(cfg)as declared:
    with self.assertRaises(RuntimeError,msg=key):L.validate_ready_info(declared,value)
class ModeTransportTests(unittest.TestCase):
 def test_display_uses_observed_mode_not_saved_recommendation(self):
  import mode_fixture as F
  cli=F.cli();state=dict(execution_defaults=dict(cut=24),placement=dict(mode='layer-split',cut=24))
  self.assertIsNone(cli.describe_execution(state))
  state['family_ready_observation']=dict(native_info=dict(configured_mode='layer-split',effective_mode='layer-split',primary_pci='0000:08:00.0',actual_secondary_pci='0000:09:00.0',layer_cut=14,secondary_experts=None))
  text=cli.describe_execution(state);self.assertIn('cut 14',text);self.assertIn('0000:09:00.0',text);self.assertNotIn('cut 24',text)
 def test_native_ownership_command_matches_real_hook(self):
  import mode_fixture as F
  hook=F.hooks();base=dict(family='deepseek41',exe='native.exe',artifact_root='assets',primary_pci='0000:07:00.0',context=4096,bundle_id='a'*64,runtime_epoch=1,native_paths=['one'],execution_defaults=dict(devices=['0000:07:00.0','0000:03:00.0'],assignment=list(range(1,384,2)),cut=24))
  with F.declared_mode_package(base)as declared:
   for mode in ('single','cache-only','expert-assist','layer-split'):
    cfg=L.overlay(declared,dict(mode=mode));self.assertEqual(L.native_command(cfg),[cfg['exe'],'--serve']+hook.native_args(cfg))
 def test_old_public_package_uses_its_actual_single_hook(self):
  import mode_fixture as F,json
  cfg=json.loads(Path('C:/Develop/AI/Strata-data/profiles/deepseek-v4.1-flash-1017-ud-q4_k_xl-4096.json').read_text(encoding='utf8'));cfg.update(runtime_epoch=1,artifact_root='assets',native_paths=['one'])
  # Historical legacy contract must not follow the mutable installed selection.
  root=Path('C:/Develop/AI/Strata-extensions/runtime/deepseek41/5df2e15e93218566e9411fafe053a20b6e102418076dd2c73695dbe7acfbc689')
  cfg['runtime_package']=dict(id=root.name,manifest=str(root/'evidence/package-manifest.json'))
  from unittest.mock import patch
  import types
  with patch.dict(sys.modules,{'deepseek_recipe':types.ModuleType('deepseek_recipe')}):old=F.load('t46_old_selected_hook',root/'Strata-extensions/models/deepseek41/server_hooks.py')
  self.assertFalse(L.execution_capability(cfg));self.assertEqual(L.native_command(cfg),[cfg['exe'],'--serve']+old.native_args(cfg))
  with self.assertRaisesRegex(ValueError,'does not declare'):L.overlay(cfg,dict(mode='expert-assist',secondary_pci='0000:03:00.0',assignment=[1]))
 def test_mode_capability_is_bound_to_hook_and_known_ABI(self):
  import mode_fixture as F,json
  with F.declared_mode_package(self._base_for_capability())as cfg:
   self.assertTrue(L.execution_capability(cfg));manifest=Path(cfg['runtime_package']['manifest']);value=json.loads(manifest.read_text());value['execution_extension']['abi']='unknown';manifest.write_text(json.dumps(value))
   with self.assertRaises(ValueError):L.execution_capability(cfg)
   value['execution_extension']['abi']='strata-deepseek-execution/v1';value['files'][0]['sha256']='0'*64;manifest.write_text(json.dumps(value))
   with self.assertRaises(ValueError):L.execution_capability(cfg)
 def _base_for_capability(self):return dict(family='deepseek41',primary_pci='0000:07:00.0')
 def test_new_profile_defaults_are_opt_in_and_not_saved_here(self):
  import mode_fixture as F
  stage=F.load('t46_stage',OWN/'tests/providers/runtime_stage.py');paths=stage.package_paths(Path('C:/isolated'), 'a'*64)
  ordinary=stage.normal_options(paths,'b'*64,4096,Path('C:/isolated-data'));self.assertNotIn('execution_defaults',ordinary)
  new=stage.mode_options(paths,'b'*64,4096,Path('C:/isolated-data'));self.assertEqual(new['execution_defaults']['cut'],24);self.assertEqual(len(new['execution_defaults']['assignment']),192)
  self.assertEqual(new['placement']['mode'],'single')
  with F.declared_mode_package(dict(new,family='deepseek41'))as declared:self.assertEqual(L.overlay(declared,dict(mode='layer-split'))['placement']['cut'],24)
 def test_cli_parses_explicit_fields_only(self):
  import mode_fixture as F
  cli=F.cli();model='deepseek-v4.1-flash-1017-ud-q4_k_xl'
  old=cli.parser().parse_args(['start','--model',model]);self.assertIsNone(old.mode)
  new=cli.parser().parse_args(['start','--model',model,'--mode','expert-assist','--secondary-pci','0000:03:00.0','--expert-ids','0,37,383'])
  self.assertEqual(new.mode,'expert-assist');self.assertEqual(new.expert_ids,'0,37,383')
 def test_cli_forwards_overlay_without_runtime_start(self):
  import mode_fixture as F
  from types import SimpleNamespace
  from unittest.mock import patch
  cli=F.cli();rt=SimpleNamespace();model='deepseek-v4.1-flash-1017-ud-q4_k_xl'
  with patch.object(cli,'start_selected')as start:
   self.assertEqual(cli.main(['start','--model',model,'--mode','expert-assist','--secondary-pci','0000:03:00.0','--expert-ids','0,37,383'],rt=rt),0)
   self.assertEqual(rt.launch_options,dict(mode='expert-assist',secondary_pci='0000:03:00.0',assignment=[0,37,383]));self.assertEqual(start.call_count,1)
  rt=SimpleNamespace()
  with patch.object(cli,'start_selected'):
   self.assertEqual(cli.main(['start','--model',model],rt=rt),0);self.assertFalse(hasattr(rt,'launch_options'))
 def test_reserved_assignment_and_cut_cannot_override_generated_arguments(self):
  import mode_fixture as F,json
  provider=F.load('t46_test_provider',OWN/'control/providers/deepseek41.py')
  cfg=json.loads(Path('C:/Develop/AI/Strata-data/profiles/deepseek-v4.1-flash-1017-ud-q4_k_xl-4096.json').read_text(encoding='utf8'))
  for flag in ('--secondary-experts','--layer-cut'):
   value=copy.deepcopy(cfg);value['args']=[flag,'1']
   with self.assertRaises(ValueError):provider.normal_fields(value)
 def test_native_args_mode_shape_and_legacy_default(self):
  import mode_fixture as F
  hook=F.hooks();base=dict(artifact_root='assets',primary_pci='0000:07:00.0',context=4096,bundle_id='a'*64,runtime_epoch=1)
  legacy=hook.native_args(base);self.assertNotIn('--mode',legacy)
  expert=L.overlay(dict(base,family='deepseek41'),dict(mode='expert-assist',secondary_pci='0000:03:00.0',assignment=[0,37,383]))
  args=hook.native_args(expert);self.assertEqual(args[args.index('--secondary-experts')+1],'0,37,383')
  split=L.overlay(expert,dict(mode='layer-split',cut=24));args=hook.native_args(split);self.assertEqual(args[args.index('--layer-cut')+1],'24');self.assertNotIn('--secondary-experts',args)

if __name__=='__main__':unittest.main()
