"""T12 independent N/Q oracle; no candidate GPU output reads."""
import unittest
import numpy as np

def bf16(x):
 x=np.asarray(x,np.float32)
 if not np.isfinite(x).all():raise ValueError('nonfinite BF16')
 b=x.view(np.uint32);return (((b+np.uint32(0x7fff)+((b>>16)&1))>>16)<<16).view(np.float32)

def residual(x):
 x=np.asarray(x,np.float32)
 if x.ndim!=3 or x.shape[1:]!=(4,5120) or not len(x) or not np.isfinite(x).all():raise ValueError('HC4/H5120 residual geometry/nonfinite')
 return x

def ordered_sum(x,axis):
 x=np.moveaxis(np.asarray(x,np.float32),axis,-1);out=np.zeros(x.shape[:-1],np.float32)
 for i in range(x.shape[-1]):out=np.add(out,x[...,i],dtype=np.float32)
 return out

def flat_rsqrt(x):
 x=residual(x).reshape(len(x),20480);squares=np.multiply(x,x,dtype=np.float32)
 mean=np.divide(ordered_sum(squares,1),np.float32(20480),dtype=np.float32)
 return np.divide(np.float32(1),np.sqrt(np.add(mean,np.float32(1e-20),dtype=np.float32),dtype=np.float32),dtype=np.float32).reshape(-1,1)

def split_sinkhorn(mixes,scale,base):
 mixes=np.asarray(mixes,np.float32);scale=np.asarray(scale,np.float32);base=np.asarray(base,np.float32)
 if mixes.ndim!=2 or mixes.shape[1]!=24 or scale.shape!=(3,) or base.shape!=(24,) or not all(np.isfinite(x).all() for x in (mixes,scale,base)):raise ValueError('mix geometry/nonfinite')
 eps=np.float32(1e-6)
 def affine(lo,hi,i):return np.add(np.multiply(mixes[:,lo:hi],scale[i],dtype=np.float32),base[lo:hi],dtype=np.float32)
 def sigmoid(x):return (1/(1+np.exp(-x.astype(np.float64)))).astype(np.float32)
 pre=np.add(sigmoid(affine(0,4,0)),eps,dtype=np.float32);post=np.multiply(np.float32(2),sigmoid(affine(4,8,1)),dtype=np.float32)
 logits=affine(8,24,2).reshape(-1,4,4);centered=np.subtract(logits,np.max(logits,axis=2,keepdims=True),dtype=np.float32)
 exponent=np.exp(centered.astype(np.float64)).astype(np.float32);row=np.add(np.divide(exponent,ordered_sum(exponent,2)[:,:,None],dtype=np.float32),eps,dtype=np.float32)
 rounds=[]
 for iteration in range(20):
  if iteration:row=np.divide(comb,np.add(ordered_sum(comb,2),eps,dtype=np.float32)[:,:,None],dtype=np.float32)
  comb=np.divide(row,np.add(ordered_sum(row,1),eps,dtype=np.float32)[:,None,:],dtype=np.float32);rounds.append((row.copy(),comb.copy()))
 return dict(pre=pre,post=post,logits=logits,centered=centered,exp=exponent,comb=comb,rounds=rounds)

def hc_pre(x,pre):
 x=residual(x);pre=np.asarray(pre,np.float32)
 if pre.shape!=x.shape[:2] or not np.isfinite(pre).all():raise ValueError('pre geometry')
 return bf16(ordered_sum(np.multiply(pre[:,:,None],x,dtype=np.float32),1))

def hc_post(x,r,post,comb):
 r=residual(r);x=np.asarray(x,np.float32);post=np.asarray(post,np.float32);comb=np.asarray(comb,np.float32)
 if x.shape!=(len(r),5120) or post.shape!=(len(r),4) or comb.shape!=(len(r),4,4) or not all(np.isfinite(v).all() for v in (x,post,comb)):raise ValueError('post geometry')
 result=np.zeros_like(r)
 for j in range(4):
  mixed=np.zeros((len(r),5120),np.float32)
  for i in range(4):mixed=np.add(mixed,np.multiply(comb[:,i,j,None],r[:,i,:],dtype=np.float32),dtype=np.float32)
  result[:,j]=np.add(np.multiply(post[:,j,None],x,dtype=np.float32),mixed,dtype=np.float32)
 return bf16(result)

