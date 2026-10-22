// T38-owned primitives. Existing native projection/attention math is not modified.
#include "draft.hpp"
#include "target_adapter.hpp"
#include "session.hpp"
#include "../sampling.hpp"
#include <core.hpp>
#include "../execution/layer_split.hpp"
#include "../../../native/device/roles.hpp"
#include <thread>
#include <map>
#include <set>
#include <device_ops.hpp> // build must bind r4 consumed immutable include directory
#include <hip/hip_runtime.h>
#include <cmath>
#include <stdexcept>
namespace strata_ext::dspark::t38 {
using namespace strata_ext::deepseek41;
namespace {
void need(bool b,const char*m){if(!b)throw std::invalid_argument(m);}
void check(hipError_t e){if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));}
uint64_t mul(uint64_t a,uint64_t b){need(!b||a<=UINT64_MAX/b,"draft geometry overflow");return a*b;}
void view(const DeviceView&v,int d,uint64_t rows,uint64_t cols,DeviceScalar t){validate_device_view(v,d);need(v.rows==rows&&v.columns==cols&&v.scalar==t,"draft view shape/type");}
void distinct(const DeviceView&a,const DeviceView&b){auto x=reinterpret_cast<uintptr_t>(a.data),y=reinterpret_cast<uintptr_t>(b.data);need(x<y?y-x>=a.bytes:x-y>=b.bytes,"draft input/output alias");}
hipStream_t stream(void*s,int d){check_device_stream(s,d);return reinterpret_cast<hipStream_t>(s);}
// T38_HOST_TRANSFER_BEGIN
// body must include the positive completion check, not merely enqueue success.
template<class Transfer>void host_transfer(DraftHostScratch&host,Transfer&&body){
 need(host.valid&&!host.pending,"host transfer owner unavailable");host.pending=true;
 try{body();host.pending=false;}catch(...){host.valid=false;throw;}
}
// Compatibility for standalone leaf callers without a provider scratch argument.
// The actual network always passes its provider-owned scratch.
template<class Drain>void retain_unknown_host(std::unique_ptr<DraftHostScratch>&host,Drain&&drain)noexcept{
 if(host&&host->pending){try{drain();host->pending=false;}catch(...){(void)host.release();}}
}
// T38_HOST_TRANSFER_END
unsigned grid(uint64_t n){need(n&&n<=uint64_t(UINT32_MAX)*256,"draft launch geometry");return unsigned((n+255)/256);}
__device__ float bf(float x){uint32_t u=__float_as_uint(x);return __uint_as_float((u+0x7fff+((u>>16)&1))&0xffff0000u);}
__device__ float half_value(uint16_t h){
 uint32_t sign=uint32_t(h&0x8000)<<16,e=(h>>10)&31,f=h&1023;
 if(e==31)return __uint_as_float(sign|0x7f800000u|(f<<13));
 if(e)return __uint_as_float(sign|((e+112)<<23)|(f<<13));
 if(!f)return __uint_as_float(sign);
 int exponent=-14;while(!(f&1024)){f<<=1;--exponent;}return __uint_as_float(sign|(uint32_t(exponent+127)<<23)|((f&1023)<<13));
}
__global__ void mean_kernel(const float*x,float*y,uint64_t rows){uint64_t i=uint64_t(blockIdx.x)*blockDim.x+threadIdx.x;if(i>=rows*5120)return;auto b=i/5120,d=i%5120;float sum=0.0f;for(unsigned hc=0;hc<4;++hc)sum=sum+x[(b*4+hc)*5120+d];y[i]=bf(sum*0.25f);}
__global__ void half_projection(const uint16_t*w,const float*x,float*y,uint64_t rows,uint64_t k,uint64_t batch,uint64_t stride){uint64_t i=uint64_t(blockIdx.x)*blockDim.x+threadIdx.x;if(i>=rows*batch)return;auto b=i/rows,r=i%rows;float acc=0.0f;for(uint64_t j=0;j<k;++j){float product=half_value(w[r*k+j])*x[b*k+j];acc=acc+product;}y[b*stride+r]=acc;}
__global__ void confidence_kernel(const float*h,const float*m,const uint16_t*w,float*y,uint64_t batch){uint64_t b=uint64_t(blockIdx.x)*blockDim.x+threadIdx.x;if(b>=batch)return;float acc=0.0f;for(uint64_t j=0;j<5376;++j){float input=j<5120?h[b*5120+j]:m[b*256+j-5120];float product=input*half_value(w[j]);acc=acc+product;}y[b]=acc;}
__global__ void router_kernel(const float*logits,const float*bias,float*scores,float*corrected,uint32_t*ids,float*weights,uint64_t rows){uint64_t row=uint64_t(blockIdx.x)*blockDim.x+threadIdx.x;if(row>=rows)return;
 for(unsigned e=0;e<128;++e){float z=logits[row*128+e];float sp=z>20.f?z:float(log1p(exp(double(z))));float score=sqrtf(sp);scores[row*128+e]=score;corrected[row*128+e]=score+bias[e];}
 for(unsigned slot=0;slot<3;++slot){unsigned best=128;float value=-INFINITY;for(unsigned e=0;e<128;++e){bool used=false;for(unsigned j=0;j<slot;++j)if(ids[row*3+j]==e)used=true;if(!used&&(best==128||corrected[row*128+e]>value)){best=e;value=corrected[row*128+e];}}ids[row*3+slot]=best;}
 float den=0.0f;for(unsigned j=0;j<3;++j)den=den+scores[row*128+ids[row*3+j]];den=den+1.e-20f;for(unsigned j=0;j<3;++j)weights[row*3+j]=(scores[row*128+ids[row*3+j]]/den)*1.5f;
}
__global__ void input_ids(uint32_t*ids,uint64_t n,uint32_t previous){uint64_t i=uint64_t(blockIdx.x)*blockDim.x+threadIdx.x;if(i<n)ids[i]=i?128799:previous;}
__global__ void seed(const float*key,float*ring,uint64_t slot){auto d=blockIdx.x*blockDim.x+threadIdx.x;if(d<512)ring[slot*512+d]=key[d];}
__global__ void noise_ids(int64_t*ids,uint64_t prefix,uint64_t width){uint64_t i=uint64_t(blockIdx.x)*blockDim.x+threadIdx.x;if(i<prefix+width)ids[i]=int64_t(i<prefix?i:128+i-prefix);}
}
void hc_mean_device(const DeviceView&x,const DeviceView&y,void*s){auto hs=stream(s,x.device);view(x,x.device,x.rows,20480,DeviceScalar::Bfloat16InFloat32);view(y,x.device,x.rows,5120,DeviceScalar::Bfloat16InFloat32);distinct(x,y);mean_kernel<<<grid(mul(x.rows,5120)),256,0,hs>>>((float*)x.data,(float*)y.data,x.rows);check(hipGetLastError());}
void f16_projection_device(const Span&source,const DeviceView&w,const DeviceView&x,const DeviceView&y,void*s,uint64_t stride){validate_f16_alignment(w.data);auto hs=stream(s,x.device);need(source.tensor.type==1&&source.tensor.dims.size()>=2&&source.count,"F16 source role/rank");auto k=source.tensor.dims[0],rows=source.count;need(source.bytes==mul(mul(rows,k),2),"F16 original full-K bytes");view(w,x.device,1,source.bytes,DeviceScalar::UInt8);need(x.scalar==DeviceScalar::Float32||x.scalar==DeviceScalar::Bfloat16InFloat32,"F16 projection input scalar");view(x,x.device,x.rows,k,x.scalar);need(reinterpret_cast<uintptr_t>(w.data)%2==0,"F16 source alignment");view(y,x.device,x.rows,rows,DeviceScalar::Float32);if(!stride)stride=rows;need(stride>=rows&&mul((x.rows-1),stride)<=UINT64_MAX-rows&&mul(mul(x.rows-1,stride)+rows,4)<=y.bytes,"F16 strided output range");distinct(x,y);distinct(w,y);half_projection<<<grid(mul(rows,x.rows)),256,0,hs>>>((uint16_t*)w.data,(float*)x.data,(float*)y.data,rows,k,x.rows,stride);check(hipGetLastError());}
void confidence_device(const DeviceView&h,const DeviceView&m,const Span&source,const DeviceView&w,const DeviceView&y,void*s){validate_f16_alignment(w.data);auto hs=stream(s,h.device);need(source.tensor.name=="dflash.dspark.confidence.weight"&&source.tensor.type==1&&source.bytes==10752&&source.row==0&&source.count==1,"confidence source");view(h,h.device,h.rows,5120,DeviceScalar::Bfloat16InFloat32);view(m,h.device,h.rows,256,DeviceScalar::Float32);view(w,h.device,1,10752,DeviceScalar::UInt8);view(y,h.device,h.rows,1,DeviceScalar::Float32);distinct(h,y);distinct(m,y);distinct(w,y);confidence_kernel<<<grid(h.rows),256,0,hs>>>((float*)h.data,(float*)m.data,(uint16_t*)w.data,(float*)y.data,h.rows);check(hipGetLastError());}
void router128_device(const DeviceView&l,const DeviceView&b,const DeviceView&sc,const DeviceView&co,const DeviceView&ids,const DeviceView&w,void*s){auto hs=stream(s,l.device);view(l,l.device,l.rows,128,DeviceScalar::Float32);view(b,l.device,1,128,DeviceScalar::Float32);view(sc,l.device,l.rows,128,DeviceScalar::Float32);view(co,l.device,l.rows,128,DeviceScalar::Float32);view(ids,l.device,l.rows,3,DeviceScalar::UInt32);view(w,l.device,l.rows,3,DeviceScalar::Float32);const DeviceView outputs[]={sc,co,ids,w};for(unsigned i=0;i<4;++i){distinct(l,outputs[i]);distinct(b,outputs[i]);for(unsigned j=0;j<i;++j)distinct(outputs[i],outputs[j]);}router_kernel<<<grid(l.rows),256,0,hs>>>((float*)l.data,(float*)b.data,(float*)sc.data,(float*)co.data,(uint32_t*)ids.data,(float*)w.data,l.rows);check(hipGetLastError());}
void noise_input_ids_device(const DeviceView&v,uint32_t previous,void*s){auto hs=stream(s,v.device);need(previous<129280,"previous original ID");view(v,v.device,1,v.columns,DeviceScalar::UInt32);input_ids<<<grid(v.columns),256,0,hs>>>((uint32_t*)v.data,v.columns,previous);check(hipGetLastError());}
void seed_main_kv_device(const DeviceView&key,const DeviceView&ring,uint64_t position,void*s){auto hs=stream(s,key.device);view(key,key.device,1,512,DeviceScalar::Bfloat16InFloat32);view(ring,key.device,128,512,DeviceScalar::Bfloat16InFloat32);distinct(key,ring);seed<<<2,256,0,hs>>>((float*)key.data,(float*)ring.data,position%128);check(hipGetLastError());}
void noise_attention_device(const DeviceView&q,const DeviceView&ring,const DeviceView&noise,const DeviceView&sink,const DeviceView&out,const DeviceView&ids,const DeviceView&error,uint64_t pos,void*s){auto hs=stream(s,q.device);need(pos>0&&pos<UINT64_MAX,"start0 seeds only, no proposals");auto width=noise.rows,prefix=pos>=127?128:pos+1;view(q,q.device,mul(width,64),512,DeviceScalar::Bfloat16InFloat32);view(ring,q.device,128,512,DeviceScalar::Bfloat16InFloat32);view(noise,q.device,width,512,DeviceScalar::Bfloat16InFloat32);view(sink,q.device,1,64,DeviceScalar::Float32);view(out,q.device,mul(width,64),512,DeviceScalar::Bfloat16InFloat32);need(width<=UINT64_MAX-prefix,"attention index count overflow");view(ids,q.device,1,prefix+width,DeviceScalar::Int64);view(error,q.device,1,1,DeviceScalar::UInt32);const DeviceView outputs[]={out,ids,error};const DeviceView inputs[]={q,ring,noise,sink};for(unsigned i=0;i<3;++i){for(auto&input:inputs)distinct(input,outputs[i]);for(unsigned j=0;j<i;++j)distinct(outputs[i],outputs[j]);}check(hipMemsetAsync(error.data,0,4,hs));noise_ids<<<grid(prefix+width),256,0,hs>>>((int64_t*)ids.data,prefix,width);check(hipGetLastError());
 for(uint64_t i=0;i<width;++i){auto x=q,y=out;x.data=(float*)q.data+i*64*512;y.data=(float*)out.data+i*64*512;x.rows=y.rows=64;x.bytes=y.bytes=64*512*4;attention_online_split_device(x,ring,noise,ids,sink,y,error,s);}
 // Caller checks device error after actual stream completion; no hidden download.
}
namespace {
TargetMatrixExtent target_extent(const SourceTensor&t){
 need(t.span.dims_ggml.size()==2,"target source matrix rank");return {t.span.dims_ggml[0],t.span.dims_ggml[1],t.span.row_bytes,t.span.absolute_offset,t.span.bytes,t.source.original_size};
}
void target_descriptor(const SourceTensor&t,const char*name,uint64_t credit){
 need(t.span.name==name&&t.span.shard_index==t.source.shard_index&&!t.source.original_path.empty()&&
      !t.source.revision.empty()&&!t.source.lfs_sha256.empty(),"target accepted source descriptor");
 auto e=target_extent(t);auto row=quant::packed_bytes(t.span.type_id,size_t(e.k));validate_target_matrix(e,row,credit);quant::validate_projection_shape(t.span.type_id,1,size_t(e.k),1);
}
__global__ void target_expand_row(const float*embedding,float*out){uint64_t i=uint64_t(blockIdx.x)*blockDim.x+threadIdx.x;if(i<20480)out[i]=embedding[i%5120];}
}
struct TargetWeightSupply::Impl {
 SourceTensor embedding_source,head_source;RequestBinding binding;uint64_t credit,read_bytes=0;bool valid=true;
 std::vector<uint8_t> staging;bool staging_valid=true;
 CoreStorage storage;DeviceView packed,decoded,cast;ContinueWork control;
 Impl(SourceTensor e,SourceTensor h,RequestBinding b,int device,uint64_t c):embedding_source(std::move(e)),head_source(std::move(h)),binding(std::move(b)),credit(c),storage(device){
  staging.resize(size_t(credit));
  packed=storage.allocate("target-native-window",1,credit,DeviceScalar::UInt8);decoded=storage.allocate("target-embedding-decoded",1,5120,DeviceScalar::Float32);cast=storage.allocate("target-embedding-bf16",1,5120,DeviceScalar::Bfloat16InFloat32);
 }
 void identity(const RequestBinding&current){need(valid,"invalid target supply");need(current.owner==binding.owner&&current.epoch==binding.epoch&&current.bundle==binding.bundle,"target supply receipt/request changed");}
 DeviceView load(const SourceTensor&t,uint64_t first,uint64_t count){
  if(control&&!control())throw DraftCancelled{};
  auto tile=target_matrix_tile(target_extent(t),first,count,credit);
  need(staging_valid,"target host staging unavailable");artifact::FixtureView original{t.source.original_path,0,t.source.original_size};auto bytes=original.read_exact(tile.offset,tile.bytes);std::copy(bytes.begin(),bytes.end(),staging.begin());
  need(bytes.size()<=UINT64_MAX-read_bytes,"target read ledger overflow");read_bytes+=bytes.size();auto v=packed;v.columns=tile.bytes;v.bytes=tile.bytes;staging_valid=false;storage.upload(v,staging.data(),bytes.size());staging_valid=true;return v;
 }
};
TargetWeightSupply::TargetWeightSupply(const Artifact&a,const RequestBinding&binding,int device,uint64_t credit){
 need(binding.owner&&binding.epoch&&!binding.bundle.empty(),"accepted target receipt binding required");auto e=a.source_tensor("token_embd.weight"),h=a.source_tensor("output.weight");target_descriptor(e,"token_embd.weight",credit);target_descriptor(h,"output.weight",credit);p_=std::make_unique<Impl>(std::move(e),std::move(h),binding,device,credit);
}
TargetWeightSupply::~TargetWeightSupply()=default;
void* TargetWeightSupply::stream()const{return p_->storage.stream();}
void TargetWeightSupply::set_control(ContinueWork control)noexcept{p_->control=std::move(control);}
uint64_t TargetWeightSupply::explicit_owned_bytes()const{return p_->storage.explicit_owned_bytes();}
uint64_t TargetWeightSupply::source_read_bytes()const{return p_->read_bytes;}
void TargetWeightSupply::drain(){auto&p=*p_;try{p.storage.drain();}catch(...){p.valid=false;throw;}}
void TargetWeightSupply::embedding(const std::vector<uint32_t>&ids,const DeviceView&output,const RequestBinding&current){
 auto&p=*p_;p.identity(current);need(!ids.empty(),"target embedding IDs empty");for(auto id:ids)need(id<129280,"target original ID range");view(output,p.packed.device,ids.size(),20480,DeviceScalar::Bfloat16InFloat32);distinct(output,p.packed);distinct(output,p.decoded);distinct(output,p.cast);auto hs=stream();target_stream_preflight(p.valid,hs,output.device,[](int&d){return int(hipGetDevice(&d));},[](void*s,int&d){return int(hipStreamGetDevice(reinterpret_cast<hipStream_t>(s),&d));});
 try{std::optional<uint32_t>last;
  for(size_t row=0;row<ids.size();++row){if(!last||*last!=ids[row]){auto packed=p.load(p.embedding_source,ids[row],1);quant::PackedDeviceView source{(const uint8_t*)packed.data,p.embedding_source.span.type_id,1,5120,size_t(packed.bytes),output.device};quant::decode_into(source,(float*)p.decoded.data,p.decoded.bytes,hs,p.storage.lease());ffn_bf16_device(p.decoded,p.cast,hs);last=ids[row];}
   target_expand_row<<<80,256,0,reinterpret_cast<hipStream_t>(hs)>>>((const float*)p.cast.data,(float*)output.data+row*20480);check(hipGetLastError());}
 }catch(...){p.valid=false;throw;}
}
void TargetWeightSupply::head(const DeviceView&input,const DeviceView&output,const RequestBinding&current){
 auto&p=*p_;p.identity(current);view(input,p.packed.device,input.rows,5120,DeviceScalar::Bfloat16InFloat32);view(output,input.device,input.rows,129280,DeviceScalar::Float32);distinct(input,output);distinct(input,p.packed);distinct(output,p.packed);auto hs=stream();target_stream_preflight(p.valid,hs,input.device,[](int&d){return int(hipGetDevice(&d));},[](void*s,int&d){return int(hipStreamGetDevice(reinterpret_cast<hipStream_t>(s),&d));});
 try{auto extent=target_extent(p.head_source);auto tile_rows=p.credit/extent.row_bytes;
  for(uint64_t first=0;first<129280;){auto count=std::min<uint64_t>(tile_rows,129280-first);auto packed=p.load(p.head_source,first,count);quant::PackedDeviceView source{(const uint8_t*)packed.data,p.head_source.span.type_id,size_t(count),5120,size_t(packed.bytes),input.device};
   auto jobs=projection_wave_offsets(input.rows,5120,129280,count,input.bytes,output.bytes-first*4,batch_waves(input.rows,8));
   for(auto job:jobs){auto x=reinterpret_cast<const float*>(reinterpret_cast<const uint8_t*>(input.data)+job.input_bytes);auto y=reinterpret_cast<float*>(reinterpret_cast<uint8_t*>(output.data)+first*4+job.output_bytes);auto binding=quant::checked_projection_strided(source,x,size_t(input.bytes-job.input_bytes),y,size_t(output.bytes-first*4-job.output_bytes),129280,hs,p.storage.lease());quant::project_into(binding,job.rows);}
   first+=count;}
 }catch(...){p.valid=false;throw;}
}
struct DraftWeights::Impl {
 Asset asset;std::string path;uint64_t credit;std::vector<uint8_t> staging;bool staging_valid=true;DraftHostScratch host;CoreStorage storage;DeviceView packed;
 std::map<std::string,DeviceView> constants,workspace;ContinueWork control;
 Impl(const std::string&p,const Asset&a,int device,uint64_t bytes):asset(a),path(p),credit(bytes),storage(device){need(bytes&&bytes<=SIZE_MAX,"finite weight credit");staging.resize(size_t(bytes));packed=storage.allocate("draft-weight-window",1,bytes,DeviceScalar::UInt8);}
};
DraftWeights::DraftWeights(const std::string&p,const Asset&a,int device,uint64_t credit){
 // Validate every declared tensor via a real schema check before allocations.
 need(!a.tensors.empty(),"empty draft asset");required_span(a,a.tensors.front().name,0,0,1);
 p_=std::make_unique<Impl>(p,a,device,credit);
}
DraftWeights::~DraftWeights()=default;
void* DraftWeights::stream()const{return p_->storage.stream();}
void DraftWeights::set_control(ContinueWork control)noexcept{p_->control=std::move(control);}
void DraftWeights::drain(){p_->storage.drain();p_->host.pending=false;}
DraftHostScratch& DraftWeights::host_scratch(){need(p_->staging_valid&&p_->host.valid&&!p_->host.pending,"draft host scratch unavailable");return p_->host;}
void DraftWeights::prepare_host(uint64_t width){auto&h=host_scratch();h.ids.resize(size_t(mul(width,3)));h.pairs.resize(size_t(mul(width,6)));h.logits.resize(129280);p_->staging.resize(size_t(std::max(p_->credit,mul(width,64*8))));}
uint64_t DraftWeights::explicit_owned_bytes()const{return p_->storage.explicit_owned_bytes();}
DeviceView DraftWeights::constant(const Span&span){
 auto&p=*p_;need(p.staging_valid&&p.host.valid,"draft provider unavailable");if(p.control&&!p.control())throw DraftCancelled{};auto expected=required_span(p.asset,span.tensor.name,span.matrix,span.row,span.count);
 need(span.tensor.type==0&&span.tensor.dims.size()==1&&span.matrix==0&&span.row==0&&span.count==1&&span.offset==expected.offset&&span.bytes==expected.bytes,"source-bound F32 constant");
 auto found=p.constants.find(span.tensor.name);if(found!=p.constants.end())return found->second;
 need(p.staging_valid,"draft host staging unavailable");auto bytes=read_span(p.path,span,p.credit);std::copy(bytes.begin(),bytes.end(),p.staging.begin());auto v=p.storage.allocate("draft-constant-"+span.tensor.name,1,span.tensor.dims[0],DeviceScalar::Float32);p.staging_valid=false;p.storage.upload(v,p.staging.data(),bytes.size());p.staging_valid=true;p.constants.emplace(span.tensor.name,v);return v;
}
DeviceView DraftWeights::load_packed(const Span&span){
 auto&p=*p_;need(p.staging_valid&&p.host.valid,"draft provider unavailable");if(p.control&&!p.control())throw DraftCancelled{};auto expected=required_span(p.asset,span.tensor.name,span.matrix,span.row,span.count);
 need(span.offset==expected.offset&&span.bytes==expected.bytes&&span.tensor.type==expected.tensor.type&&span.tensor.dims==expected.tensor.dims,"packed original span");
 need(p.staging_valid,"draft host staging unavailable");auto bytes=read_span(p.path,expected,p.credit);std::copy(bytes.begin(),bytes.end(),p.staging.begin());auto packed=p.packed;packed.columns=expected.bytes;packed.bytes=expected.bytes;p.staging_valid=false;p.storage.upload(packed,p.staging.data(),bytes.size());p.staging_valid=true;return packed;
}
void DraftWeights::project(const Span&span,const DeviceView&x,const DeviceView&y,uint64_t stride){
 auto&p=*p_;need(p.staging_valid&&p.host.valid,"draft provider unavailable");if(p.control&&!p.control())throw DraftCancelled{};auto expected=required_span(p.asset,span.tensor.name,span.matrix,span.row,span.count);
 need(span.offset==expected.offset&&span.bytes==expected.bytes&&span.tensor.type==expected.tensor.type&&span.tensor.dims==expected.tensor.dims,"projection original span");
 if(!stride)stride=y.columns;need(stride>=y.columns,"projection output stride");need(mul(mul(y.rows-1,stride)+y.columns,4)<=y.bytes,"projection output strided bytes");auto k=expected.tensor.dims[0];view(x,x.device,x.rows,k,x.scalar);need(x.scalar==DeviceScalar::Float32||x.scalar==DeviceScalar::Bfloat16InFloat32,"projection input scalar");view(y,x.device,x.rows,span.count,DeviceScalar::Float32);need(x.device==p.packed.device,"provider device");distinct(x,y);
 auto tile_rows=p.credit/expected.tensor.row_bytes;need(tile_rows,"one full-K row does not fit caller byte credit");
 for(uint64_t first=0;first<span.count;){if(p.control&&!p.control())throw DraftCancelled{};auto count=std::min<uint64_t>(tile_rows,span.count-first);auto tile=required_span(p.asset,span.tensor.name,span.matrix,span.row+first,count);need(p.staging_valid,"draft host staging unavailable");auto bytes=read_span(p.path,tile,p.credit);std::copy(bytes.begin(),bytes.end(),p.staging.begin());auto packed=p.packed;packed.columns=tile.bytes;packed.bytes=tile.bytes;p.staging_valid=false;p.storage.upload(packed,p.staging.data(),bytes.size());p.staging_valid=true;
  auto output=y;output.data=(float*)y.data+first;output.columns=count;output.bytes=y.bytes-first*4;
  if(tile.tensor.type==1)f16_projection_device(tile,packed,x,output,p.storage.stream(),stride);
  else {need(tile.tensor.type==0||tile.tensor.type==8||tile.tensor.type==39,"draft native projection type");quant::PackedDeviceView source{(const uint8_t*)packed.data,tile.tensor.type,size_t(count),size_t(k),size_t(tile.bytes),x.device};
   // Only independent projection batch rows are split; noise attention stays full-width.
   auto jobs=projection_wave_offsets(x.rows,k,stride,count,x.bytes,output.bytes,batch_waves(x.rows,8));
   for(auto job:jobs){auto input_pointer=reinterpret_cast<const float*>(reinterpret_cast<const uint8_t*>(x.data)+job.input_bytes);auto output_pointer=reinterpret_cast<float*>(reinterpret_cast<uint8_t*>(output.data)+job.output_bytes);auto binding=quant::checked_projection_strided(source,input_pointer,size_t(x.bytes-job.input_bytes),output_pointer,size_t(output.bytes-job.output_bytes),size_t(stride),p.storage.stream(),p.storage.lease());quant::project_into(binding,job.rows);}
  }
  first+=count;
 }
 // Final packed bytes stay owned until last launch completes / next same-stream upload.
}
void draft_block_device(const Asset&a,uint32_t stage,const DeviceView&residual,const DeviceView&incoming,const DeviceView&output,BlockWorkspace&w,const DraftProjection&project,const DraftConstantLookup&constant,const DraftSubblock&attention,const DraftSubblock&ffn,void*s){
 need(stage<3&&project&&constant&&attention&&ffn,"actual draft block callbacks/stage");stream(s,residual.device);view(residual,residual.device,residual.rows,20480,DeviceScalar::Bfloat16InFloat32);view(output,residual.device,residual.rows,20480,DeviceScalar::Bfloat16InFloat32);view(incoming,residual.device,residual.rows,4,DeviceScalar::Float32);distinct(residual,output);
 auto prefix=std::string("blk.")+std::to_string(stage)+".";
 auto source=[&](const std::string&role){auto name=prefix+role;for(const auto&t:a.tensors)if(t.name==name)return required_span(a,name,0,0,t.dims.size()>1?t.dims[1]:1);throw std::invalid_argument("missing draft role");};
 auto c=[&](const std::string&role,uint64_t columns){auto span=source(role);need(span.tensor.type==0&&span.tensor.dims==std::vector<uint64_t>{columns},"draft constant original geometry");auto value=constant(span);view(value,residual.device,1,columns,DeviceScalar::Float32);return value;};
 auto mixes=[&](const DeviceView&x,MhcWorkspace&mw,const std::string&which){mhc_rms_device(x,mw.inverse,s);project(source("hc_"+which+"_fn.weight"),x,mw.dot,s);mhc_mix_device(mw.dot,mw.inverse,mw.mixed,s);auto scale=c("hc_"+which+"_scale.weight",3),base=c("hc_"+which+"_base.weight",24);mhc_split_device(mw.mixed,scale,base,mw.pre,mw.post,mw.comb,s,mw.audit);};
 mixes(residual,w.attention,"attn");mhc_pre_device(residual,incoming,w.collapsed,s);mhc_rms_device(w.collapsed,w.norm_inverse,s);auto norm=c("attn_norm.weight",5120);mhc_norm_device(w.collapsed,w.norm_inverse,norm,w.normalized,s);attention(w.normalized,w.subblock,s);mhc_post_device(w.subblock,residual,w.attention.post,w.attention.comb,w.after_attention,s);
 mixes(w.after_attention,w.ffn,"ffn");mhc_pre_device(w.after_attention,w.attention.pre,w.collapsed,s);mhc_rms_device(w.collapsed,w.norm_inverse,s);norm=c("ffn_norm.weight",5120);mhc_norm_device(w.collapsed,w.norm_inverse,norm,w.normalized,s);ffn(w.normalized,w.subblock,s);mhc_post_device(w.subblock,w.after_attention,w.ffn.post,w.ffn.comb,output,s);
}
void draft_three_blocks_device(const Asset&a,DeviceView current,DeviceView next,const DeviceView&incoming,BlockWorkspace&w,const DraftProjection&project,const DraftConstantLookup&constant,const std::array<DraftSubblock,3>&attention,const std::array<DraftSubblock,3>&ffn,void*s
#if defined(STRATA_T28_CONSTRUCTION_TEST) && defined(STRATA_T38_SEED_CONSTRUCTION)
 ,const std::function<void(uint32_t,const DeviceView&,void*)>*stage_completed
#endif
 ){
 for(unsigned stage=0;stage<3;++stage){draft_block_device(a,stage,current,incoming,next,w,project,constant,attention[stage],ffn[stage],s);check(hipMemcpyAsync(incoming.data,w.ffn.pre.data,size_t(mul(mul(incoming.rows,4),4)),hipMemcpyDeviceToDevice,reinterpret_cast<hipStream_t>(s)));
#if defined(STRATA_T28_CONSTRUCTION_TEST) && defined(STRATA_T38_SEED_CONSTRUCTION)
  if(stage_completed)(*stage_completed)(stage,next,s);
#endif
  std::swap(current,next);}
 // With three stages, final residual is in the original residual_b argument.
}
namespace {
__global__ void draft_selected_rows(const float*x,const float*w,const uint32_t*pairs,float*out,float*route,uint64_t n){uint64_t i=uint64_t(blockIdx.x)*blockDim.x+threadIdx.x;if(i<n*5120){auto r=i/5120,d=i%5120;out[i]=x[uint64_t(pairs[2*r])*5120+d];if(d==0)route[r]=w[uint64_t(pairs[2*r])*3+pairs[2*r+1]];}}
__global__ void draft_scatter_rows(float*sum,const float*x,const uint32_t*pairs,uint64_t n){uint64_t i=uint64_t(blockIdx.x)*blockDim.x+threadIdx.x;if(i<n*5120){auto at=uint64_t(pairs[2*(i/5120)])*5120+i%5120;sum[at]=sum[at]+x[i];}}
}
void draft_ffn_device(const Asset&a,uint32_t stage,const DeviceView&input,const DeviceView&output,FfnWorkspace&w,const DraftProjection&project,const DraftConstantLookup&constant,void*s,DraftHostScratch*provided){
 need(stage<3&&project&&constant,"draft FFN actual source callbacks");auto hs=stream(s,input.device);auto b=input.rows;need(b<=UINT32_MAX,"draft routed row index range");view(input,input.device,b,5120,DeviceScalar::Bfloat16InFloat32);view(output,input.device,b,5120,DeviceScalar::Bfloat16InFloat32);
 auto check_view=[&](const DeviceView&v,uint64_t c,DeviceScalar t){view(v,input.device,b,c,t);};check_view(w.logits,128,DeviceScalar::Float32);check_view(w.scores,128,DeviceScalar::Float32);check_view(w.corrected,128,DeviceScalar::Float32);check_view(w.ids,3,DeviceScalar::UInt32);check_view(w.weights,3,DeviceScalar::Float32);check_view(w.accumulated,5120,DeviceScalar::Float32);check_view(w.gate,2304,DeviceScalar::Bfloat16InFloat32);check_view(w.up,2304,DeviceScalar::Bfloat16InFloat32);check_view(w.hidden,2304,DeviceScalar::Bfloat16InFloat32);check_view(w.down_dot,5120,DeviceScalar::Float32);check_view(w.down_bf16,5120,DeviceScalar::Bfloat16InFloat32);check_view(w.selected_input,5120,DeviceScalar::Bfloat16InFloat32);check_view(w.selected_route,1,DeviceScalar::Float32);check_view(w.selected_pairs,2,DeviceScalar::UInt32);
 auto prefix=std::string("blk.")+std::to_string(stage)+".";auto source=[&](const std::string&role,uint64_t matrix=0){auto name=prefix+role;for(auto&t:a.tensors)if(t.name==name)return required_span(a,name,matrix,0,t.dims.size()>1?t.dims[1]:1);throw std::invalid_argument("draft FFN missing role");};
 project(source("ffn_gate_inp.weight"),input,w.logits,s);auto bias=constant(source("exp_probs_b.bias"));router128_device(w.logits,bias,w.scores,w.corrected,w.ids,w.weights,s);
 std::unique_ptr<DraftHostScratch>local;if(!provided){local=std::make_unique<DraftHostScratch>();provided=local.get();}auto&host=*provided;
 struct LocalDrain{std::unique_ptr<DraftHostScratch>&p;hipStream_t stream;~LocalDrain(){retain_unknown_host(p,[&]{check(hipStreamSynchronize(stream));});}}local_drain{local,hs};
 need(host.valid&&!host.pending,"FFN host scratch unavailable");auto&ids=host.ids;ids.resize(size_t(mul(b,3)));host_transfer(host,[&]{check(hipMemcpyAsync(ids.data(),w.ids.data,ids.size()*4,hipMemcpyDeviceToHost,hs));check(hipStreamSynchronize(hs));});std::set<uint32_t> experts;
 for(uint64_t row=0;row<b;++row){std::set<uint32_t> seen;for(unsigned slot=0;slot<3;++slot){auto e=ids[row*3+slot];need(e<128&&seen.insert(e).second,"draft router ID/duplicate");experts.insert(e);}}
 check(hipMemsetAsync(w.accumulated.data,0,size_t(mul(mul(b,5120),4)),hs));
 auto subset=[&](const DeviceView&v,uint64_t rows){auto result=v;need(rows&&rows<=v.rows,"draft finite active rows");result.rows=rows;return result;};
 auto linear=[&](const Span&weight,const DeviceView&x,const DeviceView&dot,const DeviceView&out){project(weight,x,dot,s);ffn_bf16_device(dot,out,s);};
 for(auto e:experts){auto&pairs=host.pairs;pairs.clear();for(uint64_t row=0;row<b;++row)for(unsigned slot=0;slot<3;++slot)if(ids[row*3+slot]==e){pairs.push_back(uint32_t(row));pairs.push_back(slot);}auto n=pairs.size()/2;host_transfer(host,[&]{check(hipMemcpyAsync(w.selected_pairs.data,pairs.data(),pairs.size()*4,hipMemcpyHostToDevice,hs));draft_selected_rows<<<grid(mul(n,5120)),256,0,hs>>>((float*)input.data,(float*)w.weights.data,(uint32_t*)w.selected_pairs.data,(float*)w.selected_input.data,(float*)w.selected_route.data,n);check(hipGetLastError());
  auto x=subset(w.selected_input,n),route=subset(w.selected_route,n),gate=subset(w.gate,n),up=subset(w.up,n),hidden=subset(w.hidden,n),down=subset(w.down_bf16,n),dot=subset(w.down_dot,n);auto gate_dot=gate,up_dot=up;gate_dot.scalar=up_dot.scalar=DeviceScalar::Float32;
  linear(source("ffn_gate_exps.weight",e),x,gate_dot,gate);linear(source("ffn_up_exps.weight",e),x,up_dot,up);ffn_swiglu_device(gate,up,&route,hidden,s);linear(source("ffn_down_exps.weight",e),hidden,dot,down);draft_scatter_rows<<<grid(mul(n,5120)),256,0,hs>>>((float*)w.accumulated.data,(float*)down.data,(uint32_t*)w.selected_pairs.data,n);check(hipGetLastError());check(hipStreamSynchronize(hs));});
 }
 auto gate_dot=w.gate,up_dot=w.up;gate_dot.scalar=up_dot.scalar=DeviceScalar::Float32;linear(source("ffn_gate_shexp.weight"),input,gate_dot,w.gate);linear(source("ffn_up_shexp.weight"),input,up_dot,w.up);ffn_swiglu_device(w.gate,w.up,nullptr,w.hidden,s);linear(source("ffn_down_shexp.weight"),w.hidden,w.down_dot,w.down_bf16);ffn_add_device(w.accumulated,w.down_bf16,w.down_dot,s);ffn_bf16_device(w.down_dot,output,s);
}
namespace {
void metadata_ok(const DraftDeviceMetadata&m){need(m.valid&&m.owner&&m.epoch,"draft device metadata identity");for(auto p:m.stage_cursor)need(p==m.cursor,"draft device stage cursor");need(!m.processed_prior||*m.processed_prior<129280,"draft device prior original ID");}
bool same_view(const DeviceView&a,const DeviceView&b){return a.data==b.data&&a.bytes==b.bytes&&a.rows==b.rows&&a.columns==b.columns&&a.scalar==b.scalar&&a.device==b.device&&a.owner==b.owner&&a.generation==b.generation;}
}
struct DraftDeviceCheckpoint::Impl {
 DraftDeviceMetadata saved;std::array<DeviceView,4> targets,snapshots;CoreStorage storage;void*owner_stream;bool closed=false;
 Impl(const DraftDeviceMetadata&m,int device,void*s):saved(m),storage(device),owner_stream(s){}
};
DraftDeviceCheckpoint::DraftDeviceCheckpoint(const DraftDeviceMetadata&m,const std::array<const DeviceView*,4>&buffers,void*s){
 metadata_ok(m);for(auto*v:buffers)need(v,"missing persistent draft view");auto device=buffers[0]->device;auto hs=stream(s,device);
 for(unsigned i=0;i<4;++i){view(*buffers[i],device,i<3?128:1,i<3?512:15360,DeviceScalar::Bfloat16InFloat32);for(unsigned j=0;j<i;++j)distinct(*buffers[i],*buffers[j]);}
 // Establish actual producer last use before copying on checkpoint's own stream.
 check(hipStreamSynchronize(hs));p_=std::make_unique<Impl>(m,device,s);
 for(unsigned i=0;i<4;++i){p_->targets[i]=*buffers[i];auto t=*buffers[i];auto copy=p_->storage.allocate("draft-checkpoint-"+std::to_string(i),t.rows,t.columns,t.scalar);p_->snapshots[i]=copy;check(hipMemcpyAsync(copy.data,t.data,size_t(mul(mul(t.rows,t.columns),4)),hipMemcpyDeviceToDevice,reinterpret_cast<hipStream_t>(p_->storage.stream())));}
 p_->storage.drain();
}
DraftDeviceCheckpoint::~DraftDeviceCheckpoint()=default;
uint64_t DraftDeviceCheckpoint::explicit_owned_bytes()const{return p_->storage.explicit_owned_bytes();}
void DraftDeviceCheckpoint::restore(DraftDeviceMetadata&actual,const std::array<const DeviceView*,4>&current,void*s){
 auto&p=*p_;need(!p.closed,"closed device checkpoint");metadata_ok(actual);need(actual.owner==p.saved.owner&&actual.epoch==p.saved.epoch&&s==p.owner_stream,"device checkpoint request/stream changed");
 for(unsigned i=0;i<4;++i){validate_device_view(p.targets[i],p.targets[0].device);validate_device_view(p.snapshots[i],p.targets[0].device);need(current[i]&&same_view(*current[i],p.targets[i]),"device checkpoint view changed");validate_device_view(*current[i],p.targets[0].device);}
 checkpoint_restore_stream_preflight(actual,p.closed,s,p.targets[0].device,[](int&d){return int(hipGetDevice(&d));},[](void*s,int&d){return int(hipStreamGetDevice(reinterpret_cast<hipStream_t>(s),&d));});
 auto hs=reinterpret_cast<hipStream_t>(s);
 restore_checkpoint_operations(actual,p.saved,p.closed,
  [&]{check(hipStreamSynchronize(hs));},
  [&](unsigned i){auto t=p.targets[i];check(hipMemcpyAsync(t.data,p.snapshots[i].data,size_t(mul(mul(t.rows,t.columns),4)),hipMemcpyDeviceToDevice,reinterpret_cast<hipStream_t>(p.storage.stream())));},
  [&]{p.storage.drain();});
}
void DraftDeviceCheckpoint::commit(const DraftDeviceMetadata&actual,const std::array<const DeviceView*,4>&current,void*s){auto&p=*p_;need(!p.closed,"closed device checkpoint");metadata_ok(actual);need(actual.owner==p.saved.owner&&actual.epoch==p.saved.epoch&&actual.cursor>=p.saved.cursor&&s==p.owner_stream,"device checkpoint commit provenance");for(unsigned i=0;i<4;++i){need(current[i]&&same_view(*current[i],p.targets[i]),"device checkpoint commit view changed");validate_device_view(p.targets[i],p.targets[0].device);}check(hipStreamSynchronize(stream(s,p.targets[0].device)));p.storage.drain();p.closed=true;}
DeviceView DraftWeights::workspace(const std::string&name,uint64_t rows,uint64_t cols,DeviceScalar type){
 auto&p=*p_;need(p.staging_valid&&p.host.valid,"draft provider unavailable");need(!name.empty()&&rows&&cols,"workspace declaration");auto it=p.workspace.find(name);if(it!=p.workspace.end()){view(it->second,p.packed.device,rows,cols,type);return it->second;}auto result=p.storage.allocate("draft-work-"+name,rows,cols,type);p.workspace.emplace(name,result);return result;
}
void DraftWeights::upload(const DeviceView&v,const void*data,uint64_t bytes){auto&p=*p_;need(p.staging_valid&&data&&bytes&&bytes<=SIZE_MAX,"owned host upload source");need(p.host.valid,"draft provider unavailable");if(bytes>p.staging.size())p.staging.resize(size_t(bytes));std::copy((const uint8_t*)data,(const uint8_t*)data+size_t(bytes),p.staging.begin());p.staging_valid=false;p.storage.upload(v,p.staging.data(),bytes);p.staging_valid=true;}
namespace {
Span draft_source(const Asset&a,const std::string&name,uint64_t first=0,uint64_t count=0){for(auto&t:a.tensors)if(t.name==name)return required_span(a,name,0,first,count?count:(t.dims.size()>1?t.dims[1]:1));throw std::invalid_argument("missing draft dense source");}
__global__ void widen_half_row(const uint16_t*w,float*out,uint64_t n){uint64_t i=uint64_t(blockIdx.x)*blockDim.x+threadIdx.x;if(i<n)out[i]=half_value(w[i]);}
__global__ void group_rows(const float*x,float*out,uint64_t rows,uint64_t group){uint64_t i=uint64_t(blockIdx.x)*blockDim.x+threadIdx.x;if(i<rows*4096)out[i]=x[(i/4096)*32768+group*4096+i%4096];}
}
void draft_main_features_device(const Asset&a,const std::array<const DeviceView*,3>&means,const DeviceView&main,DraftWeights&weights){
 auto s=weights.stream();auto hs=stream(s,main.device);view(main,main.device,1,5120,DeviceScalar::Bfloat16InFloat32);
 auto joined=weights.workspace("main-concat",1,15360,DeviceScalar::Bfloat16InFloat32);
 for(unsigned i=0;i<3;++i){need(means[i],"main missing processed tap mean");view(*means[i],main.device,1,5120,DeviceScalar::Bfloat16InFloat32);distinct(*means[i],joined);distinct(*means[i],main);}
 for(unsigned i=0;i<3;++i)check(hipMemcpyAsync((float*)joined.data+i*5120,means[i]->data,5120*4,hipMemcpyDeviceToDevice,hs));
 auto dot=weights.workspace("main-dot",1,5120,DeviceScalar::Float32),cast=weights.workspace("main-cast",1,5120,DeviceScalar::Bfloat16InFloat32);
 weights.project(draft_source(a,"dflash.fc.weight"),joined,dot);ffn_bf16_device(dot,cast,s);auto norm=weights.constant(draft_source(a,"dflash.hidden_norm.weight"));attention_rms_device(cast,norm,main,s);
}
void draft_tail_device(const Asset&a,const DeviceView&residual,const DeviceView&pre,const DeviceView&collapsed,const DeviceView&normalized,DraftWeights&weights){
 auto s=weights.stream();stream(s,residual.device);auto b=residual.rows;view(residual,residual.device,b,20480,DeviceScalar::Bfloat16InFloat32);view(pre,residual.device,b,4,DeviceScalar::Float32);view(collapsed,residual.device,b,5120,DeviceScalar::Bfloat16InFloat32);view(normalized,residual.device,b,5120,DeviceScalar::Bfloat16InFloat32);distinct(residual,collapsed);distinct(pre,collapsed);distinct(collapsed,normalized);distinct(residual,normalized);distinct(pre,normalized);
 mhc_pre_device(residual,pre,collapsed,s);auto norm=weights.constant(draft_source(a,"output_norm.weight"));attention_rms_device(collapsed,norm,normalized,s);
}
void draft_markov_device(const Asset&a,uint32_t previous,const DeviceView&logits,const DeviceView&collapsed,const DeviceView&confidence,DraftWeights&weights){
 need(previous<129280,"Markov previous original ID");auto s=weights.stream();auto hs=stream(s,logits.device);view(logits,logits.device,1,129280,DeviceScalar::Float32);view(collapsed,logits.device,1,5120,DeviceScalar::Bfloat16InFloat32);view(confidence,logits.device,1,1,DeviceScalar::Float32);distinct(logits,collapsed);distinct(logits,confidence);distinct(collapsed,confidence);
 auto embedding=weights.workspace("markov-embedding",1,256,DeviceScalar::Float32),bias=weights.workspace("markov-bias",1,129280,DeviceScalar::Float32);
 auto row=draft_source(a,"dflash.dspark.markov.w1",previous,1);auto packed=weights.load_packed(row);validate_f16_alignment(packed.data);widen_half_row<<<1,256,0,hs>>>((const uint16_t*)packed.data,(float*)embedding.data,256);check(hipGetLastError());
 weights.project(draft_source(a,"dflash.dspark.markov.w2"),embedding,bias);ffn_add_device(logits,bias,logits,s);
 auto source=draft_source(a,"dflash.dspark.confidence.weight");packed=weights.load_packed(source);confidence_device(collapsed,embedding,source,packed,confidence,s);
 // T37 synthetic confidence bias is exactly0; no learned/default-extra bias is added.
}
void draft_seed_main_no_qdq_device(const Asset&a,uint32_t stage,const DeviceView&main,const DeviceView&ring,DraftWeights&weights,uint64_t pos){
 need(stage<3&&pos<=uint64_t(INT64_MAX),"draft main seed stage/position");auto prefix=std::string("blk.")+std::to_string(stage)+".";auto tag="seed-"+std::to_string(stage)+"-";auto s=weights.stream();stream(s,main.device);view(main,main.device,1,5120,DeviceScalar::Bfloat16InFloat32);
 auto work=[&](const std::string&n,uint64_t cols,DeviceScalar t=DeviceScalar::Bfloat16InFloat32){return weights.workspace(tag+n,1,cols,t);};
 auto dot=work("dot",512,DeviceScalar::Float32),cast=work("cast",512),normed=work("normed",512),rotated=work("rotated",512),freq=work("freq",32,DeviceScalar::Float32),position=work("position",1,DeviceScalar::Int64);
 weights.project(draft_source(a,prefix+"attn_kv.weight"),main,dot);ffn_bf16_device(dot,cast,s);auto norm=weights.constant(draft_source(a,prefix+"attn_kv_a_norm.weight"));kv_norm_device(cast,norm,normed,s);int64_t at=int64_t(pos);weights.upload(position,&at,8);kv_frequency_device(freq,false,s);kv_rope_device(normed,position,freq,rotated,false,s);seed_main_kv_device(rotated,ring,pos,s);
}
void draft_attention_no_qdq_device(const Asset&a,uint32_t stage,const DeviceView&input,const DeviceView&output,const DeviceView&ring,DraftWeights&weights,uint64_t pos){
 need(stage<3&&pos>0&&pos<uint64_t(INT64_MAX)&&input.rows<=uint64_t(INT64_MAX)-pos,"draft attention stage/positions");auto b=input.rows;auto s=weights.stream();auto hs=stream(s,input.device);view(input,input.device,b,5120,DeviceScalar::Bfloat16InFloat32);view(output,input.device,b,5120,DeviceScalar::Bfloat16InFloat32);auto prefix=std::string("blk.")+std::to_string(stage)+".";auto tag="attention-"+std::to_string(stage)+"-width-"+std::to_string(b)+"-";
 auto work=[&](const std::string&n,uint64_t rows,uint64_t cols,DeviceScalar t=DeviceScalar::Bfloat16InFloat32){return weights.workspace(tag+n,rows,cols,t);};
 auto qa_dot=work("qa-dot",b,1280,DeviceScalar::Float32),qa=work("qa",b,1280),qr=work("qr",b,1280),q_dot=work("q-dot",b,32768,DeviceScalar::Float32),q=work("q",b,32768),q_rot=work("q-rope",mul(b,64),512);
 weights.project(draft_source(a,prefix+"attn_q_a.weight"),input,qa_dot);ffn_bf16_device(qa_dot,qa,s);auto qnorm=weights.constant(draft_source(a,prefix+"attn_q_a_norm.weight"));attention_rms_device(qa,qnorm,qr,s);weights.project(draft_source(a,prefix+"attn_q_b.weight"),qr,q_dot);ffn_bf16_device(q_dot,q,s);
 auto kv_dot=work("kv-dot",b,512,DeviceScalar::Float32),kv=work("kv",b,512),kv_norm=work("kv-norm",b,512),kv_rot=work("kv-rope",b,512),positions=work("positions",b,1,DeviceScalar::Int64),headpos=work("head-positions",mul(b,64),1,DeviceScalar::Int64),freq=work("freq",1,32,DeviceScalar::Float32);
 weights.project(draft_source(a,prefix+"attn_kv.weight"),input,kv_dot);ffn_bf16_device(kv_dot,kv,s);auto knorm=weights.constant(draft_source(a,prefix+"attn_kv_a_norm.weight"));kv_norm_device(kv,knorm,kv_norm,s);
 std::vector<int64_t> p(static_cast<size_t>(b)),hp(static_cast<size_t>(mul(b,64)));for(uint64_t i=0;i<b;++i){p[i]=int64_t(pos+1+i);for(unsigned h=0;h<64;++h)hp[i*64+h]=p[i];}weights.upload(positions,p.data(),mul(b,8));weights.upload(headpos,hp.data(),mul(mul(b,64),8));kv_frequency_device(freq,false,s);auto qheads=q;qheads.rows=mul(b,64);qheads.columns=512;kv_rope_device(qheads,headpos,freq,q_rot,false,s);kv_rope_device(kv_norm,positions,freq,kv_rot,false,s);
 auto attended=work("attended",mul(b,64),512),inverse=work("inverse",mul(b,64),512),indices_capacity=work("indices",1,noise_index_extent(pos,b).capacity,DeviceScalar::Int64),error=work("error",1,1,DeviceScalar::UInt32);auto indices=noise_index_logical(indices_capacity,pos,b);auto sink=weights.constant(draft_source(a,prefix+"attn_sinks.weight"));noise_attention_device(q_rot,ring,kv_rot,sink,attended,indices,error,pos,s);kv_rope_device(attended,headpos,freq,inverse,true,s);
 auto flattened=inverse;flattened.rows=b;flattened.columns=32768;auto group_input=work("group-input",b,4096),group_dot=work("group-dot",b,8192,DeviceScalar::Float32),group_cast=work("group-cast",b,8192),out_dot=work("out-dot",b,5120,DeviceScalar::Float32);
 for(uint64_t group=0;group<8;++group){group_rows<<<grid(mul(b,4096)),256,0,hs>>>((float*)flattened.data,(float*)group_input.data,b,group);check(hipGetLastError());auto part=group_dot;part.data=(float*)part.data+group*1024;part.columns=1024;part.bytes-=group*1024*4;weights.project(draft_source(a,prefix+"attn_output_a.weight",group*1024,1024),group_input,part,8192);}
 ffn_bf16_device(group_dot,group_cast,s);weights.project(draft_source(a,prefix+"attn_output_b.weight"),group_cast,out_dot);ffn_bf16_device(out_dot,output,s);auto&host=weights.host_scratch();host.attention_error=0;host_transfer(host,[&]{check(hipMemcpyAsync(&host.attention_error,error.data,4,hipMemcpyDeviceToHost,hs));check(hipStreamSynchronize(hs));});need(!host.attention_error,"draft attention error buffer");
}
#ifdef STRATA_T38_GLOBAL_FIXTURE
namespace {
struct FixtureNetworkOperation {
 bool& active;
 explicit FixtureNetworkOperation(bool&value):active(value){need(!active,"overlapping draft fixture operation");active=true;}
 ~FixtureNetworkOperation(){active=false;}
};
}
#endif
struct DraftNetwork::Impl {
 Asset asset;RequestBinding binding;
#ifdef STRATA_T28_CONSTRUCTION_TEST
 // Destroy weights (including its stream drain) before releasing callback roots.
 uint64_t fixture_seed_position=0;FixtureSeedObserver fixture_seed_observer;bool fixture_seed_observed=false;
#ifdef STRATA_T38_GLOBAL_FIXTURE
 std::array<uint64_t,5> fixture_seed_positions{};std::array<bool,5> fixture_seed_seen{};
 bool fixture_seed_multiple=false,fixture_borrow_active=false,fixture_operation_active=false;
#endif
#endif
#if defined(STRATA_T28_CONSTRUCTION_TEST) && defined(STRATA_T38_SEED_CONSTRUCTION)
 FixtureProposalObserver fixture_proposal_observer;bool fixture_proposal_started=false;
#endif
 DraftWeights weights;TargetWeightSupply target;
 DraftDeviceMetadata state;std::array<DeviceView,3> rings;DeviceView features,main;
 std::unique_ptr<DraftDeviceCheckpoint> checkpoint;
 Impl(const std::string&path,const Asset&a,const Artifact&source,const RequestBinding&b,int device,uint64_t dc,uint64_t tc):asset(a),binding(b),weights(path,a,device,dc),target(source,b,device,tc){
  state.owner=b.owner;state.epoch=b.epoch;for(unsigned i=0;i<3;++i){rings[i]=weights.workspace("network-ring-"+std::to_string(i),128,512,DeviceScalar::Bfloat16InFloat32);check(hipMemsetAsync(rings[i].data,0,128*512*4,reinterpret_cast<hipStream_t>(weights.stream())));}
  features=weights.workspace("network-main-features",1,15360,DeviceScalar::Bfloat16InFloat32);main=weights.workspace("network-main-derived",1,5120,DeviceScalar::Bfloat16InFloat32);
 }
 void ready(){need(state.valid,"invalid draft network");
#ifdef STRATA_T38_GLOBAL_FIXTURE
  need(!fixture_borrow_active&&!fixture_operation_active,"draft operation during fixture borrow/operation");
#endif
 }
 std::array<const DeviceView*,4> buffers(){return {&rings[0],&rings[1],&rings[2],&features};}
 void derive_main(){
  // features is mathematical state. main/dot/cast are always overwritten before read,
  // including after every restore; none of these derived views is snapshot state.
  auto dot=weights.workspace("network-main-dot",1,5120,DeviceScalar::Float32),cast=weights.workspace("network-main-cast",1,5120,DeviceScalar::Bfloat16InFloat32);
  weights.project(draft_source(asset,"dflash.fc.weight"),features,dot);ffn_bf16_device(dot,cast,weights.stream());auto norm=weights.constant(draft_source(asset,"dflash.hidden_norm.weight"));attention_rms_device(cast,norm,main,weights.stream());
 }
 DeviceView work(const std::string&tag,const std::string&name,uint64_t rows,uint64_t cols,DeviceScalar type=DeviceScalar::Bfloat16InFloat32){return weights.workspace(tag+name,rows,cols,type);}
 MhcWorkspace mhc(const std::string&tag,uint64_t b){MhcWorkspace w;w.inverse=work(tag,"inverse",b,1,DeviceScalar::Float32);w.dot=work(tag,"dot",b,24,DeviceScalar::Float32);w.mixed=work(tag,"mixed",b,24,DeviceScalar::Float32);w.pre=work(tag,"pre",b,4,DeviceScalar::Float32);w.post=work(tag,"post",b,4,DeviceScalar::Float32);w.comb=work(tag,"comb",b,16,DeviceScalar::Float32);return w;}
 BlockWorkspace block(const std::string&tag,uint64_t b){BlockWorkspace w;w.attention=mhc(tag+"attn-",b);w.ffn=mhc(tag+"ffn-",b);w.collapsed=work(tag,"collapsed",b,5120);w.norm_inverse=work(tag,"norm-inverse",b,1,DeviceScalar::Float32);w.normalized=work(tag,"normalized",b,5120);w.subblock=work(tag,"subblock",b,5120);w.after_attention=work(tag,"after-attention",b,20480);return w;}
 FfnWorkspace ffn(const std::string&tag,uint64_t b){FfnWorkspace w;auto f=DeviceScalar::Float32;
  w.logits=work(tag,"logits",b,128,f);w.scores=work(tag,"scores",b,128,f);w.corrected=work(tag,"corrected",b,128,f);w.ids=work(tag,"ids",b,3,DeviceScalar::UInt32);w.weights=work(tag,"weights",b,3,f);w.accumulated=work(tag,"accumulated",b,5120,f);
  w.selected_input=work(tag,"selected-input",b,5120);w.selected_route=work(tag,"selected-route",b,1,f);w.selected_pairs=work(tag,"selected-pairs",b,2,DeviceScalar::UInt32);w.gate=work(tag,"gate",b,2304);w.up=work(tag,"up",b,2304);w.hidden=work(tag,"hidden",b,2304);w.down_dot=work(tag,"down-dot",b,5120,f);w.down_bf16=work(tag,"down-bf16",b,5120);return w;
 }
};
DraftNetwork::DraftNetwork(const std::string&path,const Asset&a,const Artifact&source,const RequestBinding&b,int device,uint64_t dc,uint64_t tc):p_(std::make_unique<Impl>(path,a,source,b,device,dc,tc)){}
DraftNetwork::~DraftNetwork()=default;
#ifdef STRATA_T28_CONSTRUCTION_TEST
void DraftNetwork::set_fixture_seed_observer(uint64_t position,FixtureSeedObserver observer){
 auto&p=*p_;p.ready();need(bool(observer)&&p.state.cursor==0&&!p.fixture_seed_observer,"fresh unique seed observer");p.fixture_seed_position=position;p.fixture_seed_observer=std::move(observer);
}
#endif
#if defined(STRATA_T28_CONSTRUCTION_TEST) && defined(STRATA_T38_SEED_CONSTRUCTION)
void DraftNetwork::set_fixture_proposal_observer(FixtureProposalObserver observer){
 auto&p=*p_;p.ready();need(bool(observer)&&p.state.cursor==0&&!p.fixture_proposal_observer,"fresh unique proposal observer");p.fixture_proposal_observer=std::move(observer);
}
#endif
#ifdef STRATA_T38_GLOBAL_FIXTURE
void DraftNetwork::set_fixture_seed_observer(const std::array<uint64_t,5>&positions,FixtureSeedObserver observer){
 auto&p=*p_;p.ready();need(bool(observer)&&p.state.cursor==0&&!p.fixture_seed_observer,"fresh unique global seed observer");
 for(unsigned i=0;i<5;++i)need(positions[i]<uint64_t(INT64_MAX)&&(!i||positions[i-1]<positions[i]),"five ascending fixture seed positions");
 p.fixture_seed_positions=positions;p.fixture_seed_seen={};p.fixture_seed_multiple=true;p.fixture_seed_observer=std::move(observer);
}
void DraftNetwork::fixture_visit_math(const FixtureMathVisitor&visitor){
 auto&p=*p_;p.ready();need(bool(visitor)&&p.state.cursor,"healthy completed draft fixture checkpoint");
 drain();metadata_ok(p.state);view(p.features,p.main.device,1,15360,DeviceScalar::Bfloat16InFloat32);
 for(const auto&r:p.rings)view(r,p.main.device,128,512,DeviceScalar::Bfloat16InFloat32);
 p.fixture_borrow_active=true;
 try{visitor(p.binding,p.state,p.features,p.rings,p.weights.stream());need(p.state.valid,"draft invalidated during fixture borrow");p.fixture_borrow_active=false;}
 catch(...){p.fixture_borrow_active=false;p.state.valid=false;throw;}
}
#endif
uint64_t DraftNetwork::processed_cursor()const{return p_->state.cursor;}
uint64_t DraftNetwork::explicit_owned_bytes()const{auto&p=*p_;auto a=p.weights.explicit_owned_bytes(),b=p.target.explicit_owned_bytes();need(a<=UINT64_MAX-b,"network memory ledger overflow");auto sum=a+b;if(p.checkpoint){auto c=p.checkpoint->explicit_owned_bytes();need(sum<=UINT64_MAX-c,"checkpoint memory ledger overflow");sum+=c;}return sum;}
void DraftNetwork::prepare_workspace(uint64_t width){
 auto&p=*p_;p.ready();need(width,"normal workspace width");p.weights.prepare_host(width);auto bf=DeviceScalar::Bfloat16InFloat32,f=DeviceScalar::Float32,i64=DeviceScalar::Int64,u32=DeviceScalar::UInt32;
 try{
  for(const auto&t:p.asset.tensors)if(t.type==0&&t.dims.size()==1&&t.name!="dflash.dspark.confidence.bias")p.weights.constant(required_span(p.asset,t.name,0,0,1));
  for(auto name:{"main-dot","main-cast","network-main-dot","network-main-cast"})p.weights.workspace(name,1,5120,std::string(name).find("cast")!=std::string::npos?bf:f);
  p.weights.workspace("main-concat",1,15360,bf);p.weights.workspace("markov-embedding",1,256,f);p.weights.workspace("markov-bias",1,129280,f);
  auto tag="network-width-"+std::to_string(width)+"-";p.work(tag,"residual-a",width,20480);p.work(tag,"residual-b",width,20480);p.work(tag,"incoming",width,4,f);p.block(tag+"block-",width);p.ffn(tag+"routed-",width);
  p.work(tag,"head-collapsed",width,5120);p.work(tag,"head-normalized",width,5120);p.work(tag,"head-logits",width,129280,f);p.work(tag,"confidence",width,1,f);
  for(unsigned stage=0;stage<3;++stage){
   auto seed="seed-"+std::to_string(stage)+"-";for(auto name:{"dot","cast","normed","rotated"})p.weights.workspace(seed+name,1,512,std::string(name)=="dot"?f:bf);p.weights.workspace(seed+"freq",1,32,f);p.weights.workspace(seed+"position",1,1,i64);
   auto a="attention-"+std::to_string(stage)+"-width-"+std::to_string(width)+"-";
   for(auto name:{"qa-dot","qa","qr"})p.weights.workspace(a+name,width,1280,std::string(name)=="qa-dot"?f:bf);
   for(auto name:{"q-dot","q"})p.weights.workspace(a+name,width,32768,std::string(name)=="q-dot"?f:bf);
   for(auto name:{"q-rope","attended","inverse"})p.weights.workspace(a+name,mul(width,64),512,bf);
   for(auto name:{"kv-dot","kv","kv-norm","kv-rope"})p.weights.workspace(a+name,width,512,std::string(name)=="kv-dot"?f:bf);
   p.weights.workspace(a+"positions",width,1,i64);p.weights.workspace(a+"head-positions",mul(width,64),1,i64);p.weights.workspace(a+"freq",1,32,f);p.weights.workspace(a+"indices",1,noise_index_extent(1,width).capacity,i64);p.weights.workspace(a+"error",1,1,u32);
   p.weights.workspace(a+"group-input",width,4096,bf);p.weights.workspace(a+"group-dot",width,8192,f);p.weights.workspace(a+"group-cast",width,8192,bf);p.weights.workspace(a+"out-dot",width,5120,f);
  }
  drain();
 }catch(...){p.state.valid=false;throw;}
}
void DraftNetwork::record_processed(uint32_t id,uint64_t position,const RequestBinding&binding,const std::array<TapProof,3>&proof,const std::array<const DeviceView*,3>&means,void*producer){return record_processed(id,position,binding,proof,means,producer,{});}
void DraftNetwork::record_processed(uint32_t id,uint64_t position,const RequestBinding&binding,const std::array<TapProof,3>&proof,const std::array<const DeviceView*,3>&means,void*producer,const ContinueWork&control){
 auto&p=*p_;p.ready();
#ifdef STRATA_T38_GLOBAL_FIXTURE
 FixtureNetworkOperation fixture_operation(p.fixture_operation_active);
#endif
 auto copy=control;p.weights.set_control(std::move(copy));struct Clear{DraftWeights&w;~Clear(){w.set_control({});}}clear{p.weights};need(id<129280&&position==p.state.cursor&&position<uint64_t(INT64_MAX),"draft processed token/position");need(binding.owner==p.binding.owner&&binding.epoch==p.binding.epoch&&binding.bundle==p.binding.bundle,"draft processed request binding");
 for(unsigned i=0;i<3;++i){auto&t=proof[i];need(t.owner==binding.owner&&t.epoch==binding.epoch&&t.position==position&&t.layer==37+i&&t.hc==4&&t.hidden==5120&&means[i],"processed tap mean provenance");view(*means[i],p.main.device,1,5120,DeviceScalar::Bfloat16InFloat32);distinct(*means[i],p.features);}
 auto validate_stream=[&](void*stream){target_stream_preflight(p.state.valid,stream,p.main.device,[](int&d){return int(hipGetDevice(&d));},[](void*s,int&d){return int(hipStreamGetDevice(reinterpret_cast<hipStream_t>(s),&d));});};validate_stream(producer);validate_stream(p.weights.stream());auto source_stream=reinterpret_cast<hipStream_t>(producer);auto hs=reinterpret_cast<hipStream_t>(p.weights.stream());
 try{check(hipStreamSynchronize(source_stream));for(unsigned i=0;i<3;++i)check(hipMemcpyAsync((float*)p.features.data+i*5120,means[i]->data,5120*4,hipMemcpyDeviceToDevice,hs));p.derive_main();for(unsigned stage=0;stage<3;++stage)draft_seed_main_no_qdq_device(p.asset,stage,p.main,p.rings[stage],p.weights,position);p.weights.drain();p.state.cursor=position+1;p.state.stage_cursor={position+1,position+1,position+1};p.state.processed_prior=id;
#ifdef STRATA_T28_CONSTRUCTION_TEST
#ifdef STRATA_T38_GLOBAL_FIXTURE
  if(p.fixture_seed_multiple){for(unsigned i=0;i<5;++i)if(p.fixture_seed_observer&&!p.fixture_seed_seen[i]&&position==p.fixture_seed_positions[i]){p.fixture_seed_seen[i]=true;p.fixture_seed_observer(position,p.binding,p.state,p.features,p.main,p.rings,p.weights.stream());}}
  else
#endif
  if(p.fixture_seed_observer&&!p.fixture_seed_observed&&position==p.fixture_seed_position){p.fixture_seed_observed=true;p.fixture_seed_observer(position,p.binding,p.state,p.features,p.main,p.rings,p.weights.stream());}
#endif
 }
 catch(...){p.state.valid=false;throw;}
}
void DraftNetwork::begin_checkpoint(){auto&p=*p_;p.ready();need(p.state.cursor&&!p.checkpoint,"checkpoint requires processed draft prefix");try{p.checkpoint=std::make_unique<DraftDeviceCheckpoint>(p.state,p.buffers(),p.weights.stream());}catch(...){p.state.valid=false;throw;}}
void DraftNetwork::restore_checkpoint(){auto&p=*p_;p.ready();need(bool(p.checkpoint),"missing draft checkpoint");p.checkpoint->restore(p.state,p.buffers(),p.weights.stream());/* derived main is not read until derive_main overwrites it */}
void DraftNetwork::commit_checkpoint(){auto&p=*p_;p.ready();need(bool(p.checkpoint),"missing draft checkpoint");try{p.checkpoint->commit(p.state,p.buffers(),p.weights.stream());p.checkpoint.reset();}catch(...){p.state.valid=false;throw;}}
DraftProposal DraftNetwork::propose(uint64_t width,const SamplingOptions&options,const std::vector<uint32_t>&history,NamespaceRng&rng){return propose(width,options,history,rng,{});}
DraftProposal DraftNetwork::propose(uint64_t width,const SamplingOptions&options,const std::vector<uint32_t>&history,NamespaceRng&rng,const ContinueWork&control){
 auto&p=*p_;p.ready();
#ifdef STRATA_T38_GLOBAL_FIXTURE
 FixtureNetworkOperation fixture_operation(p.fixture_operation_active);
#endif
 auto dc=control,tc=control;p.weights.set_control(std::move(dc));p.target.set_control(std::move(tc));struct Clear{DraftWeights&w;TargetWeightSupply&t;~Clear(){w.set_control({});t.set_control({});}}clear{p.weights,p.target};need(options.top_logprobs<=20&&(options.logprobs||!options.top_logprobs),"logprob options");auto q_options=options;q_options.logprobs=false;q_options.top_logprobs=0;need(width&&p.state.cursor&&p.state.processed_prior&&history.size()==p.state.cursor&&history.back()==*p.state.processed_prior,"draft proposal processed prefix/history");DraftProposal result;
 try{if(control&&!control())throw DraftCancelled{};if(p.state.cursor==1){result.seed_only=true;return result;}
#if defined(STRATA_T28_CONSTRUCTION_TEST) && defined(STRATA_T38_SEED_CONSTRUCTION)
  bool observe=p.fixture_proposal_observer&&!p.fixture_proposal_started;if(observe)p.fixture_proposal_started=true;
#endif
  auto pos=p.state.cursor-1;auto tag="network-width-"+std::to_string(width)+"-";auto s=p.weights.stream();p.derive_main();for(unsigned stage=0;stage<3;++stage)draft_seed_main_no_qdq_device(p.asset,stage,p.main,p.rings[stage],p.weights,pos);p.weights.drain();
  auto a=p.work(tag,"residual-a",width,20480),b=p.work(tag,"residual-b",width,20480),incoming=p.work(tag,"incoming",width,4,DeviceScalar::Float32);std::vector<uint32_t>ids(static_cast<size_t>(width),128799);ids[0]=*p.state.processed_prior;p.target.embedding(ids,a,p.binding);p.target.drain();
  std::vector<float>identity(static_cast<size_t>(mul(width,4)),0);for(uint64_t i=0;i<width;++i)identity[i*4]=1;p.weights.upload(incoming,identity.data(),mul(mul(width,4),4));auto block=p.block(tag+"block-",width);auto ffn=p.ffn(tag+"routed-",width);
  DraftProjection project=[&](const Span&weight,const DeviceView&x,const DeviceView&y,void*stream){need(stream==s,"network projection stream");p.weights.project(weight,x,y);};DraftConstantLookup constant=[&](const Span&span){return p.weights.constant(span);};std::array<DraftSubblock,3>attentions,ffns;
  for(unsigned stage=0;stage<3;++stage){attentions[stage]=[&,stage](const DeviceView&x,const DeviceView&y,void*stream){if(control&&!control())throw DraftCancelled{};need(stream==s,"network attention stream");draft_attention_no_qdq_device(p.asset,stage,x,y,p.rings[stage],p.weights,pos);};ffns[stage]=[&,stage](const DeviceView&x,const DeviceView&y,void*stream){need(stream==s,"network FFN stream");draft_ffn_device(p.asset,stage,x,y,ffn,project,constant,s,&p.weights.host_scratch());};}
#if defined(STRATA_T28_CONSTRUCTION_TEST) && defined(STRATA_T38_SEED_CONSTRUCTION)
  std::function<void(uint32_t,const DeviceView&,void*)>stage_completed;
  if(observe)stage_completed=[&](uint32_t stage,const DeviceView&value,void*producer){p.weights.drain();p.fixture_proposal_observer(static_cast<FixtureProposalField>(stage),p.binding,p.state.cursor,value,producer);};
#endif
  draft_three_blocks_device(p.asset,a,b,incoming,block,project,constant,attentions,ffns,s
#if defined(STRATA_T28_CONSTRUCTION_TEST) && defined(STRATA_T38_SEED_CONSTRUCTION)
   ,stage_completed?&stage_completed:nullptr
#endif
  );auto collapsed=p.work(tag,"head-collapsed",width,5120),normalized=p.work(tag,"head-normalized",width,5120),logits=p.work(tag,"head-logits",width,129280,DeviceScalar::Float32),confidence=p.work(tag,"confidence",width,1,DeviceScalar::Float32);draft_tail_device(p.asset,b,incoming,collapsed,normalized,p.weights);p.weights.drain();
#if defined(STRATA_T28_CONSTRUCTION_TEST) && defined(STRATA_T38_SEED_CONSTRUCTION)
  if(observe){p.fixture_proposal_observer(FixtureProposalField::TailCollapsed,p.binding,p.state.cursor,collapsed,s);p.fixture_proposal_observer(FixtureProposalField::HeadNormalized,p.binding,p.state.cursor,normalized,s);}
#endif
  p.target.head(normalized,logits,p.binding);p.target.drain();
#if defined(STRATA_T28_CONSTRUCTION_TEST) && defined(STRATA_T38_SEED_CONSTRUCTION)
  if(observe)p.fixture_proposal_observer(FixtureProposalField::HeadPreMarkov,p.binding,p.state.cursor,logits,p.target.stream());
#endif
  auto row_view=[&](const DeviceView&v,uint64_t row){auto x=v;auto bytes=mul(v.columns,4);x.data=(uint8_t*)v.data+mul(row,bytes);x.rows=1;x.bytes=bytes;return x;};auto local_history=history;uint32_t previous=*p.state.processed_prior;auto&host=p.weights.host_scratch();host.logits.resize(129280);auto&host_logits=host.logits;auto hs=stream(s,logits.device);
  for(uint64_t row=0;row<width;++row){auto l=row_view(logits,row),h=row_view(collapsed,row),c=row_view(confidence,row);draft_markov_device(p.asset,previous,l,h,c,p.weights);p.weights.drain();host.raw_confidence=0;host_transfer(host,[&]{check(hipMemcpyAsync(host_logits.data(),l.data,129280*4,hipMemcpyDeviceToHost,hs));check(hipMemcpyAsync(&host.raw_confidence,c.data,4,hipMemcpyDeviceToHost,hs));check(hipStreamSynchronize(hs));});if(control&&!control())throw DraftCancelled{};auto effective=effective_distribution(host_logits,local_history,q_options);auto sampled=sample_distribution(effective,rng.uniform(RngSpace::Proposal));result.ids.push_back(sampled.id);result.q.push_back(effective.probabilities());result.raw_confidence.push_back(host.raw_confidence);local_history.push_back(sampled.id);previous=sampled.id;}
  p.weights.drain();if(control&&!control())throw DraftCancelled{};return result;
 }catch(...){p.state.valid=false;throw;}
}

