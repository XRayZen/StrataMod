#include "quant.hpp"
#include "native_reader.hpp"
#include <hip/hip_runtime.h>
#include <windows.h>
#include <psapi.h>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <filesystem>
#include <cstring>
namespace {
void check(hipError_t e) { if(e!=hipSuccess) throw std::runtime_error(hipGetErrorString(e)); }
std::vector<std::string> split(const std::string& s) { std::vector<std::string> v;std::stringstream ss(s);std::string x;while(std::getline(ss,x,'\t'))v.push_back(x);return v; }
void write(const std::filesystem::path& p,const std::vector<float>& values) {std::ofstream f(p,std::ios::binary);f.write(reinterpret_cast<const char*>(values.data()),values.size()*4);if(!f)throw std::runtime_error("output write");}
std::string escaped(const std::string& s) { std::string out;for(char c:s) {if(c=='\\'||c=='"')out+='\\';out+=c;}return out; }
}
int main(int argc,char** argv) {
 try {
    if(argc==2 && std::string(argv[1])=="--shape-selftest") {
      unsigned rejected=0;
      for(unsigned type:{8u,39u,43u}) {
        std::vector<uint8_t> raw(strata_ext::quant::packed_bytes(type,32));
        try { strata_ext::quant::project(raw,type,32,1,1,std::vector<float>{1}); }
        catch(const std::runtime_error& e) {
          if(std::string(e.what())!="quant row K must align to block32")throw;
          ++rejected;
        }
      }
      for(size_t k:{1u,2u,3u})strata_ext::quant::validate_projection_shape(0,1,k,1);
      if(rejected!=3)throw std::runtime_error("rowshape negative accepted");
      std::cout<<"{\"quant_rows32_K1_rejected\":3,\"F32_K1_K2_K3_valid\":3,\"gpu_context_created\":false}"<<std::endl;return 0;
    }
    if(argc!=5 || std::string(argv[1])!="--run") throw std::runtime_error("usage: --run exactPCI jobs.tsv outputdir");
    std::ifstream jobs(argv[3]);if(!jobs) throw std::runtime_error("jobs open");
    std::vector<std::vector<std::string>> parsed;std::string line;
    while(std::getline(jobs,line)) {auto v=split(line);if(v.size()!=10)throw std::runtime_error("job field count");parsed.push_back(v);}
    if(parsed.empty())throw std::runtime_error("empty jobs");
    // Validate raw type/shape before creating a context. Actual view reads remain bounded.
    uint64_t own_peak_bytes=0;
    for(const auto& v:parsed) {
      auto bytes=std::stoull(v[3]),rows=std::stoull(v[5]),k=std::stoull(v[6]);
      unsigned type=std::stoul(v[4]);
      if(!rows || !k || rows>5120 || k>5120)throw std::runtime_error("fixture shape range");
      if(bytes!=strata_ext::quant::packed_bytes(type,rows*k))throw std::runtime_error("job packed count");
      auto batch=std::stoull(v[7]);
      if(v[0]!="decode" && v[0]!="project")throw std::runtime_error("job mode");
      if(v[0]=="project" && !(batch==1||batch==2||batch==4||batch==8))throw std::runtime_error("job batch");
      if(v[0]=="project")strata_ext::quant::validate_projection_shape(type,rows,k,batch);
      uint64_t requested=bytes+(v[0]=="decode" ? rows*k*4 : (batch*k+batch*rows)*4);
      own_peak_bytes=std::max(own_peak_bytes,requested);
    }
    int count=0,selected=-1;check(hipGetDeviceCount(&count));
    for(int i=0;i<count;++i) { char pci[64]={};check(hipDeviceGetPCIBusId(pci,sizeof(pci),i));if(std::string(pci)==argv[2])selected=i; }
    if(selected<0)throw std::runtime_error("exact PCI absent");
    check(hipSetDevice(selected));hipDeviceProp_t prop{};check(hipGetDeviceProperties(&prop,selected));
    size_t free_before=0,total_before=0,free_after=0,total_after=0;
    auto memory_before_status=hipMemGetInfo(&free_before,&total_before);
    char actual_pci[64]={};check(hipDeviceGetPCIBusId(actual_pci,sizeof(actual_pci),selected));
    std::filesystem::path dir(argv[4]);std::filesystem::create_directories(dir);
    size_t completed=0;
    for(const auto& v:parsed) {
      auto offset=std::stoull(v[2]),bytes=std::stoull(v[3]),rows=std::stoull(v[5]),k=std::stoull(v[6]),batch=std::stoull(v[7]);
      unsigned type=std::stoul(v[4]);
      strata_ext::artifact::FixtureView view{std::filesystem::path(v[1]),offset,bytes};
      auto raw=view.read_exact(offset,bytes);
      if(v[0]=="decode") write(dir/v[9],strata_ext::quant::decode(raw,type,rows*k));
      else if(v[0]=="project") {
        strata_ext::artifact::FixtureView xv{std::filesystem::path(v[8]),0,batch*k*4};
        auto xb=xv.read_exact(0,batch*k*4);std::vector<float> x(batch*k);std::memcpy(x.data(),xb.data(),xb.size());
        write(dir/v[9],strata_ext::quant::project(raw,type,rows,k,batch,x));
      } else throw std::runtime_error("job mode");
      ++completed;
    }
    check(hipDeviceSynchronize());
    auto memory_after_status=hipMemGetInfo(&free_after,&total_after);
    PROCESS_MEMORY_COUNTERS memory{};memory.cb=sizeof(memory);
    bool host_memory_ok=GetProcessMemoryInfo(GetCurrentProcess(),&memory,sizeof(memory))!=0;
    HMODULE modules[1024];DWORD needed=0;if(!EnumProcessModules(GetCurrentProcess(),modules,sizeof(modules),&needed)||needed>sizeof(modules))throw std::runtime_error("loaded module inventory");
    std::cout<<"{\"source_id\":\""<<T09_SOURCE_ID<<"\",\"pci\":\""<<actual_pci<<"\",\"arch\":\""<<prop.gcnArchName<<"\",\"completed\":"<<completed<<",\"loaded_modules\":[";
    bool first=true;for(unsigned i=0;i<needed/sizeof(HMODULE);++i) {char p[32768];if(!GetModuleFileNameA(modules[i],p,sizeof(p)))throw std::runtime_error("module path");if(!first)std::cout<<",";first=false;std::cout<<"\""<<escaped(p)<<"\"";}
    std::cout<<"],\"own_peak_device_allocation_bytes\":"<<own_peak_bytes
             <<",\"hip_memory_before_status\":"<<int(memory_before_status)<<",\"hip_free_before\":";
    if(memory_before_status==hipSuccess)std::cout<<free_before;else std::cout<<"null";
    std::cout<<",\"hip_total_before\":";if(memory_before_status==hipSuccess)std::cout<<total_before;else std::cout<<"null";
    std::cout<<",\"hip_memory_after_status\":"<<int(memory_after_status)<<",\"hip_free_after\":";
    if(memory_after_status==hipSuccess)std::cout<<free_after;else std::cout<<"null";
    std::cout<<",\"hip_total_after\":";if(memory_after_status==hipSuccess)std::cout<<total_after;else std::cout<<"null";
    std::cout<<",\"host_peak_working_set\":";if(host_memory_ok)std::cout<<memory.PeakWorkingSetSize;else std::cout<<"null";
    std::cout<<",\"allocation_observation_scope\":\"own buffers exact peak; context/cache/other consumers separate unknown; free difference is not cleanup gate\"}"<<std::endl;return 0;
 } catch(const std::exception& e) { std::cerr<<e.what()<<std::endl;return 2; }
}
