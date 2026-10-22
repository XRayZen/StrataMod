#include <hip/hip_runtime.h>
#include "baseline/quant.hip"
#include <filesystem>
#include <fstream>
#include <sstream>
#include <iostream>
#include <iomanip>
#include <cstring>
#include <chrono>
#include <windows.h>
namespace q=strata_ext::quant;
namespace candidate {
// Separate output rows share only a read-only activation. Each accumulator
// receives exactly its own accepted FP32 products, in full-K ascending order.
__global__ void two_row(const uint8_t*raw,unsigned type,const float*x,float*out,
                       size_t rows,size_t k,size_t batch,size_t stride){
 const size_t pairs=(rows+1)/2, i=blockIdx.x*blockDim.x+threadIdx.x;
 if(i>=pairs*batch)return;
 const size_t b=i/pairs,r=(i%pairs)*2;const bool second=r+1<rows;
 float acc0=0.0f,acc1=0.0f;
 const size_t width=type==8?34:type==39?17:33;
 for(size_t first=0;first<k;first+=32){
  auto block0=q::projection_block(raw+((r*k+first)/32)*width,type);
  // Avoid even constructing an out-of-bounds last-row pointer/context.
  q::ProjectionBlock block1{};
  if(second)block1=q::projection_block(raw+(((r+1)*k+first)/32)*width,type);
  for(unsigned lane=0;lane<32;++lane){
   float activation=x[b*k+first+lane];
   float product0=q::projection_block_value(block0,type,lane)*activation;
   acc0=acc0+product0;
   if(second){float product1=q::projection_block_value(block1,type,lane)*activation;acc1=acc1+product1;}
  }
 }
 out[b*stride+r]=acc0;if(second)out[b*stride+r+1]=acc1;
}
template<unsigned G>
__global__ void ordered_group(const uint8_t*raw,unsigned type,const float*x,float*out,
                             size_t rows,size_t k,size_t batch,size_t stride){
 static_assert(G==8||G==32,"reviewed subgroup widths only");
 // G divides both AMD wave32 and wave64. No lane exits before the gathers.
 const unsigned lane=threadIdx.x%G;
 const size_t i=size_t(blockIdx.x)*(256/G)+threadIdx.x/G;
 const bool valid=i<rows*batch;
 const size_t b=i/rows,r=i%rows,width=type==8?34:type==39?17:33;
 float acc=0.0f;
 for(size_t first=0;first<k;first+=32){
  q::ProjectionBlock block{};
  if(valid)block=q::projection_block(raw+((r*k+first)/32)*width,type);
  float products[32/G];
  for(unsigned qlane=0;qlane<32/G;++qlane){
   const unsigned j=qlane*G+lane;
   products[qlane]=0.0f;
   if(valid){float product=q::projection_block_value(block,type,j)*x[b*k+first+j];products[qlane]=product;}
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
}
void need(bool b,const char*s){if(!b)throw std::runtime_error(s);}
void hipcheck(hipError_t e){if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));}
struct Buffer{void*p=nullptr;explicit Buffer(size_t n){hipcheck(hipMalloc(&p,n));}
 void release(){need(p!=nullptr,"explicit live buffer release");hipcheck(hipFree(p));p=nullptr;}
 // Failure-only fallback: its return is not evidence of checked cleanup.
 ~Buffer(){if(p)(void)hipFree(p);}};
std::vector<uint8_t> read(const std::filesystem::path&p){std::ifstream f(p,std::ios::binary);need(bool(f),"input file");return {std::istreambuf_iterator<char>(f),{}};}
void write(const std::filesystem::path&p,const std::vector<uint8_t>&v){std::ofstream f(p,std::ios::binary);f.write((const char*)v.data(),v.size());need(bool(f),"output write");}
std::string json_string(const std::string&s){std::string out="\"";for(unsigned char c:s){if(c=='\\'||c=='\"')out+='\\';need(c>=32,"JSON control byte");out+=char(c);}return out+'\"';}
void json_number(double v){if(std::isfinite(v))std::cout<<v;else std::cout<<json_string(std::isnan(v)?"nan":v<0?"-inf":"+inf");}
void modules(){bool comma=false;std::cout<<"[";
 for(const wchar_t*name:{L"amdhip64_7.dll",L"amd_comgr.dll",L"msvcp140.dll",L"vcruntime140.dll",L"vcruntime140_1.dll"}){
  if(comma)std::cout<<",";comma=true;std::cout<<"{\"name\":"<<json_string(std::filesystem::path(name).u8string())<<",\"path\":";
  HMODULE module=GetModuleHandleW(name);
  if(!module){std::cout<<"null}";continue;}
  wchar_t path[32768];DWORD n=GetModuleFileNameW(module,path,32768);need(n&&n<32768,"actual module path");
  std::cout<<json_string(std::filesystem::path(std::wstring(path,n)).u8string())<<"}";
 }std::cout<<"]";
}
int main(int argc,char**argv){try{
 // The Python driver never runs this executable. Manual GPU use requires a
 // separately reviewed resource window and closed input/build manifest.
 need(argc==4,"explicit PCI jobs.tsv outputdir required");
 std::ifstream file(argv[2]);need(bool(file),"jobs file");
 std::vector<std::vector<std::string>>jobs;std::string line;
 while(std::getline(file,line)){std::stringstream s(line);std::vector<std::string>j;std::string f;while(std::getline(s,f,'\t'))j.push_back(f);need(j.size()==8,"job fields");jobs.push_back(j);}
 need(!jobs.empty()&&jobs.size()<=96,"bounded jobs");
 // Validate declared dimensions before any HIP context creation.
 for(auto&j:jobs){unsigned t=std::stoul(j[1]);size_t r=std::stoull(j[2]),k=std::stoull(j[3]),b=std::stoull(j[4]),s=std::stoull(j[5]);q::validate_projection_shape(t,r,k,b);need(r<=1713&&k<=5120&&s>=r&&s<=r+3,"bounded shape");}
 int count=0,device=-1;hipcheck(hipGetDeviceCount(&count));
 for(int i=0;i<count;++i){char pci[64]={};hipcheck(hipDeviceGetPCIBusId(pci,64,i));if(std::string(pci)==argv[1])device=i;}
 need(device>=0,"exact PCI unavailable");hipcheck(hipSetDevice(device));hipDeviceProp_t prop{};hipcheck(hipGetDeviceProperties(&prop,device));need(prop.warpSize==32||prop.warpSize==64,"reviewed physical wave widths only");
 const auto output=std::filesystem::u8path(argv[3]);std::filesystem::create_directories(output);
 char selected_pci[64]={};hipcheck(hipDeviceGetPCIBusId(selected_pci,64,device));
 std::cout<<std::setprecision(17)<<"{\"schema\":\"T35-row-parallel-G/v3\",\"device\":"<<device<<",\"pci\":"<<json_string(selected_pci)<<",\"architecture\":"<<json_string(prop.gcnArchName)<<",\"device_name\":"<<json_string(prop.name)<<",\"warp_size\":"<<prop.warpSize<<",\"jobs\":[";bool comma=false;size_t buffer_releases=0,event_destroys=0,kernel_calls=0;
 for(auto&j:jobs){unsigned type=std::stoul(j[1]);size_t rows=std::stoull(j[2]),k=std::stoull(j[3]),batch=std::stoull(j[4]),stride=std::stoull(j[5]);
  auto raw=read(std::filesystem::u8path(j[6])),x=read(std::filesystem::u8path(j[7]));need(raw.size()==q::packed_bytes(type,rows*k)&&x.size()==batch*k*4,"input bytes");
  Buffer w(raw.size()),a(x.size()),base(batch*stride*4),test(batch*stride*4);hipcheck(hipMemcpy(w.p,raw.data(),raw.size(),hipMemcpyHostToDevice));hipcheck(hipMemcpy(a.p,x.data(),x.size(),hipMemcpyHostToDevice));
  auto launch=[&](unsigned arm){float*out=(float*)(arm?test.p:base.p);
   if(!arm||type==0)q::projection_kernel<<<(rows*batch+255)/256,256>>>((const uint8_t*)w.p,type,(const float*)a.p,out,rows,k,batch,stride);
   else if(arm==1)candidate::two_row<<<(((rows+1)/2)*batch+255)/256,256>>>((const uint8_t*)w.p,type,(const float*)a.p,out,rows,k,batch,stride);
   else if(arm==2)candidate::ordered_group<8><<<(rows*batch+31)/32,256>>>((const uint8_t*)w.p,type,(const float*)a.p,out,rows,k,batch,stride);
   else if(arm==3)candidate::ordered_group<32><<<(rows*batch+7)/8,256>>>((const uint8_t*)w.p,type,(const float*)a.p,out,rows,k,batch,stride);
   else throw std::runtime_error("unqualified arm");
   hipcheck(hipGetLastError());++kernel_calls;};
  hipcheck(hipMemset(base.p,0xa5,batch*stride*4));launch(0);hipcheck(hipDeviceSynchronize());
  std::vector<uint8_t>v(batch*stride*4),z(v.size());hipcheck(hipMemcpy(v.data(),base.p,v.size(),hipMemcpyDeviceToHost));
  write(output/(j[0]+".baseline.bin"),v);
  if(comma)std::cout<<",";comma=true;std::cout<<"{\"name\":\""<<j[0]<<"\",\"candidates\":[";
  const char*names[]={"baseline","two-row","g8","g32"};
  for(unsigned candidate_arm=1;candidate_arm<=3;++candidate_arm){
   hipcheck(hipMemset(test.p,0xa5,batch*stride*4));launch(candidate_arm);hipcheck(hipDeviceSynchronize());hipcheck(hipMemcpy(z.data(),test.p,z.size(),hipMemcpyDeviceToHost));
   write(output/(j[0]+"."+names[candidate_arm]+".bin"),z);need(v==z,"baseline/candidate exact bits");
  for(size_t b=0;b<batch;++b)for(size_t r=rows;r<stride;++r){uint32_t bits;std::memcpy(&bits,z.data()+4*(b*stride+r),4);need(bits==0xa5a5a5a5,"padding guard");}
   if(candidate_arm>1)std::cout<<",";std::cout<<"{\"arm\":\""<<names[candidate_arm]<<"\",\"exact_bits\":true,\"envelopes\":[";unsigned arm=0;
   for(char label:std::string("ABBA")){hipEvent_t start,stop;hipcheck(hipEventCreate(&start));hipcheck(hipEventCreate(&stop));auto begun=std::chrono::steady_clock::now();hipcheck(hipEventRecord(start));for(unsigned n=0;n<5;++n)launch(label=='B'?candidate_arm:0);hipcheck(hipEventRecord(stop));hipcheck(hipEventSynchronize(stop));float ms;hipcheck(hipEventElapsedTime(&ms,start,stop));double wall=std::chrono::duration<double>(std::chrono::steady_clock::now()-begun).count();hipcheck(hipEventDestroy(start));hipcheck(hipEventDestroy(stop));event_destroys+=2;if(arm++)std::cout<<",";std::cout<<"{\"arm\":\""<<label<<"\",\"launches\":5,\"raw_event_ms\":";json_number(ms);std::cout<<",\"host_seconds\":";json_number(wall);std::cout<<"}";}
   std::cout<<"]}";
  }
  w.release();++buffer_releases;a.release();++buffer_releases;base.release();++buffer_releases;test.release();++buffer_releases;
  std::cout<<"]}";
 }
 std::cout<<"],\"modules\":";modules();std::cout<<",\"checked_buffer_releases\":"<<buffer_releases<<",\"checked_event_destroys\":"<<event_destroys<<",\"kernel_launch_calls\":"<<kernel_calls<<",\"model_generation\":false}\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
