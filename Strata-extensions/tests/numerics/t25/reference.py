"""Independent T25 N and native Q. Candidate kernels/references and G never imported."""
import math,struct,json,hashlib,sys
from decimal import Decimal,localcontext
from pathlib import Path
try:import numpy as np
except ModuleNotFoundError:
 sys.path.append('C:/Develop/AI/StrataMod/.vision-venv-10.1/Lib/site-packages');import numpy as np
F=np.float32
def bf16(x):
 u=np.asarray(x,dtype='<f4').view('<u4');return ((u+np.uint32(0x7fff)+((u>>16)&1))&np.uint32(0xffff0000)).view('<f4')
def decode_q8(raw):
 if not raw or len(raw)%34:raise ValueError('Q8 full blocks')
 b=np.frombuffer(raw,np.uint8).reshape(-1,34);s=b[:,:2].copy().reshape(-1).view('<f2').astype('<f4');v=b[:,2:].copy().view(np.int8).astype('<f4');return (s[:,None]*v).reshape(-1)
def decode_row(raw):
 if len(raw)!=264:raise ValueError('native row264')
 out=[]
 for j in range(0,264,33):
  scale=F(math.ldexp(1.,raw[j]-127)) if raw[j]!=255 else F(math.inf)
  for c in raw[j+1:j+33]:
   e=(c>>3)&15;m=c&7;v=math.nan if e==15 and m==7 else math.ldexp(m,-9) if e==0 else math.ldexp(8+m,e-10)
   out.append(F(-v if c&128 else v)*scale)
 return np.array(out,dtype='<f4')
_codes=np.arange(127);_e=_codes>>3;FP8=np.where(_e==0,(_codes&7)/512,np.ldexp(1+(_codes&7)/8,_e-7))
def fp8_codes(x):
 x=np.asarray(x,np.float32);a=np.minimum(np.abs(x.astype(np.float64)),448);hi=np.minimum(np.searchsorted(FP8,a),126);lo=np.maximum(hi-1,0);dh=FP8[hi]-a;dl=a-FP8[lo]
 return np.where((dh<dl)|((dh==dl)&((hi&1)==0)),hi,lo).astype(np.uint8)|(np.signbit(x).astype(np.uint8)<<7)
def qdq(x):
 x=bf16(x);b=x.reshape(len(x),-1,32);a=np.maximum(np.max(np.abs(b),axis=2),F(1e-4));n=np.multiply(a,F(1/448),dtype=np.float32);u=n.view(np.uint32);e=((u>>23)&255).astype(np.int32)-127+((u&0x7fffff)!=0);s=np.ldexp(np.ones(e.shape,np.float32),e);c=fp8_codes(np.clip(b/s[:,:,None],-448,448));v=FP8[c&127].astype('<f4');v=np.where((c&128)!=0,-v,v);return (v*s[:,:,None]).reshape(x.shape),(e+127).astype(np.uint8),c.reshape(x.shape)
def ordered(w,x):
 w=np.asarray(w,np.float32);x=np.asarray(x,np.float32);out=np.empty((len(x),len(w)),np.float32)
 for b in range(len(x)):
  for i in range(0,len(w),64):
   p=np.multiply(w[i:i+64],x[b],dtype=np.float32);s=np.concatenate((np.zeros((len(p),1),np.float32),p),axis=1);out[b,i:i+len(p)]=np.cumsum(s,axis=1,dtype=np.float32)[:,-1]
 return out
def sums(x):
 x=np.asarray(x,np.float32);return np.cumsum(np.concatenate((np.zeros(x.shape[:-1]+(1,),np.float32),x),axis=-1),axis=-1,dtype=np.float32)[...,-1]
def residual(batch,hold):
 b=np.arange(batch)[:,None,None];j=np.arange(4)[None,:,None];d=np.arange(5120)[None,None,:]
 return bf16((((b*29+j*17+d*7)%257-128)/128 if hold=='A' else ((b*31+j*43+d*11)%251-125)/64).astype('<f4')).reshape(batch,20480)

