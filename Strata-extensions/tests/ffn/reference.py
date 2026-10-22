"""Independent T11 N/Q oracle; never reads candidate G output."""
import unittest

import numpy as np
import importlib.util
from pathlib import Path
from decimal import Decimal, localcontext
import struct
import json
import copy

def bf16_codes(values):
    x=np.asarray(values,dtype=np.float32)
    if not np.isfinite(x).all():raise ValueError('nonfinite BF16 source')
    bits=x.view(np.uint32)
    return ((bits+np.uint32(0x7fff)+((bits>>16)&1))>>16).astype(np.uint16)
def bf16(values):return (bf16_codes(values).astype(np.uint32)<<16).view(np.float32)
def fp8_table():
    codes=np.arange(127,dtype=np.uint8);exponents=(codes>>3).astype(np.int32);fraction=(codes&7).astype(np.float64)
    return np.where(exponents==0,fraction/512,np.ldexp(1+fraction/8,exponents-7))
FP8=fp8_table()
def fp8_codes(values):
    x=np.asarray(values,np.float32)
    if not np.isfinite(x).all():raise ValueError('nonfinite FP8 source')
    magnitude=np.minimum(np.abs(x.astype(np.float64)),448.)
    high=np.minimum(np.searchsorted(FP8,magnitude,side='left'),126);low=np.maximum(high-1,0)
    dh=FP8[high]-magnitude;dl=magnitude-FP8[low]
    code=np.where((dh<dl)|((dh==dl)&((high&1)==0)),high,low).astype(np.uint8)
    return code|(np.signbit(x).astype(np.uint8)<<7)
def act_qdq(values):
    x=bf16(values)
    if x.ndim!=2 or not x.shape[1] or x.shape[1]%32:raise ValueError('act block geometry')
    blocks=x.reshape(len(x),-1,32);amax=np.maximum(np.max(np.abs(blocks),axis=2),np.float32(1e-4))
    normalized_max=np.multiply(amax,np.float32(1/448),dtype=np.float32)
    bits=normalized_max.view(np.uint32);exponent=((bits>>23)&255).astype(np.int32)-127+((bits&0x7fffff)!=0)
    scale=np.ldexp(np.ones(exponent.shape,np.float32),exponent).astype(np.float32)
    scales=(exponent+127).astype(np.uint8)
    normalized=np.clip(np.divide(blocks,scale[:,:,None],dtype=np.float32),-448,448)
    codes=fp8_codes(normalized)
    decoded=FP8[(codes&127)].astype(np.float32);decoded=np.where((codes&128)!=0,-decoded,decoded)
    result=np.multiply(decoded,scale[:,:,None],dtype=np.float32).reshape(x.shape)
    return result,scales,codes.reshape(x.shape)
def router_scores(logits,bias,topk=6):
    x=np.asarray(logits,np.float32);b=np.asarray(bias,np.float32)
    if x.ndim!=2 or x.shape[1]<topk or type(topk) is not int or topk!=6 or not np.isfinite(x).all() or not np.isfinite(b).all():raise ValueError('router geometry/nonfinite')
    if b.shape not in ((x.shape[1],),x.shape):raise ValueError('bias geometry')
    softplus=np.where(x>20,x.astype(np.float64),np.log1p(np.exp(np.minimum(x,20).astype(np.float64)))).astype(np.float32)
    scores=np.sqrt(softplus,dtype=np.float32);corrected=np.add(scores,b,dtype=np.float32)
    # Canonical synthetic tie order only. Contract permits any declared boundary
    # tie subset, never assumes this is torch.topk's implementation order.
    ids=np.argsort(-corrected,axis=1,kind='stable')[:,:topk].astype(np.uint32)
    selected=np.take_along_axis(scores,ids.astype(np.int64),axis=1)
    denominator=np.zeros((len(x),1),np.float32)
    for i in range(topk):denominator=np.add(denominator,selected[:,i:i+1],dtype=np.float32)
    denominator=np.add(denominator,np.float32(1e-20),dtype=np.float32)
    weights=np.multiply(np.divide(selected,denominator,dtype=np.float32),np.float32(1.5),dtype=np.float32)
    return ids,weights,scores,corrected

