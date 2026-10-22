#include "core.hpp"
#include "device_ops.hpp"
#include <hip/hip_runtime.h>
#include <fstream>
#include <iostream>
#include <sstream>
#include <filesystem>
#include <cstring>
#include <iomanip>
#include <chrono>
#include <windows.h>
namespace D=strata_ext::deepseek41;
namespace Q=strata_ext::quant;
void need(bool ok,const char*message){if(!ok)throw std::runtime_error(message);}
void hc(hipError_t code){need(code==hipSuccess,hipGetErrorString(code));}
std::vector<std::vector<std::string>> jobs(const char*path){std::ifstream f(path);need(bool(f),"TSV input");std::vector<std::vector<std::string>>out;std::string line;while(std::getline(f,line)){std::stringstream s(line);std::vector<std::string>r;std::string field;while(std::getline(s,field,'\t'))r.push_back(field);out.push_back(r);}need(!out.empty(),"finite input");return out;}
D::SourceTensor tensor(unsigned type,uint64_t k,uint64_t rows,uint64_t matrices,uint64_t rowbytes,uint64_t bytes){
 D::SourceTensor t;t.source.shard_index=1;t.source.original_path="synthetic-metadata";t.source.original_size=bytes;t.source.revision=std::string(40,'a');t.source.lfs_sha256=std::string(64,'b');
 t.span.shard_index=1;t.span.type_id=type;t.span.name="synthetic";t.span.dims_ggml={k,rows,matrices};t.span.row_bytes=rowbytes;t.span.bytes=bytes;return t;
}
struct Buffer{void*p=nullptr;explicit Buffer(size_t bytes){hc(hipMalloc(&p,bytes));}void close(){if(p){hc(hipFree(p));p=nullptr;}}~Buffer(){if(p)hipFree(p);}};
std::vector<uint8_t> bytes(const std::string&p){std::ifstream f(std::filesystem::u8path(p),std::ios::binary);need(bool(f),"raw input");return {std::istreambuf_iterator<char>(f),std::istreambuf_iterator<char>()};}
void write(const std::filesystem::path&p,const std::vector<uint8_t>&v){std::ofstream f(p,std::ios::binary);f.write(reinterpret_cast<const char*>(v.data()),v.size());need(bool(f),"output file");}
std::string quoted(const std::string&s){std::string out="\"";for(unsigned char c:s){if(c=='\\'||c=='\"')out+='\\';need(c>=32,"path control byte");out+=char(c);}return out+'\"';}
void modules(){bool comma=false;std::cout<<"[";for(const wchar_t*name:{L"amdhip64_7.dll",L"amd_comgr.dll",L"msvcp140.dll",L"vcruntime140.dll",L"vcruntime140_1.dll"}){auto module=GetModuleHandleW(name);if(!module)continue;wchar_t path[32768];DWORD size=GetModuleFileNameW(module,path,32768);need(size&&size<32768,"loaded module path");if(comma)std::cout<<",";comma=true;std::cout<<quoted(std::filesystem::path(std::wstring(path,size)).u8string());}std::cout<<"]";}
int main(int argc,char**argv){try{
 need(argc==4,"--cpu or PCI, TSV, output directory");auto all=jobs(argv[2]);std::filesystem::path out=std::filesystem::u8path(argv[3]);std::filesystem::create_directories(out);std::cout<<std::setprecision(17);
 if(std::string(argv[1])=="--cpu"){
  std::cout<<"{\"schema\":\"T35-native-row-geometry/v1\",\"GPU_work_submitted\":false,\"jobs\":[";bool comma=false;
  for(const auto&r:all){need(r.size()==8,"metadata fields");auto type=unsigned(std::stoul(r[0]));auto k=std::stoull(r[1]),rows=std::stoull(r[2]),matrices=std::stoull(r[3]),rowbytes=std::stoull(r[4]),n=std::stoull(r[5]),cap=std::stoull(r[6]),rowcap=std::stoull(r[7]);
   auto source=tensor(type,k,rows,matrices,rowbytes,n);auto tiles=D::row_tiles(source,0,cap,rowcap);uint64_t next=0,total=0;
   for(const auto&t:tiles){need(t.row_first==next&&t.k==k&&t.bytes<=cap&&t.bytes==t.row_count*rowbytes,"native row cover/bytes/fullK");next+=t.row_count;total+=t.bytes;}
   need(next==rows&&total==rows*rowbytes,"native complete row cover");if(comma)std::cout<<",";comma=true;
   std::cout<<"{\"tiles\":"<<tiles.size()<<",\"first_rows\":"<<tiles.front().row_count<<",\"last_rows\":"<<tiles.back().row_count<<",\"last_first\":"<<tiles.back().row_first<<",\"matrix_bytes\":"<<total<<"}";
  }std::cout<<"],\"loaded_modules\":";modules();std::cout<<"}\n";return 0;
 }
 need(all.size()==2,"bounded two projection matrices");
 int count=0,device=-1;hc(hipGetDeviceCount(&count));for(int i=0;i<count;++i){char pci[64]={};hc(hipDeviceGetPCIBusId(pci,sizeof(pci),i));if(std::string(pci)==argv[1])device=i;}need(device>=0,"exact PCI unavailable");hc(hipSetDevice(device));hipStream_t stream=nullptr;hc(hipStreamCreate(&stream));Q::ProjectionLease lease;
 std::cout<<"{\"schema\":\"T35-tile-rows-G/v1\",\"jobs\":[";bool comma=false;
 for(const auto&r:all){need(r.size()==8,"projection fields");const auto&name=r[0];auto type=unsigned(std::stoul(r[1]));auto rows=std::stoull(r[2]),k=std::stoull(r[3]),batch=std::stoull(r[4]),stride=std::stoull(r[5]);need(type==39&&batch==1&&stride==rows+3,"finite representative shape");auto raw=bytes(r[6]),x=bytes(r[7]);need(raw.size()==Q::packed_bytes(type,rows*k)&&x.size()==k*4,"packed/input bytes");
 auto source=tensor(type,k,rows,1,Q::packed_bytes(type,k),raw.size());Buffer weight(raw.size()),input(x.size()),a(stride*4),b(stride*4);hc(hipMemcpy(weight.p,raw.data(),raw.size(),hipMemcpyHostToDevice));hc(hipMemcpy(input.p,x.data(),x.size(),hipMemcpyHostToDevice));
 auto iv=D::checked_device_view(input.p,x.size(),batch,k,D::DeviceScalar::Float32,device,lease);
 auto launch=[&](uint64_t rowcap,Buffer&dest){D::CoreConfig cfg;cfg.device=device;cfg.tile_rows=rowcap;auto ov=D::checked_device_view(dest.p,stride*4,batch,rows,D::DeviceScalar::Float32,device,lease);uint64_t calls=0;
  D::tiled_projection(source,0,iv,ov,batch,cfg,stream,[&](const D::SourceTile&t,const D::DeviceView&i,const D::DeviceView&o,uint64_t n,void*s){
   Q::PackedDeviceView w{static_cast<const uint8_t*>(weight.p)+t.absolute_offset,type,size_t(t.row_count),size_t(k),size_t(t.bytes),device};auto output=static_cast<float*>(o.data)+t.row_first;auto handle=Q::checked_projection_strided(w,static_cast<const float*>(i.data),i.bytes,output,o.bytes-4*t.row_first,o.columns,s,lease);Q::project_into(handle,n);++calls;
  });return calls;
 };
 hc(hipMemset(a.p,0xa5,stride*4));hc(hipMemset(b.p,0xa5,stride*4));auto callsA=launch(256,a),callsB=launch(1713,b);hc(hipStreamSynchronize(stream));std::vector<uint8_t>av(stride*4),bv(stride*4);hc(hipMemcpy(av.data(),a.p,av.size(),hipMemcpyDeviceToHost));hc(hipMemcpy(bv.data(),b.p,bv.size(),hipMemcpyDeviceToHost));need(av==bv,"geometry exact output bits");for(size_t i=rows;i<stride;++i){uint32_t v;std::memcpy(&v,bv.data()+i*4,4);need(v==0xa5a5a5a5,"output padding");}write(out/(name+".256.bin"),av);write(out/(name+".1713.bin"),bv);
 if(comma)std::cout<<",";comma=true;std::cout<<"{\"name\":\""<<name<<"\",\"calls256\":"<<callsA<<",\"calls1713\":"<<callsB<<",\"weight_H2D_bytes\":"<<raw.size()<<",\"requested_device_bytes\":"<<raw.size()+x.size()+stride*8<<",\"exact_bits\":true,\"event_envelopes\":[";
 unsigned arm=0;for(char label:std::string("ABBA")){hipEvent_t start=nullptr,stop=nullptr;hc(hipEventCreate(&start));hc(hipEventCreate(&stop));auto begin=std::chrono::steady_clock::now();hc(hipEventRecord(start,stream));for(unsigned n=0;n<3;++n)launch(label=='A'?256:1713,label=='A'?a:b);hc(hipEventRecord(stop,stream));hc(hipEventSynchronize(stop));float ms=0;hc(hipEventElapsedTime(&ms,start,stop));double wall=std::chrono::duration<double>(std::chrono::steady_clock::now()-begin).count();hc(hipEventDestroy(start));hc(hipEventDestroy(stop));if(arm++)std::cout<<",";std::cout<<"{\"arm\":\""<<label<<"\",\"projections\":3,\"raw_event_ms\":"<<ms<<",\"host_seconds\":"<<wall<<"}";}std::cout<<"]}";
 a.close();b.close();input.close();weight.close();
 }
 hc(hipStreamSynchronize(stream));lease.active=false;hc(hipStreamDestroy(stream));std::cout<<"],\"loaded_modules\":";modules();std::cout<<",\"model_generation\":false}\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
