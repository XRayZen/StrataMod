import unittest,copy
from pathlib import Path
import reference as r
class Policy(unittest.TestCase):
 def test_full_vocabulary_assignment(self):
  self.assertEqual(r.assignment([0,383]),frozenset((0,383)))
  for bad in ([384],[-1],[True],[1,1],[1.0]):
   with self.assertRaises(ValueError):r.assignment(bad)
 def test_selected_original_order_and_sorted_adoption(self):
  p=r.jobs([[3,0,1,5,2,4],[1,6,3,8,7,2]],set(range(0,384,2)))
  self.assertEqual([x['expert']for x in p],list(range(9)))
  self.assertEqual(p[1]['pairs'],[[0,2],[1,0]])
  self.assertEqual([x['secondary']for x in p],[True,False,True,False,True,False,True,False,True])
 def test_router_reject(self):
  for bad in ([[0]*6],[[0,1,2,3,4]],[[0,1,2,3,4,384]],[[0,1,2,3,4,True]]):
   with self.assertRaises(ValueError):r.jobs(bad,set())
 def test_reverse_result_order_canonical_single_adoption(self):
  wanted=[('r',1,0,0,2,1),('r',1,0,0,3,2)]
  self.assertEqual(r.canonical_results(wanted,list(reversed(wanted))),wanted)
  for bad in ([wanted[0]],wanted+[wanted[0]],[("old",1,0,0,2,1),wanted[1]]):
   with self.assertRaises(ValueError):r.canonical_results(wanted,bad)
 def test_live_return_not_reusable(self):
  self.assertFalse(r.reusable(input_complete=True,compute_complete=True,return_complete=True,consumed=False,last_use_complete=False))
  self.assertFalse(r.reusable(input_complete=True,compute_complete=True,return_complete=True,consumed=True,last_use_complete=False))
  self.assertTrue(r.reusable(input_complete=True,compute_complete=True,return_complete=True,consumed=True,last_use_complete=True))
 def test_capacity(self):
  c=r.capacity(8,2)
  self.assertEqual(c['secondary_workspace'],1901056)
  self.assertEqual(c['primary_job_storage'],655872)
  self.assertEqual(c['bounce_host'],327680)
  for b,n in ((0,2),(8,0),(True,1),(8,1.0)):
   with self.assertRaises(ValueError):r.capacity(b,n)
 def test_one_slot_is_finite_not_context_cap(self):
  self.assertEqual(r.capacity(1,1)['slots'],1)
  self.assertEqual(r.capacity(9,3)['slots'],3)
 def test_payload(self):
  self.assertEqual(r.payload_bytes(355,1),dict(input=7270400,route=1420,down=7270400,total=14542220))
 def test_fixed_real_route_source(self):
  root=Path(__file__).resolve().parents[3]
  p=root/'build-deepseek-t20/full-core-attempt-1/captured-Q-manifest.json'
  result=r.fixed_reference(p)
  self.assertEqual((result['primary_calls'],result['secondary_calls'],result['frames']),(365,355,120))
  self.assertTrue(result['all40_both_roles'])
if __name__=='__main__':unittest.main()
