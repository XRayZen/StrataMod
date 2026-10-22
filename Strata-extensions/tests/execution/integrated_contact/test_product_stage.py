import copy,importlib.util,json,unittest
from pathlib import Path
P=Path(__file__).resolve().parents[2]/'providers/runtime_stage.py'
spec=importlib.util.spec_from_file_location('integrated_real_runtime_stage',P)
S=importlib.util.module_from_spec(spec);spec.loader.exec_module(S)
class PredecessorProfiles(unittest.TestCase):
 def test_old_public_root_can_follow_new_native_tuple_without_retargeting_old(self):
  original=S.load(S.ROOT/'build-deepseek-t46/actual-mode-runner/matching-contact-perf-preparation-r1/inputs-perf-r1.json')
  value=copy.deepcopy(original)
  value['public_INFO_predecessor_input']=S.record(S.ROOT/'build-deepseek-t46/actual-mode-runner/matching-contact-perf-preparation-r1/inputs-perf-r1.json')
  value['candidate_package_id']='a'*64
  value['native_compiled_source_id']='b'*64
  value['native_manifest']=dict(source='CPU metadata only; not assembled',bytes=1,sha256='c'*64)
  for row in value['selected_files']:
   if row['relative_destination']in ('native/Strata-deepseek.exe','Strata-extensions/models/deepseek41/server_hooks.py'):
    row['source']='CPU new selected bytes';row['sha256']='d'*64
  root=S.public_INFO_profile_preflight(value)
  self.assertEqual(Path(root).name,original['candidate_package_id'])
  # Original proof and public profiles are not mutated by preflight.
  self.assertEqual(S.load(value['public_INFO_predecessor_input']['path']),original)
  for key in ('parent_id','execution_abi'):
   bad=copy.deepcopy(value);bad[key]='foreign'
   with self.assertRaises(ValueError):S.public_INFO_profile_preflight(bad)
  bad=copy.deepcopy(value)
  next(row for row in bad['selected_files']if row['relative_destination']=='native/server/serve/server.py')['sha256']='f'*64
  with self.assertRaises(ValueError):S.public_INFO_profile_preflight(bad)
if __name__=='__main__':unittest.main(verbosity=2)
