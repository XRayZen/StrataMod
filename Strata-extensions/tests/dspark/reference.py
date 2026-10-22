"""Independent host N/Q contracts, not a DSpark inference executor."""
from decimal import Decimal,localcontext
import math
import numpy as np

def require(ok,message):
 if not ok:raise ValueError(message)
def effective(logits,temperature=1.,top_k=0,top_p=1.,min_p=0.,history=(),repetition=1.,frequency=0.,presence=0.,bias=None):
 require(bool(logits) and all(math.isfinite(float(x)) for x in logits),'finite logits');require(type(top_k)is int and top_k>=0,'top_k type');require(type(temperature)is not bool and math.isfinite(temperature) and temperature>=0,'temperature');require(all(type(x)is not bool and math.isfinite(x) for x in (top_p,min_p,repetition,frequency,presence)) and 0<top_p<=1 and 0<=min_p<=1 and repetition>0,'sampling options')
 x=list(map(float,logits));n=len(x)
 for token in set(history):
  require(type(token)is int and 0<=token<n,'original history ID');x[token]=x[token]/repetition if x[token]>=0 else x[token]*repetition;x[token]-=frequency*history.count(token)+presence
 for token,value in (bias or {}).items():require(type(token)is int and 0<=token<n and math.isfinite(value),'bias');x[token]+=value
 order=sorted(range(n),key=lambda i:(-x[i],i));result=[0.]*n
 if temperature==0:result[order[0]]=1.;return result
 if top_k:order=order[:top_k]
 maximum=x[order[0]]/temperature;weights=[math.exp(x[i]/temperature-maximum) for i in order];kept=[(i,w) for i,w in zip(order,weights) if w>=min_p*weights[0]];mass=math.fsum(w for i,w in kept);prefix=[];cumulative=0.
 for i,w in kept:
  prefix.append((i,w));cumulative+=w
  if cumulative>=top_p*mass:break
 mass=math.fsum(w for i,w in prefix)
 for i,w in prefix:result[i]=w/mass
 return result

def probabilities(value):
 require(bool(value) and all(type(x)is not bool and math.isfinite(x) and x>=0 for x in value) and math.isclose(math.fsum(value),1.,rel_tol=0,abs_tol=1e-12),'normalized effective distribution')
def acceptance(p,q,d):
 probabilities(p);probabilities(q);require(len(p)==len(q) and type(d)is int and 0<=d<len(p) and q[d]>0,'actual selected proposal support');return min(1.,p[d]/q[d])
def residual(p,q):
 probabilities(p);probabilities(q);require(len(p)==len(q),'p/q vocabulary');r=[max(0.,a-b) for a,b in zip(p,q)];mass=math.fsum(r);require(mass>0,'zero residual cannot follow a valid rejection');return [x/mass for x in r]
def confidence_parts(hidden,markov,weights,temperature=1.):
 require(len(hidden)==5120 and len(markov)==256 and len(weights)==5376,'confidence concat geometry');require(math.isfinite(temperature) and temperature>0,'explicit confidence temperature');values=list(hidden)+list(markov)
 with localcontext() as c:
  c.prec=80;n=sum((Decimal.from_float(float(a))*Decimal.from_float(float(b)) for a,b in zip(values,weights)),Decimal(0))
 q=np.float32(0)
 for a,b in zip(values,weights):q=np.float32(q+np.float32(np.float32(a)*np.float32(b)))
 scaled=min(60.,max(-60.,float(q)/temperature));return dict(N=str(n),ordered_Q=float(q),rate=1/(1+math.exp(-scaled)))
def f16_bits(codes):
 return np.asarray(codes,dtype='<u2').view('<f2').astype('<f4').view('<u4').astype('uint32').tolist()
def tap_mean(hc):
 require(np.shape(hc)==(4,5120),'target HC mean geometry');total=np.zeros(5120,np.float32)
 for h in hc:total=np.add(total,np.asarray(h,np.float32),dtype=np.float32)
 value=np.multiply(total,np.float32(.25),dtype=np.float32);bits=value.view(np.uint32);return ((bits+np.uint32(0x7fff)+((bits>>16)&1))>>16).astype('<u2')
def contract_fixture():
 h=[0.]*5120;m=[0.]*256;w=[0.]*5376;h[0]=2;h[-1]=-1;m[0]=.5;m[-1]=-4;w[0]=1;w[5119]=3;w[5120]=4;w[-1]=-2
 codes=[0,32768,1,1023,1024,15360,48128,31743,64511]
 p=[.5,.25,.125,.125];q=[.25,.25,.25,.25]
 return dict(F16_codes=codes,F16_expected_bits=f16_bits(codes),confidence=confidence_parts(h,m,w),P=p,Q=q,accept=[acceptance(p,q,i) for i in range(4)],residual=residual(p,q),effective_topk=effective([0.,1.,2.],top_k=1),full_model_LP_distribution=effective([0.,1.,2.]),greedy=effective([1.,1.,0.],temperature=0))

def verified_trace(ids,accepted,replacement=37,bonus=1024,cancelled=False,future_confidence=()):
 # Deliberately never inspect future_confidence. This is a host causality
 # contract, not an inference/verification implementation.
 require(len(ids)==len(accepted) and all(type(x)is int and 0<=x<129280 for x in list(ids)+[replacement,bonus]),'verification IDs')
 require(all(type(x)is bool for x in accepted),'verification decisions')
 if cancelled:return []
 output=[]
 for token,ok in zip(ids,accepted):
  output.append(token if ok else replacement)
  if not ok or output[-1]==1:return output
 return output+[bonus]

def rng_counters(proposals,verified,rejected=False,bonus=False):
 require(all(type(x)is int and x>=0 for x in (proposals,verified)) and verified<=proposals,'RNG counters')
 # Namespace consumption is recorded, not a fabricated implementation of the
 # request-owned T28 PRNG. The ordinary target namespace is never advanced.
 return dict(target=0,proposal=proposals,accept=verified,residual=int(rejected),bonus=int(bonus))
