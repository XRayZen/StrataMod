"""Independent T15 canonical N/Q. Never reads candidate G output."""
import unittest
import numpy as np
import importlib.util
from pathlib import Path
def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
_kv=module('t15_fixed_t14_q',Path(__file__).resolve().parents[1]/'kv/reference.py')
_quant=module('t15_independent_native_q',Path(__file__).resolve().parents[1]/'quant/q_reference.py')
bf16=_kv.bf16
def strict_lens(values,rows,width):
 if len(values)!=rows or any(type(v)is not int or v<0 or v>width for v in values):raise ValueError('visible positions')
 return values
def candidate_blocks(scores,visible,top_blocks=2048,block_size=8):
 x=np.asarray(scores,np.float32)
 if x.ndim!=2 or not np.isfinite(x).all() or type(top_blocks)is not int or top_blocks<1 or type(block_size)is not int or block_size<1:raise ValueError('candidate geometry')
 strict_lens(visible,len(x),x.shape[1]);out=np.zeros(x.shape,bool);blocks=(x.shape[1]+block_size-1)//block_size
 for r,count in enumerate(visible):
  value=np.full(blocks,-np.inf,np.float32)
  for b in range(blocks):
   start=b*block_size;end=min(start+block_size,count)
   if start<end:value[b]=np.max(x[r,start:end])
  if count:value[(count-1)//block_size]=np.inf
  chosen=sorted(range(blocks),key=lambda b:(-float(value[b]),b))[:min(top_blocks,blocks)]
  for b in chosen:
   if value[b]>-np.inf:out[r,b*block_size:min((b+1)*block_size,x.shape[1])]=True
 return out
def top_positions(scores,candidates,visible,offset,topk=512):
 x=np.asarray(scores,np.float32);mask=np.asarray(candidates)
 if x.ndim!=2 or mask.shape!=x.shape or mask.dtype!=np.bool_ or not np.isfinite(x).all()or type(offset)is not int or offset<0 or type(topk)is not int or topk<1:raise ValueError('top positions geometry')
 strict_lens(visible,len(x),x.shape[1]);out=np.full((len(x),min(topk,x.shape[1])),-1,np.int32)
 for r,count in enumerate(visible):
  available=[i for i in range(count)if mask[r,i]];chosen=sorted(available,key=lambda i:(-float(x[r,i]),i))[:out.shape[1]];chosen.sort()
  if chosen and chosen[-1]+offset>np.iinfo(np.int32).max:raise ValueError('position offset overflow')
  out[r,:len(chosen)]=np.array(chosen,np.int32)+offset
 return out
def validate_selection(observed,scores,candidates,visible,offset,topk=512):
 x=np.asarray(scores,np.float32);mask=np.asarray(candidates);canonical=top_positions(x,mask,visible,offset,topk)
 if not isinstance(observed,list)or len(observed)!=len(x):raise ValueError('selection rows')
 for r,row in enumerate(observed):
  if not isinstance(row,list)or len(row)!=canonical.shape[1]or any(type(v)is not int for v in row):raise ValueError('strict positions')
  ids=[v-offset for v in row if v!=-1];count=len(ids);expected_count=int(np.count_nonzero(canonical[r]!=-1))
  if count!=expected_count or ids!=sorted(set(ids))or any(i<0 or i>=visible[r]or not mask[r,i]for i in ids)or row[count:]!=[-1]*(len(row)-count):raise ValueError('candidate/order/count')
  if count:
   eligible=[i for i in range(visible[r])if mask[r,i]];boundary=sorted((float(x[r,i])for i in eligible),reverse=True)[count-1];mandatory={i for i in eligible if x[r,i]>boundary}
   if not mandatory.issubset(ids)or any(x[r,i]<boundary for i in ids):raise ValueError('mandatory/allowed rounded tie set')
def fp4_index_qdq(x):
 x=bf16(x)
 if x.ndim!=2 or x.shape[1]%32:raise ValueError('index FP4 block32')
 blocks=x.reshape(len(x),-1,32);amax=np.maximum(np.max(np.abs(blocks),axis=2),np.float32(6*2**-126));p=np.multiply(amax,np.float32(1/6),dtype=np.float32);u=p.view(np.uint32);exponent=((u>>23)&255).astype(np.int32)-127+((u&0x7fffff)!=0);scale=np.ldexp(np.ones(exponent.shape,np.float32),exponent).astype(np.float32);codes=_kv.fp4_codes(np.clip(np.divide(blocks,scale[:,:,None],dtype=np.float32),-6,6));decoded=np.multiply(_kv.narrow_decode(codes,_kv.FP4,8),scale[:,:,None],dtype=np.float32)
 return bf16(decoded.reshape(x.shape)),(exponent+127).astype(np.uint8),codes.reshape(x.shape)
def norm_features(x,weight):
 x=np.asarray(x,np.float32);w=np.asarray(weight,np.float32)
 if x.ndim!=2 or x.shape[1]!=len(w)or not len(w)or not np.isfinite(x).all()or not np.isfinite(w).all():raise ValueError('RMS feature geometry')
 squares=np.multiply(x,x,dtype=np.float32);mean=np.divide(_kv.ordered_sum(squares,1),np.float32(len(w)),dtype=np.float32);inv=np.divide(np.float32(1),np.sqrt(np.add(mean,np.float32(1e-20),dtype=np.float32),dtype=np.float32),dtype=np.float32)
 return bf16(np.multiply(np.multiply(x,inv[:,None],dtype=np.float32),w,dtype=np.float32)),inv.reshape(-1,1)
def index_scores(q,keys,weights):
 return index_trace(q,keys,weights)['score']
def index_trace(q,keys,weights):
 q=bf16(q);keys=bf16(keys);weights=bf16(weights)
 if q.ndim!=3 or q.shape[1:]!=(32,128)or keys.ndim!=2 or keys.shape[1]!=128 or weights.shape!=q.shape[:2]:raise ValueError('index native shape')
 raw=_quant.ordered(keys,q.reshape(-1,128)).reshape(q.shape[0],32,len(keys));dot=bf16(raw);relu=np.maximum(dot,np.float32(0));weighted=bf16(np.multiply(relu,weights[:,:,None],dtype=np.float32));reduced=_kv.ordered_sum(weighted,1);return dict(dot=raw,dot_bf16=dot,relu=relu,weighted=weighted,reduced=reduced,score=bf16(reduced))
def online_attention(q,kv,indices,sinks):
 q=bf16(q);kv=bf16(kv);indices=np.asarray(indices);sinks=np.asarray(sinks,np.float32)
 if q.ndim!=2 or q.shape[1]!=512 or kv.ndim!=2 or kv.shape[1]!=512 or sinks.shape!=(len(q),)or not np.isfinite(sinks).all()or indices.ndim!=1 or indices.dtype not in (np.dtype('int32'),np.dtype('int64'))or np.any(indices<-1)or np.any(indices>=len(kv)):raise ValueError('attention geometry/indices')
 maximum=np.full(len(q),-1e30,np.float32);den=np.zeros(len(q),np.float32);acc=np.zeros(q.shape,np.float32);trace={};scale=np.float32(512**-.5)
 for start in range(0,len(indices),64):
  ids=np.full(64,-1,np.int64);part=indices[start:start+64];ids[:len(part)]=part;k=np.zeros((64,512),np.float32);valid=ids>=0;k[valid]=kv[ids[valid]];score=np.multiply(_quant.ordered(k,q),scale,dtype=np.float32);score[:,~valid]=-np.inf;newmax=np.maximum(maximum,np.max(score,axis=1));alpha=np.exp(np.subtract(maximum,newmax,dtype=np.float32).astype(np.float64)).astype(np.float32);prob=np.exp(np.subtract(score,newmax[:,None],dtype=np.float32).astype(np.float64)).astype(np.float32);den=np.add(np.multiply(den,alpha,dtype=np.float32),_kv.ordered_sum(prob,1),dtype=np.float32);cast=bf16(prob);acc=np.multiply(acc,alpha[:,None],dtype=np.float32)
  for j in range(64):acc=np.add(acc,np.multiply(cast[:,j,None],k[j],dtype=np.float32),dtype=np.float32)
  maximum=newmax;prefix='block'+str(start//64)+'_';trace[prefix+'score']=score;trace[prefix+'max']=maximum.copy();trace[prefix+'alpha']=alpha;trace[prefix+'prob']=prob;trace[prefix+'prob_bf16']=cast;trace[prefix+'sum']=den.copy();trace[prefix+'acc']=acc.copy()
 with np.errstate(over='ignore'):sink=np.exp(np.subtract(sinks,maximum,dtype=np.float32).astype(np.float64)).astype(np.float32)
 den=np.add(den,sink,dtype=np.float32);out=bf16(np.divide(acc,den[:,None],dtype=np.float32));trace['denominator']=den;return out,trace
def rotary(x,positions,inverse=False):
 x=bf16(x)
 if x.ndim!=2 or x.shape[1]not in (128,512):raise ValueError('attention/index rotary geometry')
 if x.shape[1]==512:return _kv.rope(x,np.asarray(positions,np.int64),2,inverse)
 padded=np.zeros((len(x),512),np.float32);padded[:,-128:]=x
 return _kv.rope(padded,np.asarray(positions,np.int64),2,inverse)[:,-128:].copy()
def learned_weights(receipt):
 out={}
 for row in receipt['fixtures']:
  raw=Path(row['fixture_path']).read_bytes();v=_quant.decode(row['type_id'],raw);dims=row['dims_ggml'];out[row['tensor']]=v.reshape(dims[1],dims[0])if len(dims)==2 else v
 return out
def projection(weights,name,x,activation=True):
 x=bf16(x);trace=dict(input=x)
 if activation:
  y,scales,codes=_kv.fp8_qdq(x);trace.update(input_qdq=y,input_scales=scales,input_codes=codes)
 else:y=x
 dot=_quant.ordered(weights[name],y);trace.update(dot=dot,output=bf16(dot));return trace
def prepared_projection(weights):
 # Eight distinct BF16 inputs, four A plus four holdout B. Future sequence
 # fixtures explicitly declare periodic reuse rather than new weight evidence.
 x=_kv.fixed_inputs();out={}
 for layer in (2,20,24):
  prefix=f'blk.{layer}.';stages={};qa=projection(weights,prefix+'attn_q_a.weight',x)
  for key,v in qa.items():stages['qa_'+key]=v
  qr,inv=norm_features(qa['output'],weights[prefix+'attn_q_a_norm.weight']);stages.update(qr=qr,qr_inv=inv)
  iq=projection(weights,prefix+'indexer.attn_q_b.weight',qr)
  for key,v in iq.items():stages['index_q_'+key]=v
  w=projection(weights,prefix+'indexer.proj.weight',x,False)
  for key,v in w.items():stages['index_weight_'+key]=v
  stages['index_weight_scaled']=bf16(np.multiply(w['output'],np.float32(1/64),dtype=np.float32))
  if layer in (2,20):
   q=projection(weights,prefix+'attn_q_b.weight',qr)
   for key,v in q.items():stages['q_'+key]=v
   kv=projection(weights,prefix+'attn_kv.weight',x)
   for key,v in kv.items():stages['kv_'+key]=v
   norm,inv=norm_features(kv['output'],weights[prefix+'attn_kv_a_norm.weight']);stages.update(kv_norm=norm,kv_inv=inv)
  out[layer]=stages
 return out
def owner_context(weights,t14projected,writer,length,phase):
 if writer not in (2,20):raise ValueError('declared owner')
 base=_kv.temporal_projection(t14projected,length,phase);latent=base[f's{writer}_pre_rope'];ratio=2 if writer==2 else 1;stages={}
 trace=projection(weights,f'blk.{writer}.indexer.attn_k.weight',latent,False)if len(latent)else {k:np.empty((0,128 if k in ('dot','output')else 512),np.float32)for k in ('input','dot','output')}
 for key,v in trace.items():stages['key_'+key]=v
 norm,inv=norm_features(trace['output'],weights[f'blk.{writer}.indexer.k_norm.weight']);pos=np.arange(len(norm))*ratio;rot=rotary(norm,pos);decoded,scales,codes=fp4_index_qdq(rot)if len(rot)else(np.empty((0,128),np.float32),np.empty((0,4),np.uint8),np.empty((0,128),np.uint8));stages.update(key_norm=norm,key_inv=inv,key_rotated=rot,key_decoded=decoded,key_scales=scales,key_codes=codes)
 return dict(stages=stages,keys=decoded,compressed=base[f's{writer}_decoded'],latent=latent,ratio=ratio,writer=writer)
def index_context(prepared,layer,owner,length,phase,offset,candidates=None):
 ids=(np.arange(length)+phase)%8;row=prepared[layer];stages={};q=row['index_q_output'][ids].reshape(length,32,128);pos=np.repeat(np.arange(length),32);rot=rotary(q.reshape(-1,128),pos).reshape(q.shape);deq,scale,codes=fp4_index_qdq(rot.reshape(-1,128));deq=deq.reshape(q.shape);stages.update(query_rotated=rot.reshape(length,-1),query_decoded=deq.reshape(length,-1),query_codes=codes.reshape(length,-1),query_scales=scale.reshape(length,-1));weights=row['index_weight_scaled'][ids];stages['query_weights']=weights
 if len(owner['keys']):
  trace=index_trace(deq,owner['keys'],weights)
  for key,value in trace.items():stages['score_'+key]=value.reshape(length,-1)
  score=trace['score'];visible=[int((p+1)//owner['ratio'])for p in range(length)]
  mask=candidate_blocks(score,visible)if layer==20 else np.ones(score.shape,bool)if candidates is None else candidates
  selected=top_positions(score,mask,visible,offset);stages.update(candidate_mask=mask.astype(np.uint8),selected=selected)
 else:
  score=np.empty((length,0),np.float32);mask=np.empty((length,0),bool);selected=np.empty((length,0),np.int32);stages.update(score_score=score,candidate_mask=mask.astype(np.uint8),selected=selected)
 return dict(stages=stages,selected=selected,candidates=mask,score=score)
def short_context(weights,prepared,t14projected,length,phase):
 if length<1 or phase not in range(8):raise ValueError('short fixture geometry')
 ids=(np.arange(length)+phase)%8;out={};owners={layer:owner_context(weights,t14projected,layer,length,phase)for layer in (2,20)};candidate20=None
 for layer in (2,20,24):
  p=f'layer{layer}__';owner=owners[2 if layer==2 else 20];index=index_context(prepared,layer,owner,length,phase,length,candidate20 if layer==24 else None)
  for key,value in index['stages'].items():out[p+'index_'+key]=value
  if layer==20:candidate20=index['candidates']
  if layer==24:continue
  for key,value in owner['stages'].items():out[p+key]=value
  row=prepared[layer];prefix=f'blk.{layer}.';query=row['q_output'][ids].reshape(length,64,512);qrot=rotary(query.reshape(-1,512),np.repeat(np.arange(length),64)).reshape(query.shape);window=rotary(row['kv_norm'][ids],np.arange(length));deq,scales,codes=_kv.fp8_qdq(window);out.update({p+'q_rotated':qrot.reshape(length,-1),p+'window_pre_rope':row['kv_norm'][ids],p+'window_post_rope':window,p+'window_decoded':deq,p+'window_codes':codes,p+'window_scales':scales})
  kv=np.concatenate([deq,owner['compressed']],axis=0);idx=np.concatenate([_kv.window_indices(length,0),index['selected']],axis=1);attn=[]
  for position in range(length):
   result,trace=online_attention(qrot[position],kv,idx[position],weights[prefix+'attn_sinks.weight']);attn.append(result)
   for key,value in trace.items():out[p+'attention_p'+str(position)+'_'+key]=value.reshape(len(value),-1)
  attn=np.array(attn,np.float32);out[p+'selected_combined']=idx;out[p+'attention_output']=attn.reshape(length,-1);inverse=rotary(attn.reshape(-1,512),np.repeat(np.arange(length),64),True).reshape(length,8,4096);out[p+'attention_inverse']=inverse.reshape(length,-1);inputa,scales,codes=_kv.fp8_qdq(inverse.reshape(-1,4096));inputa=inputa.reshape(length,8,4096);out[p+'outa_input_qdq']=inputa.reshape(length,-1);out[p+'outa_input_codes']=codes.reshape(length,-1);out[p+'outa_input_scales']=scales.reshape(length,-1);wa=weights[prefix+'attn_output_a.weight'].reshape(8,1024,4096);parts=[];dots=[]
  for group in range(8):
   dot=_quant.ordered(wa[group],inputa[:,group]);dots.append(dot);parts.append(bf16(dot))
  outputa=np.stack(parts,axis=1).reshape(length,8192);out[p+'outa_dot']=np.stack(dots,axis=1).reshape(length,8192);out[p+'outa_output']=outputa;ob=projection(weights,prefix+'attn_output_b.weight',outputa)
  for key,value in ob.items():out[p+'outb_'+key]=value
 return out
def decimal_literals():
 # Decimal100 reconstructs mathematical formulas and explicit FP32/BF16
 # rounding without calling the canonical NumPy operators above.
 from decimal import Decimal,localcontext
 import struct
 def f(v):return Decimal.from_float(struct.unpack('<f',struct.pack('<f',float(v)))[0])
 def bits(v):return struct.pack('<f',float(v)).hex()
 def bf(v):
  u=struct.unpack('<I',struct.pack('<f',float(v)))[0];u=(u+0x7fff+((u>>16)&1))&0xffffffff;return Decimal.from_float(struct.unpack('<f',struct.pack('<I',(u>>16)<<16))[0])
 result=dict(index_fp4=dict(zero_scale_code=1,unit_scale_code=127,element_values=['0','.25','.75','1.25','1.75','2.5','3.5','5','-0','-.25'],element_codes=[0,0,2,2,4,4,6,6,8,8]),all_invalid=dict(initial_max=bits(f(Decimal('-1e30'))),denominator_class='+inf',output=bits(f(0))))
 with localcontext()as c:
  c.prec=100;scale=f(1/Decimal(512).sqrt());a=f((-scale).exp());twice=f(scale*2);sink=f((-twice).exp());p=bf(a);den1=f(0)
  for value in [a]*32+[f(1)]*32:den1=f(den1+value)
  first1=f(32);tail1=f(f(Decimal(32)*p)+Decimal(64));den2=f(f(den1*a)+Decimal(1));first2=f(f(first1*a)+Decimal(2));tail2=f(f(tail1*a)+Decimal(3));den=f(den2+sink);result['online2block']=dict(scale=bits(scale),alpha=bits(a),prob_bf16=bits(p),den1=bits(den1),acc1=[bits(first1),bits(tail1)],den2=bits(den2),acc2=[bits(first2),bits(tail2)],sink=bits(sink),denominator=bits(den),output=[bits(bf(f(first2/den))),bits(bf(f(tail2/den)))])
  q=f(Decimal('1.0078125'));product=f(q*q);acc=f(0)
  for _ in range(128):acc=f(acc+product)
  dot=bf(acc);weight=bf(Decimal(1)/64);weighted=bf(f(dot*weight));summed=f(0)
  for _ in range(32):summed=f(summed+weighted)
  result['index_cast']=dict(product=bits(product),dot_f32=bits(acc),dot_bf16=bits(dot),weight_scaled=bits(weight),weighted_bf16=bits(weighted),sum_f32=bits(summed),score_bf16=bits(bf(summed)))
 return result
def controls():
 result={}
 for name,maximum in [('zero',0.),('tiny',2**-133),('unit-ties',6.),('scale-low',6.375),('scale-high',7.125),('large',6*2**100)]:
  x=np.zeros((1,128),np.float32);x[0,:10]=[0,.25,.75,1.25,1.75,2.5,3.5,5,-0.,-.25]if name=='unit-ties'else 0;x[0,10]=maximum;x[0,11]=-0.;deq,scales,codes=fp4_index_qdq(x);result['fp4-'+name]=dict(kind='fp4',inputs=dict(input=x),outputs=dict(decoded=deq,scales=scales,codes=codes))
 for width,name,value in [(1280,'zero',0.),(1280,'tiny',2**-40),(8192,'ties',1.0625)]:
  x=np.full((1,width),value,np.float32);x[0,0]=-0.
  if name=='ties':x[0,1]=448;x[0,2]=1.1875
  y,s,c=_kv.fp8_qdq(x);result[f'fp8-{width}-{name}']=dict(kind='fp8',inputs=dict(input=x),outputs=dict(decoded=y,scales=s,codes=c))
 for width in (128,1280):
  for name,value in [('zero',0.),('tiny',2**-40)]:
   x=np.full((1,width),value,np.float32);w=np.ones(width,np.float32);y,inv=norm_features(x,w);result[f'norm-{width}-{name}']=dict(kind='norm',inputs=dict(input=x,weight=w),outputs=dict(output=y,inv=inv))
 for name,value in [('cast',1.0078125),('negative',-1.)]:
  q=np.full((1,32,128),value,np.float32);key=np.ones((2,128),np.float32)*(1.0078125 if name=='cast'else 1);weight=np.full((1,32),1/64,np.float32);trace=index_trace(q,key,weight);result['index-'+name]=dict(kind='index',inputs=dict(query=q,keys=key,weights=weight),outputs={k:v.reshape(1,-1)for k,v in trace.items()})
 for name in ('two-block','all-invalid','sink-large','asymmetric'):
  q=np.zeros((64,512),np.float32);q[:,0]=1;kv=np.empty((65,512),np.float32);kv[:32]=1;kv[:32,0]=0;kv[32:64]=2;kv[32:64,0]=1;kv[64]=3;kv[64,0]=2;idx=np.arange(65,dtype=np.int32);sink=np.zeros(64,np.float32)
  if name=='all-invalid':idx.fill(-1)
  if name=='sink-large':sink.fill(1000)
  if name=='asymmetric':q[:,0]=bf16(np.arange(1,65,dtype=np.float32)/64);sink=np.arange(64,dtype=np.float32)/16
  y,t=online_attention(q,kv,idx,sink);result['online-'+name]=dict(kind='online',inputs=dict(query=q,keys=kv,indices=idx.reshape(1,-1),sinks=sink),outputs=dict(output=y,**t))
 for width in (128,512):
  positions=np.array([0,1,127,128,129,16383,16384,16385],np.int64);x=bf16(np.tile(np.linspace(-1,1,width,dtype=np.float32),(len(positions),1)));result[f'rope-{width}']=dict(kind='rope',inputs=dict(input=x,positions=positions),outputs=dict(output=rotary(x,positions),inverse=rotary(x,positions,True)))
 for name,visible in [('pin',[16385]),('empty',[0]),('partial',[9]),('tie',[16385]),('near',[16385]),('outside',[16385])]:
  n=16385;score=np.repeat((np.arange(n,dtype=np.float32)//8).reshape(1,-1),len(visible),axis=0);score[:,-1]=-100
  if name in ('tie','near'):
   score.fill(1);score[:,16000:16008]=1+3*2**-9 if name=='near'else 1
  score=bf16(score);source_score=score.copy();mask=candidate_blocks(source_score,visible)
  if name=='outside':score.fill(0);score[:,:8]=1000
  selected=top_positions(score,mask,visible,128);result['select-'+name]=dict(kind='select',visible=visible,offset=128,inputs=dict(source_score=source_score,score=score,visible=np.array(visible,np.int64)),outputs=dict(candidate_mask=mask.astype(np.uint8),selected=selected))
 return result
def long_control(width,variant):
 if width not in (16383,16384,16385)or variant not in (0,1):raise ValueError('declared long control')
 query=np.ones((3,32,128),np.float32);query[:,1::2]=.5 if variant else 1;raw=np.repeat(bf16(.125+(np.arange(width,dtype=np.float32)%4096)/256)[:,None],128,axis=1);raw[-1].fill(-1);qdeq,qs,qc=fp4_index_qdq(query.reshape(-1,128));kd,ks,kc=fp4_index_qdq(raw);weights=np.full((3,32),1/64,np.float32);trace=index_trace(qdeq.reshape(3,32,128),kd,weights);score=trace['score'];visible=[width-2,width-1,width];mask=candidate_blocks(score,visible);selected=top_positions(score,mask,visible,128);window=np.full((128,512),.25,np.float32);compressed=bf16(np.repeat((np.arange(width,dtype=np.float32)%17/32)[:,None],512,axis=1));payload=np.concatenate([window,compressed],axis=0);attention_q=bf16(np.tile(np.linspace(-.5,.5,512,dtype=np.float32),(64,1)));sink=np.arange(64,dtype=np.float32)/32;out=dict(query_decoded=qdeq.reshape(3,-1),query_codes=qc.reshape(3,-1),query_scales=qs.reshape(3,-1),key_decoded=kd,key_codes=kc,key_scales=ks,candidate_mask=mask.astype(np.uint8),selected=selected)
 for key,value in trace.items():out['score_'+key]=value.reshape(3,-1)
 consumer=-query;cd,cs,cc=fp4_index_qdq(consumer.reshape(-1,128));ct=index_trace(cd.reshape(3,32,128),kd,weights);selected24=top_positions(ct['score'],mask,visible,128);out.update(consumer_query_decoded=cd.reshape(3,-1),consumer_query_codes=cc.reshape(3,-1),consumer_query_scales=cs.reshape(3,-1),consumer_selected=selected24)
 for key,value in ct.items():out['consumer_score_'+key]=value.reshape(3,-1)
 window_indices=np.concatenate([_kv.window_indices(1,p-1)for p in visible]);out['window_indices']=window_indices;out['combined_indices']=np.concatenate([window_indices,selected],axis=1);out['consumer_combined_indices']=np.concatenate([window_indices,selected24],axis=1)
 for r,count in enumerate(visible):
  # Three causal tail queries; each physical window has all 128 valid entries.
  indices=out['combined_indices'][r];y,t=online_attention(attention_q,payload,indices,sink);out[f'attention{r}_output']=y
  for key,value in t.items():out[f'attention{r}_'+key]=value
 return dict(inputs=dict(query=query,consumer_query=consumer,keys=raw,weights=weights,visible=np.array(visible,np.int64),attention_query=attention_q,attention_kv=payload,sinks=sink),outputs=out,kind='long',width=width,variant=variant)

class Tests(unittest.TestCase):
 def test_candidate_latest_partial(self):
  scores=np.zeros((1,16385),np.float32);scores[0,:8]=10;mask=candidate_blocks(scores,[16385]);self.assertEqual(int(mask.sum()),16377);self.assertTrue(mask[0,-1]);self.assertTrue(mask[0,:8].all())
 def test_candidate_visibility(self):
  x=np.full((2,17),-7,np.float32);m=candidate_blocks(x,[0,9]);self.assertFalse(m[0].any());self.assertEqual(int(m[1].sum()),16);self.assertEqual(int((m[1]&(np.arange(17)<9)).sum()),9)
 def test_selection_tie_sorted_offset(self):
  score=np.array([[2,2,1,99]],np.float32);mask=np.array([[1,1,1,0]],bool);out=top_positions(score,mask,[3],offset=128,topk=2);self.assertEqual(out.tolist(),[[128,129]]);validate_selection([[128,129]],score,mask,[3],128,2)
  with self.assertRaises(ValueError):validate_selection([[True,129]],score,mask,[3],128,2)
  with self.assertRaises(ValueError):validate_selection([[128,131]],score,mask,[3],128,2)
 def test_index_fp4_floor_signedzero(self):
  x=np.zeros((1,128),np.float32);x[0,0]=-0.;y,s,c=fp4_index_qdq(x);self.assertTrue(np.all(s==1));self.assertEqual(int(c[0,0]),8);self.assertTrue(np.signbit(y[0,0]))
 def test_online_sink(self):
  q=np.zeros((2,512),np.float32);kv=np.full((1,512),2,np.float32);y,trace=online_attention(q,kv,np.array([0],np.int32),np.zeros(2,np.float32));self.assertTrue(np.all(y==1));self.assertTrue(np.all(trace['denominator']==2))
 def test_online_all_invalid(self):
  y,_=online_attention(np.ones((2,512),np.float32),np.ones((1,512),np.float32),np.array([-1]*65,np.int32),np.zeros(2,np.float32));self.assertTrue(np.all(y==0));self.assertTrue(np.isfinite(y).all())
 def test_index_cast_boundary(self):
  q=np.ones((1,32,128),np.float32);k=np.ones((2,128),np.float32);w=np.zeros((1,32),np.float32);w[0,0]=1;score=index_scores(q,k,w);self.assertEqual(score.tolist(),[[128,128]])
 def test_norm_tiny(self):
  x=np.full((1,1280),2**-40,np.float32);y,inv=norm_features(x,np.ones(1280,np.float32));self.assertTrue(np.isfinite(y).all());self.assertGreater(float(inv[0,0]),1e9)
 def test_independent_N_cast(self):
  n=decimal_literals()['index_cast'];q=np.full((1,32,128),1.0078125,np.float32);keys=np.full((1,128),1.0078125,np.float32);weights=np.full((1,32),1/64,np.float32);t=index_trace(q,keys,weights)
  for key,field in [('dot','dot_f32'),('dot_bf16','dot_bf16'),('weighted','weighted_bf16'),('reduced','sum_f32'),('score','score_bf16')]:self.assertEqual(t[key].reshape(-1)[0].tobytes().hex(),n[field])
 def test_independent_N_online(self):
  n=decimal_literals()['online2block'];q=np.zeros((1,512),np.float32);q[0,0]=1;kv=np.empty((65,512),np.float32);kv[:32]=1;kv[:32,0]=0;kv[32:64]=2;kv[32:64,0]=1;kv[64]=3;kv[64,0]=2;y,trace=online_attention(q,kv,np.arange(65,dtype=np.int32),np.zeros(1,np.float32));self.assertEqual(trace['denominator'][0].tobytes().hex(),n['denominator']);self.assertEqual(y[0,0].tobytes().hex(),n['output'][0]);self.assertEqual(y[0,1].tobytes().hex(),n['output'][1]);self.assertEqual(trace['block0_prob_bf16'][0,0].tobytes().hex(),n['prob_bf16'])

if __name__=='__main__':unittest.main()
