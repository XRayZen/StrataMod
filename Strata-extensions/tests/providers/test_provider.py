import shutil,sys,hashlib,copy,importlib.util,json,pathlib,tempfile,unittest
from unittest.mock import patch
EXT=pathlib.Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('t29_provider',EXT/'control/providers/deepseek41.py');provider=importlib.util.module_from_spec(spec);spec.loader.exec_module(provider)
class ProviderTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.temp.name);self.rows=[]
  for i in range(1,10):
   name=f'DeepSeek-V4.1-Flash-1017-UD-Q4_K_XL-{i:05d}-of-00009.gguf';p=self.root/name;p.write_bytes(b'GGUF'+(3).to_bytes(4,'little')+b'0'*16);self.rows.append(dict(index=i,filename=name,bytes=24,lfs_sha256=f'{i:064x}'))
  (self.root/'tokenizer.json').write_text(json.dumps(dict(model=dict(vocab={'x':0}),added_tokens=[])))
  (self.root/'native.exe').write_bytes(b'fixture-not-runtime')
  self.asset=dict(artifact_root=str(self.root),native_paths=[str(self.root/x['filename']) for x in self.rows],fixedrevision=provider.REVISION,layout=provider.LAYOUT,tokenizer=str(self.root/'tokenizer.json'),exe=str(self.root/'native.exe'))
  self.profiles=patch.object(provider,'SOURCES',self.rows);self.profiles.start();self.tokenizer_patch=patch.object(provider,"TOKENIZER_SHA256",hashlib.sha256((self.root/"tokenizer.json").read_bytes()).hexdigest());self.tokenizer_patch.start()
 def tearDown(self):self.profiles.stop();self.tokenizer_patch.stop();self.temp.cleanup()
 def test_context_range_is_not_fixture_cap(self):
  for n in (1,3,262144,524288,1048576):self.assertEqual(provider.context(n),n)
  for n in (True,False,0,-1,1048577,1.5,'3'):
   with self.subTest(n=n),self.assertRaises(ValueError):provider.context(n)
 def test_original_sources_and_typed_spans(self):
  value=provider.assets(self.asset);self.assertEqual(len(value['sources']),9)
  provider.source_spans(value,[dict(shard_index=2,absolute_offset=8,bytes=16,type_id=0,dims=[4,1])])
  for changes in (dict(shard_index=True),dict(absolute_offset=9),dict(bytes=-1),dict(type_id=117),dict(dims=[32,True])):
   row=dict(shard_index=2,absolute_offset=8,bytes=16,type_id=0,dims=[4,1]);row.update(changes)
   with self.subTest(row=row),self.assertRaises(ValueError):provider.source_spans(value,[row])
 def test_missing_duplicate_wrong_native_binding(self):
  for key,value in [('fixedrevision','wrong'),('layout','Qwen'),('native_paths',self.asset['native_paths'][:-1]),('native_paths',[self.asset['native_paths'][0]]*9),('tokenizer',str(self.root/'missing')),('exe',str(self.root/'missing'))]:
   bad=copy.deepcopy(self.asset);bad[key]=value
   with self.subTest(key=key),self.assertRaises((ValueError,OSError)):provider.assets(bad)
 def test_profile_is_pure_and_preserves_actual_fields(self):
  before={p.name:p.read_bytes() for p in self.root.iterdir()};value=provider.profile(self.asset,262144,dict(primary_pci='0000:07:00.0',secondary=None,cache_budget=dict(device_cache_payload_bytes='auto',ram_cache_payload_bytes=67108864),host='127.0.0.1',port=18080,env={},lib_dirs=['C:/owned'],runtimeepoch=1))
  self.assertEqual(value['context'],262144);self.assertEqual(value['cache_budget']['ram_cache_payload_bytes'],67108864);self.assertEqual(value['secondary'],None);self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.iterdir()});self.assertNotIn('--mtp',value.get('args',[]));self.assertNotIn('resolved_cache_budget',value)
 def test_budget_field_meaning_not_blanket_scalar_zero(self):
  self.assertEqual(provider.budget(dict(device_cache_payload_bytes='auto',ram_cache_payload_bytes=4194304)),dict(device_cache_payload_bytes='auto',ram_cache_payload_bytes=4194304))
  for v in (0,-1,True,1.5,'2GiB'):
   with self.subTest(v=v),self.assertRaises(ValueError):provider.budget(dict(ram_cache_payload_bytes=v))
  opts=dict(primary_pci='0000:07:00.0',secondary=None,cache_budget={},seed=0,top_k=0,min_p=0)
  value=provider.profile(self.asset,262144,opts);self.assertEqual((value['seed'],value['top_k'],value['min_p']),(0,0,0))
 def test_profile_target_family_and_layout(self):
  value=provider.profile(self.asset,1048576,dict(primary_pci='0000:07:00.0',cache_budget={}))
  self.assertEqual(provider.validate_profile(value,1048576)['family'],'deepseek41')
  for change in (dict(family='qwen'),dict(context=True),dict(primary_pci='1'),dict(model_name='other')):
   bad=copy.deepcopy(value);bad.update(change)
   with self.subTest(change=change),self.assertRaises(ValueError):provider.validate_profile(bad,1048576)
 def test_actual_tokenizer_identity_and_zero_semantics(self):
  (self.root/'tokenizer.json').write_text('foreign tokenizer')
  with self.assertRaises(ValueError):provider.assets(self.asset)
 def test_declared_fraction_is_not_resolved_allocation(self):
  for v in (True,float('nan'),float('inf'),1.1,-1):
   with self.subTest(v=v),self.assertRaises(ValueError):provider.profile(self.asset,3,dict(primary_pci='0000:07:00.0',auto_cache_fraction=v))
  for fraction in (0,.5,1):
   for field in ('auto_cache_fraction','auto_row_fraction'):self.assertEqual(provider.profile(self.asset,3,dict(primary_pci='0000:07:00.0',**{field:fraction}))[field],fraction)
 def catalog(self,path,name):
  data=EXT.parents[2];sys.path.insert(0,str(data))
  try:
   spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
  finally:sys.path.pop(0)
 def test_catalog_context_and_missing_asset_reselection_is_read_only(self):
  data=EXT.parents[2];catalog=self.catalog(data/'model_catalog.py','current_catalog')
  self.assertEqual(list(catalog.CATALOG)[0],'huihui-ud-q4_k_xl_v2')
  for n in (1,3,1048576):catalog.require_public_context(provider.MODEL,n)
  for n in (True,0,1048577):
   with self.assertRaises(RuntimeError):catalog.require_public_context(provider.MODEL,n)
  before={p.name:p.read_bytes() for p in self.root.iterdir()};ready,reason=catalog.availability(provider.MODEL,self.root);self.assertFalse(ready);self.assertTrue(reason);self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.iterdir()})
 def test_huihui_catalog_and_profile_behavior_unchanged(self):
  data=EXT.parents[2];current=self.catalog(data/'model_catalog.py','current_catalog');old=self.catalog(EXT.parent/'build-deepseek-t29/before/model_catalog.py','old_catalog');model='huihui-ud-q4_k_xl_v2'
  self.assertEqual(current.CATALOG[model],old.CATALOG[model]);self.assertEqual(current.CONTEXTS,old.CONTEXTS);self.assertEqual(current.SHARDS,old.SHARDS);self.assertEqual(current.PACK_FILES,old.PACK_FILES)
  for function,args in [('public_contexts',(model,)),('shard_path',(model,2,self.root)),('source_receipts',(model,self.root)),('source_ple_shard',(model,self.root)),('availability',(model,self.root))]:self.assertEqual(getattr(current,function)(*args),getattr(old,function)(*args))
  cfg=json.loads((data/'profiles'/f'{model}-262144.json').read_text(encoding='utf-8-sig'));self.assertEqual(current.validate_layout(cfg,model,262144,2,data),old.validate_layout(cfg,model,262144,2,data))
 def test_nondefault_only_catalog_profile_is_usable(self):
  data=EXT.parents[2];catalog=self.catalog(data/'model_catalog.py','nondefault_catalog');catalog_root=self.root/'DATA';(catalog_root/'profiles').mkdir(parents=True)
  install=self.root/'Strata-extensions/control/providers';install.mkdir(parents=True);shutil.copyfile(EXT/'control/providers/deepseek41.py',install/'deepseek41.py');shutil.copyfile(EXT/'control/contracts.py',install.parent/'contracts.py')
  rows=repr(self.rows);text=(install/'deepseek41.py').read_text();start=text.index('SOURCES = ');end=text.index('\n',start);text=text[:start]+'SOURCES = '+rows+text[end:];text='\n'.join(('TOKENIZER_SHA256 = '+repr(hashlib.sha256((self.root/'tokenizer.json').read_bytes()).hexdigest())) if line.startswith('TOKENIZER_SHA256 =') else line for line in text.splitlines());(install/'deepseek41.py').write_text(text)
  value=provider.profile(self.asset,524288,dict(primary_pci='0000:07:00.0',cache_budget={}));(catalog_root/'profiles'/f'{provider.MODEL}-524288.json').write_text(json.dumps(value))
  self.assertIsNone(catalog.require_ready(provider.MODEL,catalog_root,524288));self.assertTrue(catalog.availability(provider.MODEL,catalog_root)[0]);self.assertEqual(catalog.shard_path(provider.MODEL,2,catalog_root),self.root/self.rows[1]['filename']);self.assertTrue(catalog.verify_sources(provider.MODEL,catalog_root)['sources']);self.assertTrue(catalog.availability(provider.MODEL,catalog_root,524288)[0]);self.assertEqual(catalog.shard_path(provider.MODEL,2,catalog_root,524288),self.root/self.rows[1]['filename']);self.assertFalse((catalog_root/'profiles'/f'{provider.MODEL}-262144.json').exists())
 def test_optional_generic_placement_uses_existing_contract(self):
  base=dict(primary_pci='0000:07:00.0',secondary=None,cache_budget={})
  for mode in ('single','cache-only','expert-assist','layer-split'):
   row=dict(mode=mode,primary=base['primary_pci'],secondary=None if mode=='single' else '0000:03:00.0')
   if mode=='expert-assist':row['assignment']=[0,383]
   if mode=='layer-split':row.update(cut=20,head='secondary')
   opts=copy.deepcopy(base);opts['placement']=row;opts['secondary']=row['secondary'];value=provider.profile(self.asset,262144,opts);self.assertEqual(provider.validate_profile(value,262144)['placement'],row)
  for row in (dict(mode='cache-only',primary=base['primary_pci'],secondary=base['primary_pci']),dict(mode='other',primary=base['primary_pci'],secondary=None),dict(mode='single',primary='0000:03:00.0',secondary=None),dict(mode='cache-only',primary=base['primary_pci'],secondary='0000:03:00.0')):
   opts=copy.deepcopy(base);opts['placement']=row
   with self.subTest(row=row),self.assertRaises(ValueError):provider.profile(self.asset,262144,opts)
 def normal_declaration(self):
  root=self.root/('a'*64)
  return dict(runtime_package=dict(id='a'*64,manifest=str(root/'evidence/package-manifest.json')),python=str(root/'venv/Scripts/python.exe'),server_entry=str(root/'Strata-extensions/control/deepseek_serve.py'),upstream_root=str(root/'base'),exe=str(root/'native/Strata-deepseek.exe'),tokenizer=str(root/'resources/tokenizer.json'),bundle_id='b'*64,args=[],aliases=['deepseek-v4.1-flash-1017'])
 def test_optional_normal_declaration(self):provider.normal_fields(self.normal_declaration())
 def test_partial_normal_declaration_rejected(self):
  value=self.normal_declaration();value.pop('python')
  with self.assertRaises(ValueError):provider.normal_fields(value)
 def test_runtime_path_escape_rejected(self):
  value=self.normal_declaration();value['python']=str(self.root/('a'*64)/'../foreign/python.exe')
  with self.assertRaises(ValueError):provider.normal_fields(value)
 def test_native_flag_override_rejected(self):
  for args in (['--context','16'],['--source1=other'],['--runtime-epoch','1']):
   value=self.normal_declaration();value['args']=args
   with self.assertRaises(ValueError):provider.normal_fields(value)
 def test_static_epoch_not_required_but_launch_positive(self):
  value=self.normal_declaration();provider.normal_fields(value)
  for epoch in (0,-1,True,'1'):
   value['runtime_epoch']=epoch
   with self.assertRaises(ValueError):provider.normal_fields(value)
  value['runtime_epoch']=1;provider.normal_fields(value)
 def test_alias_collision_and_type(self):
  for aliases in (['A','a'],[''],[True],'alias'):
   value=self.normal_declaration();value['aliases']=aliases
   with self.assertRaises(ValueError):provider.normal_fields(value)
if __name__=='__main__':unittest.main()