def small_restore_expected(root):
 """Independent source2 ratio2 state, never candidate/G-derived."""
 o=ActualOracle(root);inputs={h:residual(4,h).reshape(4,4,5120)[:,0].copy() for h in ['A','B']};prefix='blk.2.attn_compressor_'
 projected={h:(o.linear(prefix+'kv.weight',x),o.linear(prefix+'gate.weight',x)) for h,x in inputs.items()};weight=o.const(prefix+'norm.weight');result={}
 for checkpoint in [1,2]:
  for branch in ['A','B']:
   keys=[];scores=[];cache=[];latent=[];rotated=[]
   for p in range(4):
    h='A' if p<checkpoint else branch;k,s=projected[h];keys.append(k[p]);scores.append(s[p])
    if p%2:
     pool=o.kv.pool_pair(np.asarray(keys[-2:])[None],np.asarray(scores[-2:])[None]);z=o.kv.norm512(bf16(pool),weight)[0];r=o.kv.rope(z,np.array([p-1],np.int64),2);v=o.kv.fp4_qdq(r)[0];latent.append(z[0]);rotated.append(r[0]);cache.append(v[0])
   result[f'cp{checkpoint}-{branch}']=dict(cache=np.asarray(cache,dtype='<f4'),latent=np.asarray(latent,dtype='<f4'),rotated=np.asarray(rotated,dtype='<f4'))
  if checkpoint==1:
   result['snapshot1']=dict(pending_kv=projected['A'][0][0].copy(),pending_score=projected['A'][1][0].copy())
  else:result['snapshot2']=dict(cache=result['cp2-A']['cache'][:1].copy())
 if any(np.array_equal(result[f'cp{c}-A']['cache'],result[f'cp{c}-B']['cache']) for c in [1,2]):raise ValueError('nonidentical state branch required')
 return inputs,result,o.reads,o.diagnostics
def gate(h,kv,w,mask):
 h=np.asarray(h,np.float32);kv=np.asarray(kv,np.float32);hh=h.reshape(-1,4,5120);key=kv[:,:20480].reshape(-1,4,5120);w=np.asarray(w,np.float32).reshape(4,5120)
 sh=sums(np.multiply(hh,hh,dtype=np.float32));sk=sums(np.multiply(key,key,dtype=np.float32));dot=sums(np.multiply(np.multiply(hh,w,dtype=np.float32),key,dtype=np.float32))
 ih=np.divide(F(1),np.sqrt(np.add(np.divide(sh,F(5120),dtype=np.float32),F(1e-20),dtype=np.float32),dtype=np.float32),dtype=np.float32);ik=np.divide(F(1),np.sqrt(np.add(np.divide(sk,F(5120),dtype=np.float32),F(1e-20),dtype=np.float32),dtype=np.float32),dtype=np.float32)
 z=np.multiply(np.multiply(dot,np.multiply(ih,ik,dtype=np.float32),dtype=np.float32),F(5120**-.5),dtype=np.float32);root=np.copysign(np.sqrt(np.maximum(np.abs(z),F(1e-6)),dtype=np.float32),z);g=(1/(1+np.exp(-root.astype(np.float64)))).astype('<f4');g=np.where(np.asarray(mask)[:,None],g,F(0)).astype('<f4');out=bf16(np.add(hh,np.multiply(g[:,:,None],kv[:,None,20480:],dtype=np.float32),dtype=np.float32)).reshape(h.shape)
 return dict(sum_h=sh,sum_key=sk,weighted_dot=dot,inverse_h=ih,inverse_key=ik,z=z,root=root,gates=g,output=out)
def decimal_literals():
 rows=[]
 with localcontext() as ctx:
  ctx.prec=100
  for value in ['0','-0','0.0000001','-0.0000001','1','-1']:
   z=Decimal(value);a=max(abs(z),Decimal.from_float(float(F(1e-6))));r=a.sqrt();r=-r if z.is_signed() else r;g=1/(1+(-r).exp());rf=F(float(r));gf=F(1/(1+math.exp(-float(rf))));target=F(float(g));gap=abs(int(gf.view(np.uint32))-int(target.view(np.uint32)))
   if gap>2:raise ValueError('independent N local nonlinear bound')
   rows.append(dict(z=value,root_decimal=str(r),sigmoid_decimal=str(g),canonical_root_bits=int(rf.view(np.uint32)),sigmoid_bits=int(gf.view(np.uint32)),N_sigmoid_bits=int(target.view(np.uint32)),ULP=gap))
 return dict(checked=len(rows),rows=rows,precision=100)
