#include "engram.hpp"
#include <hip/hip_runtime.h>
#include <cmath>
#include <limits>
#include <stdexcept>
namespace strata_ext::deepseek41::engram {
namespace {
__device__ float value(const uint8_t* row,uint32_t lane){
    const uint8_t* p=row+(lane/32)*33;uint32_t c=p[1+lane%32],e=(c>>3)&15,m=c&7;
    float v=e==15&&m==7?NAN:e==0?ldexpf(float(m),-9):ldexpf(float(8+m),int(e)-10);
    if(c&128)v=-v;
    float scale=ldexpf(1.f,int(p[0])-127);return v*scale;
}
__global__ void gather(const uint8_t* bank,uint64_t rows,const uint32_t* indices,uint64_t requests,float* output,uint16_t* bf,int* error){
    uint64_t i=uint64_t(blockIdx.x)*blockDim.x+threadIdx.x;if(i>=requests*256)return;
    uint64_t request=i/256;uint32_t index=indices[request];
    if(index>=rows){atomicExch(error,1);return;}
    float v=value(bank+uint64_t(index)*264,uint32_t(i%256));output[i]=v;
    uint32_t bits=__float_as_uint(v);
    bf[i]=uint16_t((bits&0x7fffffff)>0x7f800000?((bits>>16)|0x40):((bits+0x7fff+((bits>>16)&1))>>16));
}
}
void gather_device(const uint8_t* bank,uint64_t rows,const uint32_t* indices,uint64_t requests,float* decoded,uint16_t* bf,int* error,void* stream){
    if(!bank||!indices||!decoded||!bf||!error||!rows||!requests||rows>(std::numeric_limits<uint64_t>::max)()/264||requests>uint64_t((std::numeric_limits<uint32_t>::max)())/256)throw std::runtime_error("device gather shape/pointer overflow");
    gather<<<uint32_t((requests*256+255)/256),256,0,static_cast<hipStream_t>(stream)>>>(bank,rows,indices,requests,decoded,bf,error);
    auto e=hipGetLastError();if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));
}
}
