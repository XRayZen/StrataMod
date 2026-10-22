import json,sys,unittest,uuid
from pathlib import Path
from unittest.mock import patch
OUT=Path(r'C:\Develop\AI\Strata-data\build\deepseek-v41\build-deepseek-t46\actual-mode-runner\production-integration-cli-r1')
CTX=OUT/'normal-candidate-context'
sys.path.insert(0,str(CTX/'Strata-data'))
import strata_cli as CLI
class CandidateContext(unittest.TestCase):
 def test_private_manager_profile_to_exact_new_image_and_owned_switch_stop(self):
  manifest=json.loads((CTX/'candidate-context.json').read_text())
  self.assertEqual(CLI.ROOT,CTX/'Strata-data')
  self.assertEqual(CLI.runtime.ROOT,CLI.ROOT)
  self.assertEqual(CLI.official_runtime.REPO,CTX/'Strata')
  helper=CLI.runtime.startup_progress.family_helper()
  model='deepseek-v4.1-flash-1017-ud-q4_k_xl'
  prepared=CLI.official_runtime.require_registration(model,32768)
  self.assertTrue(prepared.is_relative_to(CTX/'Strata'))
  original=CLI.ROOT/'profiles'/f'{model}-32768.json'
  self.assertEqual(prepared.read_bytes(),original.read_bytes())
  with patch.object(helper,'current_identity',return_value=dict(pid=101,created=1.,exe='CPU-owner')):
   resolved,binding=helper.resolve(original,CLI.ROOT,str(uuid.uuid4()),123456,dict(projection_graph='on'),prepared)
  cfg=helper.verify_binding(resolved,binding)
  self.assertEqual(cfg['runtime_package']['id'],manifest['package_id'])
  self.assertEqual(Path(cfg['exe']).parent.parent.name,manifest['package_id'])
  self.assertEqual(cfg['projection_graph'],'on')
  self.assertEqual(helper.native_command(cfg)[0],cfg['exe'])
  self.assertEqual(Path(binding['registered_config']),prepared)
  self.assertEqual(binding['runtime_package'],cfg['runtime_package'])
  from contextlib import nullcontext
  class RT:
   current=dict(phase='stopped');stops=0;starts=0
   def validate(self,*a):pass # Model/body asset verification is assembler proof, no model rehash here.
   def state(self):return dict(self.current)
   def active(self,s):return s.get('phase')=='ready'
   def start(self,m,c):
    self.starts+=1;self.current=dict(phase='ready',model=m,context=c,pid=202,created=2.,config=str(resolved));return self.state()
   def ready(self,state):pass # Synthetic endpoint only; never real HTTP/status.
   def stop(self,state):
    if state!=self.current:raise ValueError('foreign owner')
    self.stops+=1;self.current=dict(phase='stopped')
  rt=RT()
  with patch.object(CLI,'operation_lock',side_effect=lambda:nullcontext()):
   CLI.start_selected(rt,model,32768)
   self.assertEqual(rt.starts,1)
   CLI.start_selected(rt,model,32768)
   self.assertEqual(rt.starts,1)
   with self.assertRaises(RuntimeError):CLI.stop_current(rt,confirmed_identity=(999,9.,'foreign'))
   self.assertEqual(rt.stops,0)
   CLI.stop_current(rt)
   self.assertEqual(rt.stops,1)
   self.assertFalse(rt.active(rt.state()))
 def test_all_six_profiles_use_new_candidate_and_leave_public_unselected(self):
  context=json.loads((CTX/'candidate-context.json').read_text())
  for row in context['profiles']:
   cfg=json.loads(Path(row['path']).read_text())
   self.assertEqual(cfg['runtime_package']['id'],context['package_id'])
   self.assertEqual(Path(cfg['exe']).parent.parent.name,context['package_id'])
  public=Path(r'C:\Develop\AI\Strata-data\profiles\deepseek-v4.1-flash-1017-ud-q4_k_xl-32768.json')
  self.assertEqual(json.loads(public.read_text())['runtime_package']['id'],'de662662c8da4ab6ba8d3c3f1ca5f61309cf95d52b88e75827858862b418fddf')
if __name__=='__main__':unittest.main(verbosity=2)