def fusion(receipt):
 results=[]
 for l in [1,14]:
  d={x['tensor'].split('.')[-1]:np.fromfile(x['path'],dtype='<u2').astype('<u4')<<16 for x in receipt['official'] if x['source']['layer']==l};a=d['q_weight'].view('<f4');b=d['k_weight'].view('<f4');p=np.multiply(a,b,dtype=np.float32);raw=next(x for x in receipt['gguf_gates'] if x['tensor']==f'blk.{l}.engram_gate.weight');g=np.fromfile(raw['path'],dtype='<f4')
  if p.shape!=g.shape or not np.array_equal(p.view(np.uint32),g.view(np.uint32)):raise ValueError(f'official q*k / GGUF gate equality layer{l}: mismatches='+str(np.count_nonzero(p.view(np.uint32)!=g.view(np.uint32))))
  results.append(dict(layer=l,values=len(p),equal_bits=True,product_SHA256=hashlib.sha256(p.tobytes()).hexdigest()))
 return results

def control_inputs(name):
 h=np.ones((1,20480),np.float32);kv=np.ones((1,25600),np.float32);weight=np.ones((4,5120),np.float32);mask=np.ones(1,np.uint8)
 if name in ['positivezero','negativezero']:weight.fill(0);weight[:,0]=-np.nextafter(F(0),F(1)) if name=='negativezero' else 0
 if name=='key8':kv[:,:20480]*=8
 if name=='masked':mask[:]=0
 if name=='tiny':h[:]=F(2**-40);kv[:,:20480]=F(2**-40)
 if name=='zero-norm':h[:]=0;kv[:,:20480]=0
 if name=='asymmetric':
  for j in range(4):h[:,j*5120:(j+1)*5120]=F(2**j);kv[:,j*5120:(j+1)*5120]=F(2**(3-j));weight[j]=F(2**(j-2))
 if name=='product-order':h[:]=F(2**-80);kv[:,:20480]=F(2**50);weight[:]=F(2**-80)
 return h,kv,weight,mask

def decimal_full(h,kv,weight,mask):
 """Independent scalar official formula with explicit canonical FP32 nodes.

 No gate/sums/qdq/NumPy reductions from Q are called. Decimal also supplies
 ideal nonlinear values at each canonical input, separated from bit equality.
 """
 D=Decimal;out={k:[] for k in ['sum_h','sum_key','weighted_dot','inverse_h','inverse_key','z','root','gates']};outputs=[];ulp=[]
 def dec(x):return D.from_float(float(x))
 def rnd(x):return struct.unpack('<f',struct.pack('<f',float(x)))[0]
 def bits(x):return struct.unpack('<I',struct.pack('<f',float(x)))[0]
 with localcontext() as ctx:
  ctx.prec=100
  for b in range(len(h)):
   target=[]
   for j in range(4):
    hs=ks=dot=0.;ideal_h=ideal_k=ideal_dot=D(0)
    for d in range(5120):
     x=dec(h[b,j*5120+d]);k=dec(kv[b,j*5120+d]);w=dec(weight[j,d]);hs=rnd(dec(hs)+dec(rnd(x*x)));ks=rnd(dec(ks)+dec(rnd(k*k)));dot=rnd(dec(dot)+dec(rnd(dec(rnd(x*w))*k)));ideal_h+=x*x;ideal_k+=k*k;ideal_dot+=x*w*k
    inverses=[]
    for s in [hs,ks]:
     argument=rnd(dec(rnd(dec(s)/D(5120)))+dec(rnd(D('1e-20'))));ideal=D(1)/dec(argument).sqrt();root=rnd(dec(argument).sqrt());iv=rnd(D(1)/dec(root));gap=abs(bits(iv)-bits(rnd(ideal)))
     if gap>2:raise ValueError('independent N RMS local error')
     inverses.append(iv);ulp.append(gap)
    ih,ik=inverses;z=rnd(dec(rnd(dec(dot)*dec(rnd(dec(ih)*dec(ik)))))*dec(rnd(D(5120)**(-D('.5')))));magnitude=max(abs(dec(z)),dec(rnd(D('1e-6'))));root=rnd(magnitude.sqrt());root=math.copysign(root,z);sigmoid=D(1)/(D(1)+(-dec(root)).exp());g=rnd(D(1)/(D(1)+dec(math.exp(-root)))) if mask[b] else 0.;gap=abs(bits(g)-bits(rnd(sigmoid))) if mask[b] else 0
    if gap>2:raise ValueError('independent N sigmoid local error')
    ulp.append(gap)
    for key,value in zip(out,[hs,ks,dot,ih,ik,z,root,g],strict=True):out[key].append(value)
    for d in range(5120):
     p=rnd(dec(g)*dec(kv[b,20480+d]));v=rnd(dec(h[b,j*5120+d])+dec(p));u=bits(v);target.append(struct.unpack('<f',struct.pack('<I',(u+0x7fff+((u>>16)&1))&0xffff0000))[0])
   outputs.append(target)
 result={k:np.asarray(v,dtype='<f4').reshape(len(h),4) for k,v in out.items()};result['output']=np.asarray(outputs,dtype='<f4');return result,dict(precision=100,nonlinear_max_ULP=max(ulp),official_formula='350-365; canonical rounding explicit; independent scalar Decimal')

