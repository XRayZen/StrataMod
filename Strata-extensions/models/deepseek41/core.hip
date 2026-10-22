#include "core.hpp"
#include "../../native/cache/secondary_cache.hpp"
#include "execution/expert_assist.hpp"
#include "engram_forward.hpp"
#include <fstream>
#include <cmath>
#include <cstring>
#include <hip/hip_runtime.h>
#include <algorithm>
#include <limits>
#include <set>
#include <stdexcept>
#include <type_traits>
#include <chrono>
#include <cstdio>
namespace strata_ext::deepseek41 {
namespace {
struct PrefillInterrupted {};
using PrefillDiagnosticClock=std::chrono::steady_clock;
struct ScopedTapClear {
 CoreTapSink*&sink;bool&active;
 ~ScopedTapClear(){sink=nullptr;active=false;}
};
struct ScopedOperationClear {bool&active;~ScopedOperationClear(){active=false;}};
bool tap_identity(const measurement::Identity&a,const measurement::Identity&b){
 return a.request_id==b.request_id&&a.epoch==b.epoch&&a.fixture_sha256==b.fixture_sha256&&a.asset_sha256==b.asset_sha256&&a.bundle_sha256==b.bundle_sha256&&a.phase==b.phase;
}
bool tap_binding_matches(const measurement::Identity&a,const measurement::Identity&b,
 const std::shared_ptr<const uint8_t>&instance,const std::shared_ptr<const uint8_t>&expected,
 int device,int expected_device,uint64_t bound,uint64_t start,uint64_t cursor,uint64_t capacity){
 return instance&&instance==expected&&tap_identity(a,b)&&device==expected_device&&bound==start&&start==cursor&&start<capacity;
}
struct ScopedProgressClear {std::function<void()>&callback;~ScopedProgressClear(){callback=nullptr;}};
void need(bool ok,const char* s){if(!ok)throw std::runtime_error(s);}
uint64_t add(uint64_t a,uint64_t b){need(b<=UINT64_MAX-a,"core byte/coordinate overflow");return a+b;}
uint64_t mul(uint64_t a,uint64_t b){need(!a||b<=UINT64_MAX/a,"core byte/coordinate overflow");return a*b;}
void hipcheck(hipError_t e){if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));}
void swap_request_identity(measurement::Identity&a,measurement::Identity&b) noexcept {
 static_assert(std::is_nothrow_swappable_v<std::string>);
 a.fixture_sha256.swap(b.fixture_sha256);a.asset_sha256.swap(b.asset_sha256);
 a.bundle_sha256.swap(b.bundle_sha256);a.request_id.swap(b.request_id);
 std::swap(a.epoch,b.epoch);std::swap(a.phase,b.phase);
}
}
CoreAttentionRole attention_role(uint32_t layer){need(layer<40,"trunk layer range");if(layer<2)return {};uint32_t kv=layer<8?2:layer<14?8:layer<20?14:20;uint32_t index=layer<24?kv:24+((layer-24)/4)*4;return {layer<20?2u:1u,kv,index};}
CoreIoIssue advance_core_io(cache::PrimarySupply&weight,cache::RowSupply&rows,cache::DemandOrder&order,const CoreIoGrant&grant,cache::Kind weight_kind,int timeout){
 need(weight_kind==cache::Kind::Expert||weight_kind==cache::Kind::Prefetch,"weight demand class");
 need(grant.max_outstanding&&grant.max_outstanding_bytes,"I/O grant declaration");
 weight.poll_io(timeout);rows.poll_io(0);weight.poll_device();rows.poll_device();
 CoreIoIssue result;
 for(auto kind:order.candidates()){
  auto w=weight.io_snapshot();auto r=rows.stats();
  auto outstanding=add(w.outstanding_reads,r.outstanding_reads),bytes=add(w.outstanding_read_bytes,r.outstanding_read_bytes);
  need(outstanding<=grant.max_outstanding&&bytes<=grant.max_outstanding_bytes,"actual I/O exceeds caller credit");
  if(outstanding==grant.max_outstanding||bytes==grant.max_outstanding_bytes)break;
  auto available=grant.max_outstanding_bytes-bytes;uint64_t delta=0,operations=0;
  if(kind==weight_kind){delta=weight.issue_reads(1,available);auto after=weight.io_snapshot();need(after.issued_reads>=w.issued_reads&&after.issued_read>=w.issued_read,"weight counter reset");operations=after.issued_reads-w.issued_reads;need(after.issued_read-w.issued_read==delta,"weight actual requested delta");}
  else if(kind==cache::Kind::Row){delta=rows.issue_reads(1,available);auto after=rows.stats();need(after.issued>=r.issued&&after.issued_requested>=r.issued_requested,"row counter reset");operations=after.issued-r.issued;need(after.issued_requested-r.issued_requested==delta,"row actual requested delta");}
  need(delta<=available&&operations<=1&&((delta==0)==(operations==0)),"owner exceeded actual read grant");
  if(delta){order.issued(kind);result.operations=add(result.operations,operations);result.requested_bytes=add(result.requested_bytes,delta);}
 }
 return result;
}
namespace {
__global__ void select_ffn_rows(const float*x,const float*weights,const uint32_t*pairs,float*selected,float*route,uint64_t count){
 uint64_t i=uint64_t(blockIdx.x)*blockDim.x+threadIdx.x;if(i<count*5120){uint64_t b=i/5120,d=i%5120;selected[i]=x[uint64_t(pairs[2*b])*5120+d];if(d==0)route[b]=weights[uint64_t(pairs[2*b])*6+pairs[2*b+1]];}
}
__global__ void scatter_ffn_rows(float*accum,const float*down,const uint32_t*pairs,uint64_t count){uint64_t i=uint64_t(blockIdx.x)*blockDim.x+threadIdx.x;if(i<count*5120){uint64_t target=uint64_t(pairs[2*(i/5120)])*5120+i%5120;accum[target]=accum[target]+down[i];}}
DeviceView prefix_rows(const DeviceView&v,uint64_t n){need(n&&n<=v.rows,"finite workspace rows");auto out=v;out.rows=n;return out;}
DeviceView wave_row(const DeviceView&v,uint64_t i){validate_device_view(v,v.device);need(i<v.rows,"wave row range");auto out=v;auto bytes=mul(v.columns,scalar_bytes(v.scalar)),offset=mul(i,bytes);need(offset<=v.bytes&&bytes<=v.bytes-offset,"wave row allocation range");out.data=static_cast<uint8_t*>(v.data)+offset;out.bytes=bytes;out.rows=1;return out;}
}
void expert_forward_device(const Artifact&artifact,uint32_t layer,uint32_t expert,const DeviceView&input,const DeviceView&route,const DeviceView&down,ExpertWorkspace&w,const CoreConfig&cfg,void*stream,const DeviceProject&project){
 need(layer<40&&expert<384&&input.columns==5120&&route.columns==1&&down.columns==5120&&input.rows==route.rows&&input.rows==down.rows,"expert original geometry");
 check_device_stream(stream,cfg.device);const auto n=input.rows;
 auto check=[&](const DeviceView&v,uint64_t cols,DeviceScalar scalar){validate_device_view(v,cfg.device);need(v.rows>=n&&v.columns==cols&&v.scalar==scalar,"expert workspace geometry");};
 check(input,5120,DeviceScalar::Bfloat16InFloat32);check(route,1,DeviceScalar::Float32);check(down,5120,DeviceScalar::Bfloat16InFloat32);
 check(w.input_qdq,5120,DeviceScalar::Float32);check(w.gate,2304,DeviceScalar::Bfloat16InFloat32);check(w.up,2304,DeviceScalar::Bfloat16InFloat32);check(w.hidden,2304,DeviceScalar::Bfloat16InFloat32);check(w.down_qdq,2304,DeviceScalar::Float32);check(w.down_dot,5120,DeviceScalar::Float32);
 auto gate=prefix_rows(w.gate,n),up=prefix_rows(w.up,n),hidden=prefix_rows(w.hidden,n),dot=prefix_rows(w.down_dot,n);
 auto linear=[&](const SourceTensor&source,const DeviceView&x,const DeviceView&d,const DeviceView&out){auto qdq=prefix_rows(source.span.dims_ggml[0]==5120?w.input_qdq:w.down_qdq,n);ffn_qdq_device(x,qdq,stream);tiled_projection(source,expert,qdq,d,n,cfg,stream,project);ffn_bf16_device(d,out,stream);};
 auto gate_dot=gate;gate_dot.scalar=DeviceScalar::Float32;auto up_dot=up;up_dot.scalar=DeviceScalar::Float32;
 const auto prefix="blk."+std::to_string(layer)+".";
 linear(artifact.source_tensor(prefix+"ffn_gate_exps.weight"),input,gate_dot,gate);linear(artifact.source_tensor(prefix+"ffn_up_exps.weight"),input,up_dot,up);
 ffn_swiglu_device(gate,up,&route,hidden,stream);linear(artifact.source_tensor(prefix+"ffn_down_exps.weight"),hidden,dot,down);
}
void ffn_forward_device(const Artifact&artifact,uint32_t layer,const DeviceView&input,const DeviceView&mask,const DeviceView&bias,const DeviceView&bias_vl,const DeviceView&output,FfnWorkspace&w,const CoreConfig&cfg,void*stream,const DeviceProject&project,std::vector<uint32_t>*actual_dispatch_ids,const ExpertFrame*frame){
 need(layer<40&&input.columns==5120&&output.columns==5120&&input.rows==output.rows,"FFN layer/input/output");check_device_stream(stream,cfg.device);auto hs=reinterpret_cast<hipStream_t>(stream);auto b=input.rows;
 auto check=[&](const DeviceView&v,uint64_t cols,DeviceScalar scalar){validate_device_view(v,cfg.device);need(v.rows==b&&v.columns==cols&&v.scalar==scalar,"FFN workspace original geometry");};
 check(input,5120,DeviceScalar::Bfloat16InFloat32);check(output,5120,DeviceScalar::Bfloat16InFloat32);
 check(w.input_qdq,5120,DeviceScalar::Float32);check(w.logits,384,DeviceScalar::Float32);check(w.scores,384,DeviceScalar::Float32);check(w.corrected,384,DeviceScalar::Float32);check(w.ids,6,DeviceScalar::UInt32);check(w.weights,6,DeviceScalar::Float32);check(w.accumulated,5120,DeviceScalar::Float32);
 check(w.selected_input,5120,DeviceScalar::Bfloat16InFloat32);check(w.selected_route,1,DeviceScalar::Float32);check(w.selected_pairs,2,DeviceScalar::UInt32);check(w.gate,2304,DeviceScalar::Bfloat16InFloat32);check(w.up,2304,DeviceScalar::Bfloat16InFloat32);check(w.hidden,2304,DeviceScalar::Bfloat16InFloat32);check(w.down_qdq,2304,DeviceScalar::Float32);check(w.down_dot,5120,DeviceScalar::Float32);check(w.down_bf16,5120,DeviceScalar::Bfloat16InFloat32);
 need(!cfg.experts||(frame&&frame->token_positions.size()==b&&cfg.experts->capacity()),"complete expert dispatch frame/capacity");
 const auto prefix="blk."+std::to_string(layer)+".";
 // Router is F32 and has no activation QDQ. Its raw scores, not corrected
 // selection scores, scale the selected experts.
 tiled_projection(artifact.source_tensor(prefix+"ffn_gate_inp.weight"),0,input,w.logits,b,cfg,stream,project);
 if(cfg.routing_decode&&cfg.routing_policy&&cfg.routing_policy->active[layer]){
  auto delta=cfg.routing_delta;delta.data=static_cast<float*>(delta.data)+layer*384;delta.rows=1;delta.columns=384;delta.bytes=384*4;
  ffn_router_biased_device(w.logits,bias,bias_vl,mask,delta,w.scores,w.corrected,w.ids,w.weights,stream);cfg.routing_policy->decode_used=true;
 }else ffn_router_device(w.logits,bias,bias_vl,mask,w.scores,w.corrected,w.ids,w.weights,stream);
 audit_stage(cfg.audit,"ffn_router_logits",w.logits,stream);audit_stage(cfg.audit,"ffn_router_ids",w.ids,stream);audit_stage(cfg.audit,"ffn_router_weights",w.weights,stream);
 std::vector<uint32_t> ids(size_t(mul(b,6)));hipcheck(hipMemcpyAsync(ids.data(),w.ids.data,ids.size()*4,hipMemcpyDeviceToHost,hs));hipcheck(hipStreamSynchronize(hs));
 if(actual_dispatch_ids)*actual_dispatch_ids=ids;
 std::set<uint32_t> experts;for(uint64_t token=0;token<b;++token){std::set<uint32_t> unique;for(unsigned slot=0;slot<6;++slot){auto e=ids[token*6+slot];need(e<384&&unique.insert(e).second,"router ID range/duplicate");experts.insert(e);}}
 hipcheck(hipMemsetAsync(w.accumulated.data,0,mul(mul(b,5120),4),hs));
 auto linear=[&](const SourceTensor&source,uint64_t matrix,const DeviceView&x,const DeviceView&dot,const DeviceView&out){auto qdq=source.span.dims_ggml[0]==5120?prefix_rows(w.input_qdq,x.rows):prefix_rows(w.down_qdq,x.rows);ffn_qdq_device(x,qdq,stream);tiled_projection(source,matrix,qdq,dot,x.rows,cfg,stream,project);ffn_bf16_device(dot,out,stream);};
 // Finite result band; placement never changes canonical ID-order adoption.
 struct Pending {std::vector<uint32_t>pairs;ExpertTicket ticket;};std::vector<Pending>pending;
 auto flush=[&]{
  need(!pending.empty(),"expert pending result");auto&job=pending.front();auto n=job.pairs.size()/2;
  auto down=cfg.experts->collect(job.ticket);validate_device_view(down,cfg.device);need(down.rows==n&&down.columns==5120&&down.scalar==DeviceScalar::Bfloat16InFloat32,"expert returned result geometry");
  hipcheck(hipMemcpyAsync(w.selected_pairs.data,job.pairs.data(),job.pairs.size()*4,hipMemcpyHostToDevice,hs));
  scatter_ffn_rows<<<(n*5120+255)/256,256,0,hs>>>((float*)w.accumulated.data,(const float*)down.data,(const uint32_t*)w.selected_pairs.data,n);hipcheck(hipGetLastError());
  audit_stage(cfg.audit,"ffn_expert_"+std::to_string(job.ticket.expert),down,stream);
  hipcheck(hipStreamSynchronize(hs));cfg.experts->consumed(job.ticket,stream);pending.erase(pending.begin());
 };
 try{for(auto expert:experts){
  if(cfg.experts&&pending.size()==cfg.experts->capacity())flush();
  std::vector<uint32_t>pairs;for(uint64_t token=0;token<b;++token)for(unsigned slot=0;slot<6;++slot)if(ids[token*6+slot]==expert){pairs.push_back(uint32_t(token));pairs.push_back(slot);}
  uint64_t n=pairs.size()/2;need(b<=UINT32_MAX,"dispatch token index range");hipcheck(hipMemcpyAsync(w.selected_pairs.data,pairs.data(),pairs.size()*4,hipMemcpyHostToDevice,hs));
  select_ffn_rows<<<(n*5120+255)/256,256,0,hs>>>((const float*)input.data,(const float*)w.weights.data,(const uint32_t*)w.selected_pairs.data,(float*)w.selected_input.data,(float*)w.selected_route.data,n);hipcheck(hipGetLastError());
  auto x=prefix_rows(w.selected_input,n),route=prefix_rows(w.selected_route,n),down=prefix_rows(w.down_bf16,n);
  ExpertWorkspace ew{w.input_qdq,w.gate,w.up,w.hidden,w.down_qdq,w.down_dot};
  if(cfg.experts){
   // submit invokes local inline; remote input/route are snapshotted on this
   // same stream before the selected workspace is reused by the next expert.
   auto ticket=cfg.experts->submit(*frame,layer,expert,pairs,x,route,stream,[&](const DeviceView&out){expert_forward_device(artifact,layer,expert,x,route,out,ew,cfg,stream,project);});
   pending.push_back({std::move(pairs),std::move(ticket)});
  }else{
   expert_forward_device(artifact,layer,expert,x,route,down,ew,cfg,stream,project);
   scatter_ffn_rows<<<(n*5120+255)/256,256,0,hs>>>((float*)w.accumulated.data,(const float*)down.data,(const uint32_t*)w.selected_pairs.data,n);hipcheck(hipGetLastError());
   audit_stage(cfg.audit,"ffn_expert_"+std::to_string(expert),down,stream);hipcheck(hipStreamSynchronize(hs));
  }
 }
 while(!pending.empty())flush();
 }catch(...){auto error=std::current_exception();if(cfg.experts)cfg.experts->cancel_and_drain(stream);std::rethrow_exception(error);}
 auto gate_dot=w.gate;gate_dot.scalar=DeviceScalar::Float32;auto up_dot=w.up;up_dot.scalar=DeviceScalar::Float32;
 linear(artifact.source_tensor(prefix+"ffn_gate_shexp.weight"),0,input,gate_dot,w.gate);linear(artifact.source_tensor(prefix+"ffn_up_shexp.weight"),0,input,up_dot,w.up);
 ffn_swiglu_device(w.gate,w.up,nullptr,w.hidden,stream);linear(artifact.source_tensor(prefix+"ffn_down_shexp.weight"),0,w.hidden,w.down_dot,w.down_bf16);
 ffn_add_device(w.accumulated,w.down_bf16,w.down_dot,stream);ffn_bf16_device(w.down_dot,output,stream);audit_stage(cfg.audit,"ffn_output",output,stream);
}
namespace {
__global__ void copy_engram_bf16(const uint16_t*row,float*dst){unsigned d=blockIdx.x*blockDim.x+threadIdx.x;if(d<256)dst[d]=__uint_as_float(uint32_t(row[d])<<16);}
}
void gather_engram_device(cache::PrimarySupply&weight,cache::RowSupply&rows,cache::DemandOrder&order,const std::vector<cache::RowLookup>&lookups,const measurement::Identity&identity,const CoreIoGrant&grant,const DeviceView&embedding,void*stream){
 validate_device_view(embedding,embedding.device);check_device_stream(stream,embedding.device);
 need(embedding.scalar==DeviceScalar::Bfloat16InFloat32&&embedding.columns==6144&&lookups.size()==mul(embedding.rows,24),"Engram embedding/head geometry");
 for(size_t i=0;i<lookups.size();++i){need((lookups[i].layer==1||lookups[i].layer==14)&&lookups[i].layer==lookups[0].layer&&lookups[i].head==i%24,"Engram layer/head ordering");}
 for(size_t i=0;i<lookups.size();++i){auto token=rows.enqueue({lookups[i]},identity);need(bool(token),"finite row admission");bool borrowed=false,returned=false;cache::RowDeviceOutput view;
  try{
   while(rows.state(*token)!=cache::RowState::Ready){advance_core_io(weight,rows,order,grant,cache::Kind::Expert,10);need(rows.state(*token)!=cache::RowState::Cancelled,"row cancelled before gather");}
   rows.launch_gather(*token);while(rows.state(*token)==cache::RowState::Kernel)advance_core_io(weight,rows,order,grant,cache::Kind::Expert,0);
   view=rows.borrow_device_output(*token);borrowed=true;need(view.device==embedding.device,"borrowed row device");
   copy_engram_bf16<<<1,256,0,reinterpret_cast<hipStream_t>(stream)>>>(view.bf16,(float*)embedding.data+i*256);hipcheck(hipGetLastError());
   rows.return_device_output(*token,view,stream);returned=true;
   while(rows.state(*token)!=cache::RowState::Done){advance_core_io(weight,rows,order,grant,cache::Kind::Expert,0);need(rows.state(*token)!=cache::RowState::Cancelled,"late row identity/cancel");}
   auto result=rows.take(*token,identity);need(!result.cancelled&&result.fp32.empty()&&result.bf16.empty(),"device gather performed payload readback");
  }catch(...){
   if(borrowed&&!returned){rows.return_device_output(*token,view,stream);returned=true;}
   rows.cancel(*token);while(rows.state(*token)!=cache::RowState::Cancelled){rows.poll_io(10);rows.poll_device();}rows.take(*token,identity);throw;
  }
 }
}
namespace {
void constant_view(const CoreConstant&c,const SourceTensor&expected,uint64_t count,int device){
 const auto&a=c.original;need(a.source.shard_index==expected.source.shard_index&&a.source.original_path==expected.source.original_path&&a.source.original_size==expected.source.original_size&&a.source.revision==expected.source.revision&&a.source.lfs_sha256==expected.source.lfs_sha256&&a.span.name==expected.span.name&&a.span.absolute_offset==expected.span.absolute_offset&&a.span.bytes==expected.span.bytes&&a.span.type_id==0&&a.span.dims_ggml==std::vector<uint64_t>{count},"source-bound constant");
 validate_device_view(c.value,device);need(c.value.scalar==DeviceScalar::Float32&&c.value.rows==1&&c.value.columns==count,"constant device shape");
}
void core_mixes(const SourceTensor&fn,const DeviceView&residual,const CoreConstant&scale,const CoreConstant&base,MhcWorkspace&w,const CoreConfig&cfg,void*stream,const DeviceProject&project){
 mhc_rms_device(residual,w.inverse,stream);tiled_projection(fn,0,residual,w.dot,residual.rows,cfg,stream,project);mhc_mix_device(w.dot,w.inverse,w.mixed,stream);mhc_split_device(w.mixed,scale.value,base.value,w.pre,w.post,w.comb,stream,w.audit);
}
}
void core_block_device(const Artifact&a,uint32_t layer,const DeviceView&residual,const DeviceView&incoming,const DeviceView&output,BlockWorkspace&w,const BlockConstants&c,const CoreConfig&cfg,void*stream,const DeviceProject&project,const CoreSubblock&attention,const CoreSubblock&ffn){
 need(layer<40&&attention&&ffn,"actual block operator connection");validate_device_view(residual,cfg.device);validate_device_view(output,cfg.device);need(residual.rows==output.rows&&residual.columns==20480&&output.columns==20480&&residual.scalar==DeviceScalar::Bfloat16InFloat32&&output.scalar==DeviceScalar::Bfloat16InFloat32&&residual.data!=output.data,"block residual geometry/nonalias");
 const auto prefix="blk."+std::to_string(layer)+".";
 constant_view(c.attention_scale,a.source_tensor(prefix+"hc_attn_scale.weight"),3,cfg.device);constant_view(c.attention_base,a.source_tensor(prefix+"hc_attn_base.weight"),24,cfg.device);constant_view(c.attention_norm,a.source_tensor(prefix+"attn_norm.weight"),5120,cfg.device);
 constant_view(c.ffn_scale,a.source_tensor(prefix+"hc_ffn_scale.weight"),3,cfg.device);constant_view(c.ffn_base,a.source_tensor(prefix+"hc_ffn_base.weight"),24,cfg.device);constant_view(c.ffn_norm,a.source_tensor(prefix+"ffn_norm.weight"),5120,cfg.device);
 // Own attention coefficients are for FFN's pre; incoming coefficients collapse
 // this attention. Post/comb always belong to the current subblock.
 core_mixes(a.source_tensor(prefix+"hc_attn_fn.weight"),residual,c.attention_scale,c.attention_base,w.attention,cfg,stream,project);
 mhc_pre_device(residual,incoming,w.collapsed,stream);mhc_rms_device(w.collapsed,w.norm_inverse,stream);mhc_norm_device(w.collapsed,w.norm_inverse,c.attention_norm.value,w.normalized,stream);
 audit_stage(cfg.audit,"block_attention_input",w.normalized,stream);attention(w.normalized,w.subblock,stream);
 mhc_post_device(w.subblock,residual,w.attention.post,w.attention.comb,w.after_attention,stream);audit_stage(cfg.audit,"block_after_attention",w.after_attention,stream);
 core_mixes(a.source_tensor(prefix+"hc_ffn_fn.weight"),w.after_attention,c.ffn_scale,c.ffn_base,w.ffn,cfg,stream,project);
 mhc_pre_device(w.after_attention,w.attention.pre,w.collapsed,stream);mhc_rms_device(w.collapsed,w.norm_inverse,stream);mhc_norm_device(w.collapsed,w.norm_inverse,c.ffn_norm.value,w.normalized,stream);
 audit_stage(cfg.audit,"block_ffn_input",w.normalized,stream);ffn(w.normalized,w.subblock,stream);
 mhc_post_device(w.subblock,w.after_attention,w.ffn.post,w.ffn.comb,output,stream);audit_stage(cfg.audit,"block_output",output,stream);audit_stage(cfg.audit,"block_next_pre",w.ffn.pre,stream);
}
namespace {
__global__ void append_compressed_indices(const int32_t*selected,int64_t*out,uint64_t count){uint64_t i=uint64_t(blockIdx.x)*blockDim.x+threadIdx.x;if(i<count)out[i]=selected[i];}
}
void attention_swa_device(const Artifact&a,uint32_t layer,const DeviceView&input,const DeviceView&output,SwaState&state,SwaWorkspace&w,const SwaConstants&c,uint64_t epoch,const CoreConfig&cfg,void*stream,const DeviceProject&project){attention_step_device(a,layer,input,output,state,w,c,epoch,false,{},cfg,stream,project);}
void attention_step_device(const Artifact&a,uint32_t layer,const DeviceView&input,const DeviceView&output,SwaState&state,SwaWorkspace&w,const SwaConstants&c,uint64_t epoch,bool compressed_rope,const SharedAttentionUpdate&update,const CoreConfig&cfg,void*stream,const DeviceProject&project){
 need(layer<40&&state.valid&&state.epoch==epoch&&state.position<INT64_MAX&&compressed_rope==(attention_role(layer).ratio!=0),"SWA state/epoch/source role");check_device_stream(stream,cfg.device);auto hs=reinterpret_cast<hipStream_t>(stream);
 validate_device_view(input,cfg.device);validate_device_view(output,cfg.device);need(input.rows==1&&input.columns==5120&&input.scalar==DeviceScalar::Bfloat16InFloat32&&output.rows==1&&output.columns==5120&&output.scalar==DeviceScalar::Bfloat16InFloat32,"single token SWA geometry");
 validate_device_view(state.ring,cfg.device);need(state.ring.rows==128&&state.ring.columns==512&&state.ring.scalar==DeviceScalar::Bfloat16InFloat32,"SWA ring geometry");
 const auto prefix="blk."+std::to_string(layer)+".";constant_view(c.q_norm,a.source_tensor(prefix+"attn_q_a_norm.weight"),1280,cfg.device);constant_view(c.kv_norm,a.source_tensor(prefix+"attn_kv_a_norm.weight"),512,cfg.device);constant_view(c.sink,a.source_tensor(prefix+"attn_sinks.weight"),64,cfg.device);
 auto needview=[&](const DeviceView&v,uint64_t rows,uint64_t cols,DeviceScalar scalar){validate_device_view(v,cfg.device);need(v.rows==rows&&v.columns==cols&&v.scalar==scalar,"SWA workspace geometry");};
 needview(w.positions,1,1,DeviceScalar::Int64);needview(w.head_positions,64,1,DeviceScalar::Int64);needview(w.frequencies,1,32,DeviceScalar::Float32);validate_device_view(w.ids,cfg.device);need(w.ids.rows==1&&w.ids.columns>=128&&w.ids.scalar==DeviceScalar::Int64,"attention index capacity");needview(w.error,1,1,DeviceScalar::UInt32);
 needview(w.q_dot,1,32768,DeviceScalar::Float32);needview(w.q_bf16,1,32768,DeviceScalar::Bfloat16InFloat32);needview(w.q_rotated,64,512,DeviceScalar::Bfloat16InFloat32);needview(w.attended,64,512,DeviceScalar::Bfloat16InFloat32);needview(w.inverse,64,512,DeviceScalar::Bfloat16InFloat32);needview(w.output_qdq,1,32768,DeviceScalar::Float32);
 needview(w.group_input,1,4096,DeviceScalar::Float32);needview(w.group_dot,1,8192,DeviceScalar::Float32);needview(w.group_bf16,1,8192,DeviceScalar::Bfloat16InFloat32);needview(w.out_qdq,1,8192,DeviceScalar::Float32);needview(w.out_dot,1,5120,DeviceScalar::Float32);
 try{
  ffn_qdq_device(input,w.input_qdq,stream);tiled_projection(a.source_tensor(prefix+"attn_q_a.weight"),0,w.input_qdq,w.qa_dot,1,cfg,stream,project);ffn_bf16_device(w.qa_dot,w.qa_bf16,stream);attention_rms_device(w.qa_bf16,c.q_norm.value,w.qr,stream);ffn_qdq_device(w.qr,w.qr_qdq,stream);tiled_projection(a.source_tensor(prefix+"attn_q_b.weight"),0,w.qr_qdq,w.q_dot,1,cfg,stream,project);ffn_bf16_device(w.q_dot,w.q_bf16,stream);
  // KV uses the same x activation QDQ but its own source/normalization.
  tiled_projection(a.source_tensor(prefix+"attn_kv.weight"),0,w.input_qdq,w.kv_dot,1,cfg,stream,project);ffn_bf16_device(w.kv_dot,w.kv_bf16,stream);kv_norm_device(w.kv_bf16,c.kv_norm.value,w.kv_normalized,stream);
  int64_t position=int64_t(state.position);std::array<int64_t,64> head_positions;head_positions.fill(position);hipcheck(hipMemcpyAsync(w.positions.data,&position,8,hipMemcpyHostToDevice,hs));hipcheck(hipMemcpyAsync(w.head_positions.data,head_positions.data(),sizeof(head_positions),hipMemcpyHostToDevice,hs));kv_frequency_device(w.frequencies,compressed_rope,stream);
  auto q=w.q_bf16;q.rows=64;q.columns=512;kv_rope_device(q,w.head_positions,w.frequencies,w.q_rotated,false,stream);kv_rope_device(w.kv_normalized,w.positions,w.frequencies,w.kv_rotated,false,stream);kv_quantize_device(w.kv_rotated,w.kv_qdq,false,stream);
  hipcheck(hipMemcpyAsync((float*)state.ring.data+(state.position%128)*512,w.kv_qdq.data,512*4,hipMemcpyDeviceToDevice,hs));
  uint64_t count=std::min<uint64_t>(128,state.position+1);std::vector<int64_t> indices(count);for(uint64_t i=0;i<count;++i)indices[i]=int64_t((state.position+1-count+i)%128);
  hipcheck(hipMemcpyAsync(w.ids.data,indices.data(),count*8,hipMemcpyHostToDevice,hs));hipcheck(hipMemsetAsync(w.error.data,0,4,hs));auto ids=w.ids;ids.columns=count;
  SharedAttentionFrame frame;if(compressed_rope){need(bool(update),"actual shared attention update missing");frame=update(w.qr,stream);need(frame.position==state.position&&frame.epoch==epoch,"shared attention current frame");if(frame.has_compressed){validate_device_view(frame.compressed,cfg.device);validate_device_view(frame.selected,cfg.device);need(frame.compressed.columns==512&&frame.selected.rows==1&&frame.selected.columns==std::min<uint64_t>(512,frame.compressed.rows)&&frame.selected.scalar==DeviceScalar::Int32,"shared attention cache/selection geometry");need(frame.selected.columns<=w.ids.columns-count,"combined index capacity");append_compressed_indices<<<(frame.selected.columns+255)/256,256,0,hs>>>((const int32_t*)frame.selected.data,(int64_t*)w.ids.data+count,frame.selected.columns);hipcheck(hipGetLastError());ids.columns+=frame.selected.columns;}}
  if(frame.has_compressed)attention_online_split_device(w.q_rotated,state.ring,frame.compressed,ids,c.sink.value,w.attended,w.error,stream);else attention_online_device(w.q_rotated,state.ring,ids,c.sink.value,w.attended,w.error,stream);kv_rope_device(w.attended,w.head_positions,w.frequencies,w.inverse,true,stream);
  auto inverse=w.inverse;inverse.rows=1;inverse.columns=32768;ffn_qdq_device(inverse,w.output_qdq,stream);
  // output_a is block-diagonal: each 1024-row group sees only its own 4096
  // input columns. Original output-row coordinates stay bound to the source.
  auto wa=a.source_tensor(prefix+"attn_output_a.weight");need(wa.span.dims_ggml==std::vector<uint64_t>{4096,8192},"grouped output source");
  for(uint64_t group=0;group<8;++group){hipcheck(hipMemcpyAsync(w.group_input.data,(float*)w.output_qdq.data+group*4096,4096*4,hipMemcpyDeviceToDevice,hs));
   auto row=source_tile(wa,0,group*1024,1);auto tile_rows=std::min<uint64_t>(cfg.tile_rows,cfg.tile_bytes/row.bytes);need(tile_rows,"one grouped full-K row must fit");
   for(uint64_t first=0;first<1024;first+=std::min(tile_rows,1024-first)){auto t=source_tile(wa,0,group*1024+first,std::min(tile_rows,1024-first));project(t,w.group_input,w.group_dot,1,stream);}
  }
  ffn_bf16_device(w.group_dot,w.group_bf16,stream);ffn_qdq_device(w.group_bf16,w.out_qdq,stream);tiled_projection(a.source_tensor(prefix+"attn_output_b.weight"),0,w.out_qdq,w.out_dot,1,cfg,stream,project);ffn_bf16_device(w.out_dot,output,stream);
  uint32_t error=0;hipcheck(hipMemcpyAsync(&error,w.error.data,4,hipMemcpyDeviceToHost,hs));hipcheck(hipStreamSynchronize(hs));need(error==0,"attention rejected runtime index");
  audit_stage(cfg.audit,"attention_q_rotated",w.q_rotated,stream);audit_stage(cfg.audit,"attention_window",state.ring,stream);audit_stage(cfg.audit,"attention_output",output,stream);++state.position;
 }catch(...){state.valid=false;throw;}
}
struct CoreStorage::Impl {
 int device;hipStream_t stream=nullptr;quant::ProjectionLease lease;std::map<std::string,std::pair<void*,uint64_t>> allocations;uint64_t owned=0,h2d=0,d2h=0;
 explicit Impl(int d):device(d){hipcheck(hipSetDevice(d));hipcheck(hipStreamCreateWithFlags(&stream,hipStreamNonBlocking));}
 ~Impl(){if(!stream)return;if(hipSetDevice(device)!=hipSuccess||hipStreamSynchronize(stream)!=hipSuccess)std::terminate();lease.active=false;for(auto&item:allocations)if(hipFree(item.second.first)!=hipSuccess)std::terminate();if(hipStreamDestroy(stream)!=hipSuccess)std::terminate();}
};
CoreStorage::CoreStorage(int device):p_(std::make_unique<Impl>(device)){}
CoreStorage::~CoreStorage()=default;
bool CoreStorage::optional_workspace(uint64_t bytes,const std::function<void(const DeviceView&)>&build){
 auto&p=*p_;check_device_stream(p.stream,p.device);need(bytes&&bytes<=SIZE_MAX&&build,"optional workspace declaration");
 // Allocate map metadata before hipMalloc; every actual address has one owner
 // even if later descriptor validation or checked cleanup fails.
 auto item=p.allocations.emplace("prefill-optional",std::make_pair(nullptr,bytes));need(item.second,"one optional attempt per Core");
 void*ptr=nullptr;auto status=hipMalloc(&ptr,size_t(bytes));
 if(status!=hipSuccess){p.allocations.erase(item.first);if(status==hipErrorOutOfMemory)return false;hipcheck(status);}
 item.first->second.first=ptr;
 try{auto view=checked_device_view(ptr,bytes,1,bytes,DeviceScalar::UInt8,p.device,p.lease);build(view);p.owned=add(p.owned,bytes);return true;}
 catch(...){auto error=std::current_exception();auto release=hipFree(ptr);if(release==hipSuccess)p.allocations.erase(item.first);else{p.owned=add(p.owned,bytes);hipcheck(release);}std::rethrow_exception(error);}
 return false;
}
DeviceView CoreStorage::allocate(const std::string&name,uint64_t rows,uint64_t columns,DeviceScalar scalar){auto&p=*p_;check_device_stream(p.stream,p.device);need(!name.empty()&&!p.allocations.count(name)&&rows&&columns,"unique live device allocation");uint64_t bytes=mul(mul(rows,columns),scalar_bytes(scalar));need(bytes<=SIZE_MAX,"device allocation size");void*ptr=nullptr;hipcheck(hipMalloc(&ptr,size_t(bytes)));try{auto view=checked_device_view(ptr,bytes,rows,columns,scalar,p.device,p.lease);p.allocations.emplace(name,std::make_pair(ptr,bytes));p.owned=add(p.owned,bytes);return view;}catch(...){hipFree(ptr);throw;}}
void CoreStorage::upload(const DeviceView&v,const void*host,uint64_t bytes){auto&p=*p_;validate_device_view(v,p.device);need(v.owner==&p.lease&&host&&bytes&&bytes<=v.bytes,"owned upload range");hipcheck(hipMemcpyAsync(v.data,host,size_t(bytes),hipMemcpyHostToDevice,p.stream));hipcheck(hipStreamSynchronize(p.stream));p.h2d=add(p.h2d,bytes);}
void CoreStorage::download(const DeviceView&v,void*host,uint64_t bytes){auto&p=*p_;validate_device_view(v,p.device);need(v.owner==&p.lease&&host&&bytes&&bytes<=v.bytes,"owned output/audit download range");hipcheck(hipMemcpyAsync(host,v.data,size_t(bytes),hipMemcpyDeviceToHost,p.stream));hipcheck(hipStreamSynchronize(p.stream));p.d2h=add(p.d2h,bytes);}
void CoreStorage::drain(){hipcheck(hipStreamSynchronize(p_->stream));}
void*CoreStorage::stream()const{return p_->stream;}
const quant::ProjectionLease&CoreStorage::lease()const{return p_->lease;}
uint64_t CoreStorage::explicit_owned_bytes()const{return p_->owned;}
uint64_t CoreStorage::upload_bytes()const{return p_->h2d;}
uint64_t CoreStorage::download_bytes()const{return p_->d2h;}
bool compression_latent_device(const Artifact&a,const DeviceView&input,CompressionState&state,CompressionWorkspace&w,const CoreConstant&norm,uint64_t epoch,const CoreConfig&cfg,void*stream,const DeviceProject&project){
 need(state.valid&&state.epoch==epoch&&(state.writer==2||state.writer==8||state.writer==14||state.writer==20)&&state.ratio==(state.writer==20?1:2)&&state.position<INT64_MAX,"compression source/ratio/epoch");
 need(state.published_rows==state.position/state.ratio,"previous compressed latent not published");check_device_stream(stream,cfg.device);validate_device_view(input,cfg.device);need(input.rows==1&&input.columns==5120&&input.scalar==DeviceScalar::Bfloat16InFloat32,"compressor input");
 auto prefix="blk."+std::to_string(state.writer)+".";constant_view(norm,a.source_tensor(prefix+"attn_compressor_norm.weight"),512,cfg.device);auto hs=reinterpret_cast<hipStream_t>(stream);
 try{
  // Both sources omit activation QDQ. Ratio2 retains FP32 dot/gate until pool;
  // ratio1 casts its sole KV projection directly to BF16 before RMS.
  tiled_projection(a.source_tensor(prefix+"attn_compressor_kv.weight"),0,input,w.kv_dot,1,cfg,stream,project);
  if(state.ratio==2){
   tiled_projection(a.source_tensor(prefix+"attn_compressor_gate.weight"),0,input,w.gate_dot,1,cfg,stream,project);
   for(const auto*v:{&state.pending_kv,&state.pending_score}){validate_device_view(*v,cfg.device);need(v->rows==1&&v->columns==1024&&v->scalar==DeviceScalar::Float32,"pending ratio2 original pair");}
   auto offset=(state.position%2)*512;hipcheck(hipMemcpyAsync((float*)state.pending_kv.data+offset,w.kv_dot.data,512*4,hipMemcpyDeviceToDevice,hs));hipcheck(hipMemcpyAsync((float*)state.pending_score.data+offset,w.gate_dot.data,512*4,hipMemcpyDeviceToDevice,hs));
   ++state.position;if(state.position%2)return false;
   kv_pool_device(state.pending_kv,state.pending_score,w.pooled,stream);ffn_bf16_device(w.pooled,w.pooled_bf16,stream);
  }else{ffn_bf16_device(w.kv_dot,w.pooled_bf16,stream);++state.position;}
  kv_norm_device(w.pooled_bf16,norm.value,w.latent,stream);audit_stage(cfg.audit,"compression_pre_rope",w.latent,stream);return true;
 }catch(...){state.valid=false;throw;}
}
void compression_publish_device(CompressionState&state,CompressionWorkspace&w,uint64_t epoch,void*stream){
 need(state.valid&&state.epoch==epoch&&state.ratio&&state.position%state.ratio==0&&state.published_rows+1==state.position/state.ratio,"compressed publish order/epoch");
 auto d=w.latent.device;validate_device_view(state.cache,d);need(state.cache.scalar==DeviceScalar::Bfloat16InFloat32&&state.cache.columns==512&&state.published_rows<state.cache.rows,"caller compressed state capacity");check_device_stream(stream,d);auto hs=reinterpret_cast<hipStream_t>(stream);
 try{int64_t position=int64_t(state.position-state.ratio);hipcheck(hipMemcpyAsync(w.position.data,&position,8,hipMemcpyHostToDevice,hs));kv_frequency_device(w.frequencies,true,stream);kv_rope_device(w.latent,w.position,w.frequencies,w.rotated,false,stream);kv_quantize_device(w.rotated,w.quantized,true,stream);hipcheck(hipMemcpyAsync((float*)state.cache.data+state.published_rows*512,w.quantized.data,512*4,hipMemcpyDeviceToDevice,hs));
  // The host position source above remains alive until its actual H2D finishes.
  hipcheck(hipStreamSynchronize(hs));++state.published_rows;
 }catch(...){state.valid=false;throw;}
}
namespace {
__global__ void index_pad128(const float*x,float*out,uint64_t rows){uint64_t i=uint64_t(blockIdx.x)*blockDim.x+threadIdx.x;if(i<rows*512){auto d=i%512;out[i]=d<384?0.f:x[(i/512)*128+d-384];}}
__global__ void index_crop128(const float*x,float*out,uint64_t rows){uint64_t i=uint64_t(blockIdx.x)*blockDim.x+threadIdx.x;if(i<rows*128)out[i]=x[(i/128)*512+384+i%128];}
void index_rotate(const DeviceView&input,DeviceView padded,DeviceView rotated,DeviceView out,const DeviceView&positions,const DeviceView&freq,void*stream){auto rows=input.columns==4096?32:1;need(input.rows==1&&(input.columns==4096||input.columns==128),"index original rotary geometry");for(auto*v:{&padded,&rotated}){validate_device_view(*v,input.device);need(v->rows==uint64_t(rows)&&v->columns==512&&v->scalar==DeviceScalar::Bfloat16InFloat32,"index padded rotary view");}auto s=reinterpret_cast<hipStream_t>(stream);index_pad128<<<(rows*512+255)/256,256,0,s>>>((const float*)input.data,(float*)padded.data,rows);hipcheck(hipGetLastError());kv_rope_device(padded,positions,freq,rotated,false,stream);validate_device_view(out,input.device);need(out.rows==1&&out.columns==input.columns&&out.scalar==DeviceScalar::Bfloat16InFloat32,"index rotary output view");index_crop128<<<(rows*128+255)/256,256,0,s>>>((const float*)rotated.data,(float*)out.data,rows);hipcheck(hipGetLastError());}
void index_state(const IndexKeyState&state,uint64_t epoch,int device){need(state.valid&&state.epoch==epoch&&(state.writer==2||state.writer==8||state.writer==14||state.writer==20)&&state.ratio==(state.writer==20?1:2),"index key writer/ratio/epoch");validate_device_view(state.keys,device);need(state.keys.columns==128&&state.keys.scalar==DeviceScalar::Bfloat16InFloat32&&state.rows<=state.keys.rows,"index key cache geometry");}
}
void index_key_device(const Artifact&a,IndexKeyState&state,const DeviceView&latent,IndexWorkspace&w,const CoreConstant&norm,uint64_t position,uint64_t epoch,const CoreConfig&cfg,void*stream,const DeviceProject&project){
 index_state(state,epoch,cfg.device);need(state.rows<state.keys.rows&&position==state.rows*state.ratio&&position<=INT64_MAX,"index latent group order/capacity");auto prefix="blk."+std::to_string(state.writer)+".";constant_view(norm,a.source_tensor(prefix+"indexer.k_norm.weight"),128,cfg.device);check_device_stream(stream,cfg.device);auto hs=reinterpret_cast<hipStream_t>(stream);
 try{
  tiled_projection(a.source_tensor(prefix+"indexer.attn_k.weight"),0,latent,w.key_dot,1,cfg,stream,project);ffn_bf16_device(w.key_dot,w.key_bf16,stream);attention_rms_device(w.key_bf16,norm.value,w.key_norm,stream);
  int64_t p=int64_t(position);hipcheck(hipMemcpyAsync(w.position.data,&p,8,hipMemcpyHostToDevice,hs));kv_frequency_device(w.frequencies,true,stream);index_rotate(w.key_norm,w.key_padded,w.key_rotated_padded,w.key_rotated,w.position,w.frequencies,stream);attention_fp4_device(w.key_rotated,w.key_quantized,stream);
  hipcheck(hipMemcpyAsync((float*)state.keys.data+state.rows*128,w.key_quantized.data,128*4,hipMemcpyDeviceToDevice,hs));hipcheck(hipStreamSynchronize(hs));++state.rows;
 }catch(...){state.valid=false;throw;}
}
void index_query_device(const Artifact&a,uint32_t layer,const DeviceView&input,const DeviceView&qr,const IndexKeyState&keys,CandidateState&candidate,IndexWorkspace&w,uint64_t position,uint64_t epoch,uint64_t window_rows,const CoreConfig&cfg,void*stream,const DeviceProject&project){
 index_state(keys,epoch,cfg.device);need((layer==2||layer==8||layer==14||layer==20||layer==24||layer==28||layer==32||layer==36)&&keys.writer==(layer>=24?20:layer)&&keys.rows&&keys.rows==(position+1)/keys.ratio&&position<INT64_MAX&&window_rows<=INT32_MAX,"index current source/visibility");check_device_stream(stream,cfg.device);auto hs=reinterpret_cast<hipStream_t>(stream);auto prefix="blk."+std::to_string(layer)+".";
 // wq_b is the FP8 activation-QDQ linear, including this indexer4096 branch.
 ffn_qdq_device(qr,w.query_input_qdq,stream);tiled_projection(a.source_tensor(prefix+"indexer.attn_q_b.weight"),0,w.query_input_qdq,w.query_dot,1,cfg,stream,project);ffn_bf16_device(w.query_dot,w.query_bf16,stream);
 std::array<int64_t,32> positions;positions.fill(int64_t(position));hipcheck(hipMemcpyAsync(w.query_positions.data,positions.data(),sizeof(positions),hipMemcpyHostToDevice,hs));kv_frequency_device(w.frequencies,true,stream);index_rotate(w.query_bf16,w.query_padded,w.query_rotated_padded,w.query_rotated,w.query_positions,w.frequencies,stream);attention_fp4_device(w.query_rotated,w.query_quantized,stream);
 // weights_proj is BF16/no activation QDQ, followed by BF16(x/64).
 tiled_projection(a.source_tensor(prefix+"indexer.proj.weight"),0,input,w.weight_dot,1,cfg,stream,project);ffn_bf16_device(w.weight_dot,w.weight_bf16,stream);attention_bf16_device(w.weight_bf16,w.weight_scaled,1.f/64.f,stream);
 auto keyview=keys.keys;keyview.rows=keys.rows;auto scores=w.scores;scores.columns=keys.rows;attention_index_device(w.query_quantized,keyview,w.weight_scaled,scores,stream);
 auto source=scores;
 if(keys.writer==20){
  auto a=reinterpret_cast<uintptr_t>(candidate.scores.data),b=reinterpret_cast<uintptr_t>(scores.data),n=mul(keys.rows,4);need(a<b?b-a>=n:a-b>=n,"source20 candidates require distinct retained storage");
  validate_device_view(candidate.scores,cfg.device);need(candidate.scores.rows==1&&candidate.scores.columns>=keys.rows&&candidate.scores.scalar==DeviceScalar::Float32,"source20 candidate storage");
  if(layer==20){hipcheck(hipMemcpyAsync(candidate.scores.data,scores.data,keys.rows*4,hipMemcpyDeviceToDevice,hs));candidate.position=position;candidate.rows=keys.rows;candidate.epoch=epoch;candidate.valid=true;}
  need(candidate.valid&&candidate.position==position&&candidate.rows==keys.rows&&candidate.epoch==epoch,"candidate writer/current frame mismatch");source=candidate.scores;source.columns=keys.rows;
 }
 int64_t visible=int64_t(keys.rows);hipcheck(hipMemcpyAsync(w.visible.data,&visible,8,hipMemcpyHostToDevice,hs));hipcheck(hipMemsetAsync(w.error.data,0,4,hs));auto mask=w.mask;mask.columns=keys.rows;auto selected=w.selected;selected.columns=std::min<uint64_t>(512,keys.rows);auto work=w.work;work.columns=selected.columns;auto blocks=w.blocks;blocks.columns=(keys.rows+7)/8;
 attention_select_device(source,scores,w.visible,mask,selected,blocks,work,w.error,int(keys.writer),int(window_rows),stream);
 uint32_t error=0;hipcheck(hipMemcpyAsync(&error,w.error.data,4,hipMemcpyDeviceToHost,hs));hipcheck(hipStreamSynchronize(hs));need(!error,"index runtime selection rejected");audit_stage(cfg.audit,"index_score",scores,stream);audit_stage(cfg.audit,"index_selected",selected,stream);
}