def swiglu(gate,up,route=None):
    g=np.minimum(np.asarray(gate,np.float32),np.float32(10));u=np.clip(np.asarray(up,np.float32),-10,10)
    silu=(g.astype(np.float64)/(1+np.exp(-g.astype(np.float64)))).astype(np.float32)
    hidden=np.multiply(silu,u,dtype=np.float32)
    if route is not None:hidden=np.multiply(hidden,np.asarray(route,np.float32),dtype=np.float32)
    return bf16(hidden),g,u,silu

def fixed_inputs():
    # Exactly two deterministic BF16 vectors: A discovery, B predeclared holdout.
    i=np.arange(5120,dtype=np.int64)
    return bf16(np.stack([((i*17+11)%257-128)/256,((i*29+73)%251-125)/128]).astype(np.float32))

def native_q():
    path=Path(__file__).resolve().parents[1]/'quant/q_reference.py';spec=importlib.util.spec_from_file_location('t11_independent_t09_q',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def decimal_n_literals():
    # Independent high precision formula traces, never calls the candidate
    # Q scalar functions above, native reader, HIP, or any G output.
    def f32_bits(value):return struct.pack('<f',float(value)).hex()
    rows=[]
    with localcontext() as ctx:
        ctx.prec=100
        for source in ('-20','-10','-1','0','1','10','20','21'):
            z=Decimal(source);sp=z if z>20 else (Decimal(1)+z.exp()).ln()
            sp32=Decimal.from_float(struct.unpack('<f',bytes.fromhex(f32_bits(sp)))[0])
            score=sp32.sqrt();g=min(z,Decimal(10));u=max(min(z,Decimal(10)),Decimal(-10));silu=g/(1+(-g).exp())
            rows.append(dict(source=source,softplus_fp32_le=f32_bits(sp),sqrtsoftplus_fp32_le=f32_bits(score),clamp_gate_fp32_le=f32_bits(g),clamp_up_fp32_le=f32_bits(u),silu_fp32_le=f32_bits(silu)))
    return rows

def matrix_provider(receipt):
    entries={(r['tensor'],r['index']):r for r in receipt['fixtures']};q=native_q()
    def get(role,expert=None):
        if role in ('router','bias','bias_vl'):
            name={'router':'ffn_gate_inp.weight','bias':'exp_probs_b.bias','bias_vl':'exp_probs_b_vl.bias'}[role];name='blk.0.'+name;index=None
        elif role.startswith('shared_'):name='blk.0.ffn_'+role[7:]+'_shexp.weight';index=None
        else:name='blk.0.ffn_'+role+'_exps.weight';index=expert
        r=entries[(name,index)];raw=Path(r['fixture_path']).read_bytes();decoded=q.decode(r['type_id'],raw)
        dims=r['dims_ggml'];shape=(dims[1],dims[0]) if len(dims)>1 else (dims[0],)
        return decoded.reshape(shape),r
    return get

def expected_row(input_index,image_bias,receipt):
    provider=matrix_provider(receipt);q=native_q();trace={};x=fixed_inputs()[input_index:input_index+1]
    router_w,_=provider('router');logits=q.ordered(router_w,x);bias,_=provider('bias_vl' if image_bias else 'bias')
    ids,weights,scores,corrected=router_scores(logits,bias)
    trace.update(input=x,logits=logits,scores=scores,corrected=corrected,ids=ids,weights=weights)
    def linear(name,role,expert,values):
        quantized,scale,codes=act_qdq(values);w,r=provider(role,expert);out=q.ordered(w,quantized)
        trace[name+'_codes']=codes;trace[name+'_scales']=scale;trace[name+'_qdq']=quantized;trace[name+'_dot']=out;result=bf16(out);trace[name+'_out']=result
        return result
    accumulated=np.zeros((1,5120),np.float32)
    for expert in sorted(ids[0].tolist()):
        prefix='e'+str(expert);gate=linear(prefix+'_gate','gate',expert,x);up=linear(prefix+'_up','up',expert,x)
        position=ids[0].tolist().index(expert);route=weights[:,position:position+1]
        hidden,g,u,silu=swiglu(gate,up,route);trace[prefix+'_clamp_gate']=g;trace[prefix+'_clamp_up']=u;trace[prefix+'_silu']=silu;trace[prefix+'_hidden']=hidden
        down=linear(prefix+'_down','down',expert,hidden);accumulated=np.add(accumulated,down,dtype=np.float32);trace[prefix+'_combine']=accumulated.copy()
    gate=linear('shared_gate','shared_gate',None,x);up=linear('shared_up','shared_up',None,x)
    hidden,g,u,silu=swiglu(gate,up);trace['shared_clamp_gate']=g;trace['shared_clamp_up']=u;trace['shared_silu']=silu;trace['shared_hidden']=hidden
    shared=linear('shared_down','shared_down',None,hidden);trace['routed']=accumulated;trace['combine']=np.add(accumulated,shared,dtype=np.float32);trace['output']=bf16(trace['combine'])
    return trace

def assemble_batch(rows,masks,cache):
    selected=[cache[(row,mask)] for row,mask in zip(rows,masks,strict=True)];out={}
    names=set().union(*(x.keys() for x in selected))
    for name in sorted(names):
        if name.startswith('e') and '_' in name:
            indices=[i for i,x in enumerate(selected) if name in x]
            out[name]=np.concatenate([selected[i][name] for i in indices],axis=0)
        else:out[name]=np.concatenate([x[name] for x in selected],axis=0)
    for expert in sorted(set(e for x in selected for e in x['ids'][0].tolist())):
        out['e'+str(expert)+'_tokens']=np.array([i for i,x in enumerate(selected) if expert in x['ids'][0]],dtype=np.uint32).reshape(-1,1)
    # A row's intermediate combine occurs only when that row uses the expert.
    # Expose the canonical routed result; per-expert combine traces above remain
    # grouped by the same tokens as every matrix primitive.
    return out

class ReferenceTests(unittest.TestCase):
    def test_local_receipt_provenance_mutations(self):
        path=Path(__file__).with_name('acquire_fixtures.py');spec=importlib.util.spec_from_file_location('t11_extract_test',path);a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
        if not a.RECEIPT.exists():self.skipTest('local fixture stage not yet run')
        receipt=json.loads(a.RECEIPT.read_text())
        for field,value in [('type_id',8),('absolute_offset',1),('index',False),('dims_ggml',[5120.0,384]),('fixture_sha256','0'*64)]:
            wrong=copy.deepcopy(receipt);wrong['fixtures'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):a.verify_receipt(wrong,receipt['selected_experts'])
        wrong=copy.deepcopy(receipt);wrong['fixtures'][0]['source']['file_identity']['file_id']=float(wrong['fixtures'][0]['source']['file_identity']['file_id'])
        with self.assertRaises(ValueError):a.verify_receipt(wrong,receipt['selected_experts'])
        wrong=copy.deepcopy(receipt);wrong['fixtures']=[];wrong['total_fixture_bytes']=0
        with self.assertRaises(ValueError):a.verify_receipt(wrong,receipt['selected_experts'])

    def test_bf16_ties_and_signed_zero(self):
        values=[1.,1.00390625,1.01171875,-0.]
        self.assertEqual(bf16_codes(values).tolist(),[0x3f80,0x3f80,0x3f82,0x8000])
    def test_fp8_ties_and_saturation(self):
        self.assertEqual(fp8_codes([0.,2.**-10,3*2.**-10,448.,-448.]).tolist(),[0,0,2,126,254])
    def test_zero_activation_scale_is_not_unknown(self):
        _,scales,codes=act_qdq([[0.]*32]);self.assertEqual(scales.tolist(),[[105]]);self.assertEqual(codes.tolist(),[[0]*32])
    def test_shape_and_nonfinite(self):
        for value in [[[0.]*31],[[float('nan')]*32]]:
            with self.assertRaises(ValueError):act_qdq(value)
    def test_unbiased_router_weights(self):
        score=[[0.,0.,0.,0.,0.,0.,0.,0.]];bias=[0.,0.,1.,2.,3.,4.,5.,6.]
        ids,weights,_,_=router_scores(score,bias,6)
        self.assertEqual(ids.tolist(),[[7,6,5,4,3,2]])
        self.assertEqual(weights.view(np.uint32).tolist(),[[0x3e7fffff]*6]) # independent Decimal FP32 sum/div/mul trace

if __name__=='__main__':unittest.main()