def compare_n_control(trace,expected):
 for k,v in expected.items():
  a=np.asarray(trace[k])
  if a.shape!=v.shape or a.tobytes()!=v.tobytes():raise ValueError('independent full N control '+k)

def real_gate_n(h,kv,weight,trace):
 """Independent FP64 original formula and conservative ordered FP32 interval."""
 x=h.astype(np.float64).reshape(-1,4,5120);k=kv[:,:20480].astype(np.float64).reshape(-1,4,5120);w=weight.astype(np.float64)[None];n_h=np.sum(x*x,axis=-1);n_k=np.sum(k*k,axis=-1);n_dot=np.sum((x*w)*k,axis=-1);sa=np.nextafter(np.sum(np.abs((x*w)*k),axis=-1)*(1+5120*2**-52),np.inf);u=2**-24;gamma=lambda n:n*u/(1-n*u);tiny=2**-149
 bh=gamma(2*5120)*n_h+5120*tiny;bk=gamma(2*5120)*n_k+5120*tiny;bd=gamma(3*5120)*sa+.5*tiny*(np.sum(np.abs(k),axis=-1)+2*5120)
 for name,n,bound in [('sum_h',n_h,bh),('sum_key',n_k,bk),('weighted_dot',n_dot,bd)]:
  if not np.isfinite(trace[name]).all() or np.any(np.abs(trace[name].astype(np.float64)-n)>bound):raise ValueError('independent real N '+name)
 eps=float(F(1e-20));interval=[]
 for name,n,bound in [('inverse_h',n_h,bh),('inverse_key',n_k,bk)]:
  lo=(1/np.sqrt((n+bound)/5120+eps))*(1-8*u);hi=(1/np.sqrt(np.maximum(0,n-bound)/5120+eps))*(1+8*u);v=trace[name].astype(np.float64)
  if not np.isfinite(v).all() or np.any((v<lo)|(v>hi)):raise ValueError('independent real N '+name)
  interval.append((lo,hi))
 il=interval[0][0]*interval[1][0];ih=interval[0][1]*interval[1][1];low=n_dot-bd;high=n_dot+bd;c=float(F(5120**-.5));candidates=np.stack([low*il,low*ih,high*il,high*ih]);lo=np.min(candidates,axis=0)*c;hi=np.max(candidates,axis=0)*c;rounding=16*u*np.maximum(abs(lo),abs(hi))+16*tiny;z=trace['z'].astype(np.float64)
 if not np.isfinite(z).all() or np.any((z<lo-rounding)|(z>hi+rounding)):raise ValueError('independent real N normalized dot')
 return dict(sum_h=n_h.tolist(),sum_key=n_k.tolist(),weighted_dot=n_dot.tolist(),weighted_bound=bd.tolist(),z_FP64=(n_dot/np.sqrt(n_h/5120+eps)/np.sqrt(n_k/5120+eps)/math.sqrt(5120)).tolist(),z_lower=(lo-rounding).tolist(),z_upper=(hi+rounding).tolist(),scope='same native decoded weights; FP64 diagnostic, not official backend reduction identity')

def actual_role(layer):
 if type(layer) is not int or not 0<=layer<40:raise ValueError('actual trunk layer')
 if layer<2:return 0,None,None
 return (2 if layer<20 else 1),max(v for v in [2,8,14,20] if v<=layer),max(v for v in [2,8,14,20,24,28,32,36] if v<=layer)

