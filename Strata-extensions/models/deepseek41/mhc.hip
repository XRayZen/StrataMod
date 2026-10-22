#include "mhc.hpp"
#include "../../native/quant/quant.hpp"
#include "../../native/stats/measurement.hpp"
#include <hip/hip_runtime.h>
#include <cmath>
#include <cstring>
#include <algorithm>
namespace strata_ext::deepseek41 {
namespace {
void check(hipError_t e){if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));}
thread_local uint64_t live=0,peak=0;thread_local bool failed=false;
struct Buffer {void* p=nullptr;size_t bytes;explicit Buffer(size_t n):bytes(n){if(!n)throw std::runtime_error("empty MHC buffer");check(hipMalloc(&p,n));live+=n;peak=std::max(peak,live);}~Buffer(){if(p){auto e=hipFree(p);if(e==hipSuccess)live-=bytes;else failed=true;}}};
__device__ float bf(float x){auto u=__float_as_uint(x);return __uint_as_float(((u+0x7fff+((u>>16)&1))>>16)<<16);}
void done(){check(hipGetLastError());check(hipDeviceSynchronize());}
void upload(Buffer& b,const std::vector<float>& v){if(b.bytes!=v.size()*4)throw std::runtime_error("upload geometry");check(hipMemcpy(b.p,v.data(),b.bytes,hipMemcpyHostToDevice));}
std::vector<float> download(Buffer& b,size_t n){std::vector<float> v(n);check(hipMemcpy(v.data(),b.p,n*4,hipMemcpyDeviceToHost));return v;}
void put(MhcTrace& t,const std::string& name,const std::vector<float>& v,unsigned rows,unsigned columns){if(!rows||size_t(rows)*columns!=v.size()||t.stages.count(name))throw std::runtime_error("MHC trace geometry");t.stages.emplace(name,MhcStage{v,rows,columns});}
void finite(const std::vector<float>& v){if(std::any_of(v.begin(),v.end(),[](float x){return !std::isfinite(x);}))throw std::runtime_error("nonfinite MHC input");}
__global__ void rms_kernel(const float*x,float*out,unsigned batch,unsigned width){unsigned r=blockIdx.x*blockDim.x+threadIdx.x;if(r>=batch)return;float sum=0.f;for(unsigned i=0;i<width;++i){float v=x[size_t(r)*width+i];float square=v*v;sum=sum+square;}float mean=sum/float(width);out[r]=1.f/sqrtf(mean+1.e-20f);}
std::vector<float> rsqrt_gpu(const std::vector<float>& x,unsigned batch,unsigned width){Buffer in(x.size()*4),out(batch*4);upload(in,x);rms_kernel<<<(batch+63)/64,64>>>((float*)in.p,(float*)out.p,batch,width);done();return download(out,batch);}
__global__ void multiply_kernel(const float*x,const float*s,float*out,size_t n,unsigned width){size_t i=blockIdx.x*blockDim.x+threadIdx.x;if(i<n)out[i]=x[i]*s[i/width];}
std::vector<float> multiply_gpu(const std::vector<float>& x,const std::vector<float>& s,unsigned width){Buffer in(x.size()*4),sc(s.size()*4),out(x.size()*4);upload(in,x);upload(sc,s);multiply_kernel<<<(x.size()+255)/256,256>>>((float*)in.p,(float*)sc.p,(float*)out.p,x.size(),width);done();return download(out,x.size());}
__global__ void split_kernel(const float*x,const float*scale,const float*base,float*pre,float*post,float*logits,float*center,float*exponent,float*allrows,float*allcols,unsigned batch,float*finalcomb=nullptr){
 unsigned b=blockIdx.x*blockDim.x+threadIdx.x;if(b>=batch)return;float comb[16],row[16];
 for(unsigned j=0;j<4;++j){float z=x[b*24+j]*scale[0]+base[j];pre[b*4+j]=float(1./(1.+exp(-double(z))))+1.e-6f;z=x[b*24+4+j]*scale[1]+base[4+j];post[b*4+j]=2.f*float(1./(1.+exp(-double(z))));}
 for(unsigned i=0;i<4;++i){float maximum=-INFINITY;
  for(unsigned j=0;j<4;++j){unsigned k=i*4+j;comb[k]=x[b*24+8+k]*scale[2]+base[8+k];if(logits)logits[b*16+k]=comb[k];maximum=fmaxf(maximum,comb[k]);}
  float sum=0.f;for(unsigned j=0;j<4;++j){unsigned k=i*4+j;float z=comb[k]-maximum;if(center)center[b*16+k]=z;row[k]=float(exp(double(z)));if(exponent)exponent[b*16+k]=row[k];sum=sum+row[k];}
  for(unsigned j=0;j<4;++j){unsigned k=i*4+j;row[k]=row[k]/sum+1.e-6f;}
 }
 for(unsigned iteration=0;iteration<20;++iteration){
  if(iteration){for(unsigned i=0;i<4;++i){float sum=0.f;for(unsigned j=0;j<4;++j)sum=sum+comb[i*4+j];float den=sum+1.e-6f;for(unsigned j=0;j<4;++j)row[i*4+j]=comb[i*4+j]/den;}}
  for(unsigned j=0;j<4;++j){float sum=0.f;for(unsigned i=0;i<4;++i)sum=sum+row[i*4+j];float den=sum+1.e-6f;for(unsigned i=0;i<4;++i)comb[i*4+j]=row[i*4+j]/den;}
  for(unsigned k=0;k<16;++k){if(allrows)allrows[(size_t(iteration)*batch+b)*16+k]=row[k];if(allcols)allcols[(size_t(iteration)*batch+b)*16+k]=comb[k];if(finalcomb&&iteration==19)finalcomb[b*16+k]=comb[k];}
 }
}
struct Parts {std::vector<float> pre,post,comb;};
Parts split_gpu(const std::vector<float>& mixed,const std::vector<float>& scale,const std::vector<float>& base,unsigned batch,MhcTrace& t,const std::string& name){
 Buffer in(mixed.size()*4),s(12),b(96),pre(batch*16),post(batch*16),logits(batch*64),center(batch*64),exponent(batch*64),rows(20*batch*64),cols(20*batch*64);upload(in,mixed);upload(s,scale);upload(b,base);
 split_kernel<<<(batch+63)/64,64>>>((float*)in.p,(float*)s.p,(float*)b.p,(float*)pre.p,(float*)post.p,(float*)logits.p,(float*)center.p,(float*)exponent.p,(float*)rows.p,(float*)cols.p,batch);done();Parts p;p.pre=download(pre,batch*4);p.post=download(post,batch*4);auto r=download(rows,20*batch*16),c=download(cols,20*batch*16);p.comb.assign(c.end()-batch*16,c.end());
 put(t,name+"pre",p.pre,batch,4);put(t,name+"post",p.post,batch,4);put(t,name+"logits",download(logits,batch*16),batch,16);put(t,name+"centered",download(center,batch*16),batch,16);put(t,name+"exp",download(exponent,batch*16),batch,16);put(t,name+"comb",p.comb,batch,16);
 for(unsigned i=0;i<20;++i){put(t,name+"row"+std::to_string(i),std::vector<float>(r.begin()+i*batch*16,r.begin()+(i+1)*batch*16),batch,16);put(t,name+"col"+std::to_string(i),std::vector<float>(c.begin()+i*batch*16,c.begin()+(i+1)*batch*16),batch,16);}return p;
}
__global__ void pre_kernel(const float*x,const float*p,float*out,unsigned batch){size_t k=blockIdx.x*blockDim.x+threadIdx.x;if(k>=size_t(batch)*5120)return;unsigned b=k/5120,d=k%5120;float sum=0.f;for(unsigned h=0;h<4;++h){float value=p[b*4+h]*x[(size_t(b)*4+h)*5120+d];sum=sum+value;}out[k]=bf(sum);}
std::vector<float> pre_gpu(const std::vector<float>& x,const std::vector<float>& pre,unsigned batch){Buffer in(x.size()*4),p(pre.size()*4),out(batch*5120*4);upload(in,x);upload(p,pre);pre_kernel<<<(batch*5120+255)/256,256>>>((float*)in.p,(float*)p.p,(float*)out.p,batch);done();return download(out,batch*5120);}
__global__ void post_kernel(const float*x,const float*r,const float*p,const float*c,float*out,unsigned batch){size_t k=blockIdx.x*blockDim.x+threadIdx.x;if(k>=size_t(batch)*20480)return;unsigned b=k/20480,j=(k/5120)%4,d=k%5120;float sum=0.f;for(unsigned i=0;i<4;++i){float value=c[b*16+i*4+j]*r[(size_t(b)*4+i)*5120+d];sum=sum+value;}float product=p[b*4+j]*x[b*5120+d];out[k]=bf(product+sum);}
std::vector<float> post_gpu(const std::vector<float>& x,const std::vector<float>& residual,const Parts& parts,unsigned batch){Buffer in(x.size()*4),r(residual.size()*4),p(parts.post.size()*4),c(parts.comb.size()*4),out(residual.size()*4);upload(in,x);upload(r,residual);upload(p,parts.post);upload(c,parts.comb);post_kernel<<<(batch*20480+255)/256,256>>>((float*)in.p,(float*)r.p,(float*)p.p,(float*)c.p,(float*)out.p,batch);done();return download(out,residual.size());}
__global__ void norm_kernel(const float*x,const float*inv,const float*w,float*out,size_t n){size_t i=blockIdx.x*blockDim.x+threadIdx.x;if(i<n){float z=x[i]*inv[i/5120];out[i]=bf(z*w[i%5120]);}}
std::vector<float> norm_gpu(const std::vector<float>& x,const std::vector<float>& weight,unsigned batch){auto inv=rsqrt_gpu(x,batch,5120);Buffer in(x.size()*4),s(inv.size()*4),w(weight.size()*4),out(x.size()*4);upload(in,x);upload(s,inv);upload(w,weight);norm_kernel<<<(x.size()+255)/256,256>>>((float*)in.p,(float*)s.p,(float*)w.p,(float*)out.p,x.size());done();return download(out,x.size());}
void validate(const MhcWeights&w){if(w.fn.size()!=1966080||w.base.size()!=24||w.scale.size()!=3||w.norm.size()!=5120||w.original_fn.span.type_id!=0||w.original_fn.span.dims_ggml!=std::vector<uint64_t>{20480,24})throw std::runtime_error("MHC learned weights geometry");finite(w.base);finite(w.scale);finite(w.norm);}
Parts mixes(const std::vector<float>& x,const MhcWeights&w,unsigned batch,MhcTrace&t,const std::string&name,const measurement::Identity& identity,const std::string& device){auto inv=rsqrt_gpu(x,batch,20480);put(t,name+"_rsqrt",inv,batch,1);std::vector<float> projected;
 for(unsigned from=0;from<batch;){unsigned n=8;while(n>batch-from)n/=2;std::vector<float> input(x.begin()+size_t(from)*20480,x.begin()+size_t(from+n)*20480);auto y=quant::project(w.fn,0,24,20480,n,input);projected.insert(projected.end(),y.begin(),y.end());uint64_t owned=w.fn.size()+input.size()*4+y.size()*4;measurement::LedgerSnapshot ledger;ledger.identity=identity;ledger.owned_host=owned;ledger.devices.push_back({device,owned});t.requests.push_back({w.original_fn,n,w.fn.size(),input.size()*4,y.size()*4});(void)measurement::owned_total(ledger);t.primitive_peak=std::max(t.primitive_peak,owned);from+=n;}
 put(t,name+"_dot",projected,batch,24);auto mixed=multiply_gpu(projected,inv,24);put(t,name+"_mixes",mixed,batch,24);return split_gpu(mixed,w.scale,w.base,batch,t,name+"_");}