void DraftNetwork::drain(){auto&p=*p_;
#ifdef STRATA_T38_GLOBAL_FIXTURE
 need(!p.fixture_borrow_active&&!p.fixture_operation_active,"draft drain during fixture borrow/operation");
#endif
 std::exception_ptr first;try{p.weights.drain();}catch(...){first=std::current_exception();}try{p.target.drain();}catch(...){if(!first)first=std::current_exception();}if(first){p.state.valid=false;std::rethrow_exception(first);}}
void DraftNetwork::invalidate_and_drain(){p_->state.valid=false;drain();}
NetworkActorDraft::NetworkActorDraft(DraftNetwork&network):network_(network){}
DraftProposal NetworkActorDraft::propose(uint64_t width,const SamplingOptions&o,const std::vector<uint32_t>&history,NamespaceRng&rng,const ContinueWork&control){complete_=false;auto p=network_.propose(width,o,history,rng,control);complete_=true;return p;}
uint64_t NetworkActorDraft::cursor()const{return network_.processed_cursor();}
void NetworkActorDraft::drain(){complete_=false;network_.drain();complete_=true;}
void NetworkActorDraft::invalidate_and_drain()noexcept{complete_=false;try{network_.invalidate_and_drain();complete_=true;}catch(...){}}

struct CoreTargetAdapter::Impl:CoreTapSink {
 CoreSequence&core;DraftNetwork&network;measurement::Identity identity;RequestBinding binding;int device;
 std::function<void()> invalidate_target,quiesce_target;std::function<bool(uint64_t,uint64_t)> prefill_control;ContinueWork control;
 std::unique_ptr<CoreStorage> storage;DeviceView means;std::shared_ptr<const uint8_t> instance;
 const std::vector<uint32_t>*tokens=nullptr;uint64_t start=0,next=0,known=0;unsigned captures=0;
 bool armed=false,valid=true,complete=true,consumer_complete=true,cleanup_attempted=false;void*producer=nullptr;
 std::array<TapProof,3> proofs;StepProof last;CoreOutput prefill_result;std::vector<float> current_logits;
#ifdef STRATA_T38_GLOBAL_FIXTURE
 uint32_t fixture_last_id=0;bool fixture_last_processed=false,fixture_borrow_active=false;
 void fixture_ready(){need(valid&&!armed&&complete&&consumer_complete&&!fixture_borrow_active&&core.position()==known&&network.processed_cursor()==known,"quiescent common fixture cursor");}
#endif
 Impl(CoreSequence&c,const measurement::Identity&i,RequestBinding b,int d,DraftNetwork&n,std::function<void()>cleanup,std::function<bool(uint64_t,uint64_t)>pc,PreparedPrefix prepared,std::function<void()>quiesce):core(c),network(n),identity(i),binding(std::move(b)),device(d),invalidate_target(std::move(cleanup)),quiesce_target(std::move(quiesce)),prefill_control(std::move(pc)){
  need(binding.owner&&binding.epoch==identity.epoch&&binding.bundle==identity.bundle_sha256&&!identity.request_id.empty()&&!identity.fixture_sha256.empty()&&!identity.asset_sha256.empty()&&invalidate_target,"actual target request/identity mapping");need(core.position()==prepared.processed&&network.processed_cursor()==prepared.processed,"actual adapter prepared owners");need(prepared.logits.empty()||prepared.processed&&prepared.logits.size()==129280,"prepared raw logits shape");known=prepared.processed;current_logits=std::move(prepared.logits);auto tap=core.prepare_tap(known);(void)tap;storage=std::make_unique<CoreStorage>(device);means=storage->allocate("dspark-single-mean",1,15360,DeviceScalar::Bfloat16InFloat32);
 }
 void arm(const std::vector<uint32_t>&ids,uint64_t pos){
#ifdef STRATA_T38_GLOBAL_FIXTURE
  need(!fixture_borrow_active,"target operation during fixture borrow");fixture_last_processed=false;
#endif
  need(valid&&!armed&&pos==known&&network.processed_cursor()==known&&!ids.empty(),"target arm common prefix");tokens=&ids;start=next=pos;captures=0;producer=nullptr;armed=true;complete=false;}
 void disarm()noexcept{armed=false;tokens=nullptr;}
 void capture(const CoreTapFrame&frame)override{
  detail::validate_actor_capture(frame,identity,instance,next,captures,device,DeviceScalar::Bfloat16InFloat32,armed&&valid,producer);if(!instance)instance=frame.instance;producer=frame.stream;core_tap_mean_device(frame,means);proofs[captures]={binding.owner,binding.epoch,next,frame.target_layer,4,5120};++captures;
 }
 void processed(const CoreTapToken&token)override{
  detail::validate_actor_processed(token,identity,instance,next,captures,producer,armed&&valid&&tokens);need(next>=start&&next-start<tokens->size(),"actual processed original ID");known=token.cursor_after;consumer_complete=false;
  std::array<DeviceView,3>slices;std::array<const DeviceView*,3>views;for(unsigned i=0;i<3;++i){slices[i]=means;slices[i].data=(float*)means.data+i*5120;slices[i].columns=5120;slices[i].bytes=5120*4;views[i]=&slices[i];}
  try{network.record_processed((*tokens)[size_t(next-start)],next,binding,proofs,views,producer,control);consumer_complete=true;last={binding,next,next+1,proofs};
#ifdef STRATA_T38_GLOBAL_FIXTURE
   fixture_last_id=(*tokens)[size_t(next-start)];fixture_last_processed=true;
#endif
   ++next;captures=0;producer=nullptr;}catch(...){valid=false;throw;}
 }
};
CoreTargetAdapter::CoreTargetAdapter(CoreSequence&core,const measurement::Identity&identity,RequestBinding binding,int device,DraftNetwork&network,std::function<void()>cleanup,std::function<bool(uint64_t,uint64_t)>control,PreparedPrefix prepared,std::function<void()>quiesce):p_(std::make_unique<Impl>(core,identity,std::move(binding),device,network,std::move(cleanup),std::move(control),std::move(prepared),std::move(quiesce))){}
CoreTargetAdapter::~CoreTargetAdapter(){if(p_&&!p_->complete)(void)p_->storage.release();/* unknown producer/consumer completion retains the mean owner */}
void CoreTargetAdapter::set_control(ContinueWork control){p_->control=std::move(control);}
uint64_t CoreTargetAdapter::known_cursor()const noexcept{return p_->known;}
bool CoreTargetAdapter::completion_known()const noexcept{return p_->complete;}
ActorTransferStats CoreTargetAdapter::transfer_stats()const{ActorTransferStats s;s.primary_device_owned=p_->storage->explicit_owned_bytes();return s;}
const std::vector<float>& CoreTargetAdapter::logits()const{return p_->current_logits;}
const CoreOutput& CoreTargetAdapter::prefill_output()const{return p_->prefill_result;}
#ifdef STRATA_T38_GLOBAL_FIXTURE
void CoreTargetAdapter::fixture_visit_last_processed_mean(const FixtureProcessedMeanVisitor&visitor){
 auto&p=*p_;p.fixture_ready();need(bool(visitor)&&p.fixture_last_processed&&p.known&&p.last.before==p.known-1&&p.last.after==p.known,"actual last processed fixture proof");
 need(p.last.binding.owner==p.binding.owner&&p.last.binding.epoch==p.binding.epoch&&p.last.binding.bundle==p.binding.bundle,"last processed fixture binding");
 for(unsigned i=0;i<3;++i){auto&t=p.last.taps[i];need(t.owner==p.binding.owner&&t.epoch==p.binding.epoch&&t.position==p.last.before&&t.layer==37+i&&t.hc==4&&t.hidden==5120,"last processed fixture taps");}
 view(p.means,p.device,1,15360,DeviceScalar::Bfloat16InFloat32);need(p.means.bytes==61440,"last processed fixture mean extent");
 p.complete=false;p.fixture_borrow_active=true;
 try{p.storage->drain();visitor(p.fixture_last_id,p.last,p.means,p.storage->stream());need(p.valid,"target invalidated during fixture borrow");p.fixture_borrow_active=false;p.complete=true;}
 catch(...){p.fixture_borrow_active=false;p.valid=false;p.complete=false;throw;}
}
void CoreTargetAdapter::fixture_visit_state(const std::function<void(const FixtureStateRecord&,void*)>&visitor){
 auto&p=*p_;p.fixture_ready();need(bool(visitor),"missing Core fixture state visitor");p.complete=false;p.fixture_borrow_active=true;
 try{p.core.fixture_visit_state(visitor);need(p.valid,"target invalidated during fixture borrow");p.fixture_borrow_active=false;p.complete=true;}
 catch(...){p.fixture_borrow_active=false;p.valid=false;p.complete=false;throw;}
}
#endif
void CoreTargetAdapter::prefill(const std::vector<uint32_t>&ids){
#ifdef STRATA_T38_GLOBAL_FIXTURE
 need(!p_->fixture_borrow_active,"target prefill during fixture borrow");
#endif
 auto&p=*p_;need(p.valid&&!p.armed&&p.known<=ids.size(),"prepared tapped prefill boundary");auto reused=p.known;
 try{auto control=[&](uint64_t done,uint64_t){return (!p.control||p.control())&&(!p.prefill_control||p.prefill_control(reused+done,ids.size()));};
  if(reused==ids.size()){need(p.current_logits.size()==129280,"prepared prefix cached raw logits");if(!control(0,0))throw DraftCancelled{};p.prefill_result={};p.prefill_result.rows=1;p.prefill_result.vocabulary=129280;return;}
  std::vector<uint32_t>suffix(ids.begin()+size_t(reused),ids.end());p.arm(suffix,reused);auto binding=p.core.prepare_tap(reused);p.prefill_result=p.core.prefill_tapped(suffix,reused,{},binding,p,control);p.disarm();if(p.prefill_result.cancelled)throw DraftCancelled{};need(p.known==ids.size()&&p.next==ids.size()&&p.network.processed_cursor()==p.known&&p.prefill_result.vocabulary==129280&&p.prefill_result.logits.size()>=129280,"actual prefill successful subset/logits");p.current_logits.assign(p.prefill_result.logits.end()-129280,p.prefill_result.logits.end());p.complete=true;
 }catch(...){p.disarm();p.valid=false;invalidate_and_drain();throw;}
}
StepProof CoreTargetAdapter::step(uint32_t id,uint64_t position){
 auto&p=*p_;std::vector<uint32_t>ids{id};p.arm(ids,position);
 try{auto binding=p.core.prepare_tap(position);p.current_logits=p.core.step_tapped(id,position,binding,p);p.disarm();need(p.known==position+1&&p.network.processed_cursor()==p.known&&p.current_logits.size()==129280,"actual target/draft successful step");p.complete=true;return p.last;
 }catch(...){p.disarm();p.valid=false;invalidate_and_drain();throw;}
}
void CoreTargetAdapter::drain(){auto&p=*p_;
#ifdef STRATA_T38_GLOBAL_FIXTURE
 need(!p.fixture_borrow_active,"target drain during fixture borrow");
#endif
 need(p.valid&&!p.armed,"healthy target drain after tapped operation only");p.complete=false;if(p.quiesce_target)p.quiesce_target();else p.core.quiesce();need(p.consumer_complete,"target mean consumer incomplete");p.storage->drain();p.complete=true;}
