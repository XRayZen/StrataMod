"""Independent T14 N/Q reference; no candidate output reads."""
import unittest
import numpy as np
import math

def bf16(x):
 x=np.asarray(x,np.float32)
 if not np.isfinite(x).all():raise ValueError('nonfinite BF16 source')
 u=x.view(np.uint32);return (((u+np.uint32(0x7fff)+((u>>16)&1))>>16)<<16).view(np.float32)

FP8=np.array([m/512 if e==0 else math.ldexp(1+m/8,e-7) for e in range(16) for m in range(8) if not(e==15 and m==7)],np.float64)
FP4=np.array([0,.5,1,1.5,2,3,4,6],np.float32)
def rne_codes(x,table):
 x=np.asarray(x,np.float32)
 if not np.isfinite(x).all():raise ValueError('nonfinite narrow source')
 mag=np.minimum(np.abs(x.astype(np.float64)),table[-1]);high=np.minimum(np.searchsorted(table,mag),len(table)-1);low=np.maximum(high-1,0);dh=table[high]-mag;dl=mag-table[low]
 return np.where((dh<dl)|((dh==dl)&((high&1)==0)),high,low).astype(np.uint8)
def fp8_codes(x):return rne_codes(x,FP8)|(np.signbit(x).astype(np.uint8)<<7)
def fp4_codes(x):return rne_codes(x,FP4)|(np.signbit(x).astype(np.uint8)<<3)
def narrow_decode(codes,table,sign):return np.where((codes&sign)!=0,-table[codes&(sign-1)],table[codes&(sign-1)]).astype(np.float32)

def fp4_qdq(x):
 x=bf16(x)
 if x.ndim!=2 or x.shape[1]!=512:raise ValueError('compressed head geometry')
 blocks=x.reshape(len(x),32,16);amax=np.maximum(np.max(np.abs(blocks),axis=2),np.float32(6*2**-9));scale_float=np.divide(amax,np.float32(6),dtype=np.float32);scales=fp8_codes(scale_float);scale=narrow_decode(scales,FP8,128)
 values=np.clip(np.divide(blocks,scale[:,:,None],dtype=np.float32),-6,6);codes=fp4_codes(values);decoded=np.multiply(narrow_decode(codes,FP4,8),scale[:,:,None],dtype=np.float32)
 return bf16(decoded.reshape(x.shape)),scales,codes.reshape(x.shape)

def fp8_qdq(x):
 x=bf16(x)
 if x.ndim!=2 or x.shape[1]%32:raise ValueError('FP8 group32 geometry')
 blocks=x.reshape(len(x),-1,32);amax=np.maximum(np.max(np.abs(blocks),axis=2),np.float32(1e-4));normalized=np.multiply(amax,np.float32(1/448),dtype=np.float32);u=normalized.view(np.uint32);exponent=((u>>23)&255).astype(np.int32)-127+((u&0x7fffff)!=0);scale=np.ldexp(np.ones(exponent.shape,np.float32),exponent).astype(np.float32)
 codes=fp8_codes(np.clip(np.divide(blocks,scale[:,:,None],dtype=np.float32),-448,448));decoded=np.multiply(narrow_decode(codes,FP8,128),scale[:,:,None],dtype=np.float32).reshape(x.shape)
 return bf16(decoded), (exponent+127).astype(np.uint8),codes.reshape(x.shape)

def ordered_sum(x,axis):
 x=np.moveaxis(np.asarray(x,np.float32),axis,-1);out=np.zeros(x.shape[:-1],np.float32)
 for i in range(x.shape[-1]):out=np.add(out,x[...,i],dtype=np.float32)
 return out

def norm512(x,weight):
 x=np.asarray(x,np.float32);w=np.asarray(weight,np.float32)
 if x.ndim!=2 or x.shape[1]!=512 or w.shape!=(512,) or not np.isfinite(x).all() or not np.isfinite(w).all():raise ValueError('norm512 geometry')
 mean=np.divide(ordered_sum(np.multiply(x,x,dtype=np.float32),1),np.float32(512),dtype=np.float32);inv=np.divide(np.float32(1),np.sqrt(np.add(mean,np.float32(1e-20),dtype=np.float32),dtype=np.float32),dtype=np.float32)
 return bf16(np.multiply(np.multiply(x,inv[:,None],dtype=np.float32),w,dtype=np.float32)),inv.reshape(-1,1)

