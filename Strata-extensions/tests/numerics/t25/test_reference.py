"""CPU tests are independent of any candidate GPU output."""
import unittest,struct,sys
from pathlib import Path
try:import numpy as np
except ModuleNotFoundError:
 sys.path.append('C:/Develop/AI/StrataMod/.vision-venv-10.1/Lib/site-packages');import numpy as np
import reference as q
class OracleTests(unittest.TestCase):
 def test_bfloat_tie(self):self.assertEqual(q.bf16(np.array([1+2**-8,1+3*2**-8,-0.],np.float32)).view(np.uint32).tolist(),[0x3f800000,0x3f820000,0x80000000])
 def test_q8_scalar(self):
  raw=struct.pack('<e',.5)+bytes([0,1,255,127,128]+[0]*27);self.assertEqual(q.decode_q8(raw)[:5].tolist(),[0,.5,-.5,63.5,-64])
 def test_order(self):
  w=np.array([[2**24,1,-2**24]],np.float32);self.assertEqual(q.ordered(w,np.ones((1,3),np.float32)).item(),0)
 def test_fp8_ties(self):self.assertEqual(q.fp8_codes(np.array([1.,1.0625,1.1875,-0.],np.float32)).tolist(),[56,56,58,128])
 def test_signed_zero_real_path(self):
  h=np.ones((1,20480),np.float32);kv=np.ones((1,25600),np.float32);w=np.zeros((4,5120),np.float32)
  p=q.gate(h,kv,w,np.array([True]));w[:,0]=-np.nextafter(np.float32(0),np.float32(1));n=q.gate(h,kv,w,np.array([True]))
  self.assertEqual(p['z'].view(np.uint32).ravel().tolist(),[0]*4);self.assertEqual(n['z'].view(np.uint32).ravel().tolist(),[0x80000000]*4)
  self.assertTrue((p['root']>0).all() and (n['root']<0).all());self.assertTrue((p['gates']>.5).all() and (n['gates']<.5).all())
 def test_mask_and_key_rms(self):
  h=np.ones((1,20480),np.float32);kv=np.ones((1,25600),np.float32);w=np.ones((4,5120),np.float32)
  a=q.gate(h,kv,w,np.array([False]));self.assertTrue(np.array_equal(a['output'],h));b=q.gate(h,kv,w,np.array([True]));kv[:,:20480]*=8;c=q.gate(h,kv,w,np.array([True]));self.assertTrue(np.array_equal(b['z'],c['z']))
 def test_decimal_local(self):self.assertEqual(q.decimal_literals()['checked'],6)
 def test_independent_full_N(self):
  for name in ['positivezero','negativezero','key1','key8','masked','tiny','zero-norm','asymmetric','product-order']:
   h,kv,w,m=q.control_inputs(name);n,_=q.decimal_full(h,kv,w,m);trace=q.gate(h,kv,w,m);q.compare_n_control(trace,n)
 def test_independent_N_mutants(self):
  for name,field,change in [('key8','inverse_key',lambda v:v.fill(1)),('asymmetric','inverse_h',lambda v:v.fill(1)),('zero-norm','inverse_h',lambda v:v.fill(1000)),('product-order','weighted_dot',lambda v:v.fill(5120*2**-110))]:
   h,kv,w,m=q.control_inputs(name);n,_=q.decimal_full(h,kv,w,m);trace=q.gate(h,kv,w,m)
   if name=='asymmetric':trace[field].fill(np.float32(1/np.sqrt(np.mean(h.astype(np.float64)**2))))
   else:change(trace[field])
   with self.assertRaises(ValueError):q.compare_n_control(trace,n)
 def test_actual_schedule(self):
  self.assertEqual(q.actual_role(0),(0,None,None));self.assertEqual(q.actual_role(2),(2,2,2));self.assertEqual(q.actual_role(20),(1,20,20));self.assertEqual(q.actual_role(24),(1,20,24))
  for x in [-1,40,True]:
   with self.assertRaises(ValueError):q.actual_role(x)
if __name__=='__main__':unittest.main()
