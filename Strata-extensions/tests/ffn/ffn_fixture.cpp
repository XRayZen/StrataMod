#include "ffn.hpp"
#include <hip/hip_runtime.h>
#include <windows.h>
#include <psapi.h>
#include <fstream>
#include <iostream>
#include <sstream>
#include <cstring>
using namespace strata_ext;
namespace {
void check(hipError_t e){if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));}
std::vector<std::string> split(const std::string&s){std::stringstream stream(s);std::vector<std::string> out;std::string x;while(std::getline(stream,x,'\t'))out.push_back(x);return out;}
std::vector<std::vector<std::string>> table(const char* path,size_t columns){std::ifstream f(path);if(!f)throw std::runtime_error("table open");std::vector<std::vector<std::string>> out;std::string line;while(std::getline(f,line)){auto fields=split(line);if(fields.size()!=columns)throw std::runtime_error("table columns");out.push_back(fields);}return out;}
std::string escaped(const std::string&s){std::string out;for(char c:s){if(c=='\\'||c=='"')out+='\\';if(c=='\n')out+="\\n";else if(c=='\r')out+="\\r";else if(c=='\t')out+="\\t";else out+=c;}return out;}
std::string key(const std::string& name,int expert){return name+"#"+std::to_string(expert);}
}
int main(int argc,char**argv){try{
 if(argc==2 && std::string(argv[1])=="--identity"){std::cout<<"{\"source_id\":\""<<T11_SOURCE_ID<<"\"}";return 0;}
 if(argc==2 && std::string(argv[1])=="--shape-selftest"){
  unsigned rejected=0;deepseek41::MatrixProvider unused=[](auto,auto)->deepseek41::Matrix{throw std::runtime_error("provider must not execute");};measurement::Identity id;
  for(unsigned mode=0;mode<4;++mode){std::vector<float>x(mode==0?0:5120,0);std::vector<uint8_t> masks(1,mode==2?2:0);if(mode==3)x[0]=NAN;try{deepseek41::run_ffn(x,mode==1?2:1,masks,unused,id,"fixture");}catch(const std::exception&e){if(std::string(e.what())!="FFN shape/nonfinite/mask")throw;++rejected;}}
  std::cout<<"{\"shape_rejected\":"<<rejected<<",\"GPU_used\":false}";return rejected==4?0:2;
 }

 if(argc==5 && std::string(argv[1])=="--boundaries"){
  int count=0,selected=-1;check(hipGetDeviceCount(&count));for(int i=0;i<count;++i){char pci[64]={};check(hipDeviceGetPCIBusId(pci,sizeof(pci),i));if(std::string(pci)==argv[2])selected=i;}if(selected<0)throw std::runtime_error("boundary PCI");check(hipSetDevice(selected));
  std::filesystem::path in(argv[3]),out(argv[4]);std::filesystem::create_directory(out);
  auto read=[&](const std::string& name,size_t n){artifact::FixtureView v{in/(name+".bin"),0,n*4};auto bytes=v.read_exact(0,n*4);std::vector<float>x(n);std::memcpy(x.data(),bytes.data(),bytes.size());return x;};
  auto trace=deepseek41::run_boundaries(read("cast",32),read("act",160),read("logits",1152),read("bias",384),read("bias_vl",384),{0,1,0},read("gate",2304),read("up",2304),read("route",1));
  std::ofstream meta(out/"stages.tsv");for(const auto&[name,stage]:trace.stages){std::ofstream file(out/(name+".bin"),std::ios::binary);file.write((const char*)stage.bytes.data(),stage.bytes.size());if(!file)throw std::runtime_error("boundary write");meta<<name<<'\t'<<stage.dtype<<'\t'<<stage.rows<<'\t'<<stage.columns<<'\t'<<stage.bytes.size()<<'\n';}
  std::cout<<"{\"source_id\":\""<<T11_SOURCE_ID<<"\",\"stages\":"<<trace.stages.size()<<",\"actual_scratch_peak\":"<<trace.stats.actual_scratch_peak<<",\"cleanup_unknown\":false,\"learned_weight_qualification\":false}";return 0;
 }
 if(argc!=8 || std::string(argv[1])!="--run")throw std::runtime_error("--run PCI weights.tsv sources.tsv prefixes.tsv jobs.tsv outputdir");
 deepseek41::SourceSet sources;for(const auto&row:table(argv[4],5)){deepseek41::SourceFile f;f.shard_index=std::stoul(row[0]);f.original_size=std::stoull(row[1]);f.lfs_sha256=row[2];f.revision=row[3];f.original_path=row[4];if(sources.root.empty())sources.root=f.original_path.parent_path();sources.files.push_back(f);}
 std::vector<artifact::PrefixIndex> prefixes;std::string first;
 for(const auto&row:table(argv[5],2)){if(first.empty())first=row[1];prefixes.push_back(artifact::inspect_prefix(row[1],std::stoull(row[0])));}
 deepseek41::Artifact index(artifact::merge_prefixes(prefixes),deepseek41::inspect_metadata(first),sources);
 std::map<std::string,std::vector<std::string>> weights;
 for(const auto&row:table(argv[3],6)){auto name=key(row[0],std::stoi(row[1]));if(!weights.emplace(name,row).second)throw std::runtime_error("duplicate weight fixture");}
 deepseek41::MatrixProvider provider=[&](const std::string& role,uint32_t expert){
  std::string name;int selected=-1;
  if(role=="router")name="blk.0.ffn_gate_inp.weight";else if(role=="bias")name="blk.0.exp_probs_b.bias";else if(role=="bias_vl")name="blk.0.exp_probs_b_vl.bias";
  else if(role.substr(0,7)=="shared_")name="blk.0.ffn_"+role.substr(7)+"_shexp.weight";
  else {if(role!="gate"&&role!="up"&&role!="down")throw std::runtime_error("matrix role");name="blk.0.ffn_"+role+"_exps.weight";selected=static_cast<int>(expert);}
  auto found=weights.find(key(name,selected));if(found==weights.end())throw std::runtime_error("missing selected learned expert/weight");const auto&row=found->second;
  auto original=index.source_tensor(name);auto span=original.span;uint64_t offset=span.absolute_offset,bytes=span.bytes;
  if(selected>=0){auto slice=index.expert(0,role,expert);original=slice.original;offset=slice.absolute_offset;bytes=slice.bytes;}
  if(std::stoull(row[2])!=offset || std::stoull(row[3])!=bytes || std::stoul(row[4])!=span.type_id)throw std::runtime_error("fixture source span/type mismatch");
  artifact::FixtureView view{row[5],offset,bytes};deepseek41::Matrix m;m.original=original;m.source_absolute_offset=offset;m.type=span.type_id;m.k=static_cast<uint32_t>(span.dims_ggml[0]);m.rows=span.dims_ggml.size()==1?1:static_cast<uint32_t>(span.dims_ggml[1]);m.packed=view.read_exact(offset,bytes);return m;
 };
 auto jobs=table(argv[6],5);if(jobs.empty())throw std::runtime_error("empty jobs");
 int count=0,selected=-1;check(hipGetDeviceCount(&count));for(int i=0;i<count;++i){char pci[64]={};check(hipDeviceGetPCIBusId(pci,sizeof(pci),i));if(std::string(pci)==argv[2])selected=i;}if(selected<0)throw std::runtime_error("exact PCI absent");check(hipSetDevice(selected));hipDeviceProp_t prop{};check(hipGetDeviceProperties(&prop,selected));
 size_t free_before=0,total_before=0,free_after=0,total_after=0;auto memory_before_status=hipMemGetInfo(&free_before,&total_before);
 std::filesystem::path outroot(argv[7]);std::filesystem::create_directories(outroot);std::ostringstream summaries;summaries<<"[";bool first_job=true;uint64_t peak_matrix=0,peak_scratch=0;
 for(const auto&job:jobs){auto batch=std::stoul(job[1]),mask=std::stoul(job[2]);if(mask>1 || !batch)throw std::runtime_error("fixture batch/mask");artifact::FixtureView input{job[3],0,batch*5120*4};auto raw=input.read_exact(0,batch*5120*4);std::vector<float>x(batch*5120);std::memcpy(x.data(),raw.data(),raw.size());
  measurement::Identity identity;identity.fixture_sha256=job[4];identity.asset_sha256=sources.files[1].lfs_sha256;identity.bundle_sha256=T11_SOURCE_ID;identity.request_id=job[0];identity.epoch=1;identity.phase=measurement::Phase::Decode;
  auto trace=deepseek41::run_ffn(x,static_cast<unsigned>(batch),std::vector<uint8_t>(batch,static_cast<uint8_t>(mask)),provider,identity,argv[2]);auto directory=outroot/job[0];std::filesystem::create_directory(directory);
  std::ofstream stages(directory/"stages.tsv");for(const auto&[name,stage]:trace.stages){std::ofstream out(directory/(name+".bin"),std::ios::binary);out.write((const char*)stage.bytes.data(),stage.bytes.size());if(!out)throw std::runtime_error("stage write");stages<<name<<'\t'<<stage.dtype<<'\t'<<stage.rows<<'\t'<<stage.columns<<'\t'<<stage.bytes.size()<<'\n';}
  std::ofstream requests(directory/"atomic.tsv");for(const auto&r:trace.stats.requests)requests<<r.role<<'\t'<<r.expert<<'\t'<<r.type<<'\t'<<r.rows<<'\t'<<r.k<<'\t'<<r.batch<<'\t'<<r.source.source.original_path.generic_string()<<'\t'<<r.source_absolute_offset<<'\t'<<r.packed<<'\t'<<r.input<<'\t'<<r.output<<'\t'<<r.owned_device<<'\n';
  peak_matrix=std::max(peak_matrix,trace.stats.matrix_owned_peak);peak_scratch=std::max(peak_scratch,trace.stats.actual_scratch_peak);
  if(!first_job)summaries<<",";first_job=false;summaries<<"{\"name\":\""<<escaped(job[0])<<"\",\"stages\":"<<trace.stages.size()<<",\"matrix_owned_peak\":"<<trace.stats.matrix_owned_peak<<",\"actual_scratch_peak\":"<<trace.stats.actual_scratch_peak<<",\"host_matrix_scope_peak\":"<<trace.stats.host_matrix_scope_peak<<",\"trace_payload_bytes\":"<<trace.stats.trace_payload_bytes<<",\"cleanup_unknown\":"<<(trace.stats.cleanup_unknown?"true":"false")<<"}";
 }
 summaries<<"]";check(hipDeviceSynchronize());auto memory_after_status=hipMemGetInfo(&free_after,&total_after);HMODULE modules[1024];DWORD needed=0;if(!EnumProcessModules(GetCurrentProcess(),modules,sizeof(modules),&needed)||needed>sizeof(modules))throw std::runtime_error("loaded modules");
 std::cout<<"{\"source_id\":\""<<T11_SOURCE_ID<<"\",\"pci\":\""<<argv[2]<<"\",\"arch\":\""<<prop.gcnArchName<<"\",\"jobs\":"<<summaries.str()<<",\"matrix_owned_peak\":"<<peak_matrix<<",\"actual_scratch_peak\":"<<peak_scratch<<",\"source_qualified\":false,\"allocator_context_physical\":null,\"loaded_modules\":[";
 for(unsigned i=0;i<needed/sizeof(HMODULE);++i){char p[32768];if(!GetModuleFileNameA(modules[i],p,sizeof(p)))throw std::runtime_error("module path");if(i)std::cout<<",";std::cout<<"\""<<escaped(p)<<"\"";}std::cout<<"],\"hip_memory_before_status\":"<<int(memory_before_status)<<",\"hip_free_before\":";if(memory_before_status==hipSuccess)std::cout<<free_before;else std::cout<<"null";std::cout<<",\"hip_total_before\":";if(memory_before_status==hipSuccess)std::cout<<total_before;else std::cout<<"null";std::cout<<",\"hip_memory_after_status\":"<<int(memory_after_status)<<",\"hip_free_after\":";if(memory_after_status==hipSuccess)std::cout<<free_after;else std::cout<<"null";std::cout<<",\"hip_total_after\":";if(memory_after_status==hipSuccess)std::cout<<total_after;else std::cout<<"null";std::cout<<"}";return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<std::endl;return 2;}}
