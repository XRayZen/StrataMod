#include "quant.hpp"
#include <hip/hip_runtime.h>
#include <cmath>
#include <stdexcept>
#include <limits>
#include <string>
namespace strata_ext::quant {
namespace {
void check(hipError_t e) { if(e!=hipSuccess) throw std::runtime_error(hipGetErrorString(e)); }
struct Device {
    void* data=nullptr;
    explicit Device(size_t n) { check(hipMalloc(&data,n)); }
    ~Device() { if(data) hipFree(data); }
    void release() { check(hipFree(data)); data=nullptr; }
};
__device__ float half_value(unsigned h) {
    unsigned e=(h>>10)&31,m=h&1023;
    float v=e==0 ? ldexpf(float(m),-24) : e==31 ? (m?NAN:INFINITY) : ldexpf(float(1024+m),int(e)-25);
    return h&32768 ? -v:v;
}
__device__ float value(const uint8_t* raw,unsigned type,size_t i) {
    if(type==0) return reinterpret_cast<const float*>(raw)[i];
    const size_t block=i/32,lane=i%32;
    if(type==8) {
        const uint8_t* p=raw+block*34;
        return half_value(unsigned(p[0])|(unsigned(p[1])<<8))*float(static_cast<int8_t>(p[2+lane]));
    }
    if(type==39) {
        const uint8_t* p=raw+block*17;
        unsigned c=(p[1+lane%16]>>(lane<16?0:4))&15;
        const float table[8]={0,.5f,1,1.5f,2,3,4,6};
        if((c&7)==0) return 0.0f;
        float v=ldexpf(table[c&7],int(p[0])-127);
        return c&8 ? -v:v;
    }
    const uint8_t* p=raw+block*33;
    unsigned c=p[1+lane],e=(c>>3)&15,m=c&7;
    float v=e==15&&m==7 ? NAN : e==0 ? ldexpf(float(m),-9) : ldexpf(float(8+m),int(e)-10);
    if(c&128) v=-v;
    // Native source contract: materialize scale as FP32 before multiplication.
    float scale=ldexpf(1.0f,int(p[0])-127);
    return v*scale;
}
__global__ void decode_kernel(const uint8_t* raw,unsigned type,float* out,size_t count) {
    size_t i=blockIdx.x*blockDim.x+threadIdx.x;
    if(i<count) out[i]=value(raw,type,i);
}
// Projection-only block context. Keep value() as the independent scalar path.
struct ProjectionBlock {
    const uint8_t* raw;float scale;
    float p05,p1,p15,p2,p3,p4,p6;
};
__device__ ProjectionBlock projection_block(const uint8_t* raw,unsigned type) {
    ProjectionBlock b{};b.raw=raw;
    if(type==8) b.scale=half_value(unsigned(raw[0])|(unsigned(raw[1])<<8));
    else if(type==43) b.scale=ldexpf(1.0f,int(raw[0])-127);
    else {
        int e=int(raw[0])-127;
        b.p05=ldexpf(.5f,e);b.p1=ldexpf(1.0f,e);b.p15=ldexpf(1.5f,e);
        b.p2=ldexpf(2.0f,e);b.p3=ldexpf(3.0f,e);b.p4=ldexpf(4.0f,e);b.p6=ldexpf(6.0f,e);
    }
    return b;
}
__device__ float projection_block_value(const ProjectionBlock&b,unsigned type,unsigned lane) {
    if(type==8) return b.scale*float(static_cast<int8_t>(b.raw[2+lane]));
    if(type==39) {
        unsigned c=(b.raw[1+lane%16]>>(lane<16?0:4))&15;
        if((c&7)==0) return 0.0f;
        float v=(c&4)?((c&2)?((c&1)?b.p6:b.p4):((c&1)?b.p3:b.p2)):
                       ((c&2)?((c&1)?b.p15:b.p1):b.p05);
        return c&8 ? -v:v;
    }
    unsigned c=b.raw[1+lane],e=(c>>3)&15,m=c&7;
    float v=e==15&&m==7 ? NAN : e==0 ? ldexpf(float(m),-9) : ldexpf(float(8+m),int(e)-10);
    if(c&128) v=-v;
    return v*b.scale;
}
__global__ void projection_kernel(const uint8_t* raw,unsigned type,const float* x,float* out,size_t rows,size_t k,size_t batch,size_t output_stride) {
    size_t i=blockIdx.x*blockDim.x+threadIdx.x;
    if(i>=rows*batch) return;
    size_t b=i/rows,r=i%rows;
    float acc=0.0f;
    if(type==0) {
        for(size_t j=0;j<k;++j) {
            float product=value(raw,type,r*k+j)*x[b*k+j];
            acc=acc+product;
        }
    } else {
        size_t width=type==8?34:type==39?17:33;
        for(size_t first=0;first<k;first+=32) {
            auto block=projection_block(raw+((r*k+first)/32)*width,type);
            for(unsigned lane=0;lane<32;++lane) {
                float product=projection_block_value(block,type,lane)*x[b*k+first+lane];
                acc=acc+product;
            }
        }
    }
    out[b*output_stride+r]=acc;
}
__global__ void projection_g8_kernel(const uint8_t*raw,unsigned type,const float*x,float*out,
                             size_t rows,size_t k,size_t batch,size_t stride){
 constexpr unsigned G=8;
 // G divides both AMD wave32 and wave64. No lane exits before the gathers.
 const unsigned lane=threadIdx.x%G;
 const size_t i=size_t(blockIdx.x)*(256/G)+threadIdx.x/G;
 const bool valid=i<rows*batch;
 const size_t b=i/rows,r=i%rows,width=type==8?34:type==39?17:33;
 float acc=0.0f;
 for(size_t first=0;first<k;first+=32){
  ProjectionBlock block{};
  if(valid)block=projection_block(raw+((r*k+first)/32)*width,type);
  float products[32/G];
  for(unsigned qlane=0;qlane<32/G;++qlane){
   const unsigned j=qlane*G+lane;
   products[qlane]=0.0f;
   if(valid){float product=projection_block_value(block,type,j)*x[b*k+first+j];products[qlane]=product;}
  }
  for(unsigned qlane=0;qlane<32/G;++qlane){
   for(unsigned source=0;source<G;++source){
    // Shuffle already-rounded bits, not an integer numeric conversion. Every
    // physical lane calls it, including invalid whole row groups at the tail.
    const int bits=__shfl(__float_as_int(products[qlane]),source,G);
    if(lane==0){float product=__int_as_float(bits);acc=acc+product;}
   }
  }
 }
 if(valid&&lane==0)out[b*stride+r]=acc;
}
size_t plus(size_t a,size_t b) {
    if(b>std::numeric_limits<size_t>::max()-a)throw std::runtime_error("shape overflow");
    return a+b;
}
size_t multiply(size_t a,size_t b) {
    if(a && b>std::numeric_limits<size_t>::max()/a) throw std::runtime_error("shape overflow");
    return a*b;
}
}
size_t packed_bytes(uint32_t type,size_t count) {
    if(!count) throw std::runtime_error("empty shape");
    if(type==0) return multiply(count,4);
    if(count%32) throw std::runtime_error("partial block");
    size_t size=type==8?34:type==39?17:type==43?33:0;
    if(!size) throw std::runtime_error("unqualified type");
    return multiply(count/32,size);
}
void validate_projection_shape(uint32_t type,size_t rows,size_t k,size_t batch) {
    if(!rows || !k || !(batch==1||batch==2||batch==4||batch==8)) throw std::runtime_error("shape/batch");
    if(type!=0 && k%32) throw std::runtime_error("quant row K must align to block32");
    packed_bytes(type,multiply(rows,k));
    multiply(batch,k);multiply(rows,batch);
}
DeviceProjection checked_projection(PackedDeviceView v,const float* input,size_t input_bytes,
                                     float* output,size_t output_bytes,void* stream,const ProjectionLease& lease) {
    return checked_projection_strided(v,input,input_bytes,output,output_bytes,v.rows,stream,lease);
}
DeviceProjection checked_projection_strided(PackedDeviceView v,const float* input,size_t input_bytes,
                                     float* output,size_t output_bytes,size_t output_stride,void* stream,const ProjectionLease& lease) {
    validate_projection_shape(v.type,v.rows,v.k,1);
    if(output_stride<v.rows)throw std::runtime_error("output row stride smaller than tile");
    if(v.bytes!=packed_bytes(v.type,multiply(v.rows,v.k)) || !input || !output ||
       input_bytes<multiply(v.k,4) || output_bytes<multiply(v.rows,4) || !lease.active || !lease.generation)
        throw std::runtime_error("borrowed projection declaration");
    int current=-1;check(hipGetDevice(&current));
    if(current!=v.device)throw std::runtime_error("borrowed current device mismatch");
    const void* pointers[]={v.data,input,output};const size_t capacities[]={v.bytes,input_bytes,output_bytes};
    for(unsigned i=0;i<3;++i) {
        const void* pointer=pointers[i];hipPointerAttribute_t attributes{};check(hipPointerGetAttributes(&attributes,pointer));
        if(attributes.type!=hipMemoryTypeDevice || attributes.device!=v.device)
            throw std::runtime_error("borrowed pointer device mismatch");
        hipDeviceptr_t base=nullptr;size_t allocated=0;check(hipMemGetAddressRange(&base,&allocated,reinterpret_cast<hipDeviceptr_t>(const_cast<void*>(pointer))));
        auto delta=reinterpret_cast<uintptr_t>(pointer)-reinterpret_cast<uintptr_t>(base);
        if(delta>allocated||capacities[i]>allocated-delta)throw std::runtime_error("borrowed pointer allocation range");
    }
    // Default stream is explicitly the current device's stream. This preserves
    // the synchronous host wrapper's former default-stream semantics.
    int stream_device=current;
    if(stream)check(hipStreamGetDevice(reinterpret_cast<hipStream_t>(stream),&stream_device));
    if(stream_device!=v.device)throw std::runtime_error("borrowed stream device mismatch");
    DeviceProjection b;b.packed_=v;b.input_=input;b.output_=output;b.input_bytes_=input_bytes;
    b.output_bytes_=output_bytes;b.output_stride_=output_stride;b.stream_=stream;b.lease_=&lease;b.generation_=lease.generation;b.device_=v.device;return b;
}
void project_into(const DeviceProjection& b,size_t batch) {
    if(!b.lease_ || !b.lease_->active || b.lease_->generation!=b.generation_)throw std::runtime_error("inactive borrowed projection lease");
    validate_projection_shape(b.packed_.type,b.packed_.rows,b.packed_.k,batch);
    if(multiply(multiply(batch,b.packed_.k),4)>b.input_bytes_ || multiply(plus(multiply(batch-1,b.output_stride_),b.packed_.rows),4)>b.output_bytes_)
        throw std::runtime_error("borrowed projection I/O capacity");
    // Actual written row tiles may be adjacent to other live views, but may
    // not overwrite any packed weight or input consumed by this launch.
    auto overlap=[](uintptr_t a,size_t n,uintptr_t c,size_t m){return a<c?c-a<n:a-c<m;};
    for(size_t i=0;i<batch;++i){auto offset=multiply(multiply(i,b.output_stride_),4);auto target=plus(reinterpret_cast<uintptr_t>(b.output_),offset);auto n=multiply(b.packed_.rows,4);
      if(overlap(target,n,reinterpret_cast<uintptr_t>(b.packed_.data),b.packed_.bytes)||overlap(target,n,reinterpret_cast<uintptr_t>(b.input_),multiply(multiply(batch,b.packed_.k),4)))throw std::runtime_error("projection output overlaps live source/input");}
    int current=-1;check(hipGetDevice(&current));if(current!=b.device_)throw std::runtime_error("launch current device mismatch");
    size_t count=multiply(batch,b.packed_.rows);
    // Division/remainder avoids count+31 overflow. Bound this G8 dispatch to
    // INT_MAX blocks; retain the original launch for unsupported geometry.
    const size_t g8_grid=count/32+(count%32!=0);
    if(b.packed_.type!=0 && g8_grid<=size_t(std::numeric_limits<int>::max())) {
        projection_g8_kernel<<<g8_grid,256,0,reinterpret_cast<hipStream_t>(b.stream_)>>>(b.packed_.data,b.packed_.type,b.input_,b.output_,b.packed_.rows,b.packed_.k,batch,b.output_stride_);
    } else {
    projection_kernel<<<(count+255)/256,256,0,reinterpret_cast<hipStream_t>(b.stream_)>>>(b.packed_.data,b.packed_.type,b.input_,b.output_,b.packed_.rows,b.packed_.k,batch,b.output_stride_);
    }
    check(hipGetLastError());
}
void decode_into(PackedDeviceView v,float* out,size_t out_bytes,void* stream,const ProjectionLease& lease) {
    const size_t n=multiply(v.rows,v.k);
    if(!lease.active||!lease.generation||v.bytes!=packed_bytes(v.type,n)||!out||out_bytes<multiply(n,4))throw std::runtime_error("device decode declaration");
    int current=-1;check(hipGetDevice(&current));if(current!=v.device)throw std::runtime_error("decode current device mismatch");
    const void* ptrs[]={v.data,out};size_t lengths[]={v.bytes,out_bytes};
    for(unsigned i=0;i<2;++i){hipPointerAttribute_t attr{};check(hipPointerGetAttributes(&attr,ptrs[i]));if(attr.type!=hipMemoryTypeDevice||attr.device!=v.device)throw std::runtime_error("decode pointer device mismatch");hipDeviceptr_t base=nullptr;size_t bytes=0;check(hipMemGetAddressRange(&base,&bytes,reinterpret_cast<hipDeviceptr_t>(const_cast<void*>(ptrs[i]))));size_t delta=reinterpret_cast<uintptr_t>(ptrs[i])-reinterpret_cast<uintptr_t>(base);if(delta>bytes||lengths[i]>bytes-delta)throw std::runtime_error("decode pointer range");}
    int sd=current;if(stream)check(hipStreamGetDevice(reinterpret_cast<hipStream_t>(stream),&sd));if(sd!=current)throw std::runtime_error("decode stream device mismatch");
    decode_kernel<<<(n+255)/256,256,0,reinterpret_cast<hipStream_t>(stream)>>>(v.data,v.type,out,n);check(hipGetLastError());
}
std::vector<float> decode(const std::vector<uint8_t>& raw,uint32_t type,size_t count) {
    if(raw.size()!=packed_bytes(type,count)) throw std::runtime_error("raw count mismatch");
    Device source(raw.size()),target(multiply(count,4));
    check(hipMemcpy(source.data,raw.data(),raw.size(),hipMemcpyHostToDevice));
    decode_kernel<<<(count+255)/256,256>>>(static_cast<const uint8_t*>(source.data),type,static_cast<float*>(target.data),count);
    check(hipGetLastError());check(hipDeviceSynchronize());
    std::vector<float> output(count);
    check(hipMemcpy(output.data(),target.data,count*4,hipMemcpyDeviceToHost));
    target.release();source.release();return output;
}
std::vector<float> project(const std::vector<uint8_t>& raw,uint32_t type,size_t rows,size_t k,size_t batch,const std::vector<float>& inputs) {
    validate_projection_shape(type,rows,k,batch);
    const size_t count=multiply(rows,k),input_count=multiply(batch,k),output_count=multiply(rows,batch);
    if(raw.size()!=packed_bytes(type,count)||inputs.size()!=input_count) throw std::runtime_error("projection count mismatch");
    for(float x:inputs) if(!std::isfinite(x)) throw std::runtime_error("nonfinite activation");
    Device source(raw.size()),x(multiply(input_count,4)),y(multiply(output_count,4));
    check(hipMemcpy(source.data,raw.data(),raw.size(),hipMemcpyHostToDevice));
    check(hipMemcpy(x.data,inputs.data(),inputs.size()*4,hipMemcpyHostToDevice));
    int ordinal=-1;check(hipGetDevice(&ordinal));ProjectionLease lease;
    auto binding=checked_projection({static_cast<const uint8_t*>(source.data),type,rows,k,raw.size(),ordinal},
          static_cast<const float*>(x.data),input_count*4,static_cast<float*>(y.data),output_count*4,nullptr,lease);
    project_into(binding,batch);check(hipDeviceSynchronize());lease.active=false;
    std::vector<float> output(output_count);
    check(hipMemcpy(output.data(),y.data,output_count*4,hipMemcpyDeviceToHost));
    for(float v:output) if(!std::isfinite(v)) throw std::runtime_error("nonfinite result");
    y.release();x.release();source.release();return output;
}
}
