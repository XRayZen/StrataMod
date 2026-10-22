import unittest
from reference import effective, acceptance, residual, confidence_parts, contract_fixture, tap_mean, verified_trace, rng_counters
import numpy as np
class ReferenceTests(unittest.TestCase):
 def test_effective_q_is_not_API_logprob_distribution(self):
  q=effective([0.,1.,2.],temperature=1,top_k=1);self.assertEqual(q,[0.,0.,1.]);self.assertNotEqual(q,effective([0.,1.,2.],temperature=1,top_k=0))
 def test_pq_and_residual(self):
  p=[.5,.25,.125,.125];q=[.25,.25,.25,.25];self.assertEqual(acceptance(p,q,2),.5);self.assertEqual(residual(p,q),[1.,0.,0.,0.])
 def test_greedy_tie_and_temperature(self):
  self.assertEqual(effective([1.,1.,0.],temperature=0),[1.,0.,0.]);self.assertNotEqual(effective([0.,1.],temperature=.5),effective([0.,1.],temperature=2.))
 def test_truncation_and_penalties(self):
  self.assertEqual(effective([0.,1.,2.],min_p=.5),[0.,0.,1.]);self.assertEqual(effective([0.,1.,2.],top_p=.5),[0.,0.,1.]);self.assertNotEqual(effective([1.,2.],history=(1,1),frequency=1),effective([1.,2.]))
 def test_invalid_probability_and_zero_residual(self):
  for p,q,d in [([.5,.5],[1.,0.],1),([1.,0.],[1.,0.],True),([.5,.5],[.5,.4],0)]:
   with self.assertRaises(ValueError):acceptance(p,q,d)
  with self.assertRaises(ValueError):residual([.5,.5],[.5,.5])
 def test_confidence_concat_not_hidden_times_markov(self):
  x=contract_fixture();self.assertEqual(x['confidence']['ordered_Q'],9.);self.assertEqual(float(x['confidence']['N']),9.);self.assertGreater(x['confidence']['rate'],.99)
  with self.assertRaises(ValueError):confidence_parts([1.]*5120,[1.]*255,[1.]*5376)
 def test_HC_non_symmetric_before_layer_tap(self):
  hc=np.stack([np.full(5120,x,np.float32) for x in (0.,2.,4.,10.)]);self.assertEqual(set(tap_mean(hc).tolist()),{0x4080});self.assertNotEqual(tap_mean(hc)[0],tap_mean(hc+1)[0])
 def test_future_confidence_and_rejected_ids_not_emitted(self):
  self.assertEqual(verified_trace([5,6,7],[True,False,True],future_confidence=[-100,100]),[5,37]);self.assertEqual(verified_trace([5,6,7],[True,False,True],future_confidence=[100,-100]),[5,37])
 def test_bonus_EOS_cancel_and_namespace(self):
  self.assertEqual(verified_trace([5,6],[True,True]),[5,6,1024]);self.assertEqual(verified_trace([5,1,7],[True]*3),[5,1]);self.assertEqual(verified_trace([5],[True],cancelled=True),[]);self.assertEqual(rng_counters(6,2,True),dict(target=0,proposal=6,accept=2,residual=1,bonus=0))
 def test_options_bool_nan_rejected_and_width_not_five_limit(self):
  for options in ({'top_p':True},{'min_p':float('nan')},{'repetition':0},{'top_k':True}):
   with self.assertRaises(ValueError):effective([0.,1.],**options)
  for width in (1,5,6):self.assertEqual(len(verified_trace(list(range(2,width+2)),[True]*width)),width+1)
if __name__=='__main__':unittest.main()