def rms_norm(x,weight):
 x=np.asarray(x,np.float32);weight=np.asarray(weight,np.float32)
 if x.ndim!=2 or x.shape[1]!=5120 or weight.shape!=(5120,) or not np.isfinite(x).all() or not np.isfinite(weight).all():raise ValueError('norm geometry')
 square=np.multiply(x,x,dtype=np.float32);mean=np.divide(ordered_sum(square,1),np.float32(5120),dtype=np.float32)
 inv=np.divide(np.float32(1),np.sqrt(np.add(mean,np.float32(1e-20),dtype=np.float32),dtype=np.float32),dtype=np.float32)
 return bf16(np.multiply(np.multiply(x,inv[:,None],dtype=np.float32),weight,dtype=np.float32))

def decimal_literals():
 from decimal import Decimal,localcontext
 import struct
 def f(v):return Decimal.from_float(struct.unpack('<f',struct.pack('<f',float(v)))[0])
 def bits(v):return struct.pack('<f',float(v)).hex()
 def add(a,b):return f(a+b)
 def mul(a,b):return f(a*b)
 def div(a,b):return f(a/b)
 def total(v):
  out=f(0)
  for x in v:out=add(out,x)
  return out
 result=[]
 with localcontext() as ctx:
  ctx.prec=100;eps=f(Decimal('0.000001'))
  for name,source in [('uniform',['0']*24),('asymmetric',['-12','-1','0','12','12','0','-1','-12']+[str(x) for x in [12,-8,1,0,-2,4,-9,3,5,1,-4,2,-1,7,0,-6]])]:
   values=list(map(lambda x:f(Decimal(x)),source));pre=[add(f(1/(1+(-v).exp())),eps) for v in values[:4]];post=[mul(f(2),f(1/(1+(-v).exp()))) for v in values[4:8]]
   logits=[values[8+i*4:12+i*4] for i in range(4)];row=[]
   for r in logits:
    exp=[f((v-max(r)).exp()) for v in r];den=total(exp);row.append([add(div(v,den),eps) for v in exp])
   rounds=[]
   for iteration in range(20):
    if iteration:row=[[div(v,add(total(r),eps)) for v in r] for r in comb]
    sums=[add(total([row[i][j] for i in range(4)]),eps) for j in range(4)]
    comb=[[div(row[i][j],sums[j]) for j in range(4)] for i in range(4)]
    rounds.append(dict(row=[bits(v) for r in row for v in r],col=[bits(v) for r in comb for v in r]))
   result.append(dict(name=name,input=source,pre=[bits(v) for v in pre],post=[bits(v) for v in post],rounds=rounds))
  rms=[]
  for name,value in [('zero','0'),('tiny',str(Decimal(2)**-40)),('one','1')]:
   v=f(Decimal(value));square=mul(v,v);summed=f(0)
   for _ in range(20480):summed=add(summed,square)
   mean=div(summed,f(20480));epsmean=add(mean,f(Decimal('1e-20')));root=f(epsmean.sqrt());inv=div(f(1),root)
   rms.append(dict(name=name,value=value,square=bits(square),sum=bits(summed),mean=bits(mean),epsmean=bits(epsmean),root=bits(root),inv=bits(inv)))
 return dict(sinkhorn=result,rms=rms)

def learned_weights(receipt):
 from pathlib import Path
 rows={r['tensor']:r for r in receipt['fixtures']};result={}
 for kind in ('attn','ffn'):
  def read(name):return np.fromfile(rows['blk.0.'+name+'.weight']['fixture_path'],'<f4')
  result[kind]=dict(fn=read('hc_'+kind+'_fn').reshape(24,20480),base=read('hc_'+kind+'_base'),scale=read('hc_'+kind+'_scale'),norm=read(kind+'_norm'))
 return result

def fixed_inputs(batch,variant):
 i=np.arange(batch*4*5120,dtype=np.int64).reshape(batch,4,5120)
 if variant=='tiny':return np.full((batch,4,5120),np.float32(2**-40),np.float32)
 if variant=='zero':return np.zeros((batch,4,5120),np.float32)
 return bf16((((i*(17 if variant=='A' else 29)+11)%251-125)/128).astype(np.float32)*np.array([1,2,.5,4],np.float32)[None,:,None])