def pool_pair(kv,score):
 kv=np.asarray(kv,np.float32);score=np.asarray(score,np.float32)
 if kv.ndim!=3 or kv.shape[1]!=2 or score.shape!=kv.shape or not np.isfinite(kv).all() or not np.isfinite(score).all():raise ValueError('ratio2 pool geometry')
 centered=np.subtract(score,np.max(score,axis=1,keepdims=True),dtype=np.float32);exp=np.exp(centered.astype(np.float64)).astype(np.float32);weights=np.divide(exp,ordered_sum(exp,1)[:,None,:],dtype=np.float32)
 return ordered_sum(np.multiply(kv,weights,dtype=np.float32),1)

def window_indices(seqlen,start):
 if type(seqlen) is not int or type(start) is not int or seqlen<=0 or start<0 or (start>0 and seqlen!=1):raise ValueError('window position geometry')
 if start==0:
  end=np.arange(seqlen,dtype=np.int64)[:,None];idx=np.maximum(end-127,0)+np.arange(min(seqlen,128));idx=np.where(idx>end,-1,idx)
 else:
  oldest=start%128+1;idx=np.concatenate([np.arange(oldest,128),np.arange(oldest)]);idx=np.where(idx>start,-1,idx).reshape(1,-1)
 return idx.astype(np.int32)

def frequencies(ratio):
 if type(ratio) is not int or ratio not in (0,1,2):raise ValueError('fixed model ratio')
 theta=10000 if ratio==0 else 160000;exponent=np.divide(np.arange(0,64,2,dtype=np.float32),np.float32(64),dtype=np.float32);power=np.power(float(theta),exponent.astype(np.float64)).astype(np.float32);freq=np.divide(np.float32(1),power,dtype=np.float32)
 if ratio:
  def correction(rot):return 64*math.log(65536/(rot*2*math.pi))/(2*math.log(theta))
  low=max(math.floor(correction(32)),0);high=min(math.ceil(correction(1)),63);ramp=np.clip(np.divide(np.subtract(np.arange(32,dtype=np.float32),np.float32(low),dtype=np.float32),np.float32(max(high-low,1e-3)),dtype=np.float32),0,1);smooth=np.subtract(np.float32(1),ramp,dtype=np.float32)
  freq=np.add(np.multiply(np.divide(freq,np.float32(16),dtype=np.float32),np.subtract(np.float32(1),smooth,dtype=np.float32),dtype=np.float32),np.multiply(freq,smooth,dtype=np.float32),dtype=np.float32)
 return freq

def rope(x,positions,ratio,inverse=False):
 x=bf16(x);positions=np.asarray(positions)
 if x.ndim!=2 or x.shape[1]!=512 or positions.shape!=(len(x),) or any(type(p) not in (int,np.int64,np.int32) or p<0 for p in positions):raise ValueError('rotary geometry')
 angle=np.multiply(positions.astype(np.float32)[:,None],frequencies(ratio)[None,:],dtype=np.float32);cos=np.cos(angle.astype(np.float64)).astype(np.float32);sin=np.sin(angle.astype(np.float64)).astype(np.float32)
 if inverse:sin=-sin
 tail=x[:,-64:].reshape(len(x),32,2);a,b=tail[:,:,0],tail[:,:,1];real=np.subtract(np.multiply(a,cos,dtype=np.float32),np.multiply(b,sin,dtype=np.float32),dtype=np.float32);imag=np.add(np.multiply(a,sin,dtype=np.float32),np.multiply(b,cos,dtype=np.float32),dtype=np.float32);out=x.copy();out[:,-64:]=np.stack([real,imag],axis=2).reshape(len(x),64)
 return bf16(out)

