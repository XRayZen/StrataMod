import unittest
import ast
import importlib.util
from pathlib import Path
import reference as r
import validate
import tempfile
import hashlib
OWN=Path(__file__).resolve().parents[2]
def provider():
 p=OWN/'control/providers/deepseek41.py';spec=importlib.util.spec_from_file_location('cache_role_provider',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def native_args(config):
 p=OWN/'models/deepseek41/server_hooks.py';tree=ast.parse(p.read_text(encoding='utf-8'));fn=next(x for x in tree.body if isinstance(x,ast.FunctionDef)and x.name=='native_args');scope={};exec(compile(ast.Module(body=[fn],type_ignores=[]),str(p),'exec'),scope);return scope['native_args'](config)
class CachePolicy(unittest.TestCase):
 def test_accepted_table_input_guard(self):
  with tempfile.TemporaryDirectory()as directory:
   p=Path(directory)/'sources.tsv';p.write_bytes(b'fixed original table');record=dict(path=str(p),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest());self.assertEqual(r.bound_input({'inputs':[record]},p),p.read_bytes())
   for rows in([],[record,record]):
    with self.assertRaises(ValueError):r.bound_input({'inputs':rows},p)
   p.write_bytes(b'changed original table')
   with self.assertRaises(ValueError):r.bound_input({'inputs':[record]},p)
 def test_DRAM_checked_selection(self):
  self.assertEqual(r.dram_selection(8589934592,131072,131072)['payload'],131072)
  self.assertEqual(r.dram_selection(1,131072,131072)['condition'],'not_met')
  self.assertEqual(r.dram_selection(None,131072,131072)['condition'],'unknown')
  self.assertEqual(r.dram_selection(1,131072,131072)['payload'],131072)
  for v in(-1,True,1.0,2**64):
   with self.assertRaises(ValueError):r.dram_selection(v,131072,131072)
 def test_DRAM_all_observation_points(self):
  points={'before':8589934592,'after':9663676416}
  self.assertEqual(r.dram_observed_condition(points,['before','after']),'met_at_observed_points')
  points['after']=8589934591;self.assertEqual(r.dram_observed_condition(points,['before','after']),'not_met')
  points['after']=None;self.assertEqual(r.dram_observed_condition(points,['before','after']),'unknown')
  self.assertEqual(r.dram_observed_condition(points,['before','after','during']),'unknown')
 def test_DRAM_strict_saved_observations(self):
  with tempfile.TemporaryDirectory()as directory:
   p=Path(directory)/'dram.tsv';row=['owners-constructed','1','123','0','9126805504','0','1000','900','2000','131072','null']
   def save():p.write_text('\t'.join(row)+'\n',encoding='utf-8')
   save();self.assertEqual(validate.validate_dram({},directory,131072,True)['condition'],'met_at_observed_points')
   row[5]='5';row[6:9]=['null']*3;save();value=validate.validate_dram({},directory,131072,True);self.assertEqual(value['condition'],'met_at_observed_points');self.assertFalse(value['process_resident_observations_complete']);row[5]='0';row[6:9]=['1000','900','2000']
   row[4]='8589934591';save();value=validate.validate_dram({},directory,131072,True);self.assertEqual(value['condition'],'not_met');self.assertTrue(value['report_only']);self.assertFalse(value['band_is_acceptance_gate']);self.assertFalse(value['outside_band_refuses_GEN'])
   row[3]='5';row[4]='null';save();self.assertEqual(validate.validate_dram({},directory,131072,True)['condition'],'unknown')
   row[3]='0';save()
   with self.assertRaises(ValueError):validate.validate_dram({},directory,131072,True)
   p.write_text('',encoding='utf-8')
   with self.assertRaises(ValueError):validate.validate_dram({},directory,131072,True)
 def test_explicit_capacity_and_unused(self):
  self.assertEqual(r.slots(10000,4096),dict(slots=2,capacity=8192,unused=1808))
  for n in (0,4095,-1,True,8192.0):
   with self.assertRaises(ValueError):r.slots(n,4096)
 def test_auto_extra_and_explicit_priority(self):
  self.assertEqual(r.target(None,10000,4096,0),4096)
  self.assertEqual(r.target(None,10000,4096,.5),9096)
  self.assertEqual(r.target(12288,10000,4096,1),12288)
  self.assertEqual(r.target(None,None,4096,.5),4096)
  for x in (-.1,1.1,float('nan'),True):
   with self.assertRaises(ValueError):r.target(None,10000,4096,x)
 def test_real_byte_ranges(self):
  self.assertTrue(r.disjoint((4096,4096),(8192,4096)))
  self.assertFalse(r.disjoint((4096,4096),(8191,4096)))
  self.assertFalse(r.disjoint((4096,4096),(4096,4096)))
  with self.assertRaises(ValueError):r.disjoint((2**64-1,2),(1,1))
 def test_unknown_requires_retention_and_safe_primary(self):
  self.assertEqual(r.recovery('copy_unknown',0,True,True),'bypass_retained')
  for drain,held,separate in ((-1,True,True),(0,False,True),(0,True,False)):
   self.assertEqual(r.recovery('copy_unknown',drain,held,separate),'error_retain')
 def test_errors_are_not_cache_misses(self):
  self.assertEqual(r.recovery('allocation',0,False,True),'bypass')
  self.assertEqual(r.recovery('copy_drained',0,False,True),'bypass')
  for reason in ('source','shape','primary_context','unknown_kind'):
   self.assertEqual(r.recovery(reason,0,False,True),'error')
 def test_native_tile_key_axes(self):
  base=('revision','lfs','path','tensor',38,0,256,5120,39,1000,696320)
  self.assertEqual(r.tile_key(base),base)
  for i in range(len(base)):
   changed=list(base);changed[i]=str(changed[i])+'x';self.assertNotEqual(r.tile_key(changed),base)
 def test_declared_secondary_budget(self):
  p=provider()
  for value in ('auto',4096,2**40):self.assertEqual(p.budget({'secondary_device_cache_payload_bytes':value})['secondary_device_cache_payload_bytes'],value)
  for value in (0,-1,True,4096.0,'4096'):
   with self.assertRaises(ValueError):p.budget({'secondary_device_cache_payload_bytes':value})
 def test_normal_role_transport(self):
  cfg=dict(artifact_root='original',primary_pci='0000:07:00.0',context=4096,bundle_id='fixed',runtime_epoch=1,native_paths=[],cache_budget={'secondary_device_cache_payload_bytes':8192})
  self.assertNotIn('--mode',native_args(cfg))
  cfg['placement']=dict(mode='cache-only',primary=cfg['primary_pci'],secondary='0000:03:00.0')
  args=native_args(cfg);self.assertEqual(args[args.index('--mode')+1],'cache-only');self.assertEqual(args[args.index('--secondary-pci')+1],'0000:03:00.0');self.assertEqual(args[args.index('--secondary-device-cache-payload-bytes')+1],'8192')
  cfg['placement']['primary']='0000:01:00.0'
  with self.assertRaises(ValueError):native_args(cfg)
if __name__=='__main__':unittest.main()