namespace {
__global__ void expand_embedding(const float*x,float*out){unsigned i=blockIdx.x*blockDim.x+threadIdx.x;if(i<20480)out[i]=x[i%5120];}
}
namespace {
__global__ void tap_hc_mean(const float*x,float*y){
 unsigned d=blockIdx.x*blockDim.x+threadIdx.x;if(d<5120){
  float sum=+0.0f;for(unsigned h=0;h<4;++h)sum=sum+x[h*5120+d];
  float mean=sum*0.25f;uint32_t bits=__float_as_uint(mean);
  // BF16 round-to-nearest-even, same bit rule as the T37 scalar contract.
  bits=(bits+0x7fffu+((bits>>16)&1u))&0xffff0000u;y[d]=__uint_as_float(bits);
 }
}
}
void core_tap_mean_device(const CoreTapFrame&f,const DeviceView&destination){
 need(f.instance&&f.hc==4&&f.hidden==5120&&f.target_layer>=37&&f.target_layer<=39&&f.capture_after_layer+1==f.target_layer,"tap mean frame geometry");
 const auto&x=f.residual;validate_device_view(x,x.device);validate_device_view(destination,x.device);check_device_stream(f.stream,x.device);
 need(x.rows==1&&x.columns==20480&&x.scalar==DeviceScalar::Bfloat16InFloat32&&destination.rows==1&&destination.columns==15360&&destination.scalar==DeviceScalar::Bfloat16InFloat32&&destination.owner!=x.owner,"tap mean source/destination layout and independent owner");
 auto a=reinterpret_cast<uintptr_t>(x.data),b=reinterpret_cast<uintptr_t>(destination.data);
 need(a%alignof(float)==0&&b%alignof(float)==0,"tap mean FP32 lane alignment");
 need(a<b?b-a>=81920:a-b>=61440,"tap mean source/destination overlap");
 tap_hc_mean<<<20,256,0,reinterpret_cast<hipStream_t>(f.stream)>>>((const float*)x.data,(float*)destination.data+(f.target_layer-37)*5120);hipcheck(hipGetLastError());
}
struct CoreSequence::Impl {
 CoreTapSink* tap_sink=nullptr;bool operation_active=false;unsigned tap_captures=0;
 std::shared_ptr<const uint8_t> tap_instance;
 const Artifact&artifact;const engram::Config&engram_config;cache::PrimarySupply&weight;cache::RowSupply*rows;PartitionSpec partition;measurement::Identity identity;CoreConfig config;uint64_t capacity,position=0,serial=0,constant_source_bytes=0;bool valid=true;std::optional<std::pair<uint32_t,uint32_t>> fixture_range;
 CoreStorage storage;std::function<void()> prefill_operation;CoreIoGrant grant;CoreProjection projection;cache::DemandOrder row_order;engram::History history;
#ifdef STRATA_DEEPSEEK_T36_FIXTURE_CAPTURE
 std::array<uint64_t,48> fixture_last_hashes{};uint64_t fixture_hash_position=0;bool fixture_hash_valid=false;
 void fixture_remember_hashes(const std::vector<uint64_t>&hashes){need(hashes.size()==48,"fixture actual hash extent");std::copy(hashes.begin(),hashes.end(),fixture_last_hashes.begin());fixture_hash_position=position;fixture_hash_valid=true;}
 void fixture_visit_state(const FixtureStateVisitor&visitor){
  need(valid&&position&&bool(visitor),"fixture healthy completed checkpoint");storage.drain();
  FixtureStateRecord record;record.kind="core";record.position=position;record.epoch=identity.epoch;record.valid=valid;record.identity=&identity;record.first=partition.first;record.end=partition.end;visitor(record,storage.stream());
  auto device=[&](const char*kind,uint32_t writer,uint32_t ratio,uint64_t pos,uint64_t epoch,uint64_t rows,bool live,const DeviceView&original,uint64_t r,uint64_t c){
   FixtureStateRecord item;item.kind=kind;item.writer=writer;item.ratio=ratio;item.position=pos;item.epoch=epoch;item.rows=rows;item.valid=live;
   if(r&&c){validate_device_view(original,config.device);auto bytes=mul(mul(r,c),scalar_bytes(original.scalar));need(bytes<=original.bytes,"fixture valid extent exceeds allocation");item.value=original;item.value.rows=r;item.value.columns=c;item.value.bytes=bytes;}
   visitor(item,storage.stream());
  };
  auto first=fixture_range?fixture_range->first:partition.first,end=fixture_range?fixture_range->second:partition.end;
  for(unsigned layer=first;layer<end;++layer){const auto&w=windows[layer];need(w.valid&&w.position==position&&w.epoch==identity.epoch,"fixture SWA checkpoint");auto n=std::min<uint64_t>(position,128);device("swa",layer,1,w.position,w.epoch,n,w.valid,w.ring,n,512);}
  for(unsigned i=0;i<4;++i){const auto&state=compression[i];const auto&key=keys[i];if(!state.cache.data)continue;need(state.valid&&key.valid&&state.published_rows==key.rows&&state.published_rows<=capacity/state.ratio,"fixture compressed valid extent");
   device("compressed",state.writer,state.ratio,state.position,state.epoch,state.published_rows,state.valid,state.cache,state.published_rows,512);
   device("keys",key.writer,key.ratio,state.position,key.epoch,key.rows,key.valid,key.keys,key.rows,128);
   if(state.writer>=first&&state.writer<end&&state.ratio==2){auto pending=position%2;device("pending_kv",state.writer,state.ratio,state.position,state.epoch,pending,state.valid,state.pending_kv,pending,512);device("pending_score",state.writer,state.ratio,state.position,state.epoch,pending,state.valid,state.pending_score,pending,512);}
  }
  device("candidates",20,1,candidates.position,candidates.epoch,candidates.rows,candidates.valid,candidates.scores,candidates.valid?1:0,candidates.rows);
  device("selection",selector,selector<40?(attention_role(selector).kv_writer==20?1:2):0,selection_position,selection_epoch,selection_rows,selection_valid,index.selected,selection_valid?1:0,std::min<uint64_t>(512,selection_rows));
  history.fixture_visit_history([&](uint64_t pos,const int64_t*values,uint64_t length){need(pos==position&&length==std::min<uint64_t>(pos,3),"fixture actual history extent");FixtureStateRecord item;item.kind="history";item.position=pos;item.rows=length;item.valid=true;item.host=values;item.host_bytes=mul(length,8);visitor(item,storage.stream());});
  need(fixture_hash_valid&&fixture_hash_position+1==position,"fixture actual hash checkpoint");FixtureStateRecord hashes;hashes.kind="engram_hashes";hashes.position=fixture_hash_position;hashes.rows=48;hashes.valid=true;hashes.host=fixture_last_hashes.data();hashes.host_bytes=384;visitor(hashes,storage.stream());
 }
#endif
 std::array<std::array<uint64_t,6>,40> route_union{};std::array<uint64_t,40> routed_tokens{};
 std::array<SwaState,40> windows;std::array<CompressionState,4> compression;std::array<IndexKeyState,4> keys;CandidateState candidates;
 uint64_t selection_position=0,selection_epoch=0,selection_rows=0;uint32_t selector=0;bool selection_valid=false;
 std::map<std::string,CoreConstant> constants;BlockWorkspace block;FfnWorkspace ffn;SwaWorkspace attention;CompressionWorkspace compress_work;IndexWorkspace index;EngramWorkspace engram_work;
 DeviceView residual_a,residual_b,embedding_dot,embedding,incoming,output_norm_inverse,output_collapsed,output_normalized,logits,image_mask,engram_mask,engram_embedding,engram_residual;
 CorePrefillPreparation preparation;CorePrefillPreparationResult preparation_result;
 struct WaveWorkspace {
  DeviceView residual_a,residual_b,incoming,image_mask,engram_mask,selected,candidate_bank;
  BlockWorkspace block;FfnWorkspace ffn;
  std::array<std::array<uint64_t,48>,8> hashes{};
  std::array<CandidateState,8> candidates{};
  std::array<uint64_t,8> selection_position{},selection_epoch{},selection_rows{};
  std::array<uint32_t,8> selector{};std::array<bool,8> selection_valid{};
 };
 std::unique_ptr<WaveWorkspace> wave;
 // Fixed host-side diagnostics only. No event/query/synchronization or content.
 void prefill_diagnostic(const char*phase,const char*status,PrefillDiagnosticClock::time_point begin,uint64_t count,int layer=-1)const noexcept{
  try{
   auto now=PrefillDiagnosticClock::now();auto io=weight.io_snapshot();
   auto elapsed=std::chrono::duration_cast<std::chrono::microseconds>(now-begin).count();
   auto stamp=std::chrono::duration_cast<std::chrono::microseconds>(now.time_since_epoch()).count();
   std::fprintf(stderr,"[strata-prefill] phase=%s status=%s host_steady_us=%lld elapsed_host_us=%lld layer=%d position=%llu count=%llu requested=%u selected=%u reason=%u workspace_bytes=%llu constant_miss_bytes=%llu constant_bytes=%llu upload_bytes=%llu issued_reads=%llu issued_bytes=%llu outstanding_reads=%llu outstanding_bytes=%llu\n",
    phase,status,static_cast<long long>(stamp),static_cast<long long>(elapsed),layer,
    static_cast<unsigned long long>(position),static_cast<unsigned long long>(count),
    preparation_result.requested_capacity,preparation_result.selected_capacity,unsigned(preparation_result.reason),
    static_cast<unsigned long long>(preparation_result.workspace_payload_bytes),static_cast<unsigned long long>(preparation_result.constant_miss_bytes),
    static_cast<unsigned long long>(constant_source_bytes),static_cast<unsigned long long>(storage.upload_bytes()),
    static_cast<unsigned long long>(io.issued_reads),static_cast<unsigned long long>(io.issued_read),
    static_cast<unsigned long long>(io.outstanding_reads),static_cast<unsigned long long>(io.outstanding_read_bytes));
  }catch(...){/* Observation failure never changes prefill/cancel/math behavior. */}
 }
 void prepare_prefill(){
  if(preparation_result.reason!=CorePrefillReason::Unprepared)return;
  preparation_result.context_capacity=capacity;preparation_result.requested_capacity=preparation.max_batch;
#if defined(STRATA_T28_CONSTRUCTION_TEST) || defined(STRATA_DEEPSEEK_T36_FIXTURE_CAPTURE)
  preparation_result.reason=CorePrefillReason::SerialCompatibility;return;
#endif
  if(config.full_logits||config.audit||config.experts||tap_sink||fixture_range||partition.first!=0||partition.end!=40||!rows||preparation.required_f32_names.empty()){
   preparation_result.reason=CorePrefillReason::SerialCompatibility;return;
  }
  if(preparation.max_batch==1){preparation_result.reason=CorePrefillReason::SerialBatchOne;return;}
  need(preparation.max_batch==2||preparation.max_batch==4||preparation.max_batch==8,"prefill supported preparation capacity");
  // The registry is derived independently from the actual ordinary Core uses.
  std::set<std::string> expected{"output_norm.weight"};
  for(unsigned l=0;l<40;++l){auto p="blk."+std::to_string(l)+".";for(auto n:{"hc_attn_scale.weight","hc_attn_base.weight","attn_norm.weight","hc_ffn_scale.weight","hc_ffn_base.weight","ffn_norm.weight","attn_q_a_norm.weight","attn_kv_a_norm.weight","attn_sinks.weight","exp_probs_b.bias","exp_probs_b_vl.bias"})expected.insert(p+n);if(l==1||l==14)expected.insert(p+"engram_gate.weight");if(l==2||l==8||l==14||l==20){expected.insert(p+"attn_compressor_norm.weight");expected.insert(p+"indexer.k_norm.weight");}}
  need(expected.size()==451&&std::vector<std::string>(expected.begin(),expected.end())==preparation.required_f32_names,"exact ordinary F32 preparation registry");
  auto before=constant_source_bytes;
  for(const auto&name:preparation.required_f32_names){if(prefill_operation)prefill_operation();auto source=artifact.source_tensor(name);need(source.span.type_id==0&&source.span.bytes&&source.span.bytes%4==0,"prepared F32 source geometry");bool gate=name=="blk.1.engram_gate.weight"||name=="blk.14.engram_gate.weight";constant(name,gate?4:1,gate?5120:source.span.bytes/4);}
  preparation_result.constant_miss_bytes=constant_source_bytes-before;
  auto pending=std::make_unique<WaveWorkspace>();auto b=preparation.max_batch;uint64_t bytes=mul(b,add(453786,mul(4,capacity)));
  bool ready=storage.optional_workspace(bytes,[&](const DeviceView&owner){uint64_t offset=0;
   auto alloc=[&](uint64_t columns,DeviceScalar scalar=DeviceScalar::Float32){auto n=mul(mul(b,columns),scalar_bytes(scalar));need(offset<=owner.bytes&&n<=owner.bytes-offset,"optional workspace exact layout");auto v=checked_device_view(static_cast<uint8_t*>(owner.data)+offset,n,b,columns,scalar,config.device,storage.lease());offset=add(offset,n);return v;};
   auto bf=[&](uint64_t columns){return alloc(columns,DeviceScalar::Bfloat16InFloat32);};
   auto mhc=[&]{MhcWorkspace m;m.inverse=alloc(1);m.dot=alloc(24);m.mixed=alloc(24);m.pre=alloc(4);m.post=alloc(4);m.comb=alloc(16);return m;};
   auto&w=*pending;w.residual_a=bf(20480);w.residual_b=bf(20480);w.incoming=alloc(4);
   auto&k=w.block;k.attention=mhc();k.ffn=mhc();k.collapsed=bf(5120);k.norm_inverse=alloc(1);k.normalized=bf(5120);k.subblock=bf(5120);k.after_attention=bf(20480);
   auto&f=w.ffn;f.input_qdq=alloc(5120);f.logits=alloc(384);f.scores=alloc(384);f.corrected=alloc(384);f.ids=alloc(6,DeviceScalar::UInt32);f.weights=alloc(6);f.accumulated=alloc(5120);f.selected_input=bf(5120);f.selected_route=alloc(1);f.selected_pairs=alloc(2,DeviceScalar::UInt32);f.gate=bf(2304);f.up=bf(2304);f.hidden=bf(2304);f.down_qdq=alloc(2304);f.down_dot=alloc(5120);f.down_bf16=bf(5120);
   w.image_mask=alloc(1,DeviceScalar::UInt8);w.engram_mask=alloc(1,DeviceScalar::UInt8);w.selected=alloc(512,DeviceScalar::Int32);w.candidate_bank=alloc(capacity);
   for(unsigned i=0;i<b;++i)w.candidates[i].scores=wave_row(w.candidate_bank,i);
   need(offset==bytes,"optional workspace D(B,C) equality");
  });
  if(!ready){preparation_result.reason=CorePrefillReason::OptionalOutOfMemory;return;}
  wave=std::move(pending);preparation_result.selected_capacity=b;preparation_result.workspace_payload_bytes=bytes;preparation_result.reason=CorePrefillReason::OptionalReady;
 }
 SharedAttentionFrame wave_shared(unsigned layer,uint64_t start,uint32_t count,uint32_t i,const DeviceView&input,const DeviceView&qr,void*stream){
  auto&w=*wave;auto pos=add(start,i);auto slot=source_slot(layer);auto&state=compression[slot];auto&key=keys[slot];auto writer=state.writer;auto prefix="blk."+std::to_string(writer)+".";auto callback=projection.callback();
  need(state.valid&&state.epoch==identity.epoch&&key.valid&&key.epoch==identity.epoch,"wave writer/key epoch");
  if(layer==writer){need(state.position==pos&&state.published_rows==pos/state.ratio&&key.rows==state.published_rows,"wave writer exact frontier");auto norm=constant(prefix+"attn_compressor_norm.weight",1,512);if(compression_latent_device(artifact,input,state,compress_work,norm,identity.epoch,config,stream,callback)){index_key_device(artifact,key,compress_work.latent,index,constant(prefix+"indexer.k_norm.weight",1,128),state.position-state.ratio,identity.epoch,config,stream,callback);compression_publish_device(state,compress_work,identity.epoch,stream);}}
  else need(state.position==add(start,count)&&state.published_rows==(start+count)/state.ratio&&key.rows==state.published_rows,"wave reader exact writer frontier");
  auto visible=(pos+1)/state.ratio;need(key.rows>=visible&&state.published_rows>=visible,"wave causal allocation extent");auto causal=key;causal.rows=visible;if(visible)causal.keys.rows=visible;
  auto index_writer=index_source(layer);
  if(layer==index_writer){if(visible){index_query_device(artifact,layer,input,qr,causal,w.candidates[i],index,pos,identity.epoch,128,config,stream,callback);auto target=wave_row(w.selected,i);hipcheck(hipMemcpyAsync(target.data,index.selected.data,mul(std::min<uint64_t>(512,visible),4),hipMemcpyDeviceToDevice,reinterpret_cast<hipStream_t>(stream)));}w.selector[i]=layer;w.selection_position[i]=pos;w.selection_epoch[i]=identity.epoch;w.selection_rows[i]=visible;w.selection_valid[i]=true;}
  need(w.selection_valid[i]&&w.selector[i]==index_writer&&w.selection_position[i]==pos&&w.selection_epoch[i]==identity.epoch&&w.selection_rows[i]==visible,"wave exact selection reader identity");
  SharedAttentionFrame frame;frame.position=pos;frame.epoch=identity.epoch;frame.has_compressed=visible!=0;if(visible){frame.compressed=state.cache;frame.compressed.rows=visible;frame.selected=wave_row(w.selected,i);frame.selected.columns=std::min<uint64_t>(512,visible);}return frame;
 }
 std::vector<float> run_wave(const std::vector<uint32_t>&tokens,const std::vector<uint8_t>&mask,uint64_t from,uint32_t count,bool emit_logits,const PrefillDiagnosticClock::time_point*diagnostic_start=nullptr){
  need(wave&&count>1&&count<=preparation_result.selected_capacity&&from<=tokens.size()&&count<=tokens.size()-from,"prepared finite wave");auto&w=*wave;auto start=position;auto hs=reinterpret_cast<hipStream_t>(storage.stream());auto callback=projection.callback();
  w.selection_valid.fill(false);for(auto&candidate:w.candidates)candidate.valid=false;
  auto copy=[&](const DeviceView&to,const DeviceView&source){need(to.bytes==source.bytes,"wave row copy shape");hipcheck(hipMemcpyAsync(to.data,source.data,to.bytes,hipMemcpyDeviceToDevice,hs));};
  for(unsigned i=0;i<count;++i){bool image=!mask.empty()&&mask[from+i];auto hashes=history.append(start+i,{tokens[from+i]},{uint8_t(!image)});need(hashes.size()==48,"wave actual Engram heads");std::copy(hashes.begin(),hashes.end(),w.hashes[i].begin());uint8_t im=image,em=!image;storage.upload(wave_row(w.image_mask,i),&im,1);storage.upload(wave_row(w.engram_mask,i),&em,1);embedding_device(tokens[from+i]);copy(wave_row(w.residual_a,i),residual_a);float initial[4]={1,0,0,0};storage.upload(wave_row(w.incoming,i),initial,16);if(prefill_operation)prefill_operation();}
  auto current=prefix_rows(w.residual_a,count),next=prefix_rows(w.residual_b,count),pre=prefix_rows(w.incoming,count);
  // Workspace prefix copies retain actual allocation owners and row strides.
  auto block=w.block;auto ffn=w.ffn;
  auto mhcprefix=[&](MhcWorkspace&m){for(auto*v:{&m.inverse,&m.dot,&m.mixed,&m.pre,&m.post,&m.comb})*v=prefix_rows(*v,count);};
  mhcprefix(block.attention);mhcprefix(block.ffn);for(auto*v:{&block.collapsed,&block.norm_inverse,&block.normalized,&block.subblock,&block.after_attention})*v=prefix_rows(*v,count);
  for(auto*v:{&ffn.input_qdq,&ffn.logits,&ffn.scores,&ffn.corrected,&ffn.ids,&ffn.weights,&ffn.accumulated,&ffn.selected_input,&ffn.selected_route,&ffn.selected_pairs,&ffn.gate,&ffn.up,&ffn.hidden,&ffn.down_qdq,&ffn.down_dot,&ffn.down_bf16})*v=prefix_rows(*v,count);
  for(unsigned layer=0;layer<40;++layer){need(windows[layer].valid&&windows[layer].position==start&&windows[layer].epoch==identity.epoch,"wave layer entry frontier");auto prefix="blk."+std::to_string(layer)+".";
   if(layer==1||layer==14){for(unsigned i=0;i<count;++i){std::vector<cache::RowLookup>lookups;for(unsigned head=0;head<24;++head){auto zero=artifact.engram_row(layer,head,0);auto base=(zero.absolute_offset-zero.original.span.absolute_offset)/264;auto global=w.hashes[i][(layer==1?0:24)+head];need(global>=base,"wave Engram mapping");lookups.push_back({layer,head,global-base});}gather_engram_device(weight,*rows,row_order,lookups,identity,grant,engram_embedding,storage.stream());auto row=wave_row(current,i);auto gate=constant(prefix+"engram_gate.weight",4,5120);engram_forward_device(row,engram_embedding,artifact.source_tensor(prefix+"engram_kv.weight"),gate.value,wave_row(w.engram_mask,i),engram_residual,engram_work,config,storage.stream(),callback);copy(row,engram_residual);if(prefill_operation)prefill_operation();}}
   BlockConstants bc{constant(prefix+"hc_attn_scale.weight",1,3),constant(prefix+"hc_attn_base.weight",1,24),constant(prefix+"attn_norm.weight",1,5120),constant(prefix+"hc_ffn_scale.weight",1,3),constant(prefix+"hc_ffn_base.weight",1,24),constant(prefix+"ffn_norm.weight",1,5120)};
   auto attn=[&](const DeviceView&x,const DeviceView&y,void*stream){SwaConstants c{constant(prefix+"attn_q_a_norm.weight",1,1280),constant(prefix+"attn_kv_a_norm.weight",1,512),constant(prefix+"attn_sinks.weight",1,64)};for(unsigned i=0;i<count;++i){auto row=wave_row(x,i);SharedAttentionUpdate update;if(layer>=2)update=[&,i,row](const DeviceView&qr,void*s){return wave_shared(layer,start,count,i,row,qr,s);};attention_step_device(artifact,layer,row,wave_row(y,i),windows[layer],attention,c,identity.epoch,layer>=2,update,config,stream,callback);if(prefill_operation)prefill_operation();}};
   auto moe=[&](const DeviceView&x,const DeviceView&y,void*stream){auto b=constant(prefix+"exp_probs_b.bias",1,384),v=constant(prefix+"exp_probs_b_vl.bias",1,384);std::vector<uint32_t>ids;ffn_forward_device(artifact,layer,x,prefix_rows(w.image_mask,count),b.value,v.value,y,ffn,config,stream,callback,&ids);need(ids.size()==mul(count,6),"wave actual routes");for(auto expert:ids){need(expert<384,"wave expert range");route_union[layer][expert/64]|=uint64_t(1)<<(expert%64);}routed_tokens[layer]=add(routed_tokens[layer],count);};
   core_block_device(artifact,layer,current,pre,next,block,bc,config,storage.stream(),callback,attn,moe);hipcheck(hipMemcpyAsync(pre.data,block.ffn.pre.data,mul(count,16),hipMemcpyDeviceToDevice,hs));std::swap(current,next);need(windows[layer].position==start+count,"wave layer completed frontier");if(prefill_operation)prefill_operation();
   if(diagnostic_start&&(layer==0||layer==1||layer==14||layer==39))prefill_diagnostic("firstwave_layer","completed",*diagnostic_start,count,int(layer));
  }
  for(auto&state:windows)need(state.position==start+count,"wave all40 commit frontier");
  // Restore the serial scratch/metadata expected by later step/append/visitor.
  copy(incoming,wave_row(pre,count-1));copy(residual_a,wave_row(current,count-1));
  auto&last=w.candidates[count-1];if(last.valid){hipcheck(hipMemcpyAsync(candidates.scores.data,last.scores.data,mul(last.rows,4),hipMemcpyDeviceToDevice,hs));candidates.position=last.position;candidates.rows=last.rows;candidates.epoch=last.epoch;candidates.valid=true;}
  selection_valid=w.selection_valid[count-1];selector=w.selector[count-1];selection_position=w.selection_position[count-1];selection_epoch=w.selection_epoch[count-1];selection_rows=w.selection_rows[count-1];if(selection_rows)hipcheck(hipMemcpyAsync(index.selected.data,wave_row(w.selected,count-1).data,mul(std::min<uint64_t>(512,selection_rows),4),hipMemcpyDeviceToDevice,hs));
  std::vector<float>result;if(emit_logits){head_device(residual_a);result.resize(129280);storage.download(logits,result.data(),mul(result.size(),4));}else storage.drain();position=add(start,count);return result;
 }
 DeviceView alloc(uint64_t r,uint64_t c,DeviceScalar t=DeviceScalar::Float32){return storage.allocate("core-"+std::to_string(serial++),r,c,t);}
 DeviceView bf(uint64_t r,uint64_t c){return alloc(r,c,DeviceScalar::Bfloat16InFloat32);}
 CoreConstant constant(const std::string&name,uint64_t r,uint64_t c){auto found=constants.find(name);if(found!=constants.end()){need(found->second.value.rows==r&&found->second.value.columns==c,"constant repeated geometry");return found->second;}
  auto source=artifact.source_tensor(name);need(source.span.type_id==0&&source.span.bytes==mul(mul(r,c),4)&&source.span.absolute_offset<=uint64_t(std::numeric_limits<std::streamoff>::max()),"static F32 source geometry");std::vector<float> host(size_t(mul(r,c)));std::ifstream in(source.source.original_path,std::ios::binary);need(bool(in),"static original source open");in.seekg(std::streamoff(source.span.absolute_offset));in.read(reinterpret_cast<char*>(host.data()),std::streamsize(source.span.bytes));need(uint64_t(in.gcount())==source.span.bytes,"static original source short read");for(auto v:host)need(std::isfinite(v),"nonfinite learned constant");CoreConstant result{source,alloc(r,c)};storage.upload(result.value,host.data(),source.span.bytes);constant_source_bytes=add(constant_source_bytes,source.span.bytes);constants.emplace(name,result);return result;
 }
 MhcWorkspace mhc(){MhcWorkspace w;w.inverse=alloc(1,1);w.dot=alloc(1,24);w.mixed=alloc(1,24);w.pre=alloc(1,4);w.post=alloc(1,4);w.comb=alloc(1,16);return w;}
 Impl(const Artifact&a,const engram::Config&e,cache::PrimarySupply&w,cache::RowSupply*r,measurement::Identity id,CoreConfig cfg,uint64_t cap,PartitionSpec part={0,40}):artifact(a),engram_config(e),weight(w),rows(r),partition(part),identity(std::move(id)),config(cfg),capacity(cap),storage(cfg.device),grant{1,w.read_window_capacity()},projection(w,r,identity,grant,cfg.secondary_cache),history(e){
  need(capacity&&identity.epoch&&config.active_batch&&config.tile_bytes&&config.tile_rows,"Core sequence/storage declaration");engram_config.validate();
  need(partition.first<partition.end&&partition.end<=40,"owned contiguous partition");
  need(rows||!((partition.first<=1&&1<partition.end)||(partition.first<=14&&14<partition.end)),"actual Engram range requires row owner");
  for(unsigned layer=0;layer<40;++layer){windows[layer].epoch=identity.epoch;if(layer>=partition.first&&layer<partition.end)windows[layer].ring=bf(128,512);}
  std::array<bool,4> needed{};for(unsigned layer=partition.first;layer<partition.end;++layer){auto writer=attention_role(layer).kv_writer;if(writer<40)needed[writer==2?0:writer==8?1:writer==14?2:3]=true;}
  for(unsigned i=0;i<4;++i){auto writer=std::array<unsigned,4>{2,8,14,20}[i];unsigned ratio=writer==20?1u:2u;uint64_t count=std::max<uint64_t>(1,capacity/ratio);compression[i].writer=writer;compression[i].ratio=ratio;compression[i].epoch=identity.epoch;keys[i].writer=writer;keys[i].ratio=ratio;keys[i].epoch=identity.epoch;if(needed[i]){if(writer>=partition.first&&writer<partition.end){compression[i].pending_kv=alloc(1,1024);compression[i].pending_score=alloc(1,1024);}compression[i].cache=bf(count,512);keys[i].keys=bf(count,128);}}
  candidates.scores=alloc(1,capacity);
  residual_a=bf(1,20480);residual_b=bf(1,20480);embedding_dot=alloc(1,5120);embedding=bf(1,5120);incoming=alloc(1,4);image_mask=alloc(1,1,DeviceScalar::UInt8);engram_mask=alloc(1,1,DeviceScalar::UInt8);
  block.attention=mhc();block.ffn=mhc();block.collapsed=bf(1,5120);block.norm_inverse=alloc(1,1);block.normalized=bf(1,5120);block.subblock=bf(1,5120);block.after_attention=bf(1,20480);
  output_norm_inverse=alloc(1,1);output_collapsed=bf(1,5120);output_normalized=bf(1,5120);logits=alloc(1,129280);
  ffn.input_qdq=alloc(1,5120);ffn.logits=alloc(1,384);ffn.scores=alloc(1,384);ffn.corrected=alloc(1,384);ffn.ids=alloc(1,6,DeviceScalar::UInt32);ffn.weights=alloc(1,6);ffn.accumulated=alloc(1,5120);ffn.selected_input=bf(1,5120);ffn.selected_route=alloc(1,1);ffn.selected_pairs=alloc(1,2,DeviceScalar::UInt32);ffn.gate=bf(1,2304);ffn.up=bf(1,2304);ffn.hidden=bf(1,2304);ffn.down_qdq=alloc(1,2304);ffn.down_dot=alloc(1,5120);ffn.down_bf16=bf(1,5120);
  attention.input_qdq=alloc(1,5120);attention.qa_dot=alloc(1,1280);attention.qa_bf16=bf(1,1280);attention.qr=bf(1,1280);attention.qr_qdq=alloc(1,1280);attention.q_dot=alloc(1,32768);attention.q_bf16=bf(1,32768);attention.q_rotated=bf(64,512);attention.kv_dot=alloc(1,512);attention.kv_bf16=bf(1,512);attention.kv_normalized=bf(1,512);attention.kv_rotated=bf(1,512);attention.kv_qdq=bf(1,512);attention.positions=alloc(1,1,DeviceScalar::Int64);attention.head_positions=alloc(64,1,DeviceScalar::Int64);attention.frequencies=alloc(1,32);attention.ids=alloc(1,640,DeviceScalar::Int64);attention.error=alloc(1,1,DeviceScalar::UInt32);attention.attended=bf(64,512);attention.inverse=bf(64,512);attention.output_qdq=alloc(1,32768);attention.group_input=alloc(1,4096);attention.group_dot=alloc(1,8192);attention.group_bf16=bf(1,8192);attention.out_qdq=alloc(1,8192);attention.out_dot=alloc(1,5120);
  compress_work.kv_dot=alloc(1,512);compress_work.gate_dot=alloc(1,512);compress_work.pooled=alloc(1,512);compress_work.pooled_bf16=bf(1,512);compress_work.latent=bf(1,512);compress_work.position=alloc(1,1,DeviceScalar::Int64);compress_work.frequencies=alloc(1,32);compress_work.rotated=bf(1,512);compress_work.quantized=bf(1,512);
  index.key_dot=alloc(1,128);index.key_bf16=bf(1,128);index.key_norm=bf(1,128);index.key_padded=bf(1,512);index.key_rotated_padded=bf(1,512);index.key_rotated=bf(1,128);index.key_quantized=bf(1,128);index.query_input_qdq=alloc(1,1280);index.query_dot=alloc(1,4096);index.query_bf16=bf(1,4096);index.query_padded=bf(32,512);index.query_rotated_padded=bf(32,512);index.query_rotated=bf(1,4096);index.query_quantized=bf(1,4096);index.weight_dot=alloc(1,32);index.weight_bf16=bf(1,32);index.weight_scaled=bf(1,32);index.position=alloc(1,1,DeviceScalar::Int64);index.query_positions=alloc(32,1,DeviceScalar::Int64);index.frequencies=alloc(1,32);index.scores=bf(1,capacity);index.visible=alloc(1,1,DeviceScalar::Int64);index.mask=alloc(1,capacity,DeviceScalar::UInt8);index.selected=alloc(1,512,DeviceScalar::Int32);index.blocks=alloc(1,(capacity+7)/8);index.work=alloc(1,512,DeviceScalar::Int32);index.error=alloc(1,1,DeviceScalar::UInt32);
  engram_embedding=bf(1,6144);engram_residual=bf(1,20480);engram_work.activation_qdq=alloc(1,6144);engram_work.kv_dot=alloc(1,25600);engram_work.kv_bf16=bf(1,25600);engram_work.gates=alloc(1,4);
 }
 unsigned source_slot(unsigned layer)const{auto writer=attention_role(layer).kv_writer;need(writer!=40,"compressed layer required");return writer==2?0:writer==8?1:writer==14?2:3;}
 unsigned index_source(unsigned layer)const{return attention_role(layer).index_writer;}
 SharedAttentionFrame shared(unsigned layer,const DeviceView&input,const DeviceView&qr,void*stream){
  auto slot=source_slot(layer);auto&state=compression[slot];auto&key=keys[slot];auto writer=state.writer;auto prefix="blk."+std::to_string(writer)+".";auto callback=projection.callback();
  if(layer==writer){need(state.position==position,"compressed writer position");auto norm=constant(prefix+"attn_compressor_norm.weight",1,512);if(compression_latent_device(artifact,input,state,compress_work,norm,identity.epoch,config,stream,callback)){index_key_device(artifact,key,compress_work.latent,index,constant(prefix+"indexer.k_norm.weight",1,128),state.position-state.ratio,identity.epoch,config,stream,callback);compression_publish_device(state,compress_work,identity.epoch,stream);}}
  need(state.published_rows==(position+1)/state.ratio&&key.rows==state.published_rows,"shared current writer/cache rows");
  auto index_writer=index_source(layer);if(layer==index_writer){if(key.rows)index_query_device(artifact,layer,input,qr,key,candidates,index,position,identity.epoch,128,config,stream,callback);selector=layer;selection_position=position;selection_epoch=identity.epoch;selection_rows=key.rows;selection_valid=true;}
  need(selection_valid&&selector==index_writer&&selection_position==position&&selection_epoch==identity.epoch&&selection_rows==key.rows,"shared current selection source");SharedAttentionFrame frame;frame.position=position;frame.epoch=identity.epoch;frame.has_compressed=key.rows!=0;if(frame.has_compressed){frame.compressed=state.cache;frame.compressed.rows=key.rows;frame.selected=index.selected;frame.selected.columns=std::min<uint64_t>(512,key.rows);}return frame;
 }
 void embedding_device(uint32_t token){auto source=artifact.source_tensor("token_embd.weight");need(token<source.span.dims_ggml[1],"raw token ID range");auto tile=source_tile(source,0,token,1);cache::SupplyMatrix m{tile.original,tile.absolute_offset,tile.bytes,tile.type,1,size_t(tile.k)};m.row_tile=true;m.output_row_first=token;need(weight.begin(m,identity),"embedding resident admission");while(weight.state()!=cache::SupplyState::Ready)projection.advance(10);weight.decode_device((float*)embedding_dot.data,embedding_dot.bytes,storage.stream(),storage.lease());while(weight.state()==cache::SupplyState::Kernel)projection.advance();need(weight.take_device(identity),"embedding late identity");ffn_bf16_device(embedding_dot,embedding,storage.stream());expand_embedding<<<80,256,0,reinterpret_cast<hipStream_t>(storage.stream())>>>((const float*)embedding.data,(float*)residual_a.data);hipcheck(hipGetLastError());}
 void run_layers(DeviceView&current,DeviceView&next,const DeviceView&incoming,const std::vector<uint64_t>&hashes,unsigned first,unsigned end){auto callback=projection.callback();
  for(unsigned layer=first;layer<end;++layer){if(config.audit)config.audit->frame(position,layer);auto prefix="blk."+std::to_string(layer)+".";
   if(layer==1||layer==14){std::vector<cache::RowLookup> lookups;for(unsigned head=0;head<24;++head){auto zero=artifact.engram_row(layer,head,0);auto base=(zero.absolute_offset-zero.original.span.absolute_offset)/264;auto global=hashes[(layer==1?0:24)+head];need(global>=base,"Engram global/head row mapping");lookups.push_back({layer,head,global-base});}need(rows,"actual Engram owner");gather_engram_device(weight,*rows,row_order,lookups,identity,grant,engram_embedding,storage.stream());auto gate=constant(prefix+"engram_gate.weight",4,5120);engram_forward_device(current,engram_embedding,artifact.source_tensor(prefix+"engram_kv.weight"),gate.value,engram_mask,engram_residual,engram_work,config,storage.stream(),callback);hipcheck(hipMemcpyAsync(current.data,engram_residual.data,current.bytes,hipMemcpyDeviceToDevice,reinterpret_cast<hipStream_t>(storage.stream())));}
   // Exact attention-input HC residual: after Engram, before mHC/block.
   if(tap_sink&&layer>=37&&layer<=39){
    need(layer==std::max(37u,partition.first)+tap_captures,"tap target layer order");
    validate_device_view(current,config.device);
    need(current.rows==1&&current.columns==20480&&current.scalar==DeviceScalar::Bfloat16InFloat32,"tap HC residual geometry");
    CoreTapFrame frame;frame.identity=identity;frame.instance=tap_instance;frame.position=position;frame.target_layer=layer;frame.capture_after_layer=layer-1;frame.residual=current;frame.stream=storage.stream();frame.partition_first=partition.first;frame.partition_end=partition.end;frame.activation_generation=projection.graph_activation();
    tap_sink->capture(frame);++tap_captures;
   }
   BlockConstants bc{constant(prefix+"hc_attn_scale.weight",1,3),constant(prefix+"hc_attn_base.weight",1,24),constant(prefix+"attn_norm.weight",1,5120),constant(prefix+"hc_ffn_scale.weight",1,3),constant(prefix+"hc_ffn_base.weight",1,24),constant(prefix+"ffn_norm.weight",1,5120)};
   auto attn=[&](const DeviceView&x,const DeviceView&y,void*stream){SwaConstants c{constant(prefix+"attn_q_a_norm.weight",1,1280),constant(prefix+"attn_kv_a_norm.weight",1,512),constant(prefix+"attn_sinks.weight",1,64)};SharedAttentionUpdate update;if(layer>=2)update=[&](const DeviceView&qr,void*s){return shared(layer,x,qr,s);};attention_step_device(artifact,layer,x,y,windows[layer],attention,c,identity.epoch,layer>=2,update,config,stream,callback);};
   auto moe=[&](const DeviceView&x,const DeviceView&y,void*stream){auto b=constant(prefix+"exp_probs_b.bias",1,384),v=constant(prefix+"exp_probs_b_vl.bias",1,384);std::vector<uint32_t> actual_ids;ExpertFrame frame{identity,{position}};ffn_forward_device(artifact,layer,x,image_mask,b.value,v.value,y,ffn,config,stream,callback,&actual_ids,&frame);need(actual_ids.size()==6,"actual sequence route count");for(auto expert:actual_ids){need(expert<384,"actual sequence expert range");route_union[layer][expert/64]|=uint64_t(1)<<(expert%64);}++routed_tokens[layer];};
   core_block_device(artifact,layer,current,incoming,next,block,bc,config,storage.stream(),callback,attn,moe);hipcheck(hipMemcpyAsync(incoming.data,block.ffn.pre.data,16,hipMemcpyDeviceToDevice,reinterpret_cast<hipStream_t>(storage.stream())));std::swap(current,next);if(prefill_operation)prefill_operation();
  }
 }
 CoreLayerCapture audit_layers(uint32_t first,uint32_t end,uint32_t token,uint64_t start,const std::vector<float>&residual,const std::vector<float>&pre,bool image){
  need(valid&&first<end&&end<=40&&start==position&&position<capacity&&residual.size()==20480&&pre.size()==4,"bounded actual layer input/range");
  if(fixture_range)need(*fixture_range==std::make_pair(first,end),"fixture state range changed");else{need(position==0,"fixture starts with its own sequence state");fixture_range=std::make_pair(first,end);}
  for(float x:residual){uint32_t bits;std::memcpy(&bits,&x,4);need(std::isfinite(x)&&!(bits&0xffff),"bounded residual is not BF16 input");}for(float x:pre)need(std::isfinite(x),"bounded pre nonfinite");
  try{auto hashes=history.append(position,{token},{uint8_t(!image)});
#ifdef STRATA_DEEPSEEK_T36_FIXTURE_CAPTURE
 fixture_remember_hashes(hashes);
#endif
uint8_t im=image?1:0,em=image?0:1;storage.upload(image_mask,&im,1);storage.upload(engram_mask,&em,1);storage.upload(residual_a,residual.data(),residual.size()*4);storage.upload(incoming,pre.data(),pre.size()*4);auto current=residual_a,next=residual_b;run_layers(current,next,incoming,hashes,first,end);CoreLayerCapture capture;capture.first=first;capture.end=end;capture.position=position;capture.residual.resize(20480);capture.pre.resize(4);storage.download(current,capture.residual.data(),capture.residual.size()*4);storage.download(incoming,capture.pre.data(),capture.pre.size()*4);for(unsigned l=first;l<end;++l)need(windows[l].position==position+1,"bounded actual state progress");++position;return capture;}catch(...){valid=false;throw;}
 }
 void head_device(const DeviceView&current){auto callback=projection.callback();mhc_pre_device(current,incoming,output_collapsed,storage.stream());mhc_rms_device(output_collapsed,output_norm_inverse,storage.stream());mhc_norm_device(output_collapsed,output_norm_inverse,constant("output_norm.weight",1,5120).value,output_normalized,storage.stream());tiled_projection(artifact.source_tensor("output.weight"),0,output_normalized,logits,1,config,storage.stream(),callback);}
 std::vector<float> step(uint32_t token,uint64_t start,bool image,bool emit_logits=true){need(valid&&!fixture_range&&start==position&&position<capacity,"Core sequence position/storage");try{
  if(tap_sink)tap_captures=0;
  std::vector<uint8_t>mask{uint8_t(!image)};auto hashes=history.append(position,{token},mask);
#ifdef STRATA_DEEPSEEK_T36_FIXTURE_CAPTURE
 fixture_remember_hashes(hashes);
#endif
need(hashes.size()==48,"actual Engram hash heads");uint8_t image_byte=image?1:0,engram_byte=image?0:1;storage.upload(image_mask,&image_byte,1);storage.upload(engram_mask,&engram_byte,1);embedding_device(token);float initial[4]={1,0,0,0};storage.upload(incoming,initial,sizeof(initial));auto current=residual_a,next=residual_b;auto callback=projection.callback();
  run_layers(current,next,incoming,hashes,0,40);
  if(tap_sink)need(tap_captures==3,"missing successful token taps");
  if(!emit_logits){storage.drain();for(auto&state:windows)need(state.position==position+1,"all40 state progress");++position;return {};}
  head_device(current);std::vector<float> result(129280);storage.download(logits,result.data(),result.size()*4);for(auto&state:windows)need(state.position==position+1,"all40 state progress");++position;return result;
 }catch(...){valid=false;throw;}}
};