def decimal_literals():
 from decimal import Decimal,localcontext
 import struct
 def f(v):return Decimal.from_float(struct.unpack('<f',struct.pack('<f',float(v)))[0])
 def hx(v):return struct.pack('<f',float(v)).hex()
 def bfhex(v):
  u=struct.unpack('<I',struct.pack('<f',float(v)))[0];high=u>>16;low=u&65535
  if low>32768 or (low==32768 and high&1):high+=1
  return struct.pack('<I',high<<16).hex()
 result=dict(fp4=[dict(name='zero',amax='0',scale_code=1),dict(name='scale-tie-even-low',amax='6.375',scale_code=56),dict(name='scale-tie-even-high',amax='7.125',scale_code=58),dict(name='scale-satfinite',amax='2880',scale_code=126)],element_values=['0','0.25','0.75','1.25','1.75','2.5','3.5','5','-0','-0.25'],element_codes=[0,0,2,2,4,4,6,6,8,8])
 with localcontext() as ctx:
  ctx.prec=100
  def sin(x):
   total=term=x
   for n in range(1,100):term=-term*x*x/Decimal((2*n)*(2*n+1));total+=term
   return total
  def cos(x):
   total=term=Decimal(1)
   for n in range(1,100):term=-term*x*x/Decimal((2*n-1)*(2*n));total+=term
   return total
  result['rotation']=[dict(position=p,cos_f32=hx(cos(Decimal(p))),sin_f32=hx(sin(Decimal(p))),cos_bf16=bfhex(f(cos(Decimal(p)))),sin_bf16=bfhex(f(sin(Decimal(p))))) for p in (0,1)]
  pools=[]
  for a,b in [('0','0'),('1','-1'),('1000','-1000')]:
   aa,bb=Decimal(a),Decimal(b);e0=f((aa-max(aa,bb)).exp());e1=f((bb-max(aa,bb)).exp());den=f(e0+e1);w0=f(e0/den);w1=f(e1/den);pooled=f(f(Decimal(1)*w0)+f(Decimal(3)*w1));pools.append(dict(scores=[a,b],weights=[hx(w0),hx(w1)],pool=hx(pooled),bf16=bfhex(pooled)))
  result['pool']=pools
  result['norm']=[]
  for value in ('0',str(Decimal(2)**-40),'1'):
   v=f(Decimal(value));squared=f(v*v);total=f(0)
   for _ in range(512):total=f(total+squared)
   mean=f(total/f(512));epsmean=f(mean+f(Decimal('1e-20')));inv=f(f(1)/f(epsmean.sqrt()));out=f(v*inv);result['norm'].append(dict(value=value,inv=hx(inv),output=bfhex(out)))
 return result

def fixed_inputs():
 i=np.arange(5120,dtype=np.int64);rows=[]
 for n in range(8):
  multiplier=17 if n<4 else 29;shift=11+n*23;divisor=128 if n<4 else 256;rows.append(((i*multiplier+shift)%251-125)/divisor)
 return bf16(np.array(rows,np.float32))

def learned_projection(receipt):
 import importlib.util
 from pathlib import Path
 sp=importlib.util.spec_from_file_location('kv_independent_t09',Path(__file__).resolve().parents[1]/'quant/q_reference.py');q=importlib.util.module_from_spec(sp);sp.loader.exec_module(q);raw={r['tensor']:r for r in receipt['fixtures']};x=fixed_inputs();out={}
 def weight(name):
  r=raw[name];return q.decode(r['type_id'],Path(r['fixture_path']).read_bytes()).reshape(r['dims_ggml'][1],r['dims_ggml'][0]) if len(r['dims_ggml'])==2 else np.fromfile(r['fixture_path'],'<f4')
 quantized,scales,codes=fp8_qdq(x);dot=q.ordered(weight('blk.0.attn_kv.weight'),quantized);bf=bf16(dot);norm,inv=norm512(bf,weight('blk.0.attn_kv_a_norm.weight'));out['window']=dict(input=x,input_qdq=quantized,input_codes=codes,input_scales=scales,dot=dot,bf=bf,norm=norm,inv=inv)
 for layer in (2,8,14,20):
  ratio=2 if layer!=20 else 1;prefix='blk.'+str(layer)+'.attn_compressor_';dot=q.ordered(weight(prefix+'kv.weight'),x);row=dict(input=x,kv_dot=dot,norm_weight=weight(prefix+'norm.weight'))
  if ratio==2:row['score']=q.ordered(weight(prefix+'gate.weight'),x)
  else:row['kv_bf']=bf16(dot)
  out['source'+str(layer)]=row
 return out

