import importlib.util,sys,unittest
from pathlib import Path
from unittest.mock import patch
W=Path(__file__).resolve().parents[3]
def load(name,p):
 spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
L=load('integrated_launch',W/'control/deepseek_launch.py')
H=load('integrated_hook',W/'models/deepseek41/server_hooks.py')
class NormalOptions(unittest.TestCase):
 def config(self):return dict(family='deepseek41',exe='CPU-no-launch.exe',artifact_root='CPU-assets',primary_pci='0000:07:00.0',context=32768,bundle_id='b'*64,runtime_epoch=1,native_paths=[],args=[])
 def test_typed_graph_actor_and_existing_perf_flags_share_native_argv(self):
  cfg=L.overlay(self.config(),dict(projection_graph='on',dspark_draft=str(W/'CPU-draft'),dspark_prefix=str(W/'CPU-prefix'),dspark_width=5,dspark_draft_credit=2097152,dspark_target_credit=2097152,tile_bytes=2097152,tile_rows=256,active_batch=8,secondary_device_cache_payload_bytes=2097152))
  self.assertEqual(L.native_command(cfg)[2:],H.native_args(cfg))
  args=H.native_args(cfg)
  for key in ('projection-graph','dspark-draft','dspark-prefix','dspark-width','dspark-draft-credit','dspark-target-credit'):
   self.assertEqual(args.count('--'+key),1)
  self.assertEqual(cfg['context'],32768)
 def test_defaults_and_legacy_args_are_unchanged(self):
  cfg=self.config();cfg['args']=['--projection-graph','off']
  self.assertEqual(L.overlay(cfg,{}),cfg)
  self.assertEqual(L.native_command(cfg)[2:],H.native_args(cfg))
 def test_invalid_options_do_not_modify_original_config(self):
  cfg=self.config()
  for values in (dict(projection_graph='auto'),dict(dspark_width=True),dict(active_batch=0),dict(dspark_draft='relative',dspark_prefix='relative'),dict(dspark_prefix=str(W/'CPU-prefix'))):
   with self.subTest(values=values),self.assertRaises(ValueError):L.overlay(cfg,values)
  self.assertNotIn('projection_graph',cfg)
 def test_observed_feature_info_keeps_primary_roles_and_unknown_separate(self):
  cfg=dict(projection_graph='on',dspark_draft=str(W/'CPU-draft'),dspark_width=5)
  info=dict(projection_graph=dict(requested=True,applied_this_request=None),projection_graph_roles=dict(primary=None,secondary=dict(owner_completion_known=None)),dspark_enabled=True,dspark_width=5)
  self.assertEqual(L.validate_feature_info(cfg,info),info)
  self.assertEqual(L.validate_feature_info(cfg,{}),{})
  for bad in (dict(info,dspark_width=6),dict(info,dspark_enabled=False),dict(info,projection_graph=dict(requested=False))):
   with self.assertRaises(RuntimeError):L.validate_feature_info(cfg,bad)
 def test_actual_cli_parser_to_candidate_overlay_without_runtime(self):
  sys.path.insert(0,r'C:\Develop\AI\Strata-data')
  cli=load('integrated_cli',W/'control/strata_cli.py')
  seen=[]
  rt=type('CPUonly',(),{})()
  with patch.object(cli,'start_selected',side_effect=lambda *a:seen.append(L.overlay(self.config(),rt.launch_options))):
   self.assertEqual(cli.main(['start','--model','deepseek-v4.1-flash-1017-ud-q4_k_xl','--context','32768','--projection-graph','on','--dspark-width','5'],rt=rt),0)
  self.assertEqual(seen[0]['projection_graph'],'on')
  self.assertEqual(seen[0]['dspark_width'],5)
if __name__=='__main__':unittest.main(verbosity=2)