#ifdef STRATA_T45_TEST
static bool t45_publication_failure=false;
void t45_fail_next_publication(){t45_publication_failure=true;}
#endif
namespace {
void partition_publish(PartitionBoundary&target,const PartitionBoundary&source){
#ifdef STRATA_T45_TEST
 if(t45_publication_failure){t45_publication_failure=false;throw std::bad_alloc();}
#endif
 target=source;
}
struct PartitionDeviceScope {int previous=-1;explicit PartitionDeviceScope(int device){hipcheck(hipGetDevice(&previous));hipcheck(hipSetDevice(device));}~PartitionDeviceScope(){if(previous>=0)hipSetDevice(previous);}};
bool partition_identity(const measurement::Identity&a,const measurement::Identity&b){return a.request_id==b.request_id&&a.epoch==b.epoch&&a.phase==b.phase&&a.fixture_sha256==b.fixture_sha256&&a.asset_sha256==b.asset_sha256&&a.bundle_sha256==b.bundle_sha256;}
bool partition_view(const DeviceView&a,const DeviceView&b){return a.data==b.data&&a.bytes==b.bytes&&a.rows==b.rows&&a.columns==b.columns&&a.scalar==b.scalar&&a.device==b.device&&a.owner==b.owner&&a.generation==b.generation;}
bool partition_shared_metadata(const PartitionShared&a,const PartitionShared&b){return a.kind==b.kind&&a.writer==b.writer&&a.compressor==b.compressor&&a.ratio==b.ratio&&a.position==b.position&&a.epoch==b.epoch&&a.published_rows==b.published_rows&&a.valid==b.valid;}
using PartitionSharedKey=std::pair<PartitionDataKind,uint32_t>;
std::set<PartitionSharedKey> partition_imports(PartitionSpec spec){
 std::set<PartitionSharedKey> result;
 for(unsigned layer=spec.first;layer<spec.end;++layer){auto role=attention_role(layer);
  if(role.kv_writer<spec.first){result.emplace(PartitionDataKind::Compressed,role.kv_writer);result.emplace(PartitionDataKind::IndexKeys,role.kv_writer);}
  if(role.index_writer<spec.first)result.emplace(PartitionDataKind::Selection,role.index_writer);
  if(layer==role.index_writer&&layer>=24&&20<spec.first)result.emplace(PartitionDataKind::Candidates,20);
 }return result;
}
}
CorePartition::CorePartition(const Artifact&a,const engram::Config&e,cache::PrimarySupply&w,cache::RowSupply*r,measurement::Identity identity,CoreConfig config,uint64_t capacity,PartitionSpec spec,const CorePartition*upstream):spec_(spec),upstream_(upstream){
 need(spec.first<spec.end&&spec.end<=40&&!config.experts,"specific contiguous partition declaration");
 if(spec.first){need(upstream&&upstream->spec_.first==0&&upstream->spec_.end==spec.first&&spec.end==40,"two contiguous partition source");auto&source=*upstream->sequence_->p_;need(&source.artifact==&a&&partition_identity(source.identity,identity)&&source.config.device!=config.device,"original source/Identity/distinct device binding");}
 else need(!upstream,"first partition cannot import a boundary");
 PartitionDeviceScope current(config.device);check_device_stream(w.stream_handle(),config.device);sequence_.reset(new CoreSequence());sequence_->p_=std::make_unique<CoreSequence::Impl>(a,e,w,r,std::move(identity),config,capacity,spec);
}
void CorePartition::routing_policy(std::shared_ptr<routing::Policy>p){sequence_->routing_policy(std::move(p));}
void CorePartition::routing_decode(bool b)noexcept{sequence_->p_->config.routing_decode=b;}
CorePartition::~CorePartition(){if(!sequence_)return;if(borrowed_){sequence_.release();std::terminate();}try{PartitionDeviceScope current(sequence_->p_->config.device);sequence_.reset();}catch(...){sequence_.release();std::terminate();}}
PartitionBoundary CorePartition::targets(const PartitionBoundary&source)const{
 const auto&p=*sequence_->p_;need(p.valid&&!borrowed_&&upstream_&&upstream_->sequence_->p_->valid&&upstream_->borrowed_,"live pending partition source/target");const auto&actual=upstream_->current_;
 need(source.instance&&source.instance==upstream_->instance_&&source.generation==actual.generation&&source.generation==source.position+1&&source.position==p.position&&source.next_layer==spec_.first&&source.raw_token==actual.raw_token&&source.image==actual.image&&partition_identity(source.identity,p.identity)&&partition_identity(source.identity,actual.identity),"boundary generation/position/token/epoch/source");
 need(partition_view(source.residual,actual.residual)&&partition_view(source.pre,actual.pre)&&source.stream==actual.stream,"original boundary views/stream");
 {PartitionDeviceScope current(source.residual.device);validate_device_view(source.residual,source.residual.device);validate_device_view(source.pre,source.residual.device);check_device_stream(source.stream,source.residual.device);checked_device_view(source.residual.data,source.residual.bytes,1,20480,DeviceScalar::Bfloat16InFloat32,source.residual.device,*source.residual.owner);checked_device_view(source.pre.data,source.pre.bytes,1,4,DeviceScalar::Float32,source.residual.device,*source.pre.owner);}
 auto required=partition_imports(spec_);std::set<PartitionSharedKey>seen;PartitionBoundary result=source;result.residual=p.residual_a;result.pre=p.incoming;result.logits={};result.stream=p.storage.stream();
 for(auto&item:result.shared){PartitionSharedKey key{item.kind,item.writer};need(required.count(key)&&seen.insert(key).second,"exact needed cross-cut shared state");auto original=std::find_if(actual.shared.begin(),actual.shared.end(),[&](const auto&x){return x.kind==item.kind&&x.writer==item.writer;});need(original!=actual.shared.end()&&partition_shared_metadata(item,*original)&&partition_view(item.value,original->value),"shared original descriptor/source/geometry");
  need(item.valid&&item.epoch==p.identity.epoch&&item.position==p.position&&item.ratio==(item.compressor==20?1u:2u)&&item.published_rows==(p.position+1)/item.ratio,"current source publication metadata");unsigned slot=item.compressor==2?0:item.compressor==8?1:item.compressor==14?2:3;need(p.compression[slot].writer==item.compressor&&item.compressor<spec_.first,"source writer ownership");
  DeviceView destination;
  if(item.kind==PartitionDataKind::Compressed){destination=p.compression[slot].cache;destination.rows=item.published_rows;}
  else if(item.kind==PartitionDataKind::IndexKeys){destination=p.keys[slot].keys;destination.rows=item.published_rows;}
  else if(item.kind==PartitionDataKind::Selection){need(item.writer==attention_role(spec_.first).index_writer,"current selection writer");destination=p.index.selected;destination.columns=std::min<uint64_t>(512,item.published_rows);}
  else{need(item.writer==20&&item.compressor==20,"source20 candidate writer");destination=p.candidates.scores;destination.columns=item.published_rows;}
  if(item.published_rows){PartitionDeviceScope current(p.config.device);validate_device_view(destination,p.config.device);need(destination.rows*destination.columns*scalar_bytes(destination.scalar)<=destination.bytes,"mirror target valid capacity");}
  item.value=destination;
 }need(seen==required,"missing required shared state");return result;
}
PartitionBoundary CorePartition::advance(uint32_t token,uint64_t start,bool image,const PartitionBoundary*incoming,bool emit_logits,const std::function<void()>&safe_operation){
 auto&p=*sequence_->p_;need(!p.operation_active,"nested Core partition operation");p.operation_active=true;ScopedOperationClear operation{p.operation_active};need(p.valid&&!borrowed_&&start==p.position&&p.position<p.capacity&&token<129280,"partition input/order/storage");PartitionBoundary accepted;
 if(spec_.first){need(incoming&&upstream_&&incoming->raw_token==token&&incoming->position==start&&incoming->image==image,"partition input boundary");auto original=upstream_->current_;original.shared.clear();for(auto&item:incoming->shared){auto found=std::find_if(upstream_->current_.shared.begin(),upstream_->current_.shared.end(),[&](const auto&x){return x.kind==item.kind&&x.writer==item.writer;});need(found!=upstream_->current_.shared.end(),"unpublished source kind");original.shared.push_back(*found);}accepted=targets(original);
  need(incoming->instance==accepted.instance&&incoming->generation==accepted.generation&&partition_identity(incoming->identity,accepted.identity)&&incoming->next_layer==accepted.next_layer&&incoming->stream==accepted.stream&&partition_view(incoming->residual,accepted.residual)&&partition_view(incoming->pre,accepted.pre)&&incoming->shared.size()==accepted.shared.size(),"destination-owned boundary targets");
  for(size_t i=0;i<accepted.shared.size();++i)need(partition_shared_metadata(incoming->shared[i],accepted.shared[i])&&partition_view(incoming->shared[i].value,accepted.shared[i].value),"destination shared descriptor exact");
 }else need(!incoming,"first partition uses original token embedding");
 PartitionDeviceScope device(p.config.device);ScopedProgressClear progress{p.prefill_operation};
 try{
  p.prefill_operation=safe_operation;auto hashes=p.history.append(p.position,{token},{uint8_t(!image)});
#ifdef STRATA_DEEPSEEK_T36_FIXTURE_CAPTURE
 p.fixture_remember_hashes(hashes);
#endif
need(hashes.size()==48,"partition original history");uint8_t im=image?1:0,em=image?0:1;p.storage.upload(p.image_mask,&im,1);p.storage.upload(p.engram_mask,&em,1);
  if(spec_.first){
   for(auto&item:accepted.shared){unsigned slot=item.compressor==2?0:item.compressor==8?1:item.compressor==14?2:3;auto&state=p.compression[slot];auto&key=p.keys[slot];need(state.published_rows<=item.published_rows&&key.rows<=item.published_rows,"monotonic mirror rows");
    if(item.kind==PartitionDataKind::Compressed){state.published_rows=item.published_rows;state.position=p.position+1;state.epoch=item.epoch;state.valid=true;}
    else if(item.kind==PartitionDataKind::IndexKeys){key.rows=item.published_rows;key.epoch=item.epoch;key.valid=true;}
    else if(item.kind==PartitionDataKind::Selection){p.selector=item.writer;p.selection_rows=item.published_rows;p.selection_position=item.position;p.selection_epoch=item.epoch;p.selection_valid=true;}
    else{p.candidates.rows=item.published_rows;p.candidates.position=item.position;p.candidates.epoch=item.epoch;p.candidates.valid=true;}
   }
  }else{p.embedding_device(token);float initial[4]={1,0,0,0};p.storage.upload(p.incoming,initial,sizeof(initial));}
  auto current=p.residual_a,next=p.residual_b;p.run_layers(current,next,p.incoming,hashes,spec_.first,spec_.end);if(spec_.end==40&&emit_logits)p.head_device(current);p.storage.drain();for(unsigned layer=spec_.first;layer<spec_.end;++layer)need(p.windows[layer].position==p.position+1,"owned partition state progress");
  PartitionBoundary result;result.instance=instance_;result.identity=p.identity;result.generation=++generation_;result.position=p.position;result.raw_token=token;result.image=image;result.next_layer=spec_.end;result.residual=current;result.pre=p.incoming;result.stream=p.storage.stream();if(spec_.end==40&&emit_logits)result.logits=p.logits;
  for(unsigned i=0;i<4;++i){auto&state=p.compression[i];auto&keys=p.keys[i];if(!state.cache.data)continue;for(auto kind:{PartitionDataKind::Compressed,PartitionDataKind::IndexKeys}){PartitionShared shared;shared.kind=kind;shared.writer=shared.compressor=state.writer;shared.ratio=state.ratio;shared.position=p.position;shared.epoch=p.identity.epoch;shared.published_rows=state.published_rows;shared.valid=state.valid&&keys.valid;shared.value=kind==PartitionDataKind::Compressed?state.cache:keys.keys;shared.value.rows=state.published_rows;result.shared.push_back(shared);}}
  if(p.selection_valid){PartitionShared shared;shared.kind=PartitionDataKind::Selection;shared.writer=p.selector;shared.compressor=attention_role(p.selector).kv_writer;shared.ratio=shared.compressor==20?1:2;shared.position=p.selection_position;shared.epoch=p.selection_epoch;shared.published_rows=p.selection_rows;shared.valid=true;shared.value=p.index.selected;shared.value.columns=std::min<uint64_t>(512,p.selection_rows);result.shared.push_back(shared);}
  if(p.candidates.valid){PartitionShared shared;shared.kind=PartitionDataKind::Candidates;shared.writer=shared.compressor=20;shared.ratio=1;shared.position=p.candidates.position;shared.epoch=p.candidates.epoch;shared.published_rows=p.candidates.rows;shared.valid=true;shared.value=p.candidates.scores;shared.value.columns=p.candidates.rows;result.shared.push_back(shared);}
  partition_publish(current_,result);++p.position;borrowed_=true;return result;
 }catch(...){p.valid=false;try{p.storage.drain();}catch(...){sequence_.release();std::terminate();}throw;}
}
CorePartitionTapBinding CorePartition::prepare_partition_tap(uint64_t expected)const{
 const auto&p=*sequence_->p_;need(p.valid&&!p.operation_active&&!p.prefill_operation&&!borrowed_&&expected==p.position&&expected<p.capacity&&p.storage.lease().active,"healthy partition tap owner/cursor/activation");
 CorePartitionTapBinding b;b.identity=p.identity;b.instance=instance_;b.range=spec_;b.position=expected;b.activation_generation=p.projection.graph_activation();b.owner=&p.storage.lease();b.owner_generation=b.owner->generation;b.device=p.config.device;b.stream=p.storage.stream();return b;
}
PartitionBoundary CorePartition::advance_tapped(uint32_t token,uint64_t start,bool image,const PartitionBoundary*incoming,bool emit,const std::function<void()>&progress,const CorePartitionTapBinding&b,CoreTapSink&sink){
 auto expected=prepare_partition_tap(start);need(partition_identity(b.identity,expected.identity)&&b.instance==expected.instance&&b.range.first==expected.range.first&&b.range.end==expected.range.end&&b.position==expected.position&&b.activation_generation==expected.activation_generation&&b.owner==expected.owner&&b.owner_generation==expected.owner_generation&&b.device==expected.device&&b.stream==expected.stream,"partition tap exact binding");
 auto&p=*sequence_->p_;need(!p.tap_sink,"partition tap already armed");p.tap_sink=&sink;p.tap_instance=instance_;p.tap_captures=0;
 struct Clear{CoreTapSink*&sink;~Clear(){sink=nullptr;}}clear{p.tap_sink};
 auto out=advance(token,start,image,incoming,emit,progress);
 need(p.tap_captures==std::max(37u,spec_.end)-std::max(37u,spec_.first),"partition missing successful taps");return out;
}
bool CorePartition::retire_projection_graph(){return !sequence_||(!borrowed_&&sequence_->retire_projection_graph());}
void CorePartition::retire_boundary(uint64_t generation,void*stream){auto&p=*sequence_->p_;need(borrowed_&&generation==generation_&&current_.generation==generation,"live partition boundary return");PartitionDeviceScope current(p.config.device);check_device_stream(stream,p.config.device);hipcheck(hipStreamSynchronize(reinterpret_cast<hipStream_t>(stream)));p.storage.drain();borrowed_=false;current_={};}
std::vector<float> CorePartition::download_logits(const PartitionBoundary&boundary){auto&p=*sequence_->p_;need(p.valid&&borrowed_&&spec_.end==40&&boundary.instance==instance_&&boundary.generation==generation_&&partition_view(boundary.logits,current_.logits)&&boundary.logits.data,"requested head output");PartitionDeviceScope current(p.config.device);std::vector<float>result(129280);p.storage.download(boundary.logits,result.data(),result.size()*4);return result;}
#ifdef STRATA_DEEPSEEK_T36_FIXTURE_CAPTURE
void CorePartition::fixture_visit_state(const FixtureStateVisitor&visitor){need(!borrowed_&&!current_.instance,"fixture partition boundary must be retired");sequence_->fixture_visit_state(visitor);}
#endif
void CorePartition::invalidate_and_drain(){auto&p=*sequence_->p_;p.valid=false;PartitionDeviceScope current(p.config.device);p.storage.drain();}
void CorePartition::drain(){auto&p=*sequence_->p_;PartitionDeviceScope current(p.config.device);p.storage.drain();}
void CorePartition::request_preflight()const{
 if(borrowed_||current_.instance)throw RequestAdoptionRefused("request adoption has borrowed partition boundary");
 sequence_->request_preflight();
}
void CorePartition::quiesce_request(){request_preflight();sequence_->quiesce();}
bool CorePartition::request_valid()const{return sequence_&&sequence_->p_&&sequence_->p_->valid;}
CoreRequestBinding CorePartition::prepare_request(const measurement::Identity&id,uint64_t position){
 request_preflight();
 auto prepared=sequence_->prepare_request(id,position);
 prepared.instance=std::make_shared<const uint8_t>(0);
 return prepared;
}
void CorePartition::adopt_request(CoreRequestBinding&&prepared) noexcept {
 sequence_->adopt_request(std::move(prepared));instance_.swap(prepared.instance);
 // Numeric generation is position+1 on the next advance, never adoption count.
}
uint64_t CorePartition::position()const{return sequence_->position();}
uint64_t CorePartition::explicit_device_owned()const{return sequence_->explicit_device_owned();}
CoreRuntimeStats CorePartition::runtime_stats()const{return sequence_->runtime_stats();}
CoreSequence::CoreSequence(const Artifact&a,const engram::Config&e,cache::PrimarySupply&w,cache::RowSupply&r,measurement::Identity id,CoreConfig config,uint64_t capacity):p_(std::make_unique<Impl>(a,e,w,&r,std::move(id),config,capacity)){}
CoreSequence::CoreSequence() noexcept=default;
CoreSequence::~CoreSequence()=default;
void CoreSequence::attach_prefill_preparation(CorePrefillPreparation value){
 need(p_&&p_->valid&&!p_->operation_active&&!p_->position&&p_->preparation_result.reason==CorePrefillReason::Unprepared,"prefill intent before token state");
 need(value.max_batch==1||value.max_batch==2||value.max_batch==4||value.max_batch==8,"supported prefill preparation capacity");
 // All caller/list allocation has completed before this no-throw publication.
 p_->preparation.required_f32_names.swap(value.required_f32_names);p_->preparation.max_batch=value.max_batch;
}
void CoreSequence::routing_policy(std::shared_ptr<routing::Policy>policy){
 if(!policy&&!p_->config.routing_policy)return;quiesce();auto&p=*p_;PartitionDeviceScope current(p.config.device);p.config.routing_decode=false;
 if(policy&&!policy->neutral()){
  if(!p.config.routing_delta.data)p.config.routing_delta=p.storage.allocate("routing.request.delta",40,384,DeviceScalar::Float32);
  p.storage.upload(p.config.routing_delta,policy->delta.data(),policy->delta.size()*sizeof(float));p.storage.drain();
 }
 p.config.routing_policy=std::move(policy);
}
bool CoreSequence::retire_projection_graph(){return !p_||(!p_->operation_active&&p_->projection.retire_graph());}
CoreLayerCapture CoreSequence::audit_layers(uint32_t first,uint32_t end,uint32_t token,uint64_t position,const std::vector<float>&residual,const std::vector<float>&pre,bool image){need(!p_->operation_active,"nested Core operation");p_->operation_active=true;ScopedOperationClear operation{p_->operation_active};return p_->audit_layers(first,end,token,position,residual,pre,image);}
std::vector<float> CoreSequence::step(uint32_t token,uint64_t position,bool image){need(!p_->operation_active,"nested Core operation");p_->operation_active=true;ScopedOperationClear operation{p_->operation_active};p_->config.routing_decode=true;try{auto out=p_->step(token,position,image);p_->config.routing_decode=false;return out;}catch(...){p_->config.routing_decode=false;throw;}}
void CoreSequence::request_preflight()const{
 auto require=[](bool b,const char*message){if(!b)throw RequestAdoptionRefused(message);};
 require(p_&&p_->valid&&!p_->operation_active&&!p_->prefill_operation,"healthy request quiescence");
 const auto&w=p_->weight;auto progress=w.progress();auto stats=w.stats();
 require(w.state()==cache::SupplyState::Idle&&w.prefetch_state()==cache::SupplyState::Idle&&progress.consumer==cache::SupplyState::Idle&&progress.fill==cache::SupplyState::Idle&&!progress.consumer_readers&&!progress.fill_writer&&!stats.outstanding_reads&&!stats.outstanding_read_bytes,"request adoption has live Primary owner");
 require(!p_->rows||p_->rows->request_idle(),"request adoption has live Row owner");
 require(!p_->config.experts||p_->config.experts->request_idle(),"request adoption has live Expert owner");
 if(p_->config.secondary_cache){auto stats=p_->config.secondary_cache->stats();require(stats.available&&!stats.retained_device_bytes&&!stats.retained_host_bytes,"secondary unavailable for request adoption; safe Primary fresh remains separate");}
}
void CoreSequence::quiesce(){
 request_preflight();
 try{PartitionDeviceScope current(p_->config.device);p_->storage.drain();if(p_->config.secondary_cache)p_->config.secondary_cache->cancel_and_drain();}catch(...){p_->valid=false;throw;}
 request_preflight();
}
#ifdef STRATA_DEEPSEEK_T36_FIXTURE_CAPTURE
void CoreSequence::fixture_visit_state(const FixtureStateVisitor&visitor){need(p_&&!p_->operation_active,"fixture completed-token visitor outside operation");p_->operation_active=true;ScopedOperationClear operation{p_->operation_active};auto&p=*p_;try{PartitionDeviceScope current(p.config.device);p.fixture_visit_state(visitor);}catch(...){p.valid=false;throw;}}
#endif
bool CoreSequence::request_valid()const noexcept{return p_&&p_->valid;}
void CoreSequence::invalidate_and_drain(){
 need(bool(p_),"live Core request owner");p_->valid=false;
 PartitionDeviceScope current(p_->config.device);p_->storage.drain();
}
CoreRequestBinding CoreSequence::prepare_request(const measurement::Identity&id,uint64_t position){
 request_preflight();
 need(p_&&p_->valid&&!p_->fixture_range&&!p_->prefill_operation&&position&&position==p_->position,"healthy processed request position");
 const auto&prior=p_->identity;
 need(!id.request_id.empty()&&id.epoch==prior.epoch&&id.phase==prior.phase&&id.fixture_sha256==prior.fixture_sha256&&id.asset_sha256==prior.asset_sha256&&id.bundle_sha256==prior.bundle_sha256,"request adoption persistent identity");
 request_preflight();
 CoreRequestBinding prepared;prepared.core=id;prepared.projection=id;
 quiesce();return prepared;
}
void CoreSequence::adopt_request(CoreRequestBinding&&prepared) noexcept {
 swap_request_identity(p_->identity,prepared.core);
 swap_request_identity(p_->projection.identity_,prepared.projection);
}
void CoreSequence::continue_request(const measurement::Identity&id,uint64_t position){
 auto prepared=prepare_request(id,position);request_preflight();adopt_request(std::move(prepared));
}
CoreOutput CoreSequence::prefill(const std::vector<uint32_t>&tokens,uint64_t position,const std::vector<uint8_t>&mask,const PrefillControl&control){
 need(!p_->operation_active&&p_->valid&&!p_->fixture_range&&!tokens.empty()&&(mask.empty()||mask.size()==tokens.size()),"prefill token/mask geometry or invalid sequence");
 need(position==p_->position&&position<=p_->capacity&&tokens.size()<=p_->capacity-position,"prefill caller context storage");
 for(auto token:tokens)need(token<129280,"prefill original token ID");
 for(auto x:mask)need(x<=1,"image mask value");
 p_->operation_active=true;ScopedOperationClear operation{p_->operation_active};
 CoreOutput out;out.vocabulary=129280;ScopedProgressClear progress_scope{p_->prefill_operation};
 auto diagnostic_start=PrefillDiagnosticClock::now();const char*diagnostic_status="exception";
 struct DiagnosticExit{Impl&owner;PrefillDiagnosticClock::time_point begin;const char*&status;CoreOutput&out;~DiagnosticExit()noexcept{owner.prefill_diagnostic("terminal",status,begin,out.processed);}}diagnostic_exit{*p_,diagnostic_start,diagnostic_status,out};
 auto cancel=[&]{p_->valid=false;p_->storage.drain();out.logits.clear();out.rows=0;out.cancelled=true;diagnostic_status="cancel";};
 try{
  if(control)p_->prefill_operation=[&]{if(!control(out.processed,tokens.size()))throw PrefillInterrupted{};};
  if(control&&!control(0,tokens.size())){cancel();return out;}
  p_->prefill_diagnostic("prepare_begin","started",diagnostic_start,0);
  p_->prepare_prefill();
  p_->prefill_diagnostic("prepare_end","completed",diagnostic_start,0);
  if(p_->config.full_logits)out.logits.reserve(size_t(mul(tokens.size(),129280)));
  for(size_t i=0;i<tokens.size();){
   uint32_t n=1;if(p_->wave){n=p_->preparation_result.selected_capacity;while(n>tokens.size()-i)n/=2;}
   if(i==0)p_->prefill_diagnostic("firstwork_begin",n>1?"wave":"serial",diagnostic_start,n);
   auto logits=n>1?p_->run_wave(tokens,mask,i,n,i+n==tokens.size(),i==0?&diagnostic_start:nullptr):p_->step(tokens[i],position+i,!mask.empty()&&mask[i],p_->config.full_logits||i+1==tokens.size());
   if(i==0)p_->prefill_diagnostic("firstwork_end","completed",diagnostic_start,n);
   i+=n;out.processed+=n;
   if(p_->config.full_logits)out.logits.insert(out.logits.end(),logits.begin(),logits.end());else out.logits=std::move(logits);
   if(control&&!control(out.processed,tokens.size())){cancel();return out;}
  }
  out.rows=p_->config.full_logits?tokens.size():1;diagnostic_status="success";return out;
 }catch(const PrefillInterrupted&){cancel();return out;}catch(...){p_->valid=false;p_->storage.drain();throw;}
}
CoreTapBinding CoreSequence::prepare_tap(uint64_t expected){
 need(p_->valid&&!p_->fixture_range&&!p_->operation_active&&!p_->prefill_operation&&p_->partition.first==0&&p_->partition.end==40&&p_->rows&&expected==p_->position&&expected<p_->capacity,"tap healthy full40 primary cursor");
 need(p_->storage.lease().active,"tap Core owner inactive");
 check_device_stream(p_->storage.stream(),p_->config.device);
 if(!p_->tap_instance)p_->tap_instance=std::make_shared<const uint8_t>(0);
 CoreTapBinding b;b.identity_=p_->identity;b.instance_=p_->tap_instance;b.position_=expected;b.device_=p_->config.device;return b;
}
void CoreSequence::validate_tap(const CoreTapBinding&b,uint64_t start)const{
 need(p_->valid&&!p_->fixture_range&&!p_->operation_active&&!p_->prefill_operation&&p_->partition.first==0&&p_->partition.end==40&&p_->rows&&p_->storage.lease().active,"tap healthy full40 primary owner");
 need(tap_binding_matches(b.identity_,p_->identity,b.instance_,p_->tap_instance,b.device_,p_->config.device,b.position_,start,p_->position,p_->capacity),"tap binding instance/identity/device/cursor");
 check_device_stream(p_->storage.stream(),p_->config.device);
}
std::vector<float> CoreSequence::step_tapped(uint32_t token,uint64_t start,const CoreTapBinding&b,CoreTapSink&sink){
 validate_tap(b,start);need(token<129280,"tap original token ID");
 p_->operation_active=true;p_->tap_sink=&sink;ScopedTapClear scope{p_->tap_sink,p_->operation_active};
 try{
  p_->config.routing_decode=true;struct RoutingReset{bool&v;~RoutingReset(){v=false;}}routing_reset{p_->config.routing_decode};auto logits=p_->step(token,start,false);p_->storage.drain();
  need(p_->position==start+1&&p_->tap_captures==3,"tap processed boundary");
  sink.processed(CoreTapToken{p_->identity,p_->tap_instance,start,p_->position,p_->storage.stream()});return logits;
 }catch(...){p_->valid=false;p_->storage.drain();throw;}
}
CoreOutput CoreSequence::prefill_tapped(const std::vector<uint32_t>&tokens,uint64_t start,const std::vector<uint8_t>&mask,const CoreTapBinding&b,CoreTapSink&sink,const PrefillControl&control){
 validate_tap(b,start);
 need(!tokens.empty()&&(mask.empty()||mask.size()==tokens.size())&&tokens.size()<=p_->capacity-start,"tap prefill token/mask/storage geometry");
 for(auto token:tokens)need(token<129280,"tap prefill original token ID");
 for(auto x:mask)need(x==0,"tap prefill initial text-only mask");
 p_->operation_active=true;p_->tap_sink=&sink;ScopedTapClear scope{p_->tap_sink,p_->operation_active};
 CoreOutput out;out.vocabulary=129280;ScopedProgressClear progress_scope{p_->prefill_operation};
 auto cancel=[&]{p_->valid=false;p_->storage.drain();out.logits.clear();out.rows=0;out.cancelled=true;};
 try{
  if(control)p_->prefill_operation=[&]{if(!control(out.processed,tokens.size()))throw PrefillInterrupted{};};
  if(control&&!control(0,tokens.size())){cancel();return out;}
  if(p_->config.full_logits)out.logits.reserve(size_t(mul(tokens.size(),129280)));
  for(size_t i=0;i<tokens.size();++i){
   auto logits=p_->step(tokens[i],start+i,false,p_->config.full_logits||i+1==tokens.size());
   p_->storage.drain();need(p_->position==start+i+1&&p_->tap_captures==3,"tap prefill processed boundary");
   ++out.processed;
   sink.processed(CoreTapToken{p_->identity,p_->tap_instance,start+i,p_->position,p_->storage.stream()});
   if(p_->config.full_logits)out.logits.insert(out.logits.end(),logits.begin(),logits.end());else out.logits=std::move(logits);
   if(control&&!control(out.processed,tokens.size())){cancel();return out;}
  }
  out.rows=p_->config.full_logits?tokens.size():1;return out;
 }catch(const PrefillInterrupted&){cancel();return out;}catch(...){p_->valid=false;p_->storage.drain();throw;}
}
uint64_t CoreSequence::position()const{return p_->position;}
CoreRuntimeStats CoreSequence::runtime_stats()const{CoreRuntimeStats s{p_->storage.explicit_owned_bytes(),p_->constant_source_bytes,p_->storage.upload_bytes(),p_->storage.download_bytes(),p_->route_union,p_->routed_tokens,sizeof(p_->route_union)+sizeof(p_->routed_tokens)};for(unsigned i=0;i<40;++i)s.state_positions[i]=p_->windows[i].position;for(unsigned i=0;i<4;++i){s.compressed_rows[i]=p_->compression[i].published_rows;s.key_rows[i]=p_->keys[i].rows;}s.prefill_preparation=p_->preparation_result;return s;}
uint64_t CoreSequence::explicit_device_owned()const{return add(add(p_->storage.explicit_owned_bytes(),p_->config.secondary_cache?p_->config.secondary_cache->stats().primary_device_owned:0),add(p_->weight.stats().device_owned,p_->rows?p_->rows->stats().device_owned:0));}
CoreProjection::CoreProjection(cache::PrimarySupply&w,cache::RowSupply&r,measurement::Identity id,CoreIoGrant grant,cache::SecondaryCache*cache):CoreProjection(w,&r,std::move(id),grant,cache){}
CoreProjection::CoreProjection(cache::PrimarySupply&w,measurement::Identity id,CoreIoGrant grant,cache::SecondaryCache*cache):CoreProjection(w,nullptr,std::move(id),grant,cache){}
CoreProjection::CoreProjection(cache::PrimarySupply&w,cache::RowSupply*r,measurement::Identity id,CoreIoGrant grant,cache::SecondaryCache*cache):weight_(w),rows_(r),identity_(std::move(id)),grant_(grant),cache_(cache){need(grant.max_outstanding&&grant.max_outstanding_bytes>=4096,"one aligned source read must fit");graph_activation_=weight_.begin_graph_activation();}
CoreProjection::~CoreProjection(){try{if(!retire_graph())std::terminate();}catch(...){std::terminate();}}
bool CoreProjection::retire_graph(){if(!graph_activation_)return true;if(!weight_.end_graph_activation(graph_activation_))return false;graph_activation_=0;return true;}
void CoreProjection::advance(int timeout){
 if(rows_){advance_core_io(weight_,*rows_,order_,grant_,cache::Kind::Expert,timeout);return;}
 weight_.poll_io(timeout);weight_.poll_device();auto before=weight_.io_snapshot();
 need(before.outstanding_reads<=grant_.max_outstanding&&before.outstanding_read_bytes<=grant_.max_outstanding_bytes,"secondary actual read credit");
 if(before.outstanding_reads<grant_.max_outstanding&&before.outstanding_read_bytes<grant_.max_outstanding_bytes){
  auto available=grant_.max_outstanding_bytes-before.outstanding_read_bytes;auto bytes=weight_.issue_reads(1,available);auto after=weight_.io_snapshot();
  need(bytes<=available&&after.issued_reads>=before.issued_reads&&after.issued_reads-before.issued_reads<=1&&after.issued_read>=before.issued_read&&after.issued_read-before.issued_read==bytes,"secondary issued read credit");
 }
}
DeviceProject CoreProjection::callback(){return [this](const SourceTile&t,const DeviceView&x,const DeviceView&y,uint64_t b,void*s){(*this)(t,x,y,b,s);};}
void CoreProjection::operator()(const SourceTile&t,const DeviceView&x,const DeviceView&y,uint64_t batch,void*stream){
 auto derived=source_tile(t.original,t.matrix,t.row_first,t.row_count);
 need(derived.absolute_offset==t.absolute_offset&&derived.bytes==t.bytes&&derived.k==t.k&&derived.type==t.type,"original-bound projection tile");
 validate_device_view(x,x.device);validate_device_view(y,x.device);check_device_stream(stream,x.device);
 need(x.owner==y.owner&&x.generation==y.generation&&batch==x.rows&&batch==y.rows&&x.columns==t.k&&y.columns==t.original.span.dims_ggml[1],"activation/output lease or full stride");
 cache::SupplyMatrix m{t.original,t.absolute_offset,t.bytes,t.type,size_t(t.row_count),size_t(t.k)};
 m.row_tile=true;m.original_matrix=t.matrix;m.output_row_first=t.row_first;
 need(weight_.begin(m,identity_),"resident weight admission");
 try{
  auto output_offset=mul(t.row_first,4);need(output_offset<y.bytes,"tile output offset");
  // Only our newly admitted, unissued permit miss can be displaced by S.
  // Existing Ready/RAM DMA/other prefetch work is never cancelled for this path.
  auto progress=weight_.progress();
  if(cache_&&progress.permit_only&&progress.demand_fill&&weight_.state()==cache::SupplyState::Reading&&progress.issued_read_bytes==0&&cache_->contains(m)){
   weight_.cancel();while(weight_.state()!=cache::SupplyState::Cancelled){weight_.poll_io(0);weight_.poll_device();need(weight_.state()!=cache::SupplyState::Quarantined,"cache-hit unissued cancellation unknown");}
   (void)weight_.take(identity_);
   if(cache_->project_hit(m,identity_,(const float*)x.data,x.bytes,(float*)((uint8_t*)y.data+output_offset),y.bytes-output_offset,size_t(batch),size_t(y.columns),stream,*x.owner))return;
   need(weight_.begin(m,identity_),"cache bypass original Primary admission");
  }
  while(weight_.state()!=cache::SupplyState::Ready){advance(10);need(weight_.state()!=cache::SupplyState::Cancelled&&weight_.state()!=cache::SupplyState::Quarantined,"weight request cancelled/quarantined");}
  if(cache_)cache_->populate(weight_,m,identity_);
  weight_.launch_device(size_t(batch),(const float*)x.data,x.bytes,(float*)((uint8_t*)y.data+output_offset),y.bytes-output_offset,size_t(y.columns),stream,*x.owner,&identity_);
  while(weight_.state()==cache::SupplyState::Kernel)advance(0);
  need(weight_.take_device(identity_),"late device projection identity");
 }catch(...){
  // Preserve event/owner storage until actual drain; no inferred completion.
  if(weight_.state()!=cache::SupplyState::Idle&&weight_.state()!=cache::SupplyState::Quarantined){weight_.cancel();while(weight_.state()!=cache::SupplyState::Cancelled&&weight_.state()!=cache::SupplyState::Quarantined){weight_.poll_io(10);weight_.poll_device();}}
  if(weight_.state()==cache::SupplyState::Cancelled){try{weight_.take_device(identity_);}catch(...){/* pre-launch cancellation uses the original host take state */weight_.take(identity_);}}
  throw;
 }
}
uint64_t scalar_bytes(DeviceScalar s){switch(s){case DeviceScalar::Float32:case DeviceScalar::Bfloat16InFloat32:case DeviceScalar::UInt32:case DeviceScalar::Int32:return 4;case DeviceScalar::Int64:return 8;case DeviceScalar::Bfloat16:return 2;case DeviceScalar::UInt8:return 1;}throw std::runtime_error("unknown device scalar");}
void validate_device_view(const DeviceView&v,int device){
 need(v.data&&v.rows&&v.columns&&v.device==device&&v.owner&&v.owner->active&&v.owner->generation==v.generation,"device view owner/device/generation");
 need(mul(mul(v.rows,v.columns),scalar_bytes(v.scalar))<=v.bytes,"device view byte geometry");
}
void check_device_stream(void*stream,int device){need(stream,"explicit device stream");int current=-1,sd=-1;hipcheck(hipGetDevice(&current));hipcheck(hipStreamGetDevice(reinterpret_cast<hipStream_t>(stream),&sd));need(current==device&&sd==device,"current/stream device mismatch");}
DeviceView checked_device_view(void*data,uint64_t bytes,uint64_t rows,uint64_t columns,DeviceScalar scalar,int device,const quant::ProjectionLease&owner){DeviceView v{data,bytes,rows,columns,scalar,device,&owner,owner.generation};validate_device_view(v,device);hipPointerAttribute_t attr{};hipcheck(hipPointerGetAttributes(&attr,data));need(attr.type==hipMemoryTypeDevice&&attr.device==device,"device pointer ownership");hipDeviceptr_t base=nullptr;size_t capacity=0;hipcheck(hipMemGetAddressRange(&base,&capacity,reinterpret_cast<hipDeviceptr_t>(data)));uint64_t offset=reinterpret_cast<uintptr_t>(data)-reinterpret_cast<uintptr_t>(base);need(offset<=capacity&&bytes<=capacity-offset&&reinterpret_cast<uintptr_t>(data)%scalar_bytes(scalar)==0,"device pointer range/alignment");return v;}
void audit_stage(DeviceAudit*a,const std::string&name,const DeviceView&v,void*stream){if(a)a->stage(name,v,stream);}
SourceTile source_tile(const SourceTensor&s,uint64_t matrix,uint64_t first,uint64_t count){
 const auto& t=s.span;need(t.dims_ggml.size()==2||t.dims_ggml.size()==3,"projection requires original rank2/3");
 auto k=t.dims_ggml[0],rows=t.dims_ggml[1],matrices=t.dims_ggml.size()==3?t.dims_ggml[2]:1;
 need(k&&rows&&matrix<matrices&&count&&first<rows&&count<=rows-first,"original matrix/output row range");
 auto rowbytes=quant::packed_bytes(t.type_id,k);need(rowbytes==t.row_bytes,"original native row layout");
 need(mul(mul(rowbytes,rows),matrices)==t.bytes,"original tensor byte geometry");
 auto offset=add(t.absolute_offset,mul(add(mul(matrix,rows),first),rowbytes));auto n=mul(count,rowbytes);
 need(t.shard_index==s.source.shard_index&&!s.source.original_path.empty()&&s.source.revision.size()==40&&s.source.lfs_sha256.size()==64,"original source identity");
 need(t.absolute_offset<=s.source.original_size&&t.bytes<=s.source.original_size-t.absolute_offset&&offset>=t.absolute_offset&&n<=add(t.absolute_offset,t.bytes)-offset,"original source span");
 return {s,matrix,first,count,offset,n,k,t.type_id};
}
std::vector<SourceTile> row_tiles(const SourceTensor&s,uint64_t matrix,uint64_t byte_budget,uint64_t row_budget){
 need(byte_budget&&row_budget,"empty tile budget");auto one=source_tile(s,matrix,0,1);uint64_t n=std::min(byte_budget/one.bytes,row_budget);need(n,"one full-K row does not fit");
 std::vector<SourceTile> out;auto rows=s.span.dims_ggml[1];for(uint64_t first=0;first<rows;first+=std::min(n,rows-first))out.push_back(source_tile(s,matrix,first,std::min(n,rows-first)));return out;
}
std::vector<uint32_t> batch_waves(uint64_t n,uint32_t maximum){need(n&&maximum,"empty batch/window");std::vector<uint32_t> out;while(n){uint32_t b=8;while(b>n||b>maximum)b/=2;out.push_back(b);n-=b;}return out;}
uint64_t concurrent_peak(const std::vector<AllocationLife>&life){
 struct Event{uint64_t time,bytes;bool begin;};std::vector<Event> events;std::set<std::string> names;
 for(const auto&x:life){need(!x.name.empty()&&names.insert(x.name).second&&x.begin<x.end,"unique allocation lifetime");events.push_back({x.begin,x.bytes,true});events.push_back({x.end,x.bytes,false});}
 std::sort(events.begin(),events.end(),[](const auto&a,const auto&b){return a.time<b.time||(a.time==b.time&&a.begin<b.begin);});
 uint64_t live=0,peak=0;for(const auto&e:events){if(e.begin)live=add(live,e.bytes);else{need(live>=e.bytes,"allocation lifetime underflow");live-=e.bytes;}peak=std::max(peak,live);}need(!live,"unclosed allocation lifetimes");return peak;
}
uint64_t CoreMemory::explicit_owned()const{return add(add(add(weights,residual_state),add(activations,scratch)),add(row_output,audit));}
void tiled_projection(const SourceTensor&s,uint64_t matrix,const DeviceView&input,const DeviceView&output,uint64_t batch,const CoreConfig&cfg,void* stream,const DeviceProject&project){
 (void)source_tile(s,matrix,0,1);
 validate_device_view(input,cfg.device);validate_device_view(output,cfg.device);need(batch&&project&&stream,"projection stream/callback/batch");
 need(input.rows==batch&&output.rows==batch&&input.columns==s.span.dims_ggml[0]&&output.columns==s.span.dims_ggml[1],"projection original full-K geometry");
 need(input.scalar==DeviceScalar::Float32||input.scalar==DeviceScalar::Bfloat16InFloat32,"projection input scalar");need(output.scalar==DeviceScalar::Float32,"projection output scalar");
 // Callback writes each row directly into strided batch-major output. Its view
 // describes the full output stride; local row_first selects the actual columns.
 for(const auto&t:row_tiles(s,matrix,cfg.tile_bytes,cfg.tile_rows)){uint64_t from=0;
  for(auto n:batch_waves(batch,uint32_t(std::min<uint64_t>(cfg.active_batch,UINT32_MAX)))){
   auto x=input,y=output;auto dx=mul(mul(from,x.columns),4),dy=mul(mul(from,y.columns),4);
   x.data=reinterpret_cast<void*>(add(reinterpret_cast<uintptr_t>(x.data),dx));x.bytes-=dx;x.rows=n;
   y.data=reinterpret_cast<void*>(add(reinterpret_cast<uintptr_t>(y.data),dy));y.bytes-=dy;y.rows=n;
   project(t,x,y,n,stream);from+=n;
  }
 }
}
}
