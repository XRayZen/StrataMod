#include "engram.hpp"
#include "artifact.hpp"
#include "span_provider.hpp"
#include "strata/platform/direct_file.hpp"
#include <hip/hip_runtime.h>
#include <windows.h>
#include <psapi.h>
#include <algorithm>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
using namespace strata_ext;
namespace eg=deepseek41::engram;
namespace {
unsigned checks=0;
void check(bool ok,const char* why){++checks;if(!ok)throw std::runtime_error(why);}
template<class F>void rejects(F f){bool bad=false;try{f();}catch(const std::exception&){bad=true;}check(bad,"negative accepted");}
void hip(hipError_t e){if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));}
template<class T>std::vector<T> read(const std::filesystem::path& path){std::ifstream f(path,std::ios::binary|std::ios::ate);if(!f)throw std::runtime_error("input absent");auto size=f.tellg();if(size<0||size%sizeof(T))throw std::runtime_error("input byte alignment");std::vector<T> result(size_t(size)/sizeof(T));f.seekg(0);f.read(reinterpret_cast<char*>(result.data()),size);if(!f)throw std::runtime_error("short input");return result;}
template<class T>void write(const std::filesystem::path& path,const std::vector<T>& value){std::ofstream f(path,std::ios::binary);f.write(reinterpret_cast<const char*>(value.data()),std::streamsize(value.size()*sizeof(T)));if(!f)throw std::runtime_error("short output");}
std::vector<std::string> fields(const std::string& line){std::vector<std::string> v;std::istringstream s(line);std::string x;while(std::getline(s,x,'\t'))v.push_back(x);return v;}
deepseek41::Artifact artifact_index(const std::filesystem::path& input,std::filesystem::path& first){
    deepseek41::SourceSet sources;std::ifstream table(input/"sources.tsv");std::string line;
    while(std::getline(table,line)){auto f=fields(line);check(f.size()==5,"source columns");deepseek41::SourceFile s;s.shard_index=std::stoul(f[0]);s.original_size=std::stoull(f[1]);s.lfs_sha256=f[2];s.revision=f[3];s.original_path=std::filesystem::u8path(f[4]);if(sources.root.empty())sources.root=s.original_path.parent_path();sources.files.push_back(s);}
    std::vector<artifact::PrefixIndex> prefixes;std::ifstream list(input/"nine-prefixes.tsv");
    while(std::getline(list,line)){auto f=fields(line);check(f.size()==2,"prefix columns");auto p=std::filesystem::u8path(f[1]);if(first.empty())first=p;prefixes.push_back(artifact::inspect_prefix(p,std::stoull(f[0])));}
    return {artifact::merge_prefixes(prefixes),deepseek41::inspect_metadata(first),sources};
}
uint32_t next_u32(std::istream& f){uint32_t x=0;f.read(reinterpret_cast<char*>(&x),4);if(!f)throw std::runtime_error("truncated trace");return x;}
std::string quoted(const std::string& s){std::string r="\"";for(char c:s){if(c=='\\'||c=='\"')r+='\\';r+=c;}return r+'\"';}
std::string modules(){HMODULE handles[2048];DWORD needed=0;check(EnumProcessModules(GetCurrentProcess(),handles,sizeof(handles),&needed)&&needed<=sizeof(handles),"module inventory");std::ostringstream out;out<<'[';for(size_t i=0;i<needed/sizeof(HMODULE);++i){char path[32768];DWORD n=GetModuleFileNameA(handles[i],path,sizeof(path));check(n&&n<sizeof(path),"module path");if(i)out<<',';out<<quoted(path);}out<<']';return out.str();}
void host(const std::filesystem::path& input,const std::filesystem::path& out,const std::string& caller_hash){
    std::filesystem::path prefix;auto index=artifact_index(input,prefix);auto config=eg::inspect_metadata(prefix);
    std::vector<uint64_t> dumped(config.token_map.begin(),config.token_map.end());dumped.insert(dumped.end(),config.multipliers.begin(),config.multipliers.end());dumped.insert(dumped.end(),config.primes.begin(),config.primes.end());dumped.insert(dumped.end(),config.offsets.begin(),config.offsets.end());write(out/"config.bin",dumped);
    std::ifstream traces(input/"hash-input.bin",std::ios::binary);uint32_t count=next_u32(traces);check(count==17,"trace count");std::vector<uint64_t> full;
    for(unsigned c=0;c<count;++c){auto n=next_u32(traces);check(n>0&&n<=8,"fixture trace shape");std::vector<uint32_t> raw(n);std::vector<uint8_t> mask(n);traces.read(reinterpret_cast<char*>(raw.data()),n*4);traces.read(reinterpret_cast<char*>(mask.data()),n);check(bool(traces),"trace body");
        eg::History a(config),b(config),other(config);auto expected=a.append(0,raw,mask);std::vector<uint64_t> chunks;
        for(size_t i=0;i<n;++i){auto x=b.append(i,{raw[i]},{mask[i]});chunks.insert(chunks.end(),x.begin(),x.end());}
        check(expected==chunks&&b.position()==n,"append/chunk exact");other.append(0,{42},{1});check(other.position()==1&&a.position()==n,"sequence isolation");
        b.reset();check(b.position()==0,"reset cursor");check(b.append(0,raw,mask)==expected,"prefix reuse/reset exact");
        auto pos=a.position();rejects([&]{a.append(pos+1,{0},{1});});rejects([&]{a.append(pos,{129280},{1});});rejects([&]{a.append(pos,{0},{2});});rejects([&]{a.append(pos,{0},{});});check(a.position()==pos,"invalid append changed history");
        full.insert(full.end(),expected.begin(),expected.end());
    }
    char extra;check(!traces.read(&extra,1),"extra trace body");write(out/"hashes.bin",full);
    for(unsigned kind=0;kind<6;++kind){auto bad=config;switch(kind){case 0:bad.token_map[42]=99092;break;case 1:bad.multipliers[0]&=~1ull;break;case 2:bad.multipliers[0]=UINT64_MAX;break;case 3:bad.primes[1]=bad.primes[0];break;case 4:bad.offsets[2]++;break;case 5:bad.token_map.pop_back();break;}rejects([&]{eg::History h(bad);});}
    rejects([&]{eg::validate_indices(0,{0});});rejects([&]{eg::validate_indices(2,{2});});rejects([&]{eg::validate_indices(UINT64_MAX,{0});});rejects([&]{eg::validate_indices(2,{});});
    std::ifstream rows(input/"rows.tsv");std::string line;std::vector<artifact::FixtureView> views;
    while(std::getline(rows,line)){auto f=fields(line);check(f.size()==7,"row columns");auto slice=index.engram_row(std::stoul(f[1]),std::stoul(f[2]),std::stoull(f[3]));check(slice.absolute_offset==std::stoull(f[5])&&slice.bytes==264&&slice.original.span.dims_ggml==std::vector<uint64_t>({256,768022850})&&slice.original.source.shard_index==8,"T10 row source mapping");views.push_back({std::filesystem::u8path(f[6]),slice.absolute_offset,264});}
    check(views.size()==96,"real row count");
    using Direct=strata::platform::DirectFile;void* a=Direct::alloc_aligned(4096);void* b=Direct::alloc_aligned(4096);check(a&&b,"stage allocation");
    std::vector<io::Buffer> buffers{{a,4096},{b,4096}};measurement::Identity identity;identity.request_id="T13";identity.epoch=1;identity.fixture_sha256=caller_hash;identity.asset_sha256=caller_hash;identity.bundle_sha256=T13_SOURCE_ID;
    uint64_t logical=0,requested=0,peak=0;unsigned path=0;
    for(auto mode:{io::PathMode::PreferDirect,io::PathMode::Buffered,io::PathMode::Mapped}){
        std::vector<uint8_t> bank(96*264,0xa5);std::vector<io::Span> spans;for(uint32_t i=0;i<96;++i)spans.push_back({i,views[i].source_absolute_offset,264,uint64_t(i)*264});
        io::SpanProvider provider(views,buffers,io::Config{2,2,8192,4096,mode});auto ticket=provider.enqueue(spans,{bank.data(),bank.size()},identity);check(bool(ticket),"row enqueue");
        for(unsigned spin=0;!provider.done(*ticket)&&spin<10000;++spin){provider.issue();provider.poll(10);}check(provider.done(*ticket),"finite row progress");check(provider.take(*ticket,identity).ok,"row supply result");
        auto stats=provider.stats();check(stats.logical_delivered==25344&&stats.outstanding==0&&stats.outstanding_bytes==0,"row credits");check(provider.try_close(),"row owner drain");logical+=stats.logical_delivered;requested+=stats.read_requested;peak=(std::max)(peak,stats.peak_bytes);write(out/("row-bank-"+std::to_string(path++)+".bin"),bank);
    }
    Direct::free_aligned(a);Direct::free_aligned(b);
    std::cout<<"{\"source_id\":\""<<T13_SOURCE_ID<<"\",\"assertions\":"<<checks<<",\"hash_values\":"<<full.size()<<",\"real_rows\":96,\"logical_delivered\":"<<logical<<",\"read_requested\":"<<requested<<",\"peak_IO_bytes\":"<<peak<<",\"physical_IO\":null,\"full_source_qualified\":false}";
}
struct Device {void* p=nullptr;explicit Device(size_t n){hip(hipMalloc(&p,n));}~Device(){if(p)hipFree(p);}void release(){hip(hipFree(p));p=nullptr;}};
void gpu(const std::string& pci,const std::filesystem::path& input,const std::filesystem::path& out){
    auto bank=read<uint8_t>(input/"bank.bin");auto indices=read<uint32_t>(input/"indices.bin");check(bank.size()%264==0,"packed bank shape");eg::validate_indices(bank.size()/264,indices);
    int devices=0,chosen=-1;hip(hipGetDeviceCount(&devices));for(int d=0;d<devices;++d){char bus[64];hip(hipDeviceGetPCIBusId(bus,sizeof(bus),d));if(pci==bus)chosen=d;}check(chosen>=0,"exact PCI absent");hip(hipSetDevice(chosen));hipDeviceProp_t prop{};hip(hipGetDeviceProperties(&prop,chosen));
    size_t free_before=0,total=0;hip(hipMemGetInfo(&free_before,&total));size_t count=indices.size()*256,owned=bank.size()+indices.size()*4+count*6+4;check(free_before>owned+16*1024*1024,"small fixture free-memory budget");
    hipStream_t stream=nullptr;hip(hipStreamCreate(&stream));Device raw(bank.size()),ids(indices.size()*4),floats(count*4),bits(count*2),error(4);
    hip(hipMemcpyAsync(raw.p,bank.data(),bank.size(),hipMemcpyHostToDevice,stream));hip(hipMemcpyAsync(ids.p,indices.data(),indices.size()*4,hipMemcpyHostToDevice,stream));hip(hipMemsetAsync(error.p,0,4,stream));
    eg::gather_device(static_cast<uint8_t*>(raw.p),bank.size()/264,static_cast<uint32_t*>(ids.p),indices.size(),static_cast<float*>(floats.p),static_cast<uint16_t*>(bits.p),static_cast<int*>(error.p),stream);hip(hipStreamSynchronize(stream));
    int failure=0;hip(hipMemcpy(&failure,error.p,4,hipMemcpyDeviceToHost));check(failure==0,"valid device indices rejected");std::vector<float> values(count);std::vector<uint16_t> bf(count);hip(hipMemcpy(values.data(),floats.p,count*4,hipMemcpyDeviceToHost));hip(hipMemcpy(bf.data(),bits.p,count*2,hipMemcpyDeviceToHost));write(out/"decoded.bin",values);write(out/"bf16.bin",bf);
    uint32_t invalid=uint32_t(bank.size()/264);hip(hipMemcpyAsync(ids.p,&invalid,4,hipMemcpyHostToDevice,stream));hip(hipMemsetAsync(error.p,0,4,stream));eg::gather_device(static_cast<uint8_t*>(raw.p),bank.size()/264,static_cast<uint32_t*>(ids.p),1,static_cast<float*>(floats.p),static_cast<uint16_t*>(bits.p),static_cast<int*>(error.p),stream);hip(hipStreamSynchronize(stream));hip(hipMemcpy(&failure,error.p,4,hipMemcpyDeviceToHost));check(failure==1,"invalid device row accepted");
    hip(hipMemcpyAsync(ids.p,indices.data(),4,hipMemcpyHostToDevice,stream));hip(hipMemsetAsync(error.p,0,4,stream));eg::gather_device(static_cast<uint8_t*>(raw.p),bank.size()/264,static_cast<uint32_t*>(ids.p),1,static_cast<float*>(floats.p),static_cast<uint16_t*>(bits.p),static_cast<int*>(error.p),stream);hip(hipStreamSynchronize(stream));hip(hipMemcpy(&failure,error.p,4,hipMemcpyDeviceToHost));check(failure==0,"next operation failed");std::vector<float> next(256);hip(hipMemcpy(next.data(),floats.p,1024,hipMemcpyDeviceToHost));write(out/"next.bin",next);
    raw.release();ids.release();floats.release();bits.release();error.release();hip(hipStreamDestroy(stream));size_t free_after=0;hip(hipMemGetInfo(&free_after,&total));
    std::string loaded=modules();std::cout<<"{\"source_id\":\""<<T13_SOURCE_ID<<"\",\"pci\":"<<quoted(pci)<<",\"arch\":"<<quoted(prop.gcnArchName)<<",\"requests\":"<<indices.size()<<",\"own_device_bytes\":"<<owned<<",\"free_before\":"<<free_before<<",\"free_after\":"<<free_after<<",\"context_internal_bytes\":null,\"invalid_row_rejected\":true,\"cleanup_next_operation\":true,\"loaded_modules\":"<<loaded<<"}";
}
}
int main(int argc,char** argv){try{if(argc==2&&std::string(argv[1])=="--identity"){std::cout<<T13_SOURCE_ID;return 0;}if(argc==3&&std::string(argv[1])=="--metadata"){std::cout<<eg::inspect_metadata(std::filesystem::u8path(argv[2])).token_map.size();return 0;}if(argc!=6)throw std::runtime_error("mode/PCI-or-input/input-or-output/output-or-identity required");std::string mode=argv[1];if(mode=="--host"){std::filesystem::path out=std::filesystem::u8path(argv[3]);std::filesystem::create_directories(out);host(std::filesystem::u8path(argv[2]),out,argv[4]);}else if(mode=="--gpu"){std::filesystem::path out=std::filesystem::u8path(argv[4]);std::filesystem::create_directories(out);gpu(argv[2],std::filesystem::u8path(argv[3]),out);}else throw std::runtime_error("unknown mode");return 0;}catch(const std::exception& e){std::cerr<<e.what();return 2;}}
