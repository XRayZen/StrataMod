#include <hip/hip_runtime.h>
#define strata_ext t35_old_ext
#include "baseline/quant.hip"
#undef strata_ext
#include "candidate/quant.hip"
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <cstring>
#include <chrono>
#include <iomanip>
#include <windows.h>
namespace oldq=t35_old_ext::quant;
namespace newq=strata_ext::quant;
void require(bool value,const char* why){if(!value)throw std::runtime_error(why);}
void hipcheck(hipError_t value){require(value==hipSuccess,hipGetErrorString(value));}
struct Buffer{void*p=nullptr;explicit Buffer(size_t bytes){hipcheck(hipMalloc(&p,bytes));}~Buffer(){if(p)hipFree(p);}};
std::vector<uint8_t> read(const std::filesystem::path&path){std::ifstream in(path,std::ios::binary);require(bool(in),"input file");return {std::istreambuf_iterator<char>(in),std::istreambuf_iterator<char>()};}
void write(const std::filesystem::path&path,const std::vector<uint8_t>&bytes){std::ofstream out(path,std::ios::binary);out.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());require(bool(out),"output file");}
std::string json_string(const std::string&s){std::string out="\"";for(unsigned char c:s){if(c=='\\'||c=='\"')out+='\\';require(c>=32,"module path control character");out+=char(c);}return out+'\"';}
void modules(){
 bool comma=false;std::cout<<"[";
 for(const wchar_t*name:{L"amdhip64_7.dll",L"amd_comgr.dll",L"msvcp140.dll",L"vcruntime140.dll",L"vcruntime140_1.dll"}){
  HMODULE module=GetModuleHandleW(name);if(!module)continue;wchar_t path[32768];DWORD n=GetModuleFileNameW(module,path,32768);require(n&&n<32768,"actual module path");
  if(comma)std::cout<<",";comma=true;std::cout<<json_string(std::filesystem::path(std::wstring(path,n)).u8string());
 }std::cout<<"]";
}
__global__ void candidate_values(const uint8_t*raw,unsigned type,float*out,size_t n){
 size_t i=blockIdx.x*blockDim.x+threadIdx.x;if(i>=n)return;
 if(type==0){out[i]=newq::value(raw,type,i);return;}
 size_t width=type==8?34:type==39?17:33;
 auto block=newq::projection_block(raw+(i/32)*width,type);
 out[i]=newq::projection_block_value(block,type,unsigned(i%32));
}
int main(int argc,char**argv){try{
 require(argc==4,"exact PCI jobs.tsv outputdir required");
 std::ifstream input(argv[2]);require(bool(input),"jobs file");std::vector<std::vector<std::string>>jobs;std::string line;
 while(std::getline(input,line)){std::stringstream stream(line);std::vector<std::string>fields;std::string field;while(std::getline(stream,field,'\t'))fields.push_back(field);require(fields.size()==9,"job fields");jobs.push_back(fields);}
 require(!jobs.empty()&&jobs.size()<=64,"finite jobs");
 // Parse all shapes before HIP context creation.
 for(const auto&j:jobs){auto type=std::stoul(j[2]);auto rows=std::stoull(j[3]),k=std::stoull(j[4]),batch=std::stoull(j[5]),stride=std::stoull(j[6]);require(j[1]=="decode"||j[1]=="project","job kind");require(rows>0&&rows<=65536&&k>0&&k<=5120&&stride>=rows&&stride<=rows+3,"shape bounds");newq::validate_projection_shape(type,rows,k,batch);}
 int count=0,device=-1;hipcheck(hipGetDeviceCount(&count));for(int i=0;i<count;++i){char pci[64]={};hipcheck(hipDeviceGetPCIBusId(pci,sizeof(pci),i));if(std::string(pci)==argv[1])device=i;}require(device>=0,"exact PCI unavailable");hipcheck(hipSetDevice(device));
 std::filesystem::path out=std::filesystem::u8path(argv[3]);std::filesystem::create_directories(out);std::cout<<std::setprecision(17)<<"{\"schema\":\"T35-block-scale-G/v1\",\"device\":"<<device<<",\"jobs\":[";bool comma=false;
 for(const auto&j:jobs){
  auto type=unsigned(std::stoul(j[2]));size_t rows=std::stoull(j[3]),k=std::stoull(j[4]),batch=std::stoull(j[5]),stride=std::stoull(j[6]);auto raw=read(std::filesystem::u8path(j[7]));require(raw.size()==newq::packed_bytes(type,rows*k),"packed bytes");
  auto x=read(std::filesystem::u8path(j[8]));require(x.size()==batch*k*4,"input float bytes");size_t n=j[1]=="decode"?rows*k:batch*stride;
  Buffer weights(raw.size()),activation(x.size()),oldout(n*4),newout(n*4);hipcheck(hipMemcpy(weights.p,raw.data(),raw.size(),hipMemcpyHostToDevice));hipcheck(hipMemcpy(activation.p,x.data(),x.size(),hipMemcpyHostToDevice));
  auto launch=[&](bool newer){void*dest=newer?newout.p:oldout.p;
   if(j[1]=="decode"){
    if(newer)candidate_values<<<(n+255)/256,256>>>(static_cast<const uint8_t*>(weights.p),type,static_cast<float*>(dest),n);
    else oldq::decode_kernel<<<(n+255)/256,256>>>(static_cast<const uint8_t*>(weights.p),type,static_cast<float*>(dest),n);
   }else if(newer)newq::projection_kernel<<<(rows*batch+255)/256,256>>>(static_cast<const uint8_t*>(weights.p),type,static_cast<const float*>(activation.p),static_cast<float*>(dest),rows,k,batch,stride);
   else oldq::projection_kernel<<<(rows*batch+255)/256,256>>>(static_cast<const uint8_t*>(weights.p),type,static_cast<const float*>(activation.p),static_cast<float*>(dest),rows,k,batch,stride);
   hipcheck(hipGetLastError());};
  hipcheck(hipMemset(oldout.p,0xa5,n*4));hipcheck(hipMemset(newout.p,0xa5,n*4));launch(false);launch(true);hipcheck(hipDeviceSynchronize());
  std::vector<uint8_t>a(n*4),b(n*4);hipcheck(hipMemcpy(a.data(),oldout.p,a.size(),hipMemcpyDeviceToHost));hipcheck(hipMemcpy(b.data(),newout.p,b.size(),hipMemcpyDeviceToHost));write(out/(j[0]+".old.bin"),a);write(out/(j[0]+".new.bin"),b);require(a==b,"old/new exact bits");
  if(j[1]=="project")for(size_t lane=0;lane<batch;++lane)for(size_t r=rows;r<stride;++r){uint32_t value=0;std::memcpy(&value,b.data()+4*(lane*stride+r),4);require(value==0xa5a5a5a5,"padded output overwritten");}
  if(comma)std::cout<<",";comma=true;std::cout<<"{\"name\":\""<<j[0]<<"\",\"exact_bits\":true,\"requested_device_bytes\":"<<raw.size()+x.size()+n*8<<",\"event_envelopes_ms\":[";
  unsigned arm=0;for(char label:std::string("ABBA")){hipEvent_t start=nullptr,stop=nullptr;hipcheck(hipEventCreate(&start));hipcheck(hipEventCreate(&stop));auto begun=std::chrono::steady_clock::now();hipcheck(hipEventRecord(start));for(unsigned repeat=0;repeat<5;++repeat)launch(label=='B');hipcheck(hipEventRecord(stop));hipcheck(hipEventSynchronize(stop));float ms=0;hipcheck(hipEventElapsedTime(&ms,start,stop));hipcheck(hipEventDestroy(start));hipcheck(hipEventDestroy(stop));double wall=std::chrono::duration<double>(std::chrono::steady_clock::now()-begun).count();if(arm++)std::cout<<",";std::cout<<"{\"arm\":\""<<label<<"\",\"launches\":5,\"ms\":"<<ms<<",\"host_seconds\":"<<wall<<"}";}std::cout<<"]}";
 }
 hipcheck(hipDeviceSynchronize());std::cout<<"],\"loaded_modules\":";modules();std::cout<<",\"old_new_exact\":true,\"model_generation\":false}\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