def temporal_projection(projected,length,start=0):
 indices=(np.arange(length,dtype=np.int64)+start)%8;out={};window=projected['window']['norm'][indices];rotated=rope(window,np.arange(length),0);decoded,scales,codes=fp8_qdq(rotated);out.update(window_pre_rope=window,window_post_rope=rotated,window_codes=codes,window_scales=scales,window_decoded=decoded,window_indices=window_indices(length,0))
 # Every prefill query retains its whole chunk view; only the later decode view
 # sees this separately seeded physical ring. -1 records an unoccupied slot.
 ring_codes=np.zeros((128,512),np.uint8);ring_scales=np.zeros((128,16),np.uint8);ring_positions=np.full(128,-1,np.int64)
 for p in range(length):ring_codes[p%128]=codes[p];ring_scales[p%128]=scales[p];ring_positions[p%128]=p
 out.update(ring_codes=ring_codes,ring_scales=ring_scales,ring_positions=ring_positions.reshape(1,128))
 for layer in (2,8,14,20):
  ratio=2 if layer!=20 else 1;source=projected['source'+str(layer)];kv=source['kv_dot'][indices]
  if ratio==2:
   score=source['score'][indices];whole=length//2;pooled=pool_pair(kv[:whole*2].reshape(whole,2,512),score[:whole*2].reshape(whole,2,512));before_norm=bf16(pooled)
   out['s'+str(layer)+'_partial_kv']=kv[whole*2:];out['s'+str(layer)+'_partial_score']=score[whole*2:]
  else:before_norm=bf16(kv)
  latent,inv=norm512(before_norm,source['norm_weight']);positions=np.arange(len(latent))*ratio;post=rope(latent,positions,ratio);deq,scale,code=fp4_qdq(post);packed=(code[:,0::2]|(code[:,1::2]<<4)).astype(np.uint8);prefix='s'+str(layer)+'_';out[prefix+'pre_rope']=latent;out[prefix+'post_rope']=post;out[prefix+'codes']=code;out[prefix+'packed']=packed;out[prefix+'scales']=scale;out[prefix+'decoded']=deq;out[prefix+'inv']=inv;out[prefix+'visible']=(np.arange(length)+1).astype(np.int64).reshape(-1,1)//ratio
 return out

KV_SOURCES=(2,8,14,20)
RATIOS=tuple([0,0]+[2]*18+[1]*20)
def source_of(layer):
 if type(layer) is not int or not 0<=layer<40:raise ValueError('trunk layer')
 return None if RATIOS[layer]==0 else max(v for v in KV_SOURCES if v<=layer)

class SequenceState:
 # Pure independent oracle state, never runtime identity/ownership authority.
 def __init__(self):self.reset(1)
 def reset(self,epoch):
  if type(epoch) is not int or not 0<epoch<2**64:raise ValueError('caller epoch')
  self.epoch=epoch;self.position=0;self.active=True;self.view=None;self.events=[]
 def accept(self,position,epoch,writer):
  if not self.active or type(epoch) is not int or epoch!=self.epoch or type(position) is not int or position!=self.position or writer not in KV_SOURCES:raise ValueError('state epoch/position/writer')
 def publish(self,writer,rows,epoch):
  if not self.active or epoch!=self.epoch or writer not in KV_SOURCES:raise ValueError('publish writer/epoch')
  self.view=(writer,rows,epoch);self.events.append((2,writer,rows,self.position,epoch))
 def read(self,layer):
  source=source_of(layer)
  if source is None:return None
  if self.view is None or self.view[0]!=source or self.view[2]!=self.epoch:raise ValueError('stale/wrong source shared view')
  self.events.append((3,layer,self.view[1],self.position,self.epoch));return self.view
 def cancel(self,epoch):
  if epoch!=self.epoch:raise ValueError('cancel epoch')
  self.active=False
 def reuse(self,new_epoch):
  if not self.active or type(new_epoch) is not int or new_epoch<=self.epoch or new_epoch>=2**64:raise ValueError('exact-prefix caller reuse')
  self.epoch=new_epoch;self.view=None

def shared_events(length,epoch=1):
 state=SequenceState();state.reset(epoch)
 for layer in range(40):
  if layer in KV_SOURCES:
   state.accept(0,epoch,layer);count=length//RATIOS[layer];state.events.append((1,layer,count,0,epoch));state.publish(layer,count,epoch)
  state.read(layer)
 return np.array(state.events,np.int64)