class ActualOracle:
 """Independent composed CPU graph; candidate T20 code/reference never imported.

 Original matrix rows are streamed, no full model/raw table copy. Qualified
 prior independent numerical primitives are reused, not their G receipts.
 """
 def __init__(self,root):
  import importlib.util
  self.root=Path(root);self.ext=self.root/'Strata-extensions';self.reads=[];self.diagnostics=[]
  def load(name,relative):
   p=self.ext/relative;s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
  self.native=load('t25_actual_q09','tests/quant/q_reference.py');self.mhc=load('t25_actual_q12','tests/mhc/reference.py');self.kv=load('t25_actual_q14','tests/kv/reference.py');self.att=load('t25_actual_q15','tests/attention/reference.py');self.ffn=load('t25_actual_q11','tests/ffn/reference.py');self.eg=load('t25_actual_q13','tests/engram/reference.py')
  self.inventory=json.loads((self.ext/'tests/artifact/header-inventory.json').read_text(encoding='utf-8'));self.tensors={t['name']:(s,t) for s in self.inventory['shards'] for t in s['tensors']};self.sources={int(x[0]):x for x in [line.split('\t') for line in (self.root/'build-deepseek-t10/sources.tsv').read_text(encoding='utf-8').splitlines()]};self.nq=json.loads((self.root/'build-deepseek-t13/nq.json').read_text(encoding='utf-8'));self.constants={}
 def raw(self,name,start,count):
  shard,t=self.tensors[name];source=self.sources[shard['index']];p=Path(source[4]);before=p.stat();absolute=t['absolute_offset']+start
  if p.suffix=='.part' or start<0 or count<=0 or start+count>t['bytes']:raise ValueError('original bounded span')
  with p.open('rb') as f:f.seek(absolute);b=f.read(count)
  after=p.stat()
  if len(b)!=count or (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):raise ValueError('changed/short original')
  self.reads.append(dict(tensor=name,source=source,absolute_offset=absolute,bytes=count,sha256=hashlib.sha256(b).hexdigest()));return b
 def const(self,name):
  if name not in self.constants:
   _,t=self.tensors[name]
   if t['type_id']!=0 or t['bytes']>81920:raise ValueError('bounded F32 constant')
   self.constants[name]=np.frombuffer(self.raw(name,0,t['bytes']),'<f4').copy()
  return self.constants[name]
 def linear(self,name,x,activation=False,matrix=0,first=0,count=None):
  _,t=self.tensors[name];dims=t['dims_ggml'];k,n=dims[:2];count=n-first if count is None else count;x=np.asarray(x,np.float32)
  if x.ndim!=2 or x.shape[1]!=k or first<0 or count<=0 or first+count>n or matrix<0 or matrix>=(dims[2] if len(dims)>2 else 1):raise ValueError('original fullK matrix')
  if activation:x=qdq(x)[0]
  out=np.empty((len(x),count),np.float32);row=t['row_bytes'];gamma=(2*k*2**-24)/(1-2*k*2**-24);maximum=0.;largest_bound=0.
  for r in range(0,count,64):
   rows=min(64,count-r);raw=self.raw(name,(matrix*n+first+r)*row,rows*row);w=self.native.decode(t['type_id'],raw).reshape(rows,k);v=ordered(w,x);out[:,r:r+rows]=v
   for b in range(len(x)):
    p=w.astype(np.float64)*x[b].astype(np.float64);ideal=np.sum(p,axis=1);ab=np.nextafter(np.sum(np.abs(p),axis=1)*(1+k*2**-52),np.inf);bound=gamma*ab+k*2**-149;error=np.abs(v[b].astype(np.float64)-ideal)
    if not np.isfinite(v).all() or np.any(error>bound):raise ValueError('independent actual projection N bound '+name)
    maximum=max(maximum,float(error.max()));largest_bound=max(largest_bound,float(bound.max()))
  self.diagnostics.append(dict(tensor=name,matrix=matrix,first=first,count=count,K=k,max_error=maximum,max_bound=largest_bound));return out
 def reset(self):self.windows={};self.compression={};self.keys={};self.pending={};self.selection=None;self.candidates=None;self.history=[];self.position=0;self.frames=[];self.range=None
 def emit(self,name,x):
  x=np.asarray(x)
  if x.dtype.kind=='f' and not np.isfinite(x).all():raise ValueError('nonfinite real canonical stage '+name)
  self.stages[name]=x.copy()
 def norm(self,x,name):return self.att.norm_features(x,self.const(name))[0]
 def mixes(self,prefix,r):
  dot=self.linear(prefix+'fn.weight',r.reshape(1,20480));inv=self.mhc.flat_rsqrt(r);mixed=np.multiply(dot,inv,dtype=np.float32);return self.mhc.split_sinkhorn(mixed,self.const(prefix+'scale.weight'),self.const(prefix+'base.weight'))
 def engram(self,layer,h):
  rawids=[t for t in self.history];ids=self.eg.hashes(rawids,[True]*len(rawids),self.nq['token_map'],self.nq['multipliers'],self.nq['primes'],self.nq['offsets'])[-1];bank=[]
  for head in range(24):
   row=ids[(0 if layer==1 else 24)+head];bank.append(decode_row(self.raw('per_layer_token_embd.weight',row*264,264)))
  emb=bf16(np.asarray(bank,np.float32).reshape(1,6144));act=qdq(emb)[0];dot=self.linear(f'blk.{layer}.engram_kv.weight',act);kv=bf16(dot);w=self.const(f'blk.{layer}.engram_gate.weight').reshape(4,5120);g=gate(h.reshape(1,20480),kv,w,np.ones(1,np.uint8));self.diagnostics.append(dict(engram_layer=layer,position=self.position,gate_N=real_gate_n(h.reshape(1,20480),kv,w,g)))
  for name,x in [('engram_embedding',emb),('engram_act_qdq',act),('engram_kv_dot',dot),('engram_kv_bf16',kv),('engram_gates',g['gates']),('engram_residual',g['output'])]:self.emit(name,x)
  return g['output'].reshape(1,4,5120)
 def shared(self,layer,x,qr):
  ratio,writer,indexwriter=actual_role(layer);prefix=f'blk.{writer}.'
  if layer==writer:
   value=self.linear(prefix+'attn_compressor_kv.weight',x)
   if ratio==2:
    score=self.linear(prefix+'attn_compressor_gate.weight',x);self.pending.setdefault(writer,[]).append((value,score))
    if len(self.pending[writer])==2:
     pair=self.pending.pop(writer);value=self.kv.pool_pair(np.stack([v[0][0] for v in pair])[None],np.stack([v[1][0] for v in pair])[None]);publish=True
    else:publish=False
   else:publish=True
   if publish:
    latent=self.norm(bf16(value),prefix+'attn_compressor_norm.weight');self.emit('compression_pre_rope',latent);pos=np.array([self.position+1-ratio],np.int64);key=bf16(self.linear(prefix+'indexer.attn_k.weight',latent));key=self.norm(key,prefix+'indexer.k_norm.weight');key=self.att.rotary(key,pos);key=self.att.fp4_index_qdq(key)[0];self.keys.setdefault(writer,[]).append(key[0]);rot=self.kv.rope(latent,pos,ratio);compressed=self.kv.fp4_qdq(rot)[0];self.compression.setdefault(writer,[]).append(compressed[0])
  keys=np.asarray(self.keys.get(writer,[]),np.float32).reshape(-1,128)
  if layer==indexwriter:
   if len(keys):
    p=f'blk.{layer}.';query=bf16(self.linear(p+'indexer.attn_q_b.weight',qr,True)).reshape(32,128);query=self.att.rotary(query,np.full(32,self.position,np.int64));query=self.att.fp4_index_qdq(query)[0];weights=bf16(np.multiply(bf16(self.linear(p+'indexer.proj.weight',x)),F(1/64),dtype=np.float32));score=self.att.index_scores(query[None],keys,weights)
    if layer==20:self.candidates=self.att.candidate_blocks(score,[len(keys)])
    mask=self.candidates if layer>=20 else np.ones(score.shape,bool);self.selection=self.att.top_positions(score,mask,[len(keys)],128);self.emit('index_score',score);self.emit('index_selected',self.selection)
   else:self.selection=np.empty((1,0),np.int32)
  if self.selection is None:raise ValueError('missing independent current selection')
  return np.asarray(self.compression.get(writer,[]),np.float32).reshape(-1,512),self.selection
 def attention(self,layer,x):
  prefix=f'blk.{layer}.';ratio,_,_=actual_role(layer);qa=bf16(self.linear(prefix+'attn_q_a.weight',x,True));qr=self.norm(qa,prefix+'attn_q_a_norm.weight');query=bf16(self.linear(prefix+'attn_q_b.weight',qr,True)).reshape(64,512);query=self.kv.rope(query,np.full(64,self.position,np.int64),ratio);value=bf16(self.linear(prefix+'attn_kv.weight',x,True));value=self.norm(value,prefix+'attn_kv_a_norm.weight');value=self.kv.rope(value,np.array([self.position],np.int64),ratio);value=self.kv.fp8_qdq(value)[0];self.windows.setdefault(layer,[]).append(value[0]);window=np.asarray(self.windows[layer][-128:],np.float32);indices=np.arange(len(window),dtype=np.int64);allkv=window
  if ratio:
   compressed,selected=self.shared(layer,x,qr)
   if len(compressed):allkv=np.concatenate((window,compressed));indices=np.concatenate((indices,(selected[0].astype(np.int64)-128+len(window))))
  attended,_=self.att.online_attention(query,allkv,indices,self.const(prefix+'attn_sinks.weight'));inverse=self.kv.rope(attended,np.full(64,self.position,np.int64),ratio,True).reshape(1,8,4096);parts=[]
  for group in range(8):parts.append(bf16(self.linear(prefix+'attn_output_a.weight',inverse[:,group],True,first=group*1024,count=1024)))
  joined=np.concatenate(parts,axis=1);out=bf16(self.linear(prefix+'attn_output_b.weight',joined,True));self.emit('attention_q_rotated',query);self.emit('attention_window',window);self.emit('attention_output',out);return out
 def moe(self,layer,x):
  p=f'blk.{layer}.';logits=self.linear(p+'ffn_gate_inp.weight',x);ids,weights,_,_=self.ffn.router_scores(logits,self.const(p+'exp_probs_b.bias'));self.emit('ffn_router_logits',logits);self.emit('ffn_router_ids',ids);self.emit('ffn_router_weights',weights);acc=np.zeros((1,5120),np.float32)
  for expert in sorted(ids[0].tolist()):
   up=bf16(self.linear(p+'ffn_up_exps.weight',x,True,matrix=expert));g=bf16(self.linear(p+'ffn_gate_exps.weight',x,True,matrix=expert));route=weights[:,ids[0].tolist().index(expert):ids[0].tolist().index(expert)+1];hidden=self.ffn.swiglu(g,up,route)[0];down=bf16(self.linear(p+'ffn_down_exps.weight',hidden,True,matrix=expert));acc=np.add(acc,down,dtype=np.float32);self.emit('ffn_expert_'+str(expert),down)
  up=bf16(self.linear(p+'ffn_up_shexp.weight',x,True));g=bf16(self.linear(p+'ffn_gate_shexp.weight',x,True));hidden=self.ffn.swiglu(g,up)[0];shared=bf16(self.linear(p+'ffn_down_shexp.weight',hidden,True));out=bf16(np.add(acc,shared,dtype=np.float32));self.emit('ffn_output',out);return out
 def step(self,first,end,token,position,h,pre):
  if position!=self.position or not 0<=first<end<=40 or np.asarray(h).shape!=(1,4,5120) or np.asarray(pre).shape!=(1,4):raise ValueError('independent boundary/range/position')
  if self.range is not None and self.range!=(first,end):raise ValueError('independent state range changed')
  self.range=(first,end)
  self.history.append(token);current=np.asarray(h,np.float32).copy();incoming=np.asarray(pre,np.float32).copy();frames=[]
  for layer in range(first,end):
   self.stages={};p=f'blk.{layer}.'
   if layer in [1,14]:current=self.engram(layer,current)
   am=self.mixes(p+'hc_attn_',current);collapsed=self.mhc.hc_pre(current,incoming);x=self.mhc.rms_norm(collapsed,self.const(p+'attn_norm.weight'));self.emit('block_attention_input',x);att=self.attention(layer,x);after=self.mhc.hc_post(att,current,am['post'],am['comb']);self.emit('block_after_attention',after.reshape(1,20480));fm=self.mixes(p+'hc_ffn_',after);collapsed=self.mhc.hc_pre(after,am['pre']);x=self.mhc.rms_norm(collapsed,self.const(p+'ffn_norm.weight'));self.emit('block_ffn_input',x);moe=self.moe(layer,x);current=self.mhc.hc_post(moe,after,fm['post'],fm['comb']);incoming=fm['pre'];self.emit('block_output',current.reshape(1,20480));self.emit('block_next_pre',incoming);frames.append(dict(layer=layer,position=position,stages=self.stages))
  self.position+=1;return current,incoming,frames
