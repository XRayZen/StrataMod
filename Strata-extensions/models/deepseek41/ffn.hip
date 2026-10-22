#include "ffn.hpp"
#include "../../native/quant/quant.hpp"
#include <hip/hip_runtime.h>
#include <cmath>
#include <cstring>
#include <algorithm>
#include <limits>
#include <set>

namespace strata_ext::deepseek41 {
namespace {
void check(hipError_t e){if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));}
struct ScratchStats{uint64_t live=0,peak=0;bool failed=false;};
thread_local ScratchStats scratch;
struct Buffer{
 void* p=nullptr;size_t n=0;
 explicit Buffer(size_t size):n(size){if(!n)throw std::runtime_error("empty scratch");check(hipMalloc(&p,n));scratch.live+=n;scratch.peak=std::max(scratch.peak,scratch.live);}
 ~Buffer(){if(p){auto e=hipFree(p);if(e==hipSuccess)scratch.live-=n;else scratch.failed=true;}}
};
__device__ float bf(float x){auto b=__float_as_uint(x);return __uint_as_float(((b+0x7fff+((b>>16)&1))>>16)<<16);}
__device__ float fp8_value(unsigned c){unsigned e=(c>>3)&15,m=c&7;return e==0?ldexpf(float(m),-9):ldexpf(float(8+m),int(e)-10);}
__device__ unsigned fp8_code(float x){
 float v=fminf(fabsf(x),448.f);unsigned lo=0,hi=126;
 while(lo<hi){unsigned mid=(lo+hi)/2;if(fp8_value(mid)<v)lo=mid+1;else hi=mid;}
 unsigned high=lo,low=lo?lo-1:0;float dh=fp8_value(high)-v,dl=v-fp8_value(low);
 unsigned code=dh<dl || (dh==dl && (high&1)==0)?high:low;return code | (signbit(x)?128:0);
}
__global__ void bf_kernel(const float*x,float*y,size_t n){size_t i=blockIdx.x*blockDim.x+threadIdx.x;if(i<n)y[i]=bf(x[i]);}
__global__ void qdq_kernel(const float*x,float*y,uint8_t*scale,uint8_t*code,size_t blocks){
 size_t b=blockIdx.x*blockDim.x+threadIdx.x;if(b>=blocks)return;float amax=1.e-4f;
 for(unsigned j=0;j<32;++j)amax=fmaxf(amax,fabsf(bf(x[b*32+j])));
 float normalized=amax*(1.f/448.f);unsigned bits=__float_as_uint(normalized);int exponent=int((bits>>23)&255)-127+((bits&0x7fffff)!=0);
 float s=ldexpf(1.f,exponent);if(scale)scale[b]=uint8_t(exponent+127);
 for(unsigned j=0;j<32;++j){float v=fminf(fmaxf(bf(x[b*32+j])/s,-448.f),448.f);unsigned c=fp8_code(v);if(code)code[b*32+j]=uint8_t(c);float d=fp8_value(c&127);if(c&128)d=-d;y[b*32+j]=d*s;}
}
__global__ void router_kernel(const float*logits,const float*bias,const float*bias_vl,const uint8_t*mask,float*scores,float*corrected,uint32_t*ids,float*weights,unsigned batch){
 unsigned row=blockIdx.x*blockDim.x+threadIdx.x;if(row>=batch)return;
 for(unsigned e=0;e<384;++e){float z=logits[row*384+e];float sp=z>20.f?z:float(log1p(exp(double(z))));float score=sqrtf(sp);scores[row*384+e]=score;corrected[row*384+e]=score+(mask[row]?bias_vl[e]:bias[e]);}
 for(unsigned slot=0;slot<6;++slot){unsigned best=384;float value=-INFINITY;
  for(unsigned e=0;e<384;++e){bool used=false;for(unsigned i=0;i<slot;++i)if(ids[row*6+i]==e)used=true;if(!used && (best==384 || corrected[row*384+e]>value)){best=e;value=corrected[row*384+e];}}
  ids[row*6+slot]=best;
 }
 float denominator=0.f;for(unsigned i=0;i<6;++i)denominator=denominator+scores[row*384+ids[row*6+i]];denominator=denominator+1.e-20f;
 for(unsigned i=0;i<6;++i)weights[row*6+i]=(scores[row*384+ids[row*6+i]]/denominator)*1.5f;
}
__global__ void router_biased_kernel(const float*logits,const float*bias,const float*bias_vl,const uint8_t*mask,const float*delta,float*scores,float*corrected,uint32_t*ids,float*weights,unsigned batch){
 unsigned row=blockIdx.x*blockDim.x+threadIdx.x;if(row>=batch)return;
 for(unsigned e=0;e<384;++e){float z=logits[row*384+e];float sp=z>20.f?z:float(log1p(exp(double(z))));float score=sqrtf(sp);scores[row*384+e]=score;corrected[row*384+e]=score+(mask[row]?bias_vl[e]:bias[e]);}
 uint32_t original[6];for(unsigned slot=0;slot<6;++slot){unsigned best=384;float value=-INFINITY;for(unsigned e=0;e<384;++e){bool used=false;for(unsigned i=0;i<slot;++i)if(original[i]==e)used=true;if(!used&&(best==384||corrected[row*384+e]>value)){best=e;value=corrected[row*384+e];}}original[slot]=best;}
 for(unsigned slot=0;slot<6;++slot){unsigned best=384;float value=-INFINITY;
  for(unsigned e=0;e<384;++e){bool used=false;for(unsigned i=0;i<slot;++i)if(ids[row*6+i]==e)used=true;if(!used && (best==384 || (corrected[row*384+e]+delta[e])>value)){best=e;value=corrected[row*384+e]+delta[e];}}
  ids[row*6+slot]=best;
 }
 bool same_set=true;for(unsigned i=0;i<6;++i){bool found=false;for(unsigned j=0;j<6;++j)found|=ids[row*6+j]==original[i];same_set&=found;}if(same_set)for(unsigned i=0;i<6;++i)ids[row*6+i]=original[i];
 float denominator=0.f;for(unsigned i=0;i<6;++i)denominator=denominator+scores[row*384+ids[row*6+i]];denominator=denominator+1.e-20f;
 for(unsigned i=0;i<6;++i)weights[row*6+i]=(scores[row*384+ids[row*6+i]]/denominator)*1.5f;
}
__global__ void swiglu_kernel(const float*gate,const float*up,const float*weights,float*g,float*u,float*silu,float*out,size_t n,unsigned width){
 size_t i=blockIdx.x*blockDim.x+threadIdx.x;if(i>=n)return;float a=fminf(gate[i],10.f),b=fminf(fmaxf(up[i],-10.f),10.f);
 float c=float(double(a)/(1.+exp(-double(a))));float hidden=c*b;if(weights)hidden=hidden*weights[i/width];if(g)g[i]=a;if(u)u[i]=b;if(silu)silu[i]=c;out[i]=bf(hidden);
}
__global__ void add_kernel(const float*a,const float*b,float*c,size_t n){size_t i=blockIdx.x*blockDim.x+threadIdx.x;if(i<n)c[i]=a[i]+b[i];}
void launch_done(){check(hipGetLastError());check(hipDeviceSynchronize());}
std::vector<float> copy_float(Buffer& b,size_t count){std::vector<float> x(count);check(hipMemcpy(x.data(),b.p,count*4,hipMemcpyDeviceToHost));return x;}
std::vector<float> bf_gpu(const std::vector<float>& x){Buffer in(x.size()*4),out(x.size()*4);check(hipMemcpy(in.p,x.data(),x.size()*4,hipMemcpyHostToDevice));bf_kernel<<<(x.size()+255)/256,256>>>((float*)in.p,(float*)out.p,x.size());launch_done();return copy_float(out,x.size());}
std::vector<float> add_gpu(const std::vector<float>& a,const std::vector<float>& b){if(a.size()!=b.size())throw std::runtime_error("combine shape");Buffer x(a.size()*4),y(a.size()*4),z(a.size()*4);check(hipMemcpy(x.p,a.data(),a.size()*4,hipMemcpyHostToDevice));check(hipMemcpy(y.p,b.data(),b.size()*4,hipMemcpyHostToDevice));add_kernel<<<(a.size()+255)/256,256>>>((float*)x.p,(float*)y.p,(float*)z.p,a.size());launch_done();return copy_float(z,a.size());}
template<class T> void put(FfnTrace& trace,const std::string& name,const std::vector<T>& values,uint64_t rows,uint64_t columns,const std::string& dtype){
 if(rows*columns!=values.size() || trace.stages.count(name))throw std::runtime_error("trace shape/duplicate");Stage stage;stage.rows=rows;stage.columns=columns;stage.dtype=dtype;stage.bytes.resize(values.size()*sizeof(T));std::memcpy(stage.bytes.data(),values.data(),stage.bytes.size());trace.stages.emplace(name,std::move(stage));
}
void floats(FfnTrace& t,const std::string& n,const std::vector<float>& v,unsigned rows,unsigned columns){put(t,n,v,rows,columns,"<f4");}
std::vector<float> qdq_gpu(const std::vector<float>& x,unsigned rows,unsigned columns,FfnTrace& trace,const std::string& name){
 if(x.size()!=size_t(rows)*columns || !rows || !columns || columns%32)throw std::runtime_error("QDQ geometry");
 Buffer in(x.size()*4),out(x.size()*4),s(x.size()/32),c(x.size());check(hipMemcpy(in.p,x.data(),x.size()*4,hipMemcpyHostToDevice));
 qdq_kernel<<<(x.size()/32+255)/256,256>>>((float*)in.p,(float*)out.p,(uint8_t*)s.p,(uint8_t*)c.p,x.size()/32);launch_done();
 std::vector<uint8_t> scales(x.size()/32),codes(x.size());check(hipMemcpy(scales.data(),s.p,scales.size(),hipMemcpyDeviceToHost));check(hipMemcpy(codes.data(),c.p,codes.size(),hipMemcpyDeviceToHost));auto y=copy_float(out,x.size());put(trace,name+"_codes",codes,rows,columns,"|u1");put(trace,name+"_scales",scales,rows,columns/32,"|u1");floats(trace,name+"_qdq",y,rows,columns);return y;
}
std::vector<float> gather(const std::vector<float>& x,const std::vector<uint32_t>& tokens,unsigned width){std::vector<float> out;out.reserve(tokens.size()*width);for(auto t:tokens)out.insert(out.end(),x.begin()+t*width,x.begin()+(t+1)*width);return out;}
void scatter(std::vector<float>& out,const std::vector<float>& x,const std::vector<uint32_t>& tokens,unsigned width){if(x.size()!=tokens.size()*width)throw std::runtime_error("scatter shape");for(size_t i=0;i<tokens.size();++i)std::copy_n(x.begin()+i*width,width,out.begin()+tokens[i]*width);}
void validate_matrix(const Matrix& m){
 if(!m.rows || !m.k || m.type!=m.original.span.type_id || m.packed.size()!=quant::packed_bytes(m.type,size_t(m.rows)*m.k))throw std::runtime_error("matrix raw geometry");
 const auto& t=m.original.span;
 if(t.absolute_offset>UINT64_MAX-t.bytes)throw std::runtime_error("source span overflow");
 if(m.source_absolute_offset<t.absolute_offset || m.source_absolute_offset>t.absolute_offset+t.bytes || m.packed.size()>t.absolute_offset+t.bytes-m.source_absolute_offset)throw std::runtime_error("matrix source span");
}
std::vector<float> projection(const MatrixProvider& provider,const std::string& role,uint32_t expert,const std::vector<float>& x,unsigned batch,FfnTrace& trace,const measurement::Identity& identity,const std::string& device){
 auto m=provider(role,expert);validate_matrix(m);if(x.size()!=size_t(batch)*m.k)throw std::runtime_error("matrix input");
 std::vector<float> result;result.reserve(size_t(batch)*m.rows);
 for(unsigned from=0;from<batch;){unsigned count=8;while(count>batch-from)count/=2;
  std::vector<float> input(x.begin()+size_t(from)*m.k,x.begin()+size_t(from+count)*m.k);
  auto output=quant::project(m.packed,m.type,m.rows,m.k,count,input);result.insert(result.end(),output.begin(),output.end());
  AtomicRequest request{role,expert,m.type,m.rows,m.k,count,m.original,m.source_absolute_offset,m.packed.size(),input.size()*4,output.size()*4,0};request.owned_device=request.packed+request.input+request.output;
  measurement::LedgerSnapshot ledger;ledger.identity=identity;ledger.owned_host=request.owned_device;ledger.devices.push_back({device,request.owned_device});(void)measurement::owned_total(ledger);
  trace.stats.matrix_owned_peak=std::max(trace.stats.matrix_owned_peak,request.owned_device);trace.stats.host_matrix_scope_peak=std::max(trace.stats.host_matrix_scope_peak,ledger.owned_host);trace.stats.requests.push_back(request);from+=count;
 }
 return result;
}
std::vector<float> linear(const MatrixProvider& provider,const std::string& role,uint32_t expert,const std::vector<float>& x,unsigned batch,unsigned k,unsigned rows,FfnTrace& trace,const std::string& name,const measurement::Identity& identity,const std::string& device){
 auto input=qdq_gpu(x,batch,k,trace,name);auto out=projection(provider,role,expert,input,batch,trace,identity,device);if(out.size()!=size_t(batch)*rows)throw std::runtime_error("matrix role dimensions");floats(trace,name+"_dot",out,batch,rows);out=bf_gpu(out);floats(trace,name+"_out",out,batch,rows);return out;
}
std::vector<float> swiglu_gpu(const std::vector<float>& gate,const std::vector<float>& up,const std::vector<float>& weights,unsigned batch,FfnTrace& trace,const std::string& name){
 size_t n=size_t(batch)*2304;if(gate.size()!=n || up.size()!=n || (!weights.empty() && weights.size()!=batch))throw std::runtime_error("SwiGLU shape");
 Buffer a(n*4),b(n*4),w(weights.empty()?4:weights.size()*4),g(n*4),u(n*4),s(n*4),out(n*4);check(hipMemcpy(a.p,gate.data(),n*4,hipMemcpyHostToDevice));check(hipMemcpy(b.p,up.data(),n*4,hipMemcpyHostToDevice));if(!weights.empty())check(hipMemcpy(w.p,weights.data(),weights.size()*4,hipMemcpyHostToDevice));
 swiglu_kernel<<<(n+255)/256,256>>>((float*)a.p,(float*)b.p,weights.empty()?nullptr:(float*)w.p,(float*)g.p,(float*)u.p,(float*)s.p,(float*)out.p,n,2304);launch_done();floats(trace,name+"_clamp_gate",copy_float(g,n),batch,2304);floats(trace,name+"_clamp_up",copy_float(u,n),batch,2304);floats(trace,name+"_silu",copy_float(s,n),batch,2304);auto hidden=copy_float(out,n);floats(trace,name+"_hidden",hidden,batch,2304);return hidden;
}
}
namespace {
void dv(const DeviceView&v,int device,DeviceScalar scalar,uint64_t rows,uint64_t columns){validate_device_view(v,device);if(v.scalar!=scalar||v.rows!=rows||v.columns!=columns)throw std::runtime_error("FFN device geometry/scalar");}
void fdv(const DeviceView&v,int device,uint64_t rows,uint64_t columns){validate_device_view(v,device);if((v.scalar!=DeviceScalar::Float32&&v.scalar!=DeviceScalar::Bfloat16InFloat32)||v.rows!=rows||v.columns!=columns)throw std::runtime_error("FFN floating device geometry");}
hipStream_t ds(void*s,int device){check_device_stream(s,device);return reinterpret_cast<hipStream_t>(s);}
}
void ffn_bf16_device(const DeviceView&x,const DeviceView&out,void*stream){fdv(x,x.device,x.rows,x.columns);dv(out,x.device,DeviceScalar::Bfloat16InFloat32,x.rows,x.columns);auto n=x.rows*x.columns;bf_kernel<<<(n+255)/256,256,0,ds(stream,x.device)>>>((float*)x.data,(float*)out.data,n);check(hipGetLastError());}
void ffn_qdq_device(const DeviceView&x,const DeviceView&out,void*stream,DeviceView*scales,DeviceView*codes){fdv(x,x.device,x.rows,x.columns);dv(out,x.device,DeviceScalar::Float32,x.rows,x.columns);if(x.columns%32)throw std::runtime_error("act block32 row alignment");if(scales)dv(*scales,x.device,DeviceScalar::UInt8,x.rows,x.columns/32);if(codes)dv(*codes,x.device,DeviceScalar::UInt8,x.rows,x.columns);auto n=x.rows*x.columns;qdq_kernel<<<(n/32+255)/256,256,0,ds(stream,x.device)>>>((float*)x.data,(float*)out.data,scales?(uint8_t*)scales->data:nullptr,codes?(uint8_t*)codes->data:nullptr,n/32);check(hipGetLastError());}
void ffn_router_device(const DeviceView&z,const DeviceView&bias,const DeviceView&bias_vl,const DeviceView&mask,const DeviceView&scores,const DeviceView&corrected,const DeviceView&ids,const DeviceView&weights,void*stream){auto b=z.rows;dv(z,z.device,DeviceScalar::Float32,b,384);dv(bias,z.device,DeviceScalar::Float32,1,384);dv(bias_vl,z.device,DeviceScalar::Float32,1,384);dv(mask,z.device,DeviceScalar::UInt8,b,1);dv(scores,z.device,DeviceScalar::Float32,b,384);dv(corrected,z.device,DeviceScalar::Float32,b,384);dv(ids,z.device,DeviceScalar::UInt32,b,6);dv(weights,z.device,DeviceScalar::Float32,b,6);if(b>UINT32_MAX)throw std::runtime_error("router launch wave geometry");router_kernel<<<(b+63)/64,64,0,ds(stream,z.device)>>>((float*)z.data,(float*)bias.data,(float*)bias_vl.data,(uint8_t*)mask.data,(float*)scores.data,(float*)corrected.data,(uint32_t*)ids.data,(float*)weights.data,unsigned(b));check(hipGetLastError());}
void ffn_router_biased_device(const DeviceView&z,const DeviceView&bias,const DeviceView&bias_vl,const DeviceView&mask,const DeviceView&delta,const DeviceView&scores,const DeviceView&corrected,const DeviceView&ids,const DeviceView&weights,void*stream){auto b=z.rows;dv(delta,z.device,DeviceScalar::Float32,1,384);dv(z,z.device,DeviceScalar::Float32,b,384);dv(bias,z.device,DeviceScalar::Float32,1,384);dv(bias_vl,z.device,DeviceScalar::Float32,1,384);dv(mask,z.device,DeviceScalar::UInt8,b,1);dv(scores,z.device,DeviceScalar::Float32,b,384);dv(corrected,z.device,DeviceScalar::Float32,b,384);dv(ids,z.device,DeviceScalar::UInt32,b,6);dv(weights,z.device,DeviceScalar::Float32,b,6);if(b>UINT32_MAX)throw std::runtime_error("router launch wave geometry");router_biased_kernel<<<(b+63)/64,64,0,ds(stream,z.device)>>>((float*)z.data,(float*)bias.data,(float*)bias_vl.data,(uint8_t*)mask.data,(float*)delta.data,(float*)scores.data,(float*)corrected.data,(uint32_t*)ids.data,(float*)weights.data,unsigned(b));check(hipGetLastError());}
void ffn_swiglu_device(const DeviceView&gate,const DeviceView&up,const DeviceView*route,const DeviceView&out,void*stream,SwiGluAuditViews*a){auto b=gate.rows;fdv(gate,gate.device,b,2304);fdv(up,gate.device,b,2304);dv(out,gate.device,DeviceScalar::Bfloat16InFloat32,b,2304);if(route)dv(*route,gate.device,DeviceScalar::Float32,b,1);if(a){dv(a->clamp_gate,gate.device,DeviceScalar::Float32,b,2304);dv(a->clamp_up,gate.device,DeviceScalar::Float32,b,2304);dv(a->silu,gate.device,DeviceScalar::Float32,b,2304);}auto n=b*2304;swiglu_kernel<<<(n+255)/256,256,0,ds(stream,gate.device)>>>((float*)gate.data,(float*)up.data,route?(float*)route->data:nullptr,a?(float*)a->clamp_gate.data:nullptr,a?(float*)a->clamp_up.data:nullptr,a?(float*)a->silu.data:nullptr,(float*)out.data,n,2304);check(hipGetLastError());}
void ffn_add_device(const DeviceView&a,const DeviceView&b,const DeviceView&out,void*stream){fdv(a,a.device,a.rows,a.columns);fdv(b,a.device,a.rows,a.columns);dv(out,a.device,DeviceScalar::Float32,a.rows,a.columns);auto n=a.rows*a.columns;add_kernel<<<(n+255)/256,256,0,ds(stream,a.device)>>>((float*)a.data,(float*)b.data,(float*)out.data,n);check(hipGetLastError());}
FfnTrace run_ffn(const std::vector<float>& input,unsigned batch,const std::vector<uint8_t>& masks,const MatrixProvider& provider,const measurement::Identity& identity,const std::string& device){
 if(!batch || input.size()!=size_t(batch)*5120 || masks.size()!=batch || std::any_of(masks.begin(),masks.end(),[](auto x){return x>1;}) || std::any_of(input.begin(),input.end(),[](float x){return !std::isfinite(x);}))throw std::runtime_error("FFN shape/nonfinite/mask");
 if(scratch.live)throw std::runtime_error("previous scratch cleanup incomplete");scratch=ScratchStats{};FfnTrace trace;auto x=bf_gpu(input);floats(trace,"input",x,batch,5120);
 auto logits=projection(provider,"router",0,x,batch,trace,identity,device);if(logits.size()!=size_t(batch)*384)throw std::runtime_error("router shape");floats(trace,"logits",logits,batch,384);
 std::vector<uint32_t> ids(size_t(batch)*6);std::vector<float> weights(size_t(batch)*6);
 {
  auto b=provider("bias",0),v=provider("bias_vl",0);if(b.type!=0 || v.type!=0 || b.packed.size()!=384*4 || v.packed.size()!=384*4)throw std::runtime_error("router bias shape");
  for(const auto* bias:{&b,&v}){for(size_t i=0;i<384;++i){float value;std::memcpy(&value,bias->packed.data()+i*4,4);if(!std::isfinite(value))throw std::runtime_error("nonfinite router bias");}}
  Buffer z(logits.size()*4),db(b.packed.size()),dv(v.packed.size()),mask(masks.size()),scores(logits.size()*4),corrected(logits.size()*4),di(ids.size()*4),dw(weights.size()*4);
  check(hipMemcpy(z.p,logits.data(),logits.size()*4,hipMemcpyHostToDevice));check(hipMemcpy(db.p,b.packed.data(),b.packed.size(),hipMemcpyHostToDevice));check(hipMemcpy(dv.p,v.packed.data(),v.packed.size(),hipMemcpyHostToDevice));check(hipMemcpy(mask.p,masks.data(),masks.size(),hipMemcpyHostToDevice));
  router_kernel<<<(batch+63)/64,64>>>((float*)z.p,(float*)db.p,(float*)dv.p,(uint8_t*)mask.p,(float*)scores.p,(float*)corrected.p,(uint32_t*)di.p,(float*)dw.p,batch);launch_done();check(hipMemcpy(ids.data(),di.p,ids.size()*4,hipMemcpyDeviceToHost));check(hipMemcpy(weights.data(),dw.p,weights.size()*4,hipMemcpyDeviceToHost));floats(trace,"scores",copy_float(scores,logits.size()),batch,384);floats(trace,"corrected",copy_float(corrected,logits.size()),batch,384);put(trace,"ids",ids,batch,6,"<u4");floats(trace,"weights",weights,batch,6);
 }
 std::set<unsigned> experts(ids.begin(),ids.end());std::vector<float> accumulated(size_t(batch)*5120,0.f);
 for(unsigned expert:experts){if(expert>=384)throw std::runtime_error("router index out of bounds");std::vector<uint32_t> tokens;std::vector<float> routes;
  for(unsigned token=0;token<batch;++token)for(unsigned slot=0;slot<6;++slot)if(ids[token*6+slot]==expert){tokens.push_back(token);routes.push_back(weights[token*6+slot]);}
  auto name="e"+std::to_string(expert);put(trace,name+"_tokens",tokens,tokens.size(),1,"<u4");auto selected=gather(x,tokens,5120);unsigned count=static_cast<unsigned>(tokens.size());
  auto gate=linear(provider,"gate",expert,selected,count,5120,2304,trace,name+"_gate",identity,device);auto up=linear(provider,"up",expert,selected,count,5120,2304,trace,name+"_up",identity,device);
  auto hidden=swiglu_gpu(gate,up,routes,count,trace,name);auto down=linear(provider,"down",expert,hidden,count,2304,5120,trace,name+"_down",identity,device);auto current=gather(accumulated,tokens,5120);current=add_gpu(current,down);scatter(accumulated,current,tokens,5120);floats(trace,name+"_combine",current,count,5120);
 }
 auto gate=linear(provider,"shared_gate",0,x,batch,5120,2304,trace,"shared_gate",identity,device);auto up=linear(provider,"shared_up",0,x,batch,5120,2304,trace,"shared_up",identity,device);auto hidden=swiglu_gpu(gate,up,{},batch,trace,"shared");auto shared=linear(provider,"shared_down",0,hidden,batch,2304,5120,trace,"shared_down",identity,device);floats(trace,"routed",accumulated,batch,5120);auto combined=add_gpu(accumulated,shared);floats(trace,"combine",combined,batch,5120);floats(trace,"output",bf_gpu(combined),batch,5120);
 trace.stats.actual_scratch_peak=scratch.peak;trace.stats.cleanup_unknown=scratch.failed || scratch.live;for(const auto& [key,stage]:trace.stages){(void)key;trace.stats.trace_payload_bytes+=stage.bytes.size();}if(trace.stats.cleanup_unknown)throw std::runtime_error("scratch cleanup unknown");return trace;
}
FfnTrace run_boundaries(const std::vector<float>& casts,const std::vector<float>& qdq,
 const std::vector<float>& logits,const std::vector<float>& bias,const std::vector<float>& bias_vl,
 const std::vector<uint8_t>& masks,const std::vector<float>& gate,const std::vector<float>& up,const std::vector<float>& routes){
 if(casts.empty() || qdq.empty() || qdq.size()%32 || masks.empty() || logits.size()!=masks.size()*384 || bias.size()!=384 || bias_vl.size()!=384 || gate.size()!=2304 || up.size()!=2304 || routes.size()!=1)throw std::runtime_error("boundary geometry");
 if(scratch.live)throw std::runtime_error("boundary previous scratch");scratch=ScratchStats{};FfnTrace trace;
 floats(trace,"cast",bf_gpu(casts),1,casts.size());qdq_gpu(qdq,qdq.size()/32,32,trace,"act");
 {
  auto batch=masks.size();Buffer z(logits.size()*4),b(bias.size()*4),v(bias_vl.size()*4),mask(masks.size()),scores(logits.size()*4),corrected(logits.size()*4),di(batch*6*4),dw(batch*6*4);
  check(hipMemcpy(z.p,logits.data(),logits.size()*4,hipMemcpyHostToDevice));check(hipMemcpy(b.p,bias.data(),bias.size()*4,hipMemcpyHostToDevice));check(hipMemcpy(v.p,bias_vl.data(),bias_vl.size()*4,hipMemcpyHostToDevice));check(hipMemcpy(mask.p,masks.data(),masks.size(),hipMemcpyHostToDevice));
  router_kernel<<<(batch+63)/64,64>>>((float*)z.p,(float*)b.p,(float*)v.p,(uint8_t*)mask.p,(float*)scores.p,(float*)corrected.p,(uint32_t*)di.p,(float*)dw.p,batch);launch_done();std::vector<uint32_t> ids(batch*6);check(hipMemcpy(ids.data(),di.p,ids.size()*4,hipMemcpyDeviceToHost));
  floats(trace,"scores",copy_float(scores,logits.size()),batch,384);floats(trace,"corrected",copy_float(corrected,logits.size()),batch,384);put(trace,"ids",ids,batch,6,"<u4");floats(trace,"weights",copy_float(dw,batch*6),batch,6);
 }
 swiglu_gpu(gate,up,routes,1,trace,"boundary");trace.stats.actual_scratch_peak=scratch.peak;trace.stats.cleanup_unknown=scratch.failed||scratch.live;if(trace.stats.cleanup_unknown)throw std::runtime_error("boundary cleanup");return trace;
}

}