def controls():
 result={}
 for name,maximum in [('zero',0.),('tiny',2**-40),('scale-low',6.375),('scale-high',7.125),('scale-saturation',2880.)]:
  x=np.zeros((1,512),np.float32);x[0,0]=np.float32(maximum);x[0,1]=-0.;out,scale,code=fp4_qdq(x);result[name]=dict(input=x,decoded=out,scales=scale,codes=code,packed=(code[:,0::2]|(code[:,1::2]<<4)).astype(np.uint8))
 x=np.zeros((1,512),np.float32);x[0,:11]=[0,.25,.75,1.25,1.75,2.5,3.5,5,-0.,-.25,6];out,scale,code=fp4_qdq(x);result['element-ties']=dict(input=x,decoded=out,scales=scale,codes=code,packed=(code[:,0::2]|(code[:,1::2]<<4)).astype(np.uint8))
 for name,score in [('pool-tie',[0,0]),('pool-near',[0,np.spacing(np.float32(1))]),('pool-large',[1000,-1000])]:
  x=np.stack([np.full(512,.125,np.float32),np.full(512,-.25,np.float32)])[None,:,:];scores=np.broadcast_to(np.array(score,np.float32)[None,:,None],x.shape).copy();result[name]=dict(kv=x.reshape(2,512),score=scores.reshape(2,512),pooled=pool_pair(x,scores))
 for name in ('window-zero','window-ties','window-tiny'):
  x=np.zeros((1,512),np.float32);x[0,0]=-0.
  if name=='window-ties':x[0,:8]=[448,1.0625,1.1875,-1.0625,1/1024,3/1024,-1/1024,-3/1024]
  if name=='window-tiny':x.fill(np.float32(2**-30));x[0,0]=-np.float32(2**-30)
  y,scale,code=fp8_qdq(x);result[name]=dict(input=x,decoded=y,scales=scale,codes=code)
 for name,value in [('norm-zero',0.),('norm-tiny',2**-40)]:
  x=np.full((1,512),np.float32(value),np.float32);y,inv=norm512(x,np.ones(512,np.float32));result[name]=dict(input=x,output=y,inv=inv)
 for ratio in (0,2):
  x=bf16(np.tile(np.linspace(-1,1,512,dtype=np.float32),(5,1)));positions=np.array([0,1,127,128,129],np.int64);result['rope'+str(ratio)]=dict(input=x,positions=positions.reshape(-1,1),frequencies=frequencies(ratio).reshape(1,32),output=rope(x,positions,ratio),inverse=rope(x,positions,ratio,inverse=True))

 return result

class Tests(unittest.TestCase):
 def test_fp4_zero_floor_and_sign(self):
  x=np.zeros((1,512),np.float32);x[0,0]=-0.;y,scales,codes=fp4_qdq(x)
  self.assertTrue(np.all(scales==1));self.assertEqual(codes[0,0],8);self.assertTrue(np.signbit(y[0,0]))
 def test_pool_and_partial(self):
  kv=np.array([[[1,3],[3,1]]],np.float32);score=np.zeros_like(kv)
  self.assertTrue(np.array_equal(pool_pair(kv,score),np.array([[2,2]],np.float32)))
 def test_window_prefill129(self):
  idx=window_indices(129,0);self.assertEqual(idx.shape,(129,128));self.assertEqual(idx[0,0],0);self.assertTrue(np.all(idx[0,1:]==-1));self.assertEqual(idx[-1,0],1);self.assertEqual(idx[-1,-1],128)
 def test_window_decode129(self):
  idx=window_indices(1,129);self.assertEqual(idx.reshape(-1).tolist(),list(range(2,128))+[0,1])
 def test_rope_config_zero(self):
  x=bf16(np.arange(512,dtype=np.float32).reshape(1,512));rot=rope(x,[0],ratio=0)
  self.assertTrue(np.array_equal(rot,x));self.assertFalse(np.array_equal(frequencies(0),frequencies(2)))
 def test_scale_and_midpoints(self):
  x=np.zeros((1,512),np.float32);x[0,:4]=[6,.25,.75,-.25];y,s,c=fp4_qdq(x)
  self.assertEqual(s[0,0],56);self.assertEqual(c[0,:4].tolist(),[7,0,2,8])
if __name__=='__main__':unittest.main()
