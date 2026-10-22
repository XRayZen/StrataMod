"""CPU-only fixed runtime packaging guards; no native or listener."""
import hashlib,json,pathlib,tempfile,unittest
from unittest.mock import patch
import runtime_stage as runtime

class StageTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.temp.name)
 def tearDown(self):self.temp.cleanup()
 def test_raw_sha(self):
  p=self.root/'METADATA';p.write_bytes(b'Name: x\r\n');r=runtime.record(p)
  self.assertEqual(r['sha256'],hashlib.sha256(b'Name: x\r\n').hexdigest());runtime.check_record(r)
 def test_mutated_record_rejected(self):
  p=self.root/'x';p.write_bytes(b'a');r=runtime.record(p);p.write_bytes(b'b')
  with self.assertRaises(ValueError):runtime.check_record(r)
 def test_size_rejected(self):
  p=self.root/'x';p.write_bytes(b'a');r=runtime.record(p);r['bytes']=2
  with self.assertRaises(ValueError):runtime.check_record(r)
 def test_safe_relative(self):
  self.assertEqual(runtime.destination(self.root,'serve/frontend.py'),self.root/'serve/frontend.py')
 def test_parent_and_absolute_rejected(self):
  for v in ('../escape','/escape','C:/escape','serve/../../escape'):
   with self.assertRaises(ValueError):runtime.destination(self.root,v)
 def test_wheel_lock(self):
  p=self.root/'x.whl';p.write_bytes(b'wheel');r=runtime.record(p)
  self.assertIn('--hash=sha256:'+r['sha256'],runtime.lock_line(r))
 def test_whitespace_wheel_lock(self):
  p=self.root/'with space'/'x.whl';p.parent.mkdir();p.write_bytes(b'w')
  self.assertTrue(runtime.lock_line(runtime.record(p)).startswith('file:///'));self.assertIn('with%20space',runtime.lock_line(runtime.record(p)))
 def test_wheel_expected_hash_required(self):
  p=self.root/'x.whl';p.write_bytes(b'x')
  with self.assertRaises(ValueError):runtime.check_wheel(p,1,'0'*64)
 def test_metadata_raw_not_normalized(self):
  p=self.root/'METADATA';p.write_bytes(b'a\r\n');r=runtime.record(p)
  self.assertNotEqual(r['sha256'],hashlib.sha256(p.read_text().encode()).hexdigest())
 def test_profile_protection_detects_newfile(self):
  (self.root/'a.json').write_text('{}');before=runtime.protected(self.root)
  (self.root/'b.json').write_text('{}');self.assertNotEqual(before,runtime.protected(self.root))
 def test_distribution_exact_filename(self):
  with self.assertRaises(ValueError):runtime.wheel_name('../escape.whl')
 def test_distribution_exact_filename_good(self):
  self.assertEqual(runtime.wheel_name('jinja2-3.1.6-py3-none-any.whl'),'jinja2-3.1.6-py3-none-any.whl')
 def test_atomic_new_keeps_foreign(self):
  p=self.root/'profile.json';p.write_bytes(b'foreign')
  with self.assertRaises(ValueError):runtime.atomic_new(p,b'new')
  self.assertEqual(p.read_bytes(),b'foreign')
 def test_atomic_new_idempotent(self):
  p=self.root/'profile.json';runtime.atomic_new(p,b'new');runtime.atomic_new(p,b'new');self.assertEqual(p.read_bytes(),b'new')
 def test_racing_foreign_creation_not_replaced(self):
  p=self.root/'profile.json';link=runtime.os.link
  def racing(source,target):
   pathlib.Path(target).write_bytes(b'foreign');return link(source,target)
  with patch.object(runtime.os,'link',racing),self.assertRaises(FileExistsError):runtime.atomic_new(p,b'new')
  self.assertEqual(p.read_bytes(),b'foreign')
 def test_package_id_rejects_bool_or_short(self):
  for v in (True,'a'*63,'z'*64):
   with self.assertRaises(ValueError):runtime.package_paths(self.root,v)
 def test_package_paths_is_owned(self):
  paths=runtime.package_paths(self.root,'a'*64)
  self.assertTrue(paths['python'].is_relative_to(self.root));self.assertEqual(paths['base'].name,'base')
 def test_runtime_epoch_not_static(self):
  options=runtime.normal_options(runtime.package_paths(self.root,'a'*64),'b'*64,4096,self.root)
  self.assertNotIn('runtime_epoch',options);self.assertEqual(options['cache_budget']['device_cache_payload_bytes'],'auto')
 def test_catalog_import_uses_data_siblings_and_restores_path(self):
  import sys
  (self.root/'profile_defaults.py').write_text('VALUE=17\n')
  (self.root/'model_catalog.py').write_text('from profile_defaults import VALUE\n')
  old=list(sys.path);previous=sys.modules.pop('profile_defaults',None)
  try:
   with patch.object(runtime,'DATA',self.root):self.assertEqual(runtime.catalog_module().VALUE,17)
   self.assertEqual(sys.path,old)
  finally:
   sys.modules.pop('profile_defaults',None)
   if previous is not None:sys.modules['profile_defaults']=previous

if __name__=='__main__':unittest.main()
