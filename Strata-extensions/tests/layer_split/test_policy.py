import unittest
import reference as r
class LayerSplitPolicy(unittest.TestCase):
 def test_two_contiguous_ranges(self):
  self.assertEqual(r.ranges(24),[(0,24),(24,40)])
  for cut in (0,40,-1,True,2.0):
   with self.assertRaises(ValueError):r.ranges(cut)
 def test_selection_edges(self):
  self.assertEqual(r.cross_edges(3)['selected'],[2])
  self.assertEqual(r.cross_edges(24)['selected'],[])
  self.assertEqual(r.cross_edges(25)['selected'],[24])
  self.assertEqual(r.cross_edges(24)['candidates'],[20])
 def test_valid_delta(self):
  self.assertEqual(r.delta(2,0,1),dict(first=0,rows=1,kv_bytes=2048,key_bytes=512))
  self.assertEqual(r.delta(2,1,1),dict(first=1,rows=0,kv_bytes=0,key_bytes=0))
  for args in ((2,2,1),(0,0,1),(2,0,True)):
   with self.assertRaises(ValueError):r.delta(*args)
 def test_representative_payload(self):
  self.assertEqual(r.cut24_bytes(3),dict(residual_pre=245808,new_kv=6144,new_keys=1536,candidates=24,total=253512))
 def test_visible_indices(self):
  self.assertEqual(r.selected_bytes(0),0)
  self.assertEqual(r.selected_bytes(600),2048)
  self.assertEqual(r.selected_bytes(3),12)
 def test_tap_physical_and_semantic(self):
  self.assertEqual(r.tap_bytes(2,3),368640)
  with self.assertRaises(ValueError):r.tap_bytes(True,1)
if __name__=='__main__':unittest.main()
