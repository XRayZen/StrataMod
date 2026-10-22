#include "engram_forward.hpp"
#include <hip/hip_runtime.h>
#include <cmath>
#include <stdexcept>
namespace strata_ext::deepseek41 {
namespace {
void need(bool x,const char*s){if(!x)throw std::runtime_error(s);}
__device__ float rounded_bf(float x){unsigned u=__float_as_uint(x);return __uint_as_float((u+0x7fff+((u>>16)&1))&0xffff0000u);}
__global__ void gate_kernel(const float*h,const float*kv,const float*weight,const uint8_t*mask,float*gate,
 float*inv_h,float*inv_k,float*dot_out,float*sqrt_out,float*sum_h,float*sum_key,float*weighted_dot,uint64_t batch){
 uint64_t index=blockIdx.x*blockDim.x+threadIdx.x;if(index>=batch*4)return;uint64_t b=index/4,j=index%4;
 float hs=0.f,ks=0.f,dot=0.f;
 for(unsigned d=0;d<5120;++d){float x=h[(b*4+j)*5120+d],k=kv[b*25600+j*5120+d];float a=x*x,c=k*k;hs=hs+a;ks=ks+c;float w=x*weight[j*5120+d];float v=w*k;dot=dot+v;}
 float ih=1.f/sqrtf(hs/5120.f+1.e-20f),ik=1.f/sqrtf(ks/5120.f+1.e-20f);
 float z=dot*(ih*ik);z=z*float(0.013975424859373685); // Python dim**-0.5 -> FP32 scalar
 float signed_root=copysignf(sqrtf(fmaxf(fabsf(z),1.e-6f)),z);
 float g=float(1./(1.+exp(-double(signed_root))));gate[index]=mask[b]?g:0.f;
 if(sum_h)sum_h[index]=hs;if(sum_key)sum_key[index]=ks;if(weighted_dot)weighted_dot[index]=dot;
 if(inv_h)inv_h[index]=ih;if(inv_k)inv_k[index]=ik;if(dot_out)dot_out[index]=z;if(sqrt_out)sqrt_out[index]=signed_root;
}
__global__ void residual_kernel(const float*h,const float*kv,const float*g,float*out,uint64_t n){
 uint64_t i=blockIdx.x*blockDim.x+threadIdx.x;if(i>=n)return;uint64_t b=i/20480,j=(i/5120)%4,d=i%5120;
 float p=g[b*4+j]*kv[b*25600+20480+d];out[i]=rounded_bf(h[i]+p);
}
}
void engram_gate_device(const DeviceView&h,const DeviceView&kv,const DeviceView&w,const DeviceView&mask,const DeviceView&g,const DeviceView&out,void* stream,EngramAuditViews*a){
 auto device=h.device;for(const auto*v:{&h,&kv,&w,&mask,&g,&out})validate_device_view(*v,device);
 need(stream&&h.rows&&h.columns==20480&&kv.rows==h.rows&&kv.columns==25600&&w.rows==4&&w.columns==5120&&mask.rows==h.rows&&mask.columns==1&&g.rows==h.rows&&g.columns==4&&out.rows==h.rows&&out.columns==20480,"Engram original geometry");
 need(h.scalar==DeviceScalar::Bfloat16InFloat32&&kv.scalar==DeviceScalar::Bfloat16InFloat32&&w.scalar==DeviceScalar::Float32&&mask.scalar==DeviceScalar::UInt8&&g.scalar==DeviceScalar::Float32&&out.scalar==DeviceScalar::Bfloat16InFloat32,"Engram scalar/cast contract");
 float* traces[7]={};if(a){DeviceView* views[]={&a->inverse_h,&a->inverse_key,&a->dot,&a->signed_sqrt,&a->sum_h,&a->sum_key,&a->weighted_dot};for(unsigned i=0;i<7;++i){if(i>=4&&!views[i]->data)continue;validate_device_view(*views[i],device);need(views[i]->rows==h.rows&&views[i]->columns==4&&views[i]->scalar==DeviceScalar::Float32,"Engram trace geometry");traces[i]=(float*)views[i]->data;}}
 check_device_stream(stream,device);auto s=reinterpret_cast<hipStream_t>(stream);gate_kernel<<<(h.rows*4+63)/64,64,0,s>>>((const float*)h.data,(const float*)kv.data,(const float*)w.data,(const uint8_t*)mask.data,(float*)g.data,traces[0],traces[1],traces[2],traces[3],traces[4],traces[5],traces[6],h.rows);
 auto e=hipGetLastError();if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));
 residual_kernel<<<(h.rows*20480+255)/256,256,0,s>>>((const float*)h.data,(const float*)kv.data,(const float*)g.data,(float*)out.data,h.rows*20480);
 e=hipGetLastError();if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));
}
void engram_forward_device(const DeviceView&residual,const DeviceView&embedding,const SourceTensor&wkv,const DeviceView&gate,const DeviceView&mask,const DeviceView&output,EngramWorkspace&w,const CoreConfig&cfg,void*stream,const DeviceProject&project){
 validate_device_view(embedding,cfg.device);if(embedding.scalar!=DeviceScalar::Bfloat16InFloat32||embedding.rows!=residual.rows||embedding.columns!=6144||wkv.span.type_id!=8||wkv.span.dims_ggml!=std::vector<uint64_t>{6144,25600})throw std::runtime_error("Engram full forward source/embedding");
 ffn_qdq_device(embedding,w.activation_qdq,stream,w.qdq_scales,w.qdq_codes);
 tiled_projection(wkv,0,w.activation_qdq,w.kv_dot,embedding.rows,cfg,stream,project);
 ffn_bf16_device(w.kv_dot,w.kv_bf16,stream);
 engram_gate_device(residual,w.kv_bf16,gate,mask,w.gates,output,stream,w.gate_audit);
 audit_stage(cfg.audit,"engram_embedding",embedding,stream);audit_stage(cfg.audit,"engram_act_qdq",w.activation_qdq,stream);audit_stage(cfg.audit,"engram_kv_dot",w.kv_dot,stream);audit_stage(cfg.audit,"engram_kv_bf16",w.kv_bf16,stream);audit_stage(cfg.audit,"engram_gates",w.gates,stream);audit_stage(cfg.audit,"engram_residual",output,stream);
}

}