def expected_staggered(x,weights):
 import importlib.util
 from pathlib import Path
 spec=importlib.util.spec_from_file_location('mhc_independent_ordered',Path(__file__).resolve().parents[1]/'quant/q_reference.py');q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)
 trace={};incoming=np.zeros((len(x),4),np.float32);incoming[:,0]=1
 def put(name,a):trace[name]=np.asarray(a,np.float32).copy()
 def mixes(name,res,w):
  put(name+'_rsqrt',flat_rsqrt(res));dot=q.ordered(w['fn'],res.reshape(len(x),20480));put(name+'_dot',dot);mixed=np.multiply(dot,trace[name+'_rsqrt'],dtype=np.float32);put(name+'_mixes',mixed);parts=split_sinkhorn(mixed,w['scale'],w['base'])
  for key in ('pre','post','logits','centered','exp','comb'):put(name+'_'+key,parts[key].reshape(len(x),-1))
  for n,(r,c) in enumerate(parts['rounds']):put(name+'_row'+str(n),r.reshape(len(x),16));put(name+'_col'+str(n),c.reshape(len(x),16))
  return parts
 put('input',x.reshape(len(x),20480));put('initial_pre',incoming)
 for layer in range(2):
  prefix='block'+str(layer);res=x;attn=mixes(prefix+'_attn',res,weights['attn']);collapsed=hc_pre(res,incoming);put(prefix+'_attn_input',collapsed);put(prefix+'_attn_norm',rms_norm(collapsed,weights['attn']['norm']))
  # Predetermined injected BF16 subblocks isolate staggered routing only.
  a=bf16(np.full((len(x),5120),np.float32(.25+layer/8)));put(prefix+'_attn_injected',a);x=hc_post(a,res,attn['post'],attn['comb']);put(prefix+'_attn_output',x.reshape(len(x),20480))
  res=x;ffn=mixes(prefix+'_ffn',res,weights['ffn']);collapsed=hc_pre(res,attn['pre']);put(prefix+'_ffn_input',collapsed);put(prefix+'_ffn_norm',rms_norm(collapsed,weights['ffn']['norm']))
  f=bf16(np.full((len(x),5120),np.float32(-.125-layer/16)));put(prefix+'_ffn_injected',f);x=hc_post(f,res,ffn['post'],ffn['comb']);put(prefix+'_ffn_output',x.reshape(len(x),20480));incoming=ffn['pre'];put(prefix+'_next_pre',incoming)
 # Synthetic declared head-pre collapse, no learned head qualification.
 put('head',hc_pre(x,incoming));return trace

class OracleTests(unittest.TestCase):
 def test_single_flatten_rms(self):
  x=np.repeat(np.array([1,2,4,8],np.float32),5120).reshape(1,4,5120)
  expected=np.float32(1/np.sqrt(np.float32(21.25)))
  self.assertEqual(flat_rsqrt(x).view(np.uint32).item(),expected.view(np.uint32).item())
 def test_sinkhorn_rounds_and_eps(self):
  trace=split_sinkhorn(np.zeros((1,24),np.float32),np.ones(3,np.float32),np.zeros(24,np.float32))
  self.assertEqual(len(trace['rounds']),20)
  self.assertEqual(trace['pre'].shape,(1,4))
  self.assertTrue(np.all(trace['pre']>np.float32(.5)))
  self.assertTrue(np.all(trace['post']==np.float32(1)))
 def test_post_orientation(self):
  residual=np.arange(4*5120,dtype=np.float32).reshape(1,4,5120);sub=np.zeros((1,5120),np.float32)
  comb=np.zeros((1,4,4),np.float32);comb[0,1,3]=1
  y=hc_post(sub,residual,np.zeros((1,4),np.float32),comb)
  self.assertEqual(y[0,3,0],bf16(residual)[0,1,0]);self.assertEqual(y[0,1,0],0)
 def test_pre_cast_and_tiny(self):
  x=np.zeros((1,4,5120),np.float32);pre=np.array([[1,0,0,0]],np.float32)
  self.assertTrue(np.array_equal(hc_pre(x,pre),np.zeros((1,5120),np.float32)))
  self.assertEqual(flat_rsqrt(x).shape,(1,1));self.assertTrue(np.isfinite(flat_rsqrt(x)).all())
 def test_geometry_nonfinite(self):
  for x in (np.zeros((1,3,5120),np.float32),np.full((1,4,5120),np.nan,np.float32)):
   with self.assertRaises(ValueError):flat_rsqrt(x)
if __name__=='__main__':unittest.main()