void begin(){if(live)throw std::runtime_error("MHC previous cleanup unknown");peak=0;failed=false;}
void finish(MhcTrace&t){t.scratch_peak=peak;t.cleanup_unknown=failed||live;if(t.cleanup_unknown)throw std::runtime_error("MHC cleanup unknown");}
}
namespace {
void mdv(const DeviceView&v,int d,uint64_t r,uint64_t c){validate_device_view(v,d);if(v.rows!=r||v.columns!=c||(v.scalar!=DeviceScalar::Float32&&v.scalar!=DeviceScalar::Bfloat16InFloat32))throw std::runtime_error("MHC device geometry/scalar");}
hipStream_t ms(void*s,int d){check_device_stream(s,d);return reinterpret_cast<hipStream_t>(s);}
}
void mhc_rms_device(const DeviceView&x,const DeviceView&out,void*stream){mdv(x,x.device,x.rows,x.columns);mdv(out,x.device,x.rows,1);if((x.columns!=20480&&x.columns!=5120)||x.rows>UINT32_MAX)throw std::runtime_error("MHC RMS width/launch wave");rms_kernel<<<(x.rows+63)/64,64,0,ms(stream,x.device)>>>((float*)x.data,(float*)out.data,unsigned(x.rows),unsigned(x.columns));check(hipGetLastError());}
void mhc_mix_device(const DeviceView&dot,const DeviceView&inverse,const DeviceView&out,void*stream){mdv(dot,dot.device,dot.rows,24);mdv(inverse,dot.device,dot.rows,1);mdv(out,dot.device,dot.rows,24);auto n=dot.rows*24;multiply_kernel<<<(n+255)/256,256,0,ms(stream,dot.device)>>>((float*)dot.data,(float*)inverse.data,(float*)out.data,n,24);check(hipGetLastError());}
void mhc_split_device(const DeviceView&mix,const DeviceView&scale,const DeviceView&base,const DeviceView&pre,const DeviceView&post,const DeviceView&comb,void*stream,MhcSplitAuditViews*a){auto b=mix.rows;mdv(mix,mix.device,b,24);mdv(scale,mix.device,1,3);mdv(base,mix.device,1,24);mdv(pre,mix.device,b,4);mdv(post,mix.device,b,4);mdv(comb,mix.device,b,16);if(b>UINT32_MAX)throw std::runtime_error("MHC split launch wave");if(a){mdv(a->logits,mix.device,b,16);mdv(a->centered,mix.device,b,16);mdv(a->exponent,mix.device,b,16);mdv(a->all_rows,mix.device,b*20,16);mdv(a->all_columns,mix.device,b*20,16);}split_kernel<<<(b+63)/64,64,0,ms(stream,mix.device)>>>((float*)mix.data,(float*)scale.data,(float*)base.data,(float*)pre.data,(float*)post.data,a?(float*)a->logits.data:nullptr,a?(float*)a->centered.data:nullptr,a?(float*)a->exponent.data:nullptr,a?(float*)a->all_rows.data:nullptr,a?(float*)a->all_columns.data:nullptr,unsigned(b),(float*)comb.data);check(hipGetLastError());}
void mhc_pre_device(const DeviceView&x,const DeviceView&pre,const DeviceView&out,void*stream){auto b=x.rows;mdv(x,x.device,b,20480);mdv(pre,x.device,b,4);mdv(out,x.device,b,5120);pre_kernel<<<(b*5120+255)/256,256,0,ms(stream,x.device)>>>((float*)x.data,(float*)pre.data,(float*)out.data,unsigned(b));check(hipGetLastError());}
void mhc_post_device(const DeviceView&x,const DeviceView&r,const DeviceView&post,const DeviceView&comb,const DeviceView&out,void*stream){auto b=x.rows;mdv(x,x.device,b,5120);mdv(r,x.device,b,20480);mdv(post,x.device,b,4);mdv(comb,x.device,b,16);mdv(out,x.device,b,20480);post_kernel<<<(b*20480+255)/256,256,0,ms(stream,x.device)>>>((float*)x.data,(float*)r.data,(float*)post.data,(float*)comb.data,(float*)out.data,unsigned(b));check(hipGetLastError());}
void mhc_norm_device(const DeviceView&x,const DeviceView&inverse,const DeviceView&w,const DeviceView&out,void*stream){mdv(x,x.device,x.rows,5120);mdv(inverse,x.device,x.rows,1);mdv(w,x.device,1,5120);mdv(out,x.device,x.rows,5120);auto n=x.rows*5120;norm_kernel<<<(n+255)/256,256,0,ms(stream,x.device)>>>((float*)x.data,(float*)inverse.data,(float*)w.data,(float*)out.data,n);check(hipGetLastError());}
MhcTrace run_staggered(const std::vector<float>& input,uint32_t batch,const MhcWeights&attn,const MhcWeights&ffn,const std::vector<std::vector<float>>& injected,const measurement::Identity& identity,const std::string& device){
 if(!batch||input.size()!=size_t(batch)*20480||injected.size()!=4)throw std::runtime_error("MHC residual geometry");finite(input);for(const auto&v:injected){if(v.size()!=size_t(batch)*5120)throw std::runtime_error("MHC injected geometry");finite(v);}validate(attn);validate(ffn);begin();MhcTrace t;auto x=input;std::vector<float> incoming(batch*4,0.f);for(unsigned b=0;b<batch;++b)incoming[b*4]=1;put(t,"input",x,batch,20480);put(t,"initial_pre",incoming,batch,4);
 for(unsigned layer=0;layer<2;++layer){auto prefix="block"+std::to_string(layer);auto residual=x;auto a=mixes(x,attn,batch,t,prefix+"_attn",identity,device);auto collapsed=pre_gpu(x,incoming,batch);put(t,prefix+"_attn_input",collapsed,batch,5120);put(t,prefix+"_attn_norm",norm_gpu(collapsed,attn.norm,batch),batch,5120);put(t,prefix+"_attn_injected",injected[layer*2],batch,5120);x=post_gpu(injected[layer*2],residual,a,batch);put(t,prefix+"_attn_output",x,batch,20480);
 residual=x;auto f=mixes(x,ffn,batch,t,prefix+"_ffn",identity,device);collapsed=pre_gpu(x,a.pre,batch);put(t,prefix+"_ffn_input",collapsed,batch,5120);put(t,prefix+"_ffn_norm",norm_gpu(collapsed,ffn.norm,batch),batch,5120);put(t,prefix+"_ffn_injected",injected[layer*2+1],batch,5120);x=post_gpu(injected[layer*2+1],residual,f,batch);put(t,prefix+"_ffn_output",x,batch,20480);incoming=f.pre;put(t,prefix+"_next_pre",incoming,batch,4);}
 put(t,"head",pre_gpu(x,incoming,batch),batch,5120);finish(t);return t;
}
MhcTrace run_controlled_mixes(const std::vector<float>& mixed,uint32_t batch){if(!batch||mixed.size()!=size_t(batch)*24)throw std::runtime_error("MHC controlled geometry");finite(mixed);begin();MhcTrace t;split_gpu(mixed,{1,1,1},std::vector<float>(24,0),batch,t,"");finish(t);return t;}
}