void CoreTargetAdapter::invalidate_and_drain()noexcept{
 auto&p=*p_;if(p.armed){p.valid=false;p.complete=false;return;}if(p.cleanup_attempted)return;p.cleanup_attempted=true;p.valid=false;p.complete=false;bool producer=false,consumer=false,own=false;
 try{p.invalidate_target();producer=true;}catch(...){}try{p.network.invalidate_and_drain();consumer=true;p.consumer_complete=true;}catch(...){}try{p.storage->drain();own=true;}catch(...){}p.complete=producer&&consumer&&own;
}

struct LayerSplitActorTarget::Impl:LayerSplitTapSink {
 LayerSplit&core;DraftNetwork&network;measurement::Identity identity;RequestBinding binding;int device;
 std::function<void()>invalidate_target,quiesce_target;std::function<bool(uint64_t,uint64_t)>prefill_control;ContinueWork control;
 struct Mean {std::unique_ptr<CoreStorage>storage;DeviceView value;};
 std::map<int,Mean>means;std::unique_ptr<CoreStorage>destination;DeviceView output;
 struct Copy {cache::ResidentSlot source,dest;std::unique_ptr<device::CopyTask>task;};
 std::array<Copy,3>copies;std::vector<uint8_t>bounce=std::vector<uint8_t>(5120*4);
 ActorTransferStats transferred;LayerSplitTapBinding tap;const std::vector<uint32_t>*tokens=nullptr;uint64_t start=0,next=0,known=0;
 unsigned captures=0;bool armed=false,valid=true,complete=true,consumer_complete=true,cleanup_attempted=false;
 std::array<TapProof,3>proofs;StepProof last;CoreOutput prefill_result;std::vector<float>current_logits;
 struct On {int before=-1;explicit On(int d){check(hipGetDevice(&before));check(hipSetDevice(d));}~On(){if(before>=0)hipSetDevice(before);}};
 Impl(LayerSplit&c,const measurement::Identity&i,RequestBinding b,int d,DraftNetwork&n,std::function<void()>cleanup,std::function<bool(uint64_t,uint64_t)>pc,PreparedPrefix prepared,std::function<void()>quiesce):core(c),network(n),identity(i),binding(std::move(b)),device(d),invalidate_target(std::move(cleanup)),quiesce_target(std::move(quiesce)),prefill_control(std::move(pc)){
  need(binding.owner&&binding.epoch==identity.epoch&&binding.bundle==identity.bundle_sha256&&invalidate_target,"paired Actor request mapping");need(core.position()==prepared.processed&&network.processed_cursor()==prepared.processed,"paired prepared owners");need(prepared.logits.empty()||prepared.processed&&prepared.logits.size()==129280,"paired prepared raw logits");known=prepared.processed;current_logits=std::move(prepared.logits);tap=core.prepare_tap(known);
  for(int id:{tap.primary.device,tap.secondary.device}){On on(id);auto&v=means[id];v.storage=std::make_unique<CoreStorage>(id);v.value=v.storage->allocate("dspark-partition-mean",1,15360,DeviceScalar::Bfloat16InFloat32);}
  On on(device);destination=std::make_unique<CoreStorage>(device);output=destination->allocate("dspark-paired-mean",1,15360,DeviceScalar::Bfloat16InFloat32);
 }
 void arm(const std::vector<uint32_t>&ids,uint64_t pos){need(valid&&!armed&&pos==known&&network.processed_cursor()==known&&!ids.empty(),"paired arm common prefix");tap=core.prepare_tap(pos);tokens=&ids;start=next=pos;captures=0;armed=true;complete=false;}
 void disarm()noexcept{armed=false;tokens=nullptr;}
 DeviceView slice(DeviceView v,unsigned index){v.data=(float*)v.data+index*5120;v.columns=5120;v.bytes=5120*4;return v;}
 void capture(const CoreTapFrame&frame)override{
  need(armed&&valid&&frame.residual.scalar==DeviceScalar::Bfloat16InFloat32,"paired armed scalar");auto current=tap;current.position=next;current.primary.position=current.secondary.position=next;layer_tap_detail::validate_capture(frame,current,captures);
  auto&mean=means.at(frame.residual.device);{On on(frame.residual.device);core_tap_mean_device(frame,mean.value);}
  auto src=slice(mean.value,captures),dst=slice(output,captures);auto&copy=copies[captures];need(!copy.task,"paired mean slot not returned");
  // Each exact slice has its own lease. CopyTask waits the actual producer stream,
  // and retains the destination reader until record_processed's real last use.
  copy.source={reinterpret_cast<uintptr_t>(src.data),src.bytes,binding.owner,1,0,false,true,false};copy.dest={reinterpret_cast<uintptr_t>(dst.data),dst.bytes,binding.owner,0,0,false,false,false};
  device::Endpoint se{src.data,src.bytes,src.device,reinterpret_cast<hipStream_t>(frame.stream),&copy.source,copy.source.owner,copy.source.generation};device::Endpoint de{dst.data,dst.bytes,dst.device,reinterpret_cast<hipStream_t>(destination->stream()),&copy.dest,copy.dest.owner,copy.dest.generation};
  On on(device);copy.task=std::make_unique<device::CopyTask>(se,de,bounce.data(),bounce.size(),device::Policy::Auto);copy.task->submit(src.bytes);
  while(copy.task->phase()!=device::Phase::Ready){copy.task->poll();need(copy.task->phase()!=device::Phase::Quarantined,"paired mean copy completion unknown");std::this_thread::yield();}
  proofs[captures]={binding.owner,binding.epoch,next,frame.target_layer,4,5120};++captures;
 }
 void close_copies(bool cancel){On on(device);for(auto&copy:copies){if(!copy.task)continue;if(cancel)copy.task->cancel();while(copy.task->phase()!=device::Phase::Done){if(copy.task->phase()==device::Phase::Ready)copy.task->consumer_done_on(reinterpret_cast<hipStream_t>(destination->stream()));else copy.task->poll();need(copy.task->phase()!=device::Phase::Quarantined,"paired mean last use unknown");std::this_thread::yield();}need(copy.task->try_close(),"paired mean copy close unknown");auto stats=copy.task->stats();transferred.peer_bytes+=stats.peer_bytes;transferred.bounce_d2h+=stats.bounce_d2h;transferred.bounce_h2d+=stats.bounce_h2d;copy.task.reset();}}
 void processed(const LayerSplitTapToken&t)override{
  need(armed&&valid&&tokens&&captures==3&&detail::same_actor_identity(t.identity,identity)&&t.instance==tap.instance&&t.primary.instance==tap.primary.instance&&t.secondary.instance==tap.secondary.instance&&t.position==next&&next!=UINT64_MAX&&t.cursor_after==next+1&&next>=start&&next-start<tokens->size(),"paired processed original token/instances");known=t.cursor_after;consumer_complete=false;
  std::array<DeviceView,3>slices;std::array<const DeviceView*,3>views;for(unsigned j=0;j<3;++j){slices[j]=slice(output,j);views[j]=&slices[j];}
  try{On on(device);network.record_processed((*tokens)[size_t(next-start)],next,binding,proofs,views,destination->stream(),control);close_copies(false);consumer_complete=true;last={binding,next,next+1,proofs};++next;captures=0;}catch(...){valid=false;throw;}
 }
};
LayerSplitActorTarget::LayerSplitActorTarget(LayerSplit&core,const measurement::Identity&i,RequestBinding b,int d,DraftNetwork&n,std::function<void()>cleanup,std::function<bool(uint64_t,uint64_t)>control,PreparedPrefix prepared,std::function<void()>quiesce):p_(std::make_unique<Impl>(core,i,std::move(b),d,n,std::move(cleanup),std::move(control),std::move(prepared),std::move(quiesce))){}
LayerSplitActorTarget::~LayerSplitActorTarget(){if(p_&&!p_->complete)(void)p_.release();/* retain all source/destination/stream/bounce/copy owners */}
void LayerSplitActorTarget::set_control(ContinueWork c){p_->control=std::move(c);}
uint64_t LayerSplitActorTarget::known_cursor()const noexcept{return p_->known;}
bool LayerSplitActorTarget::completion_known()const noexcept{return p_->complete;}
ActorTransferStats LayerSplitActorTarget::transfer_stats()const{auto out=p_->transferred;out.bounce_host_owned=p_->bounce.capacity();out.primary_device_owned=p_->destination->explicit_owned_bytes();for(const auto&mean:p_->means){if(mean.first==p_->device)out.primary_device_owned+=mean.second.storage->explicit_owned_bytes();else out.secondary_device_owned+=mean.second.storage->explicit_owned_bytes();}return out;}
const std::vector<float>&LayerSplitActorTarget::logits()const{return p_->current_logits;}
void LayerSplitActorTarget::prefill(const std::vector<uint32_t>&ids){
 auto&p=*p_;need(p.valid&&!p.armed&&p.known<=ids.size(),"prepared tapped prefill boundary");auto reused=p.known;
 try{auto control=[&](uint64_t done,uint64_t){return (!p.control||p.control())&&(!p.prefill_control||p.prefill_control(reused+done,ids.size()));};
  if(reused==ids.size()){need(p.current_logits.size()==129280,"prepared prefix cached raw logits");if(!control(0,0))throw DraftCancelled{};p.prefill_result={};p.prefill_result.rows=1;p.prefill_result.vocabulary=129280;return;}
  std::vector<uint32_t>suffix(ids.begin()+size_t(reused),ids.end());p.arm(suffix,reused);auto binding=p.core.prepare_tap(reused);p.prefill_result=p.core.prefill_tapped(suffix,reused,{},binding,p,control);p.disarm();if(p.prefill_result.cancelled)throw DraftCancelled{};need(p.known==ids.size()&&p.next==ids.size()&&p.network.processed_cursor()==p.known&&p.prefill_result.vocabulary==129280&&p.prefill_result.logits.size()>=129280,"actual prefill successful subset/logits");p.current_logits.assign(p.prefill_result.logits.end()-129280,p.prefill_result.logits.end());p.complete=true;
 }catch(...){p.disarm();p.valid=false;invalidate_and_drain();throw;}
}
StepProof LayerSplitActorTarget::step(uint32_t id,uint64_t position){
 auto&p=*p_;std::vector<uint32_t>ids{id};p.arm(ids,position);
 try{auto binding=p.core.prepare_tap(position);p.current_logits=p.core.step_tapped(id,position,binding,p);p.disarm();need(p.known==position+1&&p.network.processed_cursor()==p.known&&p.current_logits.size()==129280,"actual target/draft successful step");p.complete=true;return p.last;
 }catch(...){p.disarm();p.valid=false;invalidate_and_drain();throw;}
}

void LayerSplitActorTarget::drain(){auto&p=*p_;need(p.valid&&!p.armed,"paired healthy target drain");p.complete=false;p.core.quiesce();need(p.consumer_complete,"paired consumer incomplete");p.close_copies(false);for(auto&mean:p.means){Impl::On on(mean.first);mean.second.storage->drain();}Impl::On on(p.device);p.destination->drain();p.complete=true;}
void LayerSplitActorTarget::invalidate_and_drain()noexcept{auto&p=*p_;if(p.armed){p.valid=false;p.complete=false;return;}if(p.cleanup_attempted)return;p.cleanup_attempted=true;p.valid=false;p.complete=false;bool producer=false,consumer=false,own=false;try{p.invalidate_target();producer=true;}catch(...){}try{Impl::On on(p.device);p.network.invalidate_and_drain();consumer=true;}catch(...){}try{if(consumer){p.close_copies(true);for(auto&mean:p.means){Impl::On on(mean.first);mean.second.storage->drain();}Impl::On on(p.device);p.destination->drain();own=true;}}catch(...){}p.complete=producer&&consumer&&own;}

}






