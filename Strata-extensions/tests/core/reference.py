"""T20 independent CPU geometry/numerics oracle; no candidate GPU imports."""
import decimal, math, struct, unittest

def uint(x,positive=False):
 if type(x) is not int or x<0 or x>2**64-1 or (positive and not x):raise ValueError('unsigned geometry')
 return x

def source_tile(base,rowbytes,k,rows,matrices,matrix,first,count):
 for x in (base,rowbytes,k,rows,matrices,matrix,first,count):uint(x)
 if not all((rowbytes,k,rows,matrices,count)) or matrix>=matrices or first>=rows or count>rows-first:raise ValueError('original row range')
 offset=base+(matrix*rows+first)*rowbytes;size=count*rowbytes
 uint(offset);uint(offset+size)
 return offset,size,k,count

def row_tiles(rows,rowbytes,budget,maxrows):
 for x in (rows,rowbytes,budget,maxrows):uint(x,True)
 n=min(budget//rowbytes,maxrows)
 if not n:raise ValueError('one full-K row does not fit')
 return [(i,min(n,rows-i)) for i in range(0,rows,n)]

def bounded_source_windows(offset,size,credit):
 uint(offset);uint(size,True);uint(credit,True)
 if credit<4096:raise ValueError('one direct physical page does not fit')
 capacity=min(65536,credit//4096*4096);out=[]
 while size:
  count=min(size,capacity-offset%4096)
  requested=(offset%4096+count+4095)//4096*4096
  out.append((offset,count,requested));offset+=count;size-=count
 return out

def batch_waves(batch):
 uint(batch,True);out=[]
 while batch:
  n=8
  while n>batch:n//=2
  out.append(n);batch-=n
 return out

def scatter_rows(left,right):
 if len(left)!=len(right) or not left or len({len(x) for x in left})!=1 or len({len(x) for x in right})!=1:raise ValueError('row-major batch scatter')
 return [a+b for a,b in zip(left,right)]

def live_peak(buffers):
 names=set();events=[]
 for name,start,end,size in buffers:
  uint(start);uint(end);uint(size)
  if name in names or end<=start:raise ValueError('unique allocation lifetime')
  names.add(name);events.extend([(start,1,size),(end,0,-size)])
 live=peak=0
 for _,_,delta in sorted(events):live+=delta;peak=max(peak,live)
 return peak

def bf16_bits(x):
 u=struct.unpack('<I',struct.pack('<f',x))[0]
 return ((u+0x7fff+((u>>16)&1))>>16)&0xffff

def decimal_output_norm(values,weight,epsilon=decimal.Decimal('1e-20')):
 if len(values)!=len(weight) or not values:raise ValueError('RMS geometry')
 with decimal.localcontext() as c:
  c.prec=100;mean=sum(x*x for x in values)/decimal.Decimal(len(values));inv=1/(mean+epsilon).sqrt()
  return [+(x*inv*w) for x,w in zip(values,weight)]

def decimal_engram_gate(h,weight,key):
 if not h or len(h)!=len(weight) or len(h)!=len(key):raise ValueError('HC geometry')
 out=[]
 with decimal.localcontext() as c:
  c.prec=100
  for x,w,k in zip(h,weight,key):
   if not x or len(x)!=len(w) or len(x)!=len(k):raise ValueError('per-HC RMS')
   d=decimal.Decimal(len(x));inv=1/(sum(v*v for v in x)/d+decimal.Decimal('1e-20')).sqrt()
   key_inv=1/(sum(v*v for v in k)/d+decimal.Decimal('1e-20')).sqrt()
   dot=sum((v*a)*b for v,a,b in zip(x,w,k));z=dot*(inv*key_inv)/d.sqrt()
   signed=max(abs(z),decimal.Decimal('1e-6')).sqrt().copy_sign(z)
   out.append(+(1/(1+(-signed).exp())))
 return out



def core_storage_layout(capacity):
 """Declared simultaneous Core allocation contract, independent of G counters.

 All retained 40-layer SWA state, compressed/key states and reusable activation
 workspaces are live together. Constants are separately original-source-sized.
 """
 uint(capacity,True);out=[]
 def group(name,sizes):
  for i,n in enumerate(sizes):out.append((name+'-'+str(i),0,1,uint(n)))
 group('SWA40',[128*512*4]*40)
 group('compress-pending',[1024*4,1024*4]*4)
 counts=[max(1,capacity//2)]*3+[capacity]
 group('compressed-KV',[n*512*4 for n in counts]);group('index-key',[n*128*4 for n in counts]);group('candidate',[capacity*4])
 group('residual-and-embedding',[20480*4]*2+[5120*4]*2+[16,1,1])
 group('mHC',[n*4 for n in [1,24,24,4,4,16]*2])
 group('block',[n*4 for n in [5120,1,5120,5120,20480]])
 group('head',[n*4 for n in [1,5120,5120,129280]])
 group('FFN',[n*4 for n in [5120,384,384,384,6,6,5120,5120,1,2,2304,2304,2304,2304,5120,5120]])
 group('attention-payload',[n*4 for n in [5120,1280,1280,1280,1280,32768,32768,32768,512,512,512,512,512,32,32768,32768,32768,4096,8192,8192,8192,5120]])
 group('attention-control',[8,64*8,640*8,4])
 group('compression-work',[512*4]*7+[8,32*4])
 group('index-work',[n*4 for n in [128,128,128,512,512,128,128,1280,4096,4096,16384,16384,4096,4096,32,32,32,32,capacity,512,(capacity+7)//8,512]])
 group('index-control',[8,32*8,8,capacity,4])
 group('engram',[n*4 for n in [6144,20480,6144,25600,25600,4]])
 uint(sum(v[3] for v in out));return out

def full_constant_names():
 names=[]
 for layer in range(40):
  p='blk.'+str(layer)+'.'
  names.extend(p+n for n in ['hc_attn_scale.weight','hc_attn_base.weight','attn_norm.weight','hc_ffn_scale.weight','hc_ffn_base.weight','ffn_norm.weight','attn_q_a_norm.weight','attn_kv_a_norm.weight','attn_sinks.weight','exp_probs_b.bias','exp_probs_b_vl.bias'])
 for layer in [2,8,14,20]:names.extend(['blk.'+str(layer)+'.attn_compressor_norm.weight','blk.'+str(layer)+'.indexer.k_norm.weight'])
 names.extend(['blk.1.engram_gate.weight','blk.14.engram_gate.weight','output_norm.weight'])
 return names

class FullModelOracle:
 """Semantic embedding/head adapter around the independent operator graph.

 The supplied ActualOracle is authored independently from candidate Core and
 imports only fixed prior CPU references. This adapter does not infer any
 expectation from a candidate native output or its allocation trace.
 """
 def __init__(self,actual):
  self.actual=actual;actual.reset()
 def step(self,raw_token,position):
  import numpy as np
  uint(raw_token);uint(position)
  if raw_token>=129280:raise ValueError('raw token outside fixed vocabulary')
  actual=self.actual;_,tensor=actual.tensors['token_embd.weight']
  if tensor['dims_ggml']!=[5120,129280] or tensor['type_id']!=8:raise ValueError('original embedding geometry/type')
  raw=actual.raw('token_embd.weight',raw_token*tensor['row_bytes'],tensor['row_bytes'])
  emb=actual.native.decode(8,raw).reshape(1,5120)
  # BF16 rounding is an independent explicit integer RNE, not native casting.
  bits=emb.view(np.uint32);rounded=(bits+np.uint32(0x7fff)+((bits>>16)&1))&np.uint32(0xffff0000);emb=rounded.view(np.float32)
  h=np.repeat(emb[:,None,:],4,axis=1);pre=np.array([[1,0,0,0]],np.float32)
  residual,last_pre,frames=actual.step(0,40,raw_token,position,h,pre)
  collapsed=actual.mhc.hc_pre(residual,last_pre)
  normalized=actual.mhc.rms_norm(collapsed,actual.const('output_norm.weight'))
  logits=actual.linear('output.weight',normalized,activation=False)
  if logits.shape!=(1,129280) or not np.isfinite(logits).all():raise ValueError('full native-source canonical logits')
  return dict(token_id=raw_token,position=position,embedding=emb,residual=residual,pre=last_pre,collapsed=collapsed,normalized=normalized,logits=logits,frames=frames)

class ContractTests(unittest.TestCase):
 def test_expert_row_source_coordinates(self):
  x=source_tile(100000,2720,5120,2304,384,38,2300,4)
  self.assertEqual(x,(100000+(38*2304+2300)*2720,10880,5120,4))
  with self.assertRaises(ValueError):source_tile(100000,2720,5120,2304,384,38,2303,2)
 def test_tile_fullk_and_ragged(self):
  tiles=row_tiles(5120,8704,2097152,256)
  self.assertEqual(tiles[-1],(5040,80))
  self.assertEqual(sum(n for _,n in tiles),5120)
  self.assertEqual([x for x in batch_waves(19)],[8,8,2,1])
 def test_scatter_batch_major(self):
  self.assertEqual(scatter_rows([[10,11],[20,21]],[[12],[22]]),[[10,11,12],[20,21,22]])
  with self.assertRaises(ValueError):scatter_rows([[1]],[[2],[3]])
 def test_strict_source_range(self):
  for args in [(0,2720,5120,2304,384,384,0,1),(0,2720,5120,2304,384,0,0,0),((1<<64)-2,2720,5120,2304,384,0,1,1)]:
   with self.assertRaises(ValueError):source_tile(*args)
  with self.assertRaises(ValueError):source_tile(0,2720,True,2304,384,0,0,1)
 def test_borrow_lifetime(self):
  self.assertEqual(live_peak([('state',0,10,100),('weight',1,5,40),('output',2,8,20),('scratch',3,4,30)]),190)
  with self.assertRaises(ValueError):live_peak([('x',0,0,1)])
 def test_independent_output_norm(self):
  # Real H5120, constant magnitude gives exact math oracle; general Q differs.
  got=decimal_output_norm([decimal.Decimal(2)]*5120,[decimal.Decimal(1)]*5120)
  self.assertEqual(bf16_bits(float(got[0])),0x3f80)
  tiny=decimal_output_norm([decimal.Decimal('1e-12')]*5120,[decimal.Decimal(1)]*5120)
  wrong=decimal_output_norm([decimal.Decimal('1e-12')]*5120,[decimal.Decimal(1)]*5120,decimal.Decimal('1e-6'))
  self.assertNotEqual(bf16_bits(float(tiny[0])),bf16_bits(float(wrong[0])))
 def test_real_4k_credit_trace(self):
  # Original expert38 is above 4GiB. Each operation stays within a single
  # physical 4096B window even though the logical span starts inside a page.
  self.assertEqual(bounded_source_windows(5051106880,5000,4096),[(5051106880,2496,4096),(5051109376,2504,4096)])
  with self.assertRaises(ValueError):bounded_source_windows(0,1,4095)
 def test_engram_hc_norm_separate(self):
  x=decimal_engram_gate([[decimal.Decimal(2)]*4,[decimal.Decimal(8)]*4],[[decimal.Decimal(1)]*4]*2,[[decimal.Decimal(1)]*4]*2)
  self.assertTrue(abs(x[0]-x[1])<decimal.Decimal('1e-18'))
  self.assertNotEqual(x[0],0)
  y=decimal_engram_gate([[decimal.Decimal(2)]*4]*2,[[decimal.Decimal(1)]*4]*2,[[decimal.Decimal(1)]*4,[decimal.Decimal(8)]*4])
  self.assertTrue(abs(y[0]-y[1])<decimal.Decimal("1e-18"))

if __name__=='__main__':unittest.main()
