#include "producer.hpp"
#include "core.hpp"
#include "prefix_state.hpp"
#include "../../native/cache/secondary_cache.hpp"
#include "execution/expert_assist.hpp"
#include "execution/layer_split.hpp"
#include "../../native/protocol/generation.hpp"
#include "dspark/draft.hpp"
#include "dspark/session.hpp"
#include <climits>
#include <hip/hip_runtime.h>
#define NOMINMAX
#include <Windows.h>
#include <bcrypt.h>
#include <dxgi1_4.h>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstring>
#include <iostream>
#include <iomanip>
#include <limits>
#include <fstream>
#include <map>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <thread>
#include <set>
#include <exception>
#include <new>
#include <strata/core/device.hpp>
namespace strata_ext::deepseek41 {
#ifdef STRATA_T28_CONSTRUCTION_TEST
void t46_expert_startup_result(std::exception_ptr,bool,std::exception_ptr);
#endif
namespace {
constexpr const char*revision="f924b94f19c1fea02c06a65c8475b0a45e2b88b1";
struct SourceSpec {uint64_t bytes;const char*name;const char*sha;};
const SourceSpec source_specs[]={
 {5780589ULL,"DeepSeek-V4.1-Flash-1017-UD-Q4_K_XL-00001-of-00009.gguf","cc15d470afcb030558bbc4d8e2ccd840182e2e95de1a95198138efe63a5fd99f"},
 {48129640000ULL,"DeepSeek-V4.1-Flash-1017-UD-Q4_K_XL-00002-of-00009.gguf","17df217d8fc26a39f21ea40805dc6ab788c7ce8623a59a95c431051df7eafc94"},
 {48129640000ULL,"DeepSeek-V4.1-Flash-1017-UD-Q4_K_XL-00003-of-00009.gguf","0c8065f620a049cb437024c54ff12c314c94603a1cc683f5191be4689d6d6d3b"},
 {48129640000ULL,"DeepSeek-V4.1-Flash-1017-UD-Q4_K_XL-00004-of-00009.gguf","3bd8b2ebf8f51d8708a73ae0895f8d4acc7e4c983ba4e89d038492b203cc89ac"},
 {48129640000ULL,"DeepSeek-V4.1-Flash-1017-UD-Q4_K_XL-00005-of-00009.gguf","929054a6bbf3701765779b58c37988b6c6284a3b8413901858b59c0e95f37cc3"},
 {48129640000ULL,"DeepSeek-V4.1-Flash-1017-UD-Q4_K_XL-00006-of-00009.gguf","49d3de04bd6a09de786c9ef7db900eae02ee9fd391573f91a923013d7d5b24d3"},
 {48129640000ULL,"DeepSeek-V4.1-Flash-1017-UD-Q4_K_XL-00007-of-00009.gguf","f18feae5878dd680f1ea87ecd1d84f4fb098480298b25a3162dcbdab8dc2ca5b"},
 {202758032592ULL,"DeepSeek-V4.1-Flash-1017-UD-Q4_K_XL-00008-of-00009.gguf","12df293355efbd104b088a77e13ee22410fb1ec3f7ab3863947f09896e64bec7"},
 {9165923392ULL,"DeepSeek-V4.1-Flash-1017-UD-Q4_K_XL-00009-of-00009.gguf","c21ad6105a780bc2f44eb7dd41f9b1a1efb4e8ec87618f60b733bc2652bd2ffe"},
};
void need(bool b,const char*m){if(!b)throw std::runtime_error(m);}
void hip(hipError_t s){if(s!=hipSuccess)throw std::runtime_error(hipGetErrorString(s));}
uint64_t add(uint64_t a,uint64_t b){need(b<=UINT64_MAX-a,"budget overflow");return a+b;}
uint64_t mul(uint64_t a,uint64_t b){need(!a||b<=UINT64_MAX/a,"budget multiplication overflow");return a*b;}
uint64_t align(uint64_t x){return add(x,255)&~uint64_t(255);}
std::string quote(const std::string&s){std::string o="\"";const char*h="0123456789abcdef";for(unsigned char c:s){if(c=='"'||c=='\\'){o+='\\';o+=c;}else if(c<32){o+="\\u00";o+=h[c>>4];o+=h[c&15];}else o+=c;}return o+'"';}
uint64_t number(const std::string&s){need(!s.empty()&&s.find_first_not_of("0123456789")==std::string::npos,"unsigned integer syntax");size_t n=0;auto v=std::stoull(s,&n);need(n==s.size(),"integer trailing bytes");return v;}
double real(const std::string&s){size_t n=0;double x=std::stod(s,&n);need(n==s.size()&&std::isfinite(x),"finite real syntax");return x;}
std::string modules(){std::string out="{";bool first=true;for(const wchar_t*name:{L"amdhip64_7.dll",L"amd_comgr.dll",L"rocm_kpack.dll"}){if(!first)out+=',';first=false;auto key=std::filesystem::path(name).u8string();out+=quote(key)+':';auto handle=GetModuleHandleW(name);wchar_t path[32768]{};auto n=handle?GetModuleFileNameW(handle,path,32768):0;out+=n&&n<32768?quote(std::filesystem::path(path).u8string()):"null";}return out+'}';}
std::vector<uint32_t> ids(const std::string&s){std::vector<uint32_t>out;std::istringstream f(s);std::string item;while(std::getline(f,item,',')){auto id=number(item);need(id<129280,"original token outside vocabulary");out.push_back(uint32_t(id));}need(!out.empty()&&s.back()!=',',"empty original prompt");return out;}
Artifact load(const ProducerConfig&c){
 SourceSet source;source.root=c.artifact_root;std::vector<artifact::PrefixIndex> indexes;
 need(c.native_paths.empty()||c.native_paths.size()==9,"nine ordered original paths required");
 std::set<std::filesystem::path>unique;std::filesystem::path first;
 for(size_t i=0;i<9;++i){auto p=c.native_paths.empty()?c.artifact_root/source_specs[i].name:c.native_paths[i];need(p.is_absolute()&&p.filename()==source_specs[i].name&&unique.insert(p.lexically_normal()).second,"original path/order identity");need(std::filesystem::file_size(p)==source_specs[i].bytes,"original source size");if(first.empty())first=p;source.files.push_back({uint32_t(i+1),p,source_specs[i].bytes,revision,source_specs[i].sha});indexes.push_back(artifact::inspect_prefix(p,source_specs[i].bytes));}
 return Artifact(artifact::merge_prefixes(indexes),inspect_metadata(first),std::move(source));
}
struct Available {std::optional<uint64_t>device,host;int hip_status=-1,luid_status=-1;long binding_status=E_FAIL,local_status=E_FAIL;};
Available available(int dev){Available o;size_t free=0,total=0;o.hip_status=int(hipMemGetInfo(&free,&total));if(!o.hip_status)o.device=free;
 char raw[8]{};unsigned mask=0;o.luid_status=int(hipDeviceGetLuid(raw,&mask,dev));if(!o.luid_status){LUID luid;std::memcpy(&luid,raw,8);IDXGIFactory4*f=nullptr;o.binding_status=CreateDXGIFactory1(__uuidof(IDXGIFactory4),reinterpret_cast<void**>(&f));if(SUCCEEDED(o.binding_status)){IDXGIAdapter3*a=nullptr;o.binding_status=f->EnumAdapterByLuid(luid,__uuidof(IDXGIAdapter3),reinterpret_cast<void**>(&a));if(SUCCEEDED(o.binding_status)){DXGI_QUERY_VIDEO_MEMORY_INFO m{};o.local_status=a->QueryVideoMemoryInfo(0,DXGI_MEMORY_SEGMENT_GROUP_LOCAL,&m);if(SUCCEEDED(o.local_status)){uint64_t n=m.Budget>m.CurrentUsage?m.Budget-m.CurrentUsage:0;o.device=o.device?std::min(*o.device,n):n;}a->Release();}f->Release();}}
 MEMORYSTATUSEX m{};m.dwLength=sizeof(m);if(GlobalMemoryStatusEx(&m))o.host=m.ullAvailPhys;(void)hipGetLastError();return o;}
struct Counts{size_t weight=1,row=1;uint64_t bytes=0,unused=0;};
Counts counts(uint64_t target,uint64_t weight,double row_fraction,bool explicit_budget=false){Counts x;need(target>=weight+264,"explicit cache payload below required working minimum");if(explicit_budget){x.weight=x.row=size_t(target/(weight+264));x.bytes=mul(x.weight,weight+264);x.unused=target-x.bytes;return x;}uint64_t extra=target-weight-264;uint64_t row_extra=uint64_t(std::floor(double(extra)*row_fraction));x.row=size_t(1+row_extra/264);x.weight=size_t(1+(extra-row_extra)/weight);x.bytes=add(mul(x.weight,weight),mul(x.row,264));x.unused=target-x.bytes;return x;}
uint64_t ratio_floor(uint64_t value,uint64_t numerator,uint64_t denominator){need(denominator&&numerator<=denominator,"mode budget fraction");return add(mul(value/denominator,numerator),mul(value%denominator,numerator)/denominator);}
uint64_t fraction_floor(uint64_t value,double fraction){need(std::isfinite(fraction)&&fraction>=0&&fraction<=1,"mode auto fraction");if(fraction==0)return 0;if(fraction==1)return value;auto product=std::floor(double(value)*fraction);need(product>=0&&product<18446744073709551616.0,"mode auto fraction range");return std::min(value,uint64_t(product));}
Counts role_counts(uint64_t target,uint64_t weight,bool has_rows,double row_fraction,bool explicit_budget){
 need(weight&&std::isfinite(row_fraction)&&row_fraction>=0&&row_fraction<=1,"role cache unit/fraction");
 auto minimum=add(weight,has_rows?264:0);need(target>=minimum,"role cache below working minimum");Counts result;uint64_t weights=1,rows=has_rows?1:0;
 if(explicit_budget){weights=target/minimum;rows=has_rows?weights:0;}
 else{auto extra=target-minimum,row_extra=has_rows?fraction_floor(extra,row_fraction):0;weights=add(1,(extra-row_extra)/weight);if(has_rows)rows=add(1,row_extra/264);}
 need(weights<=SIZE_MAX&&rows<=SIZE_MAX,"role slot range");result.weight=size_t(weights);result.row=size_t(rows);result.bytes=add(mul(weights,weight),mul(rows,264));result.unused=target-result.bytes;return result;
}
struct ModeRam {Counts primary,secondary;uint64_t minimum=0,total=0,extra_primary=0,extra_secondary=0,unused=0;};
ModeRam mode_ram(uint64_t total,uint64_t primary_weight,bool primary_rows,uint64_t secondary_weight,bool secondary_rows,uint64_t secondary_part,uint64_t whole,double row_fraction,bool explicit_budget){
 ModeRam result;auto p=add(primary_weight,primary_rows?264:0),s=add(secondary_weight,secondary_rows?264:0);result.minimum=add(p,s);need(total>=result.minimum,"all-role RAM payload below working minimum");result.total=total;auto extra=total-result.minimum;result.extra_secondary=ratio_floor(extra,secondary_part,whole);result.extra_primary=extra-result.extra_secondary;
 result.primary=role_counts(add(p,result.extra_primary),primary_weight,primary_rows,row_fraction,explicit_budget);result.secondary=role_counts(add(s,result.extra_secondary),secondary_weight,secondary_rows,row_fraction,explicit_budget);result.unused=total-add(result.primary.bytes,result.secondary.bytes);return result;
}
std::vector<uint32_t> expert_ids(const std::string&value){
 need(!value.empty()&&value.back()!=',',"nonempty secondary expert assignment");std::vector<uint32_t> result;std::set<uint32_t> seen;std::istringstream input(value);std::string part;
 while(std::getline(input,part,',')){auto id=number(part);need(id<384&&seen.insert(uint32_t(id)).second,"secondary expert range/duplicate");result.push_back(uint32_t(id));}return result;
}
void mode_options(const ProducerConfig&c){
 need(c.mode=="single"||c.mode=="cache-only"||c.mode=="expert-assist"||c.mode=="layer-split","known execution mode");
 if(c.mode=="expert-assist"){need(c.secondary_experts&& !c.secondary_experts->empty()&&!c.layer_cut,"expert assignment required / layer cut in other mode");std::set<uint32_t> seen;for(auto id:*c.secondary_experts)need(id<384&&seen.insert(id).second,"secondary expert range/duplicate");}
 else need(!c.secondary_experts,"expert assignment in other mode");
 if(c.mode=="layer-split")need(c.layer_cut&&*c.layer_cut>=1&&*c.layer_cut<=39,"layer cut 1..39 required");else need(!c.layer_cut,"layer cut in other mode");
 if(c.mode=="expert-assist"||c.mode=="layer-split")need(!c.secondary_pci.empty()&&c.secondary_pci!=c.primary_pci,"compute mode requires distinct secondary PCI");
}
#ifdef STRATA_T28_CONSTRUCTION_TEST
int mode_policy_test(){
 uint64_t checks=0;auto check=[&](bool value){need(value,"mode policy CPU expectation");++checks;};auto rejects=[&](auto action){bool caught=false;try{action();}catch(const std::exception&){caught=true;}check(caught);};
 check(ratio_floor(UINT64_MAX,0,384)==0);check(ratio_floor(UINT64_MAX,384,384)==UINT64_MAX);check(ratio_floor(UINT64_MAX,192,384)==UINT64_MAX/2);check(fraction_floor(UINT64_MAX,1)==UINT64_MAX);check(fraction_floor(UINT64_MAX,0)==0);
 for(unsigned cut:{1u,2u,14u,15u,24u,39u}){bool pr=cut>1,sr=cut<=14;auto minimum=uint64_t(1024+2048+(pr?264:0)+(sr?264:0));auto result=mode_ram(minimum,1024,pr,2048,sr,40-cut,40,1.0/64,true);check(result.minimum==minimum&&result.primary.weight==1&&result.secondary.weight==1&&result.primary.row==unsigned(pr)&&result.secondary.row==unsigned(sr)&&result.unused==0);}
 auto explicit_split=mode_ram(23336,1024,true,2048,false,192,384,1.0/64,true);check(explicit_split.extra_primary==10000&&explicit_split.extra_secondary==10000&&explicit_split.primary.weight==8&&explicit_split.primary.row==8&&explicit_split.secondary.weight==5&&explicit_split.secondary.row==0&&explicit_split.unused==2792);
 auto auto_split=mode_ram(23336,1024,true,2048,false,192,384,1.0/64,false);check(auto_split.primary.weight==10&&auto_split.primary.row==1&&auto_split.secondary.weight==5&&auto_split.secondary.row==0&&auto_split.unused==2592);
 auto all_primary=mode_ram(10000,1024,false,2048,false,0,384,0,true);check(all_primary.extra_secondary==0&&all_primary.secondary.weight==1);auto all_secondary=mode_ram(10000,1024,false,2048,false,384,384,0,true);check(all_secondary.extra_primary==0&&all_secondary.primary.weight==1);
 rejects([&]{mode_ram(1,1024,true,2048,false,192,384,0,true);});rejects([&]{mode_ram(UINT64_MAX,UINT64_MAX,true,1,false,1,2,0,true);});rejects([&]{ratio_floor(1,2,1);});rejects([&]{role_counts(4096,1024,true,-1,false);});
 check(expert_ids("0,37,383")==std::vector<uint32_t>({0,37,383}));for(const auto&bad:{"","0,","0,,1","-1","384","0,0","+1","1.0"})rejects([&]{expert_ids(bad);});
 ProducerConfig config;config.primary_pci="0000:07:00.0";config.secondary_pci="0000:03:00.0";mode_options(config);++checks;config.mode="expert-assist";rejects([&]{mode_options(config);});config.secondary_experts=std::vector<uint32_t>{0,383};mode_options(config);++checks;config.secondary_experts=std::vector<uint32_t>{};rejects([&]{mode_options(config);});config.secondary_experts.reset();config.mode="layer-split";for(auto cut:{1u,24u,39u}){config.layer_cut=cut;mode_options(config);++checks;}for(auto cut:{0u,40u}){config.layer_cut=cut;rejects([&]{mode_options(config);});}config.layer_cut=24;config.secondary_pci=config.primary_pci;rejects([&]{mode_options(config);});
 std::cout<<"{\"assertions\":"<<checks<<",\"GPU_used\":false,\"zero_assignment_scope\":\"budget arithmetic only; public assignment remains nonempty\"}\n";return 0;
}
#endif
measurement::Identity identity(const ProducerConfig&c,const std::string&id){return {c.bundle_id,c.bundle_id,c.bundle_id,id,c.runtime_epoch,measurement::Phase::Prefill};}
// Keep these EH classifiers out of caller catch funclets: the fixed clang O2/O3
// inliner traps on the controlled custom exception_ptr rethrow (CPU reproducer).
[[clang::noinline]]bool construction_unknown(const std::exception_ptr&e){try{std::rethrow_exception(e);}catch(const cache::SecondaryConstructionUnknown&){return true;}catch(const std::exception&x){return std::strstr(x.what(),"construction completion unknown")!=nullptr;}catch(...){return false;}}
[[clang::noinline]]bool construction_allocation(const std::exception_ptr&e){
 try{std::rethrow_exception(e);}
 catch(const cache::SecondaryConstructionUnknown&){return false;}
 catch(const strata::core::CudaError&x){return x.code()==int(hipErrorOutOfMemory);}
 catch(const std::bad_array_new_length&){return false;}
 catch(const std::bad_alloc&){return true;}
 catch(const std::exception&x){const char*message=x.what();return std::strcmp(message,hipGetErrorString(hipErrorOutOfMemory))==0||std::strcmp(message,"I/O buffer allocation")==0||std::strcmp(message,"row IO allocation")==0;}
 catch(...){return false;}
}
bool reduce_auto_allocation(const std::exception_ptr&e,bool device_auto,bool ram_auto,uint64_t minimum,uint64_t&dt,uint64_t&ht){
 if(construction_unknown(e)||!construction_allocation(e))return false;
 bool reduced=false;if(device_auto&&dt>minimum){dt=minimum+(dt-minimum)/2;reduced=true;}if(ram_auto&&ht>minimum){ht=minimum+(ht-minimum)/2;reduced=true;}return reduced;
}
bool reduce_mode_allocation(const std::exception_ptr&error,bool p_auto,bool s_auto,bool ram_auto,uint64_t p_min,uint64_t s_min,uint64_t&dp,uint64_t&ds,uint64_t&rt){
 auto minimum=add(p_min,s_min);need(dp>=p_min&&ds>=s_min&&rt>=minimum,"valid mode retry targets");if(construction_unknown(error)||!construction_allocation(error))return false;bool reduced=false;auto shrink=[&](uint64_t&value,uint64_t floor,bool automatic){if(automatic&&value>floor){value=floor+(value-floor)/2;reduced=true;}};shrink(dp,p_min,p_auto);shrink(ds,s_min,s_auto);shrink(rt,minimum,ram_auto);return reduced;
}
#ifdef STRATA_T28_CONSTRUCTION_TEST
int mode_failure_test(){
 uint64_t checks=0;auto check=[&](bool value){if(!value)throw std::runtime_error("mode failure classification CPU expectation "+std::to_string(checks));++checks;};auto oom=std::make_exception_ptr(std::bad_alloc{}),other=std::make_exception_ptr(std::runtime_error("controlled source geometry")),cleanup_oom=std::make_exception_ptr(strata::core::CudaError("controlled cleanup OOM",int(hipErrorOutOfMemory)));
 auto result=[&](std::exception_ptr initial,bool closed,std::exception_ptr cleanup){try{t46_expert_startup_result(initial,closed,cleanup);}catch(...){return std::current_exception();}throw std::runtime_error("startup failure unexpectedly returned");};
 for(auto initial:{oom,other}){auto error=result(initial,true,{});bool preserved=false;try{std::rethrow_exception(error);}catch(const std::bad_alloc&){preserved=initial==oom;}catch(const std::runtime_error&value){preserved=initial==other&&std::string(value.what())=="controlled source geometry";}check(preserved&&!construction_unknown(error));check(construction_allocation(error)==(initial==oom));}
 for(auto cleanup:{std::exception_ptr{},other,cleanup_oom})for(bool closed:{false,true}){
  if(closed&&!cleanup)continue;auto error=result(oom,closed,cleanup);check(construction_unknown(error)&&!construction_allocation(error));try{std::rethrow_exception(error);}catch(const cache::SecondaryConstructionUnknown&unknown){check(unknown.initialization_error()==oom&&unknown.cleanup_error()==cleanup);}uint64_t p=120,s=240,r=390;check(!reduce_mode_allocation(error,true,true,true,100,200,p,s,r)&&p==120&&s==240&&r==390);
 }
 uint64_t p=120,s=240,r=390;check(reduce_mode_allocation(oom,true,true,true,100,200,p,s,r)&&p==110&&s==220&&r==345);p=120;s=240;r=390;check(!reduce_mode_allocation(oom,false,false,false,100,200,p,s,r)&&p==120&&s==240&&r==390);check(!reduce_mode_allocation(other,true,true,true,100,200,p,s,r)&&p==120&&s==240&&r==390);check(reduce_mode_allocation(oom,false,true,false,100,200,p,s,r)&&p==120&&s==220&&r==390);
 std::cout<<"{\"assertions\":"<<checks<<",\"GPU_used\":false,\"actual_driver_failure\":false,\"production_startup_result_helper\":true,\"owned_causes\":true}\n";return 0;
}
#endif
struct OnDevice {int previous=-1;explicit OnDevice(int device){hip(hipGetDevice(&previous));hip(hipSetDevice(device));}~OnDevice(){if(previous>=0)hipSetDevice(previous);}};
// Owns only the two existing compute components and their supplies. Mathematical
// execution stays in CoreSequence/ExpertAssist/LayerSplit, without a new executor.
struct ComputeOwners {
 const Artifact&artifact;const engram::Config&engram;ProducerConfig config;device::Roles roles;
 std::unique_ptr<cache::PrimarySupply>weight,secondary_weight;std::unique_ptr<cache::RowSupply>rows,secondary_rows;
 std::unique_ptr<ExpertAssist>experts;std::unique_ptr<CoreSequence>core;std::unique_ptr<LayerSplit>split;
 Counts pd,sd;ModeRam ram;Available p_available,s_available;uint64_t graph_generation=0,secondary_graph_generation=0,dp=0,ds=0,rt=0,minimum_p=0,minimum_s=0,deferred_p=0,deferred_s=0,deferred_host=0,attempts=0;double construction_ms=0;
 bool is_split()const{return config.mode=="layer-split";}
 bool p_rows()const{return !is_split()||*config.layer_cut>1;}
 bool s_rows()const{return is_split()&&*config.layer_cut<=14;}
 uint64_t share()const{return is_split()?40-*config.layer_cut:config.secondary_experts->size();}
 uint64_t whole()const{return is_split()?40:384;}
 CoreConfig cc(int device)const{CoreConfig c;c.device=device;c.tile_bytes=config.tile_bytes;c.tile_rows=config.tile_rows;c.active_batch=config.active_batch;return c;}
 uint64_t constants(unsigned first,unsigned end,bool head)const{
  std::set<std::string>names;if(head)names.insert("output_norm.weight");for(unsigned layer=first;layer<end;++layer){auto p="blk."+std::to_string(layer)+".";for(auto n:{"hc_attn_scale.weight","hc_attn_base.weight","attn_norm.weight","hc_ffn_scale.weight","hc_ffn_base.weight","ffn_norm.weight","attn_q_a_norm.weight","attn_kv_a_norm.weight","attn_sinks.weight","exp_probs_b.bias","exp_probs_b_vl.bias"})names.insert(p+n);if(layer==1||layer==14)names.insert(p+"engram_gate.weight");if(layer==2||layer==8||layer==14||layer==20){names.insert(p+"attn_compressor_norm.weight");names.insert(p+"indexer.k_norm.weight");}}
  uint64_t bytes=0;for(const auto&name:names)bytes=add(bytes,artifact.source_tensor(name).span.bytes);return bytes;
 }
 void make_core(const std::string&id){
  OnDevice current(roles.primary.ordinal);auto primary=cc(roles.primary.ordinal);
  if(is_split()){LayerSplitConfig c;c.roles=roles;c.cut=*config.layer_cut;c.transfer_bytes=config.tile_bytes;c.primary=primary;c.secondary=cc(roles.secondary->ordinal);split=std::make_unique<LayerSplit>(artifact,engram,*weight,rows.get(),*secondary_weight,secondary_rows.get(),identity(config,id),c,config.context);}
  else{primary.experts=experts.get();core=std::make_unique<CoreSequence>(artifact,engram,*weight,*rows,identity(config,id),primary,config.context);}
 }
 void make(const Counts&p,const Counts&s,const ModeRam&h,const std::string&id){
  auto start=std::chrono::steady_clock::now();++attempts;OnDevice current(roles.primary.ordinal);weight=std::make_unique<cache::PrimarySupply>(cache::SupplyConfig{p.weight,h.primary.weight,config.tile_bytes,4,4,roles.primary.ordinal,true,config.projection_graph,STRATA_GRAPH_BUILD_ABI});++graph_generation;
  auto source=artifact.source_tensor("per_layer_token_embd.weight").source;
  if(p_rows())rows=std::make_unique<cache::RowSupply>(cache::RowConfig{p.row,h.primary.row,1,1,roles.primary.ordinal},artifact,cache::RowSourceViews({{source,{source.original_path,0,source.original_size}}}));
  if(is_split()){
   OnDevice secondary(roles.secondary->ordinal);secondary_weight=std::make_unique<cache::PrimarySupply>(cache::SupplyConfig{s.weight,h.secondary.weight,config.tile_bytes,4,4,roles.secondary->ordinal,true,config.projection_graph,STRATA_GRAPH_BUILD_ABI});++secondary_graph_generation;if(s_rows())secondary_rows=std::make_unique<cache::RowSupply>(cache::RowConfig{s.row,h.secondary.row,1,1,roles.secondary->ordinal},artifact,cache::RowSourceViews({{source,{source.original_path,0,source.original_size}}}));
  }else{ExpertAssistConfig c;c.roles=roles;c.secondary_experts=*config.secondary_experts;c.max_batch=config.active_batch;c.secondary_weights={s.weight,h.secondary.weight,config.tile_bytes,4,4,roles.secondary->ordinal,true,config.projection_graph,STRATA_GRAPH_BUILD_ABI};c.secondary_core=cc(roles.secondary->ordinal);experts=std::make_unique<ExpertAssist>(artifact,c);++secondary_graph_generation;}
  make_core(id);construction_ms+=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
 }
 bool drain_role(cache::PrimarySupply*w,cache::RowSupply*r,int device,const measurement::Identity&id){
  OnDevice current(device);if(hipDeviceSynchronize()!=hipSuccess)return false;if(w){if(w->state()!=cache::SupplyState::Idle)w->cancel();if(w->prefetch_state()!=cache::SupplyState::Idle)w->cancel_prefetch();}auto tokens=r?r->cancel_all():std::vector<cache::Token>{};
  for(;;){if(w){w->poll_io(10);w->poll_device();auto state=w->state();if(state==cache::SupplyState::Quarantined)return false;if(state==cache::SupplyState::Cancelled||state==cache::SupplyState::Done){try{(void)w->take_device(id);}catch(const std::exception&){(void)w->take(id);}}if(w->prefetch_state()==cache::SupplyState::Cancelled||w->prefetch_state()==cache::SupplyState::Done)(void)w->take_prefetch(id);}if(r){r->poll_io(0);r->poll_device();for(auto i=tokens.begin();i!=tokens.end();){auto state=r->state(*i);if(state==cache::RowState::Cancelled||state==cache::RowState::Done){(void)r->take(*i,id);i=tokens.erase(i);}else ++i;}}
   if((!w||w->state()==cache::SupplyState::Idle&&w->prefetch_state()==cache::SupplyState::Idle)&&tokens.empty()&&(!r||!r->fill_pending()))return true;std::this_thread::yield();}
 }
 bool drain(const std::string&id){if(split){if(split->request_valid())split->quiesce();else split->cancel_and_drain();}if(experts)experts->drain();return drain_role(weight.get(),rows.get(),roles.primary.ordinal,identity(config,id))&&(!secondary_weight||drain_role(secondary_weight.get(),secondary_rows.get(),roles.secondary->ordinal,identity(config,id)));}
 bool clear(const std::string&id){
  if(!drain(id))return false;if(core&&!core->retire_projection_graph())return false;if(experts)experts->cancel_and_drain(nullptr);if(split&&!split->retire_projection_graphs())return false;if(split){if(!split->try_close())return false;split.reset();}core.reset();experts.reset();
  {OnDevice current(roles.secondary->ordinal);if(secondary_rows){if(!secondary_rows->try_close())return false;secondary_rows.reset();}if(secondary_weight){if(!secondary_weight->try_close())return false;secondary_weight.reset();}}
  OnDevice current(roles.primary.ordinal);if(rows){if(!rows->try_close())return false;rows.reset();}if(weight){if(!weight->try_close())return false;weight.reset();}return true;
 }
 void retain(){(void)split.release();(void)core.release();(void)experts.release();(void)secondary_rows.release();(void)secondary_weight.release();(void)rows.release();(void)weight.release();}
 ComputeOwners(const Artifact&a,const engram::Config&e,ProducerConfig c):artifact(a),engram(e),config(std::move(c)),roles(device::resolve(device::inventory(),config.primary_pci,config.secondary_pci)){
  mode_options(config);need(config.context&&config.context<=1048576&&config.runtime_epoch&&config.tile_bytes&&config.tile_rows&&config.active_batch,"normal compute context/identity/window");need(std::isfinite(config.auto_cache_fraction)&&config.auto_cache_fraction>=0&&config.auto_cache_fraction<=1&&std::isfinite(config.auto_row_fraction)&&config.auto_row_fraction>=0&&config.auto_row_fraction<=1,"auto fractions in [0,1]");for(const auto&t:a.tensors())if(t.type_id!=0)need(t.row_bytes<=config.tile_bytes,"one full-K row exceeds selected finite tile");
  minimum_p=add(config.tile_bytes,p_rows()?264:0);minimum_s=add(config.tile_bytes,s_rows()?264:0);deferred_host=add(add(add(mul(129280,4+8+4+8+4+8),mul(config.context,8)),20*8),config.dspark_deferred_host_bytes);if(is_split()){deferred_p=constants(0,*config.layer_cut,false);deferred_s=constants(*config.layer_cut,40,true);}else deferred_p=constants(0,40,true);if(!config.dspark_draft.empty()){deferred_p=add(deferred_p,is_split()?122880:61440);if(is_split()){deferred_s=add(deferred_s,61440);deferred_host=add(deferred_host,20480);}}
  try{
   auto min_ram=mode_ram(add(minimum_p,minimum_s),config.tile_bytes,p_rows(),config.tile_bytes,s_rows(),share(),whole(),config.auto_row_fraction,true);auto p=role_counts(minimum_p,config.tile_bytes,p_rows(),0,true),s=role_counts(minimum_s,config.tile_bytes,s_rows(),0,true);make(p,s,min_ram,"startup-measurement");{OnDevice current(roles.primary.ordinal);p_available=available(roles.primary.ordinal);}{OnDevice current(roles.secondary->ordinal);s_available=available(roles.secondary->ordinal);}
   auto target=[&](std::optional<uint64_t>explicit_bytes,std::optional<uint64_t>free,uint64_t deferred,uint64_t minimum){if(explicit_bytes)return *explicit_bytes;return add(minimum,fraction_floor(free&&*free>deferred?*free-deferred:0,config.auto_cache_fraction));};dp=target(config.device_cache_payload_bytes,p_available.device,deferred_p,minimum_p);ds=target(config.secondary_device_cache_payload_bytes,s_available.device,deferred_s,minimum_s);rt=target(config.ram_cache_payload_bytes,p_available.host,deferred_host,add(minimum_p,minimum_s));need(clear("startup-measurement"),"construction completion unknown: measurement compute owner");
   for(;;){pd=role_counts(dp,config.tile_bytes,p_rows(),config.auto_row_fraction,config.device_cache_payload_bytes.has_value());sd=role_counts(ds,config.tile_bytes,s_rows(),config.auto_row_fraction,config.secondary_device_cache_payload_bytes.has_value());ram=mode_ram(rt,config.tile_bytes,p_rows(),config.tile_bytes,s_rows(),share(),whole(),config.auto_row_fraction,config.ram_cache_payload_bytes.has_value());try{make(pd,sd,ram,"startup-final");break;}catch(...){auto error=std::current_exception();if(construction_unknown(error)){retain();std::rethrow_exception(error);}bool complete=false;std::exception_ptr cleanup;try{complete=clear("startup-final");}catch(...){cleanup=std::current_exception();}if(!complete||cleanup){retain();throw cache::SecondaryConstructionUnknown(error,cleanup);}if(!reduce_mode_allocation(error,!config.device_cache_payload_bytes,!config.secondary_device_cache_payload_bytes,!config.ram_cache_payload_bytes,minimum_p,minimum_s,dp,ds,rt))std::rethrow_exception(error);}}
  }catch(...){auto error=std::current_exception();if(construction_unknown(error)){retain();std::rethrow_exception(error);}bool complete=false;std::exception_ptr cleanup;try{complete=clear("startup-failure");}catch(...){cleanup=std::current_exception();}if(!complete||cleanup){retain();throw cache::SecondaryConstructionUnknown(error,cleanup);}std::rethrow_exception(error);}
 }
 ~ComputeOwners(){try{if(!clear("shutdown"))retain();}catch(...){retain();}}
 void request(const std::string&id){need(drain(id),"previous compute owner operation not drained");need(!core||core->retire_projection_graph(),"compute graph activation retirement unknown");if(experts)experts->cancel_and_drain(nullptr);if(split)need(split->retire_projection_graphs(),"partition graph activation retirement unknown");if(split){need(split->try_close(),"previous split close unknown");split.reset();}core.reset();make_core(id);}
 CoreOutput prefill(const std::vector<uint32_t>&tokens,const PrefillControl&control,uint64_t start=0){return split?split->prefill(tokens,start,{},control):core->prefill(tokens,start,{},control);}
 void continue_request(const std::string&id){if(split)split->continue_request(identity(config,id),position());else core->continue_request(identity(config,id),position());}
 bool request_valid()const noexcept{return split?split->request_valid():core&&core->request_valid();}
 void quiesce(){if(experts)experts->drain();if(split)split->quiesce();else core->quiesce();}
 void invalidate_math(){if(split)split->cancel_and_drain();else core->invalidate_and_drain();if(experts){experts->drain();experts->cancel_and_drain(nullptr);}}
 uint64_t position()const{return split?split->position():core->position();}
 std::vector<float>step(uint32_t token){return split?split->step(token,position()):core->step(token,position());}
 CoreRuntimeStats runtime_stats()const{
  if(core)return core->runtime_stats();auto s=split->stats();auto out=s.primary;out.storage_device_owned=add(out.storage_device_owned,s.secondary.storage_device_owned);out.constant_source_bytes=add(out.constant_source_bytes,s.secondary.constant_source_bytes);out.storage_upload_bytes=add(out.storage_upload_bytes,s.secondary.storage_upload_bytes);out.requested_output_or_fixture_download_bytes=add(out.requested_output_or_fixture_download_bytes,s.secondary.requested_output_or_fixture_download_bytes);out.route_metadata_bytes=add(out.route_metadata_bytes,s.secondary.route_metadata_bytes);
  for(unsigned layer=*config.layer_cut;layer<40;++layer){out.route_union[layer]=s.secondary.route_union[layer];out.routed_tokens[layer]=s.secondary.routed_tokens[layer];out.state_positions[layer]=s.secondary.state_positions[layer];}unsigned index=0;for(unsigned writer:{2u,8u,14u,20u}){if(writer>=*config.layer_cut){out.compressed_rows[index]=s.secondary.compressed_rows[index];out.key_rows[index]=s.secondary.key_rows[index];}++index;}return out;
 }
 std::string info(uint64_t prefix_host=0)const{
  auto p=weight->stats();auto pr=rows?rows->stats():cache::RowStats{};ExpertAssistStats e;if(experts)e=experts->stats();LayerSplitStats l;if(split)l=split->stats();auto s=experts?e.secondary_weights:secondary_weight->stats();auto sr=secondary_rows?secondary_rows->stats():cache::RowStats{};auto c=runtime_stats();auto primary_owned=split?l.primary_device_owned:add(core->explicit_device_owned(),e.primary_device_owned);auto secondary_owned=split?l.secondary_device_owned:add(e.secondary_workspace_owned,e.secondary_weight_owned);auto bounce=split?l.bounce_host_owned:e.bounce_host_owned;
  auto metadata=add(add(p.metadata,pr.metadata_capacity),add(s.metadata,sr.metadata_capacity));auto host=add(prefix_host,add(add(add(p.host_owned,pr.host_payload),add(s.host_owned,sr.host_payload)),add(metadata,bounce)));std::ostringstream assignment;assignment<<'[';if(config.secondary_experts)for(size_t i=0;i<config.secondary_experts->size();++i){if(i)assignment<<',';assignment<<(*config.secondary_experts)[i];}assignment<<']';
  std::ostringstream o;o<<"{\"family\":\"deepseek41\",\"context\":"<<config.context<<",\"configured_mode\":"<<quote(config.mode)<<",\"effective_mode\":"<<quote(config.mode)<<",\"primary_pci\":"<<quote(roles.primary.pci)<<",\"requested_secondary_pci\":"<<quote(config.secondary_pci)<<",\"actual_secondary_pci\":"<<quote(roles.secondary->pci)<<",\"secondary_experts\":"<<(config.secondary_experts?assignment.str():"null")<<",\"layer_cut\":"<<(config.layer_cut?std::to_string(*config.layer_cut):"null")<<",\"head_role\":"<<quote(is_split()?"secondary":"primary")<<",\"core_position\":"<<position()<<",\"actual_device_owned\":"<<primary_owned<<",\"actual_primary_device_owned\":"<<primary_owned<<",\"actual_secondary_device_owned\":"<<secondary_owned<<",\"actual_all_role_device_owned\":"<<add(primary_owned,secondary_owned)<<",\"owned_host_owner_subset_bytes\":"<<host<<",\"all_known_host_owner_subset_bytes\":"<<host<<",\"owner_metadata_bytes\":"<<metadata<<",\"mode_bounce_host_owned\":"<<bounce;
  o<<",\"device_slots\":"<<pd.weight<<",\"row_device_slots\":"<<pd.row<<",\"secondary_device_slots\":"<<sd.weight<<",\"secondary_row_device_slots\":"<<sd.row<<",\"ram_slots\":"<<ram.primary.weight<<",\"row_ram_slots\":"<<ram.primary.row<<",\"secondary_ram_slots\":"<<ram.secondary.weight<<",\"secondary_row_ram_slots\":"<<ram.secondary.row<<",\"device_cache_payload_bytes\":"<<pd.bytes<<",\"secondary_device_cache_payload_bytes\":"<<sd.bytes<<",\"ram_cache_payload_bytes\":"<<add(ram.primary.bytes,ram.secondary.bytes)<<",\"declared_device_cache_payload_bytes\":"<<(config.device_cache_payload_bytes?std::to_string(*config.device_cache_payload_bytes):"null")<<",\"declared_ram_cache_payload_bytes\":"<<(config.ram_cache_payload_bytes?std::to_string(*config.ram_cache_payload_bytes):"null")<<",\"weight_tile_bytes\":"<<config.tile_bytes<<",\"working_minimum_payload_bytes\":"<<ram.minimum<<",\"mode_ram_target_bytes\":"<<ram.total<<",\"mode_ram_minimum_payload_bytes\":"<<ram.minimum<<",\"mode_ram_extra_primary_bytes\":"<<ram.extra_primary<<",\"mode_ram_extra_secondary_bytes\":"<<ram.extra_secondary<<",\"mode_ram_unused_bytes\":"<<ram.unused<<",\"mode_primary_ram_payload_bytes\":"<<ram.primary.bytes<<",\"mode_secondary_ram_payload_bytes\":"<<ram.secondary.bytes<<",\"resolved_device_cache_target_bytes\":"<<dp<<",\"resolved_secondary_device_cache_target_bytes\":"<<ds<<",\"auto_cache_fraction\":"<<config.auto_cache_fraction<<",\"auto_row_fraction\":"<<config.auto_row_fraction<<",\"construction_attempts\":"<<attempts<<",\"construction_ms\":"<<construction_ms<<",\"measurement_available_device_bytes\":"<<(p_available.device?std::to_string(*p_available.device):"null")<<",\"measurement_available_secondary_device_bytes\":"<<(s_available.device?std::to_string(*s_available.device):"null")<<",\"measurement_available_host_bytes\":"<<(p_available.host?std::to_string(*p_available.host):"null")<<",\"deferred_constant_device\":"<<deferred_p<<",\"deferred_secondary_constant_device\":"<<deferred_s<<",\"deferred_host_sampling\":"<<deferred_host;
  o<<",\"primary_logical_read\":"<<p.weight_read<<",\"primary_h2d\":"<<p.weight_h2d<<",\"primary_aligned_read\":"<<p.aligned_read<<",\"primary_issued_read\":"<<p.issued_read<<",\"primary_issued_reads\":"<<p.issued_reads<<",\"primary_gpu_hits\":"<<p.gpu_hits<<",\"primary_ram_hits\":"<<p.ram_hits<<",\"secondary_logical_read\":"<<s.weight_read<<",\"secondary_h2d\":"<<s.weight_h2d<<",\"secondary_aligned_read\":"<<s.aligned_read<<",\"secondary_issued_read\":"<<s.issued_read<<",\"secondary_issued_reads\":"<<s.issued_reads<<",\"secondary_gpu_hits\":"<<s.gpu_hits<<",\"secondary_ram_hits\":"<<s.ram_hits<<",\"row_logical_read\":"<<pr.logical_read<<",\"secondary_row_logical_read\":"<<sr.logical_read<<",\"requested_logits_or_audit_d2h\":"<<c.requested_output_or_fixture_download_bytes<<",\"core_storage_device_owned\":"<<c.storage_device_owned<<",\"core_constant_source_bytes\":"<<c.constant_source_bytes<<",\"core_storage_upload_bytes\":"<<c.storage_upload_bytes;
  o<<",\"expert_primary_jobs\":"<<e.primary_jobs<<",\"expert_secondary_jobs\":"<<e.secondary_jobs<<",\"expert_adopted\":"<<e.adopted<<",\"expert_cancelled\":"<<e.cancelled<<",\"expert_snapshot_d2d\":"<<e.primary_snapshot_d2d_issued<<",\"layer_boundary_payload\":"<<l.boundary_payload<<",\"layer_new_kv\":"<<l.new_kv<<",\"layer_new_keys\":"<<l.new_keys<<",\"layer_selected_payload\":"<<l.selected<<",\"layer_candidate_payload\":"<<l.candidates<<",\"mode_peer_bytes\":"<<add(e.peer_bytes,l.peer_bytes)<<",\"mode_bounce_d2h\":"<<add(e.bounce_d2h,l.bounce_d2h)<<",\"mode_bounce_h2d\":"<<add(e.bounce_h2d,l.bounce_h2d)<<",\"loaded_runtime_modules\":"<<modules()<<",\"driver_event_private_bytes\":null,\"mode_allocator_overhead_bytes\":null,\"physical_peak\":null}";return o.str();
 }
};
// T38_NORMAL_POLICY_BEGIN
namespace t38=strata_ext::dspark::t38;
bool dspark_enabled(const ProducerConfig&c){return !c.dspark_draft.empty();}
void validate_dspark_config(const ProducerConfig&c){
 need(c.dspark_width>0,"DSpark width must be positive");
 if(!dspark_enabled(c)){need(c.dspark_prefix.empty()&&!c.dspark_draft_credit&&!c.dspark_target_credit,"DSpark configuration without draft");return;}
 need(c.mode=="single"||c.mode=="cache-only"||c.mode=="expert-assist"||c.mode=="layer-split","DSpark normal Actor target mode");
 need(std::filesystem::u8path(c.dspark_draft).is_absolute()&&std::filesystem::u8path(c.dspark_prefix).is_absolute(),"DSpark absolute draft/prefix paths");
 if(c.dspark_draft_credit)need(*c.dspark_draft_credit>0,"DSpark draft credit positive");
 if(c.dspark_target_credit)need(*c.dspark_target_credit>0,"DSpark target credit positive");
}
bool parse_dspark_option(ProducerConfig&c,const std::string&key,const std::string&value){
 if(key=="--dspark-draft")c.dspark_draft=value;
 else if(key=="--dspark-prefix")c.dspark_prefix=value;
 else if(key=="--dspark-draft-credit")c.dspark_draft_credit=number(value);
 else if(key=="--dspark-target-credit")c.dspark_target_credit=number(value);
 else if(key=="--dspark-width")c.dspark_width=number(value);
 else return false;return true;
}
struct DsparkCredits {uint64_t draft=0,target=0,host_deferred=0;};
DsparkCredits dspark_credits(const ProducerConfig&c,const t38::Asset&asset,uint64_t embedding_row,uint64_t head_row){
 uint64_t minimum=0;for(const auto&t:asset.tensors)minimum=std::max(minimum,t.dims.size()==1?std::max(t.row_bytes,t.bytes):t.row_bytes);
 need(minimum&&embedding_row&&head_row,"DSpark native source credit geometry");auto target_minimum=std::max(embedding_row,head_row);
 DsparkCredits r;r.draft=c.dspark_draft_credit.value_or(std::max(c.tile_bytes,minimum));r.target=c.dspark_target_credit.value_or(std::max(c.tile_bytes,target_minimum));
 need(r.draft>=minimum&&r.target>=target_minimum&&r.draft<=SIZE_MAX&&r.target<=SIZE_MAX,"DSpark explicit credit below actual required source span");
 // Existing deferred host already budgets target logits/transforms and two histories.
 // Additional full proposal q, IDs/confidence and per-width temporary scalar controls.
 // Three extra context-sized vectors cover proposal history and E/G ID ledgers.
 // One transient native read tile and extra raw/p/residual coexistence are deferred;
 // provider-owned staging/scratch was already touched before available().
 r.host_deferred=add(add(add(mul(mul(c.dspark_width,129280),8),mul(c.dspark_width,8+4*4+65*8)),std::max(r.draft,r.target)),add(mul(129280,4+8+8),mul(c.context,12)));return r;
}
bool projection_graph_choice(const std::string&value){need(value=="off"||value=="on","projection graph must be off or on");return value=="on";}
std::optional<cache::PrimaryGraphStats> graph_counter_delta(const cache::PrimaryGraphStats&before,const cache::PrimaryGraphStats&after){
 auto delta=after;
#define GRAPH_COUNTER(field) if(after.field<before.field)return {};delta.field=after.field-before.field
 GRAPH_COUNTER(resident_fill_eager);GRAPH_COUNTER(prepare_eager);GRAPH_COUNTER(replayed);GRAPH_COUNTER(activation_scopes);
 GRAPH_COUNTER(module.eager);GRAPH_COUNTER(module.replays);GRAPH_COUNTER(module.captures);GRAPH_COUNTER(module.recaptures);GRAPH_COUNTER(module.capture_fallbacks);
#undef GRAPH_COUNTER
 return delta;
}
std::string graph_counter_json(const cache::PrimaryGraphStats&s){
 std::ostringstream o;o<<"{\"resident_fill_eager\":"<<s.resident_fill_eager<<",\"prepare_eager\":"<<s.prepare_eager<<",\"replayed\":"<<s.replayed<<",\"activation_scopes\":"<<s.activation_scopes<<",\"module_eager\":"<<s.module.eager<<",\"captures\":"<<s.module.captures<<",\"recaptures\":"<<s.module.recaptures<<",\"replays\":"<<s.module.replays<<",\"fallbacks\":"<<s.module.capture_fallbacks<<'}';return o.str();
}
std::string graph_info_json(bool requested,bool applicable,bool observed,uint64_t generation,const char*reason,const std::optional<cache::PrimaryGraphStats>&total,const std::optional<cache::PrimaryGraphStats>&delta,bool tap_selected=false){
 const bool configured=requested&&applicable;std::ostringstream o;
 o<<"{\"requested\":"<<(requested?"true":"false")<<",\"backend_present\":true,\"applicable\":"<<(applicable?"true":"false")<<",\"configured\":"<<(configured?"true":"false")<<",\"reason\":"<<quote(reason)<<",\"observed\":"<<(observed?"true":"false")<<",\"applied_this_request\":"<<(observed&&delta?(delta->replayed?"true":"false"):"null")<<",\"owner_generation\":"<<generation<<",\"tap_callback_count\":null,\"counter_scope\":\"Primary owner generation\",\"source_set_sha256\":"<<quote(T28_SOURCE_ID)<<",\"math_abi\":"<<quote(STRATA_GRAPH_BUILD_ABI)<<",\"adopted_flags\":{\"projection_graph\":"<<(configured?"true":"false")<<",\"normal_observer\":"<<(STRATA_T39_NORMAL_OBSERVER?"true":"false")<<",\"tap_consumer\":"<<(tap_selected?"true":"false")<<"},\"totals\":"<<(total?graph_counter_json(*total):"null")<<",\"request_delta\":"<<(observed&&delta?graph_counter_json(*delta):"null");
 if(total)o<<",\"metadata_upper_bound_bytes\":"<<total->module.metadata_bytes<<",\"aliased_payload_bytes\":"<<total->module.aliased_payload_bytes<<",\"explicit_graph_device_owned_bytes\":"<<total->module.explicit_device_owned_bytes<<",\"hip_internal_bytes\":null";
 else o<<",\"metadata_upper_bound_bytes\":null,\"aliased_payload_bytes\":null,\"explicit_graph_device_owned_bytes\":null,\"hip_internal_bytes\":null";
 o<<'}';return o.str();
}
t38::ActorStop actor_stop(int value){return value==1?t38::ActorStop::Cancel:value==2?t38::ActorStop::RecipeStop:t38::ActorStop::Continue;}
struct ActorFinish {protocol::Finish finish;const char*origin;bool healthy;};
ActorFinish actor_finish(t38::Finish f,int stopped,const std::string&error){
 if(f==t38::Finish::Invalid)return {error.find("nonfinite")!=std::string::npos?protocol::Finish::NonFinite:protocol::Finish::Error,error.find("nonfinite")!=std::string::npos?"nonfinite":"error",false};
 if(stopped==1)return {protocol::Finish::Cancel,"user_cancel",false};
 if(stopped==2||f==t38::Finish::RecipeStop)return {protocol::Finish::Stop,"recipe",false};
 if(f==t38::Finish::Cancel)return {protocol::Finish::Cancel,"user_cancel",false};
 if(f==t38::Finish::Eos)return {protocol::Finish::Stop,"eos",true};
 if(f==t38::Finish::Length)return {protocol::Finish::Length,"limit",true};
 return {protocol::Finish::Error,"error",false};
}
bool retain_actor_owners(bool target_known,bool draft_known,bool network_known,bool cache_known){return !(target_known&&draft_known&&network_known&&cache_known);}

// One DS completion boundary: diagnostic transport cannot bypass owner finish.
class ActorCompletionFailure final:public std::runtime_error {
 std::exception_ptr completion_,diagnostic_;std::string actor_error_;
 static std::string message(const std::exception_ptr&error){try{std::rethrow_exception(error);}catch(const std::exception&e){return std::string("Actor completion failure: ")+e.what();}catch(...){return "Actor completion failure: non-standard exception";}}
public:
 ActorCompletionFailure(std::exception_ptr completion,std::exception_ptr diagnostic,std::string actor_error):std::runtime_error(message(completion)),completion_(std::move(completion)),diagnostic_(std::move(diagnostic)),actor_error_(std::move(actor_error)){}
 const std::exception_ptr&completion_error()const noexcept{return completion_;}
 const std::exception_ptr&diagnostic_error()const noexcept{return diagnostic_;}
 const std::string&actor_error()const noexcept{return actor_error_;}
};
template<class Emit,class Finish>bool finish_actor_boundary(bool invalid,const std::string&actor_error,Emit&&emit,Finish&&finish){
 std::exception_ptr diagnostic_error,completion_error;bool cache_known=false;
 if(invalid){try{emit("ERR "+actor_error);}catch(...){diagnostic_error=std::current_exception();}}
 try{cache_known=finish();}catch(...){completion_error=std::current_exception();}
 if(completion_error){if(diagnostic_error)throw ActorCompletionFailure(completion_error,diagnostic_error,actor_error);std::rethrow_exception(completion_error);}
 if(diagnostic_error)std::rethrow_exception(diagnostic_error);
 return cache_known;
}
bool prepared_prefix_matches(uint64_t core,uint64_t draft,bool healthy){return healthy&&core==draft;}
void require_normal_reusable(bool restart_required){need(!restart_required,"owner completion unknown; restart required");}
// Owns no resources itself. On uncertain completion retain the actual complete root,
// including originals and closures, rather than merely leaking one borrowed view.
template<class Root>struct NormalRootRetention {
 std::unique_ptr<Root>&root;bool armed=false;
 ~NormalRootRetention()noexcept{if(root&&(armed||root->restart_required))(void)root.release();}
};
// T38_NORMAL_POLICY_END
std::string routing_digest(const routing::Policy&p){
 std::vector<uint8_t>object;BCRYPT_ALG_HANDLE algorithm=nullptr;BCRYPT_HASH_HANDLE hash=nullptr;
 struct Close{BCRYPT_ALG_HANDLE&a;BCRYPT_HASH_HANDLE&h;~Close(){if(h)BCryptDestroyHash(h);if(a)BCryptCloseAlgorithmProvider(a,0);}}close{algorithm,hash};
 need(BCryptOpenAlgorithmProvider(&algorithm,BCRYPT_SHA256_ALGORITHM,nullptr,0)>=0,"routing SHA provider");DWORD size=0,written=0;
 need(BCryptGetProperty(algorithm,BCRYPT_OBJECT_LENGTH,reinterpret_cast<PUCHAR>(&size),sizeof(size),&written,0)>=0,"routing SHA object");object.resize(size);std::array<uint8_t,32>digest{};
 need(BCryptCreateHash(algorithm,&hash,object.data(),size,nullptr,0,0)>=0,"routing SHA create");
 auto add=[&](const void*data,size_t n){need(n<=UINT32_MAX&&BCryptHashData(hash,(PUCHAR)data,ULONG(n),0)>=0,"routing SHA data");};
 add(p.binding.data(),p.binding.size());add(&p.config.primary,4);add(&p.config.secondary,4);add(&p.config.ssd,4);add(p.delta.data(),p.delta.size()*4);add(p.counts.data(),p.counts.size()*8);add(p.coverage.data(),p.coverage.size());
 need(BCryptFinishHash(hash,digest.data(),digest.size(),0)>=0,"routing SHA finish");const char*hex="0123456789abcdef";std::string out;for(auto b:digest){out+=hex[b>>4];out+=hex[b&15];}return out;
}
struct Owners {
 routing::Config routing_config;std::shared_ptr<routing::Policy> routing_policy;
 bool routing_prefix_dirty=false,routing_last_neutral=true;std::array<uint64_t,6>routing_last_counts{};std::string routing_last_digest;
 const Artifact&artifact;const engram::Config&engram;ProducerConfig config;int device;
 std::unique_ptr<cache::PrimarySupply>weight;std::unique_ptr<cache::RowSupply>rows;std::unique_ptr<cache::SecondaryCache>secondary_cache;std::unique_ptr<CoreSequence>core;
 std::unique_ptr<ComputeOwners>compute;
 PrefixState prefix;bool prefix_enabled=true,cached_request_logits=false;uint64_t prefix_reused=0,prefix_new=0,last_request_raw_logit_capacity_bytes=0,last_request_history_capacity_bytes=0;
 const char*prefix_action="fresh",*prefix_reason="empty";
 uint64_t prefix_host_bytes()const{return prefix.host_known_subset_bytes();}
 int secondary_device=-1;uint64_t secondary_slots=1,secondary_target=0,secondary_unused=0,secondary_attempts=0;bool cache_unavailable=false;std::string cache_reason;Available secondary_observed;double secondary_construction_ms=0;
 Counts device_count,ram_count;uint64_t deferred_device=0,deferred_host=0,mandatory_device=0;Available observed;
 std::vector<std::string>lifetime;double construction_ms=0;uint64_t construction_attempts=0;
 std::vector<std::string>required_f32_names;
 void attach_prefill_intent(){
  CorePrefillPreparation value;
  if(!compute&&!config.projection_graph&&!dspark_enabled(config)&&(config.mode=="single"||config.mode=="cache-only")){
   value.max_batch=8;while(value.max_batch>config.active_batch)value.max_batch/=2;
   value.required_f32_names=required_f32_names;
  }
  core->attach_prefill_preparation(std::move(value));
 }
 CoreConfig cc()const{CoreConfig x;
#ifdef STRATA_T38_GLOBAL_FIXTURE
 x.audit=config.fixture_audit_root.get();
#endif
 x.device=device;x.tile_bytes=config.tile_bytes;x.tile_rows=config.tile_rows;x.active_batch=config.active_batch;x.secondary_cache=secondary_cache.get();return x;}
 void make_secondary(){
  if(config.mode!="cache-only"||cache_unavailable||secondary_device<0)return;
  for(;;){auto started=std::chrono::steady_clock::now();++secondary_attempts;
   try{secondary_cache=std::make_unique<cache::SecondaryCache>(cache::SecondaryConfig{device,secondary_device,size_t(secondary_slots),config.tile_bytes});secondary_construction_ms+=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-started).count();return;}
   catch(...){auto e=std::current_exception();secondary_construction_ms+=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-started).count();if(construction_unknown(e))throw;if(!construction_allocation(e))std::rethrow_exception(e);
    if(!config.secondary_device_cache_payload_bytes&&secondary_slots>1){secondary_slots=1+(secondary_slots-1)/2;continue;}
    cache_unavailable=true;cache_reason="secondary allocation unavailable; safe Primary RAM/SSD bypass";secondary_slots=0;return;
   }
  }
 }
 void make(Counts d,Counts h,const std::string&id){
  auto started=std::chrono::steady_clock::now();++construction_attempts;lifetime.push_back("owners-create");cache::SupplyConfig supply{d.weight,h.weight,config.tile_bytes,4,4,device,true};supply.projection_graph=config.projection_graph;supply.projection_graph_abi=config.projection_graph?STRATA_GRAPH_BUILD_ABI:"";weight=std::make_unique<cache::PrimarySupply>(supply);++graph_generation;
  auto s=artifact.source_tensor("per_layer_token_embd.weight").source;
  rows=std::make_unique<cache::RowSupply>(cache::RowConfig{d.row,h.row,1,1,device},artifact,cache::RowSourceViews({{s,{s.original_path,0,s.original_size}}}));
  make_secondary();lifetime.push_back("core-create");core=std::make_unique<CoreSequence>(artifact,engram,*weight,*rows,identity(config,id),cc(),config.context);construction_ms+=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-started).count();
 }
 bool idle_drain(const measurement::Identity&id){
  if(compute)return compute->drain(id.request_id);
  if(hipDeviceSynchronize()!=hipSuccess)return false;if(secondary_cache)secondary_cache->cancel_and_drain();
  if(weight){if(weight->state()!=cache::SupplyState::Idle)weight->cancel();if(weight->prefetch_state()!=cache::SupplyState::Idle)weight->cancel_prefetch();}
  auto cancelled=rows?rows->cancel_all():std::vector<cache::Token>{};
  // Poll only previously issued operations. No fresh source read on cleanup.
  while(true){if(weight){weight->poll_io(10);weight->poll_device();auto state=weight->state();if(state==cache::SupplyState::Quarantined)return false;if(state==cache::SupplyState::Cancelled||state==cache::SupplyState::Done){try{(void)weight->take_device(id);}catch(const std::exception&){(void)weight->take(id);}}if(weight->prefetch_state()==cache::SupplyState::Cancelled||weight->prefetch_state()==cache::SupplyState::Done)(void)weight->take_prefetch(id);}
   if(rows){rows->poll_io(0);rows->poll_device();for(auto it=cancelled.begin();it!=cancelled.end();){auto state=rows->state(*it);if(state==cache::RowState::Cancelled||state==cache::RowState::Done){(void)rows->take(*it,id);it=cancelled.erase(it);}else ++it;}}
   if((!weight||weight->state()==cache::SupplyState::Idle&&weight->prefetch_state()==cache::SupplyState::Idle)&&cancelled.empty()&&(!rows||!rows->fill_pending()))return true;
   std::this_thread::yield();
  }
 }
 bool clear(const std::string&id){if(compute){if(!compute->clear(id))return false;compute.reset();return true;}if(!idle_drain(identity(config,id)))return false;if(core&&!core->retire_projection_graph())return false;lifetime.push_back("core-destroy");core.reset();if(secondary_cache){if(!secondary_cache->try_close())return false;lifetime.push_back("secondary-cache-destroy");secondary_cache.reset();}if(rows){if(!rows->try_close())return false;lifetime.push_back("row-destroy");rows.reset();}if(weight){if(!weight->try_close())return false;lifetime.push_back("weight-destroy");weight.reset();}return true;}
 void retain(){if(compute){compute->retain();(void)compute.release();}(void)core.release();(void)secondary_cache.release();(void)rows.release();(void)weight.release();}
 Owners(const Artifact&a,const engram::Config&e,ProducerConfig c,int dev):artifact(a),engram(e),config(std::move(c)),device(dev){routing_config=config.routing;
  try{prefix.allocate(config.context);}catch(const std::bad_alloc&){prefix_enabled=false;prefix_reason="optional ledger allocation unavailable";}
  if(config.mode=="expert-assist"||config.mode=="layer-split"){compute=std::make_unique<ComputeOwners>(artifact,engram,config);return;}
  need(config.mode=="single"||config.mode=="cache-only","requested normal compute-mode connection is pending T46; not executing single under another mode");
  if(config.mode=="cache-only"){
   need(!config.secondary_pci.empty()&&config.secondary_pci!=config.primary_pci,"cache-only distinct requested secondary PCI");auto roles=strata_ext::device::inventory();for(auto&role:roles)if(role.pci==config.secondary_pci)secondary_device=role.ordinal;
   if(secondary_device<0){cache_unavailable=true;secondary_slots=0;cache_reason="requested secondary absent; safe Primary RAM/SSD bypass";}
   if(config.secondary_device_cache_payload_bytes)cache::secondary_capacity(*config.secondary_device_cache_payload_bytes,config.tile_bytes);
  }
  need(config.context&&config.context<=1048576&&config.runtime_epoch&&config.tile_bytes&&config.tile_rows&&config.active_batch,"normal context/identity/window");
  need(std::isfinite(config.auto_cache_fraction)&&config.auto_cache_fraction>=0&&config.auto_cache_fraction<=1&&std::isfinite(config.auto_row_fraction)&&config.auto_row_fraction>=0&&config.auto_row_fraction<=1,"auto fractions in [0,1]");
  for(const auto&t:a.tensors())if(t.type_id!=0)need(t.row_bytes<=config.tile_bytes,"one full-K row exceeds selected finite tile");
  // Every lazy learned F32 constant used by actual Core, once; not all F32 matrices.
  std::set<std::string> names{"output_norm.weight"};for(unsigned layer=0;layer<40;++layer){std::string p="blk."+std::to_string(layer)+".";for(auto n:{"hc_attn_scale.weight","hc_attn_base.weight","attn_norm.weight","hc_ffn_scale.weight","hc_ffn_base.weight","ffn_norm.weight","attn_q_a_norm.weight","attn_kv_a_norm.weight","attn_sinks.weight","exp_probs_b.bias","exp_probs_b_vl.bias"})names.insert(p+n);if(layer==1||layer==14)names.insert(p+"engram_gate.weight");if(layer==2||layer==8||layer==14||layer==20){names.insert(p+"attn_compressor_norm.weight");names.insert(p+"indexer.k_norm.weight");}}
  for(const auto&n:names)deferred_device=add(deferred_device,artifact.source_tensor(n).span.bytes);
  required_f32_names.assign(names.begin(),names.end());
   if(dspark_enabled(config))deferred_device=add(deferred_device,15360*4); // request-local mean; startup Network residency is already in available()
  // host logits, adjusted doubles, ordering, weights, LP alternatives/history.
  deferred_host=add(add(add(mul(129280,4+8+4+8+4+8),mul(config.context,8)),20*8),config.dspark_deferred_host_bytes);
  try{make({}, {},"startup-measurement");mandatory_device=core->explicit_device_owned();observed=available(device);uint64_t minimum=config.tile_bytes+264;
   if(secondary_cache){size_t free=0,total=0;auto old=device;hip(hipSetDevice(secondary_device));secondary_observed=available(secondary_device);hip(hipSetDevice(old));auto unit=cache::secondary_capacity(UINT64_MAX,config.tile_bytes).unit;secondary_target=config.secondary_device_cache_payload_bytes?*config.secondary_device_cache_payload_bytes:add(unit,uint64_t(std::floor(double(secondary_observed.device.value_or(0))*config.auto_cache_fraction)));auto resolved=cache::secondary_capacity(secondary_target,config.tile_bytes);secondary_slots=resolved.slots;secondary_unused=resolved.unused;deferred_host=add(deferred_host,mul(secondary_slots-1,cache::SecondaryCache::slot_metadata_bytes()));}

   auto target=[&](std::optional<uint64_t> requested,std::optional<uint64_t>free,uint64_t deferred){if(requested)return *requested;uint64_t remaining=free&&*free>deferred?*free-deferred:0;return add(minimum,uint64_t(std::floor(double(remaining)*config.auto_cache_fraction)));};
   uint64_t dt=target(config.device_cache_payload_bytes,observed.device,deferred_device),ht=target(config.ram_cache_payload_bytes,observed.host,deferred_host);need(clear("startup-measurement"),"measurement owner drain unknown");
   for(;;){device_count=counts(dt,config.tile_bytes,config.auto_row_fraction,config.device_cache_payload_bytes.has_value());ram_count=counts(ht,config.tile_bytes,config.auto_row_fraction,config.ram_cache_payload_bytes.has_value());try{make(device_count,ram_count,"startup-final");break;}catch(...){auto error=std::current_exception();if(construction_unknown(error)){retain();std::rethrow_exception(error);}if(!clear("startup-final")){retain();std::rethrow_exception(error);}if(!reduce_auto_allocation(error,!config.device_cache_payload_bytes,!config.ram_cache_payload_bytes,minimum,dt,ht))std::rethrow_exception(error);}}
   attach_prefill_intent();
  }catch(...){if(construction_unknown(std::current_exception())){retain();throw;}if(!clear("startup-failure"))retain();throw;}
 }
 ~Owners(){try{if(!clear("shutdown"))retain();}catch(...){retain();}}
 void begin_routing(const routing::Config&requested,const std::string&id){
  if(routing_prefix_dirty||(routing_policy&&routing_policy->decode_used)){prefix.invalidate();routing_prefix_dirty=false;}
  routing_config=requested;routing_last_digest.clear();routing_last_counts.fill(0);routing_last_neutral=true;
  // No snapshot, allocation, table upload, digest or meter work for zero coefficients.
  if(requested.exact()){routing_policy.reset();return;}
  need(idle_drain(identity(config,id)),"routing capture previous owner drain");routing_policy.reset();
  std::vector<routing::Snapshot>snapshots;
  if(compute){
   auto first=compute->weight->routing_snapshot();
   if(compute->split)first.spans.erase(std::remove_if(first.spans.begin(),first.spans.end(),[&](const auto&v){auto dot=v.tensor.find('.',4);return std::stoul(v.tensor.substr(4,dot-4))>=*config.layer_cut;}),first.spans.end());snapshots.push_back(std::move(first));
   if(compute->secondary_weight){auto s=compute->secondary_weight->routing_snapshot();if(compute->split)s.spans.erase(std::remove_if(s.spans.begin(),s.spans.end(),[&](const auto&v){auto dot=v.tensor.find('.',4);return std::stoul(v.tensor.substr(4,dot-4))<*config.layer_cut;}),s.spans.end());
    else for(auto&v:s.spans)if(v.tier==routing::Tier::Primary)v.tier=routing::Tier::Secondary;snapshots.push_back(std::move(s));}
   // The worker owns private slots; no cross-thread access or invented absence.
   if(compute->experts){routing::Snapshot unknown;unknown.complete=false;snapshots.push_back(std::move(unknown));}
  }else snapshots.push_back(weight->routing_snapshot());
  if(secondary_cache)snapshots.push_back(secondary_cache->routing_snapshot());
  auto expected=std::make_unique<std::array<routing::Expected,40*384>>();bool geometry_known=true;
  for(unsigned l=0;l<40;++l)for(unsigned e=0;e<384;++e){unsigned k=0;for(const char*n:{"ffn_gate_exps.weight","ffn_up_exps.weight","ffn_down_exps.weight"}){
   auto source=artifact.source_tensor("blk."+std::to_string(l)+"."+n);auto tile=source_tile(source,e,0,source.span.dims_ggml.at(1));
   cache::SupplyMatrix m{tile.original,tile.absolute_offset,tile.bytes,tile.type,size_t(tile.row_count),size_t(tile.k)};
   auto span=cache::routing_span(m,routing::Tier::Primary);geometry_known=geometry_known&&span.bytes!=0;(*expected)[l*384+e].spans[k++]=std::move(span);
  }}
  if(!geometry_known){routing::Snapshot unknown;unknown.complete=false;snapshots.push_back(std::move(unknown));}
  std::string binding="routing-v1|target-decode|"+quote(revision)+"|"+quote(id)+"|"+quote(config.bundle_id)+"|"+std::to_string(config.runtime_epoch)+"|"+config.primary_pci+"|"+config.secondary_pci;
  for(auto&s:snapshots)binding+="|"+std::to_string(s.owner)+":"+std::to_string(s.generation)+":"+(s.complete?"known":"unknown");
  routing_policy=routing::derive(requested,snapshots,*expected,binding);routing_policy->digest=routing_digest(*routing_policy);
 }
 void finish_routing(bool completion_known){
  if(!routing_policy)return;
  routing_prefix_dirty=routing_prefix_dirty||routing_policy->decode_used;
  // Unknown completion retains the original table/Core and policy owner.
  if(!completion_known)return;
  auto policy=std::move(routing_policy);
  try{if(request_valid())attach_routing();}catch(...){routing_policy=std::move(policy);throw;}
  routing_last_digest=std::move(policy->digest);routing_last_counts=policy->counts;routing_last_neutral=policy->neutral();
  // Invalid cancelled Core is unusable and may retain its shared reference until
  // existing Fresh destruction; no destructor/free completion is invented.
 }
 void attach_routing(){
  if(compute){if(compute->split)compute->split->routing_policy(routing_policy);else compute->core->routing_policy(routing_policy);}
  else core->routing_policy(routing_policy);
 }
 std::string routing_info()const{
  std::ostringstream o;o<<std::setprecision(std::numeric_limits<float>::max_digits10);o<<",\"routing\":{\"version\":1,\"phase\":\"target_decode\",\"primary_bonus\":"<<routing_config.primary<<",\"secondary_bonus\":"<<routing_config.secondary<<",\"ssd_penalty\":"<<routing_config.ssd<<",\"effective\":"<<quote(routing_policy?routing_policy->neutral()?"exact":"cache_aware":routing_last_neutral?"exact":"cache_aware")<<",\"reason\":"<<quote(routing_config.exact()?"zero_coefficients":!routing_policy&&routing_last_digest.empty()?"snapshot_unavailable":(routing_policy?routing_policy->neutral():routing_last_neutral)?"neutral_coverage":"request_snapshot")<<",\"snapshot_digest\":"<<(routing_policy?quote(routing_policy->digest):routing_last_digest.empty()?"null":quote(routing_last_digest))<<",\"coverage_counts\":[";
  for(unsigned i=0;i<6;++i){if(i)o<<',';o<<(routing_policy?routing_policy->counts[i]:routing_last_counts[i]);}o<<"],\"coverage_order\":[\"primary\",\"secondary\",\"ram\",\"partial\",\"none\",\"unknown\"]}";return o.str();
 }
 void request(const std::string&id){if(compute){compute->request(id);return;}need(idle_drain(identity(config,id)),"previous owner operation not drained");need(!core||core->retire_projection_graph(),"graph activation retirement unknown");core.reset();core=std::make_unique<CoreSequence>(artifact,engram,*weight,*rows,identity(config,id),cc(),config.context);attach_prefill_intent();}
 CoreOutput prefill(const std::vector<uint32_t>&tokens,const PrefillControl&control,uint64_t start=0){return compute?compute->prefill(tokens,control,start):core->prefill(tokens,start,{},control);}
 void continue_request(const std::string&id){if(compute)compute->continue_request(id);else core->continue_request(identity(config,id),position());}
 bool request_valid()const noexcept{return compute?compute->request_valid():core&&core->request_valid();}
 void quiesce(){if(compute)compute->quiesce();else core->quiesce();}
 void invalidate_math(){prefix.invalidate();if(compute)compute->invalidate_math();else core->invalidate_and_drain();}
 PrefixMathKey prefix_key()const{
  PrefixMathKey key;key.asset=revision;key.bundle=config.bundle_id;key.epoch=config.runtime_epoch;key.context=config.context;key.mode=config.mode;
  key.primary=compute?compute->roles.primary.pci:config.primary_pci;key.secondary=compute?compute->roles.secondary->pci:(secondary_device<0?"":config.secondary_pci);
  if(config.secondary_experts)key.assignment=*config.secondary_experts;key.cut=config.layer_cut;
  // Artifact, tile geometry and canonical math are immutable in this one Owners.
  return key;
 }
 PrefixDecision prepare_prefix_request(const std::string&id,const std::vector<uint32_t>&prompt,const std::atomic<int>&request_stop,std::vector<uint32_t>*prepared_suffix=nullptr){
  cached_request_logits=false;prefix_reused=prefix_new=0;prefix_action="fresh";prefix_reason=prefix_enabled?"incompatible or empty prefix":"optional ledger unavailable";
  PrefixMathKey key;PrefixDecision choice;std::vector<uint8_t>mask;
  if(prefix_enabled){try{key=prefix_key();mask.resize(prompt.size(),0);choice=prefix.decide(key,prompt,mask,position(),true);if(prepared_suffix&&choice.action==PrefixAction::Append)prepared_suffix->assign(prompt.begin()+size_t(choice.reused),prompt.end());}
   catch(const std::bad_alloc&){prefix.invalidate();prefix_enabled=false;prefix_reason="optional request metadata unavailable";choice={};}}
  if(request_stop.load()!=0){prefix.invalidate();return {};}
  if(choice.action!=PrefixAction::Fresh){try{continue_request(id);}
   catch(const RequestAdoptionRefused&){choice={};prefix_reason="owner adoption refused; fresh";}
   catch(const std::bad_alloc&){if(!request_valid()){prefix.invalidate();throw;}choice={};prefix_reason="request binding allocation unavailable; fresh";}}
  if(choice.action==PrefixAction::Fresh){prefix.invalidate();request(id);if(prefix_enabled)prefix.begin_fresh(std::move(key));}
  else{prefix.begin_append();prefix_reused=choice.reused;prefix_action=choice.action==PrefixAction::Logits?"logits":"append";prefix_reason="exact processed prefix";}
  if(request_stop.load()!=0){prefix.invalidate();return {};}
  attach_routing();return choice;
 }
 CoreOutput prefill_request(const std::string&id,const std::vector<uint32_t>&prompt,const PrefillControl&control,const std::atomic<int>&request_stop){
  std::vector<uint32_t>suffix;auto choice=prepare_prefix_request(id,prompt,request_stop,&suffix);
  if(request_stop.load()!=0){prefix.invalidate();CoreOutput stopped;stopped.cancelled=true;return stopped;}
  auto progress=[&](uint64_t done,uint64_t){return !control||control(prefix_reused+done,prompt.size());};
  if(choice.action==PrefixAction::Logits){if(!progress(0,0)){prefix.invalidate();CoreOutput stopped;stopped.cancelled=true;return stopped;}cached_request_logits=true;CoreOutput out;out.rows=1;out.vocabulary=129280;return out;}
  const auto&work=choice.action==PrefixAction::Append?suffix:prompt;auto out=prefill(work,progress,prefix_reused);
  if(out.cancelled){prefix.invalidate();return out;}
  need(out.processed==work.size(),"prefix successful prefill count");prefix_new=out.processed;
  if(prefix_enabled){try{for(auto token:work)prefix.processed(token);need(prefix.processed_count()==position(),"prefix processed cursor");}catch(...){invalidate_math();throw;}}
  return out;
 }
 void processed_step(uint32_t token){if(prefix_enabled){try{prefix.processed(token);need(prefix.processed_count()==position(),"prefix decode cursor");}catch(...){invalidate_math();throw;}}}
 uint64_t graph_generation=0,graph_entry_generation=0;
 const cache::PrimarySupply*graph_entry_owner=nullptr;
 cache::PrimaryGraphStats graph_entry_stats{};bool graph_entry_valid=false,graph_owner_completion_known=true,graph_tap_selected=false;
 struct SecondaryGraphSnapshot {cache::PrimaryGraphStats stats;uint64_t generation;bool known;const void*owner;};
 std::optional<SecondaryGraphSnapshot> graph_secondary_entry;
 std::string graph_json,graph_frame,graph_roles_json;
 std::optional<SecondaryGraphSnapshot> graph_secondary()const{
  if(!compute)return {};if(compute->experts){auto s=compute->experts->stats();return SecondaryGraphSnapshot{s.secondary_graph,compute->secondary_graph_generation,s.secondary_known,compute->experts.get()};}
  if(compute->secondary_weight)return SecondaryGraphSnapshot{compute->secondary_weight->projection_graph_stats(),compute->secondary_graph_generation,true,compute->secondary_weight.get()};return {};
 }
 cache::PrimarySupply* graph_primary()const{return compute?compute->weight.get():weight.get();}
 uint64_t graph_primary_generation()const{return compute?compute->graph_generation:graph_generation;}
 bool graph_applicable()const{return bool(graph_primary());}
 void graph_begin_request()noexcept{graph_tap_selected=false;
  graph_entry_valid=false;graph_secondary_entry.reset();graph_json.clear();graph_frame.clear();graph_roles_json.clear();
  if(!graph_owner_completion_known||!graph_applicable()||!config.projection_graph||!graph_primary())return;
  try{graph_entry_stats=graph_primary()->projection_graph_stats();graph_entry_owner=graph_primary();graph_entry_generation=graph_primary_generation();graph_entry_valid=true;graph_secondary_entry=graph_secondary();}catch(...){/* Optional observation only. */}
 }
 void graph_complete_request(bool known,bool request_finished)noexcept{
  graph_owner_completion_known=known;graph_json.clear();graph_frame.clear();graph_roles_json.clear();
  try{
   std::optional<cache::PrimaryGraphStats>total,delta;bool observed=false;
   const char*reason=!known?"successful request boundary unavailable for graph observation":!graph_applicable()?"compute path not wired":!config.projection_graph?"disabled; invocation counters unavailable":!request_finished?"before first completed request":"entry snapshot unavailable";
   if(known&&graph_applicable()&&config.projection_graph&&graph_primary()){
    total=graph_primary()->projection_graph_stats();
    if(request_finished&&graph_entry_valid){
     if(graph_entry_owner==graph_primary()&&graph_entry_generation==graph_primary_generation()){delta=graph_counter_delta(graph_entry_stats,*total);observed=bool(delta);reason=observed?"actual Primary owner counters":"owner counters reset; delta unavailable";}
     else reason="owner generation changed; current totals only";
    }
   }
   auto value=graph_info_json(config.projection_graph,graph_applicable(),observed,graph_primary_generation(),reason,total,delta,graph_tap_selected);
   auto frame="INFO {\"projection_graph\":"+value+"}";
   graph_json.swap(value);graph_frame.swap(frame);
   if(compute){auto second=known?graph_secondary():std::optional<SecondaryGraphSnapshot>{};std::optional<cache::PrimaryGraphStats>st,sd;bool so=false;
    const char*sr=!known?"owner completion unknown":!config.projection_graph?"disabled; invocation counters unavailable":"entry snapshot unavailable";
    if(known&&config.projection_graph&&second&&second->known){st=second->stats;if(request_finished&&graph_secondary_entry&&graph_secondary_entry->known&&graph_secondary_entry->generation==second->generation&&graph_secondary_entry->owner==second->owner){sd=graph_counter_delta(graph_secondary_entry->stats,*st);so=bool(sd);sr=so?"actual secondary Primary owner counters":"secondary counters reset; delta unavailable";}else sr="secondary generation changed or entry unavailable";}
    graph_roles_json="[{\"role\":\"primary\",\"device\":"+std::to_string(compute->roles.primary.ordinal)+",\"owner_completion_known\":"+(known?"true":"false")+",\"projection_graph\":"+graph_json+"},{\"role\":\"secondary\",\"device\":"+std::to_string(compute->roles.secondary->ordinal)+",\"owner_completion_known\":"+(known&&second&&second->known?"true":"false")+",\"projection_graph\":"+graph_info_json(config.projection_graph,true,so,second?second->generation:0,sr,st,sd,graph_tap_selected)+"}]";
    graph_frame="INFO {\"projection_graph\":"+graph_json+",\"projection_graph_roles\":"+graph_roles_json+"}";
   }
  }catch(...){graph_json.clear();graph_frame.clear();/* Optional JSON/snapshot failure never gates math. */}
 }

 bool finish_prefix(const std::string&id,bool healthy){
  if(healthy&&prefix_enabled){try{quiesce();return true;}catch(const RequestAdoptionRefused&){prefix_reason="healthy reuse boundary unavailable; fresh next";}}
  prefix.invalidate();need(idle_drain(identity(config,id)),"request drain unknown");return false;
 }
 void publish_prefix(const std::vector<float>&logits){if(prefix_enabled){try{prefix.publish(logits,position());}catch(...){invalidate_math();throw;}}}
 std::string prefix_info()const{
  std::ostringstream o;o<<",\"prefix_reuse_enabled\":"<<(prefix_enabled?"true":"false")<<",\"prefix_action\":"<<quote(prefix_action)<<",\"prefix_reason\":"<<quote(prefix_reason)<<",\"prefix_reused_tokens\":"<<prefix_reused<<",\"prefix_new_prompt_tokens\":"<<prefix_new<<",\"prefix_processed_tokens\":"<<prefix.processed_count()<<",\"prefix_ledger_known_subset_bytes\":"<<prefix_host_bytes()<<",\"prefix_key_heap_bytes\":null,\"prefix_cached_raw_logit_bytes\":"<<prefix.logits().size()*4<<",\"prefix_cached_raw_logit_capacity_bytes\":"<<prefix.logits().capacity()*4<<",\"last_request_raw_logit_capacity_bytes\":"<<last_request_raw_logit_capacity_bytes<<",\"last_request_history_capacity_bytes\":"<<last_request_history_capacity_bytes<<",\"request_mask_suffix_capacity_bytes\":null";return o.str();
 }
 std::string info()const{auto text=base_info();need(!text.empty()&&text.back()=='}',"prefix INFO object");text.pop_back();text+=prefix_info();text+=routing_info();text+='}';if(!graph_json.empty()){try{auto enriched=text;enriched.pop_back();enriched+=",\"projection_graph\":"+graph_json;if(!graph_roles_json.empty())enriched+=",\"projection_graph_roles\":"+graph_roles_json;enriched+="}";return enriched;}catch(const std::bad_alloc&){}}return text;}
 uint64_t position()const{return compute?compute->position():core->position();}
 std::vector<float>step(uint32_t token){return compute?compute->step(token):core->step(token,core->position());}
 std::string cache_info()const{
  cache::SecondaryStats s;if(secondary_cache)s=secondary_cache->stats();else{s.available=false;s.bypass_reason=cache_reason;}
  auto w=weight->stats();auto r=rows->stats();auto primary_owned=core->explicit_device_owned();auto host_subset=add(prefix_host_bytes(),add(add(w.host_owned,r.host_payload),add(add(w.metadata,r.metadata_capacity),add(s.host_owned,s.metadata))));std::ostringstream o;o<<",\"actual_primary_device_owned\":"<<primary_owned<<",\"actual_all_role_device_owned\":"<<add(primary_owned,s.secondary_device_owned)<<",\"all_known_host_owner_subset_bytes\":"<<host_subset<<",\"cache_allocator_overhead_bytes\":null,\"cache_exception_runtime_bytes\":null,\"cache_driver_private_bytes\":null,\"configured_mode\":"<<quote(config.mode)<<",\"effective_mode\":"<<quote(config.mode=="cache-only"?(s.available?"cache-only":"cache-bypass"):"single")<<",\"primary_pci\":"<<quote(config.primary_pci)<<",\"requested_secondary_pci\":"<<(config.secondary_pci.empty()?"null":quote(config.secondary_pci))<<",\"actual_secondary_pci\":"<<(secondary_device<0?"null":quote(config.secondary_pci))<<",\"cache_bypass_reason\":"<<quote(s.bypass_reason)<<",\"cache_secondary_slots\":"<<s.slots<<",\"cache_valid_slots\":"<<s.valid_slots<<",\"cache_slot_capacity\":"<<s.slot_capacity<<",\"cache_declared_secondary_payload_bytes\":"<<(config.secondary_device_cache_payload_bytes?std::to_string(*config.secondary_device_cache_payload_bytes):"null")<<",\"cache_secondary_target_bytes\":"<<secondary_target<<",\"cache_secondary_unused_bytes\":"<<secondary_unused<<",\"cache_primary_device_owned\":"<<s.primary_device_owned<<",\"cache_secondary_device_owned\":"<<s.secondary_device_owned<<",\"cache_host_owned\":"<<s.host_owned<<",\"cache_metadata_bytes\":"<<s.metadata<<",\"cache_retained_device_bytes\":"<<s.retained_device_bytes<<",\"cache_retained_host_payload_bytes\":"<<s.retained_host_bytes<<",\"cache_snapshot_d2d\":"<<s.snapshot_d2d<<",\"cache_fill_bytes\":"<<s.fill_bytes<<",\"cache_hit_bytes\":"<<s.hit_bytes<<",\"cache_peer_bytes\":"<<s.peer_bytes<<",\"cache_bounce_d2h\":"<<s.bounce_d2h<<",\"cache_bounce_h2d\":"<<s.bounce_h2d<<",\"cache_hits\":"<<s.hits<<",\"cache_misses\":"<<s.misses<<",\"cache_fills\":"<<s.fills<<",\"cache_evictions\":"<<s.evictions<<",\"cache_bypasses\":"<<s.bypasses<<",\"cache_created_streams\":"<<s.created_streams<<",\"cache_created_events\":"<<s.created_events<<",\"cache_pinned_known\":"<<(s.pinned_known?"true":"false")<<",\"cache_pinned_observed\":"<<(s.pinned_observed?"true":"false")<<",\"cache_pinned_subset\":"<<(s.pinned_known?std::to_string(s.pinned_subset):"null")<<",\"cache_measurement_available_secondary_bytes\":"<<(secondary_observed.device?std::to_string(*secondary_observed.device):"null")<<",\"cache_construction_attempts\":"<<secondary_attempts<<",\"cache_construction_ms\":"<<secondary_construction_ms;return o.str();
 }
 std::string prefill_preparation_info(const CoreRuntimeStats&c)const{const auto&p=c.prefill_preparation;std::ostringstream o;o<<",\"prefill_preparation\":{\"requested_capacity\":"<<p.requested_capacity<<",\"selected_capacity\":"<<p.selected_capacity<<",\"context_capacity\":"<<p.context_capacity<<",\"workspace_payload_bytes\":"<<p.workspace_payload_bytes<<",\"constant_miss_bytes\":"<<p.constant_miss_bytes<<",\"reason_code\":"<<unsigned(p.reason)<<",\"producer_f32_registry_name_count\":"<<required_f32_names.size()<<"}";return o.str();}
 std::string base_info()const{if(compute)return compute->info(prefix_host_bytes());auto w=weight->stats();auto r=rows->stats();auto c=core->runtime_stats();uint64_t ring_events=0;for(const auto&stage:w.stages)ring_events+=stage.address!=0;for(const auto&stage:r.stages)ring_events+=stage[0]!=0;std::ostringstream o;o<<"{\"family\":\"deepseek41\",\"context\":"<<config.context<<",\"device_slots\":"<<device_count.weight<<",\"ram_slots\":"<<ram_count.weight<<",\"row_device_slots\":"<<device_count.row<<",\"row_ram_slots\":"<<ram_count.row<<",\"device_cache_payload_bytes\":"<<device_count.bytes<<",\"ram_cache_payload_bytes\":"<<ram_count.bytes<<",\"cache_unused_device_bytes\":"<<device_count.unused<<",\"cache_unused_ram_bytes\":"<<ram_count.unused<<",\"mandatory_measurement_device\":"<<mandatory_device<<",\"deferred_constant_device\":"<<deferred_device<<",\"deferred_host_sampling\":"<<deferred_host<<",\"actual_device_owned\":"<<core->explicit_device_owned()<<",\"owned_host_owner_subset_bytes\":"<<w.host_owned+r.host_payload+w.metadata+r.metadata_capacity+prefix_host_bytes()<<",\"core_position\":"<<core->position()<<",\"primary_logical_read\":"<<w.weight_read<<",\"primary_h2d\":"<<w.weight_h2d<<",\"row_logical_read\":"<<r.logical_read<<",\"row_weight_h2d\":"<<r.weight_h2d<<",\"row_index_h2d\":"<<r.index_h2d<<",\"row_control_d2h\":"<<r.control_d2h<<",\"row_output_d2h\":"<<r.output_d2h<<",\"requested_logits_or_audit_d2h\":"<<c.requested_output_or_fixture_download_bytes<<",\"hip_mem_status\":"<<observed.hip_status<<",\"hip_luid_status\":"<<observed.luid_status<<",\"wddm_binding_status\":"<<observed.binding_status<<",\"wddm_local_status\":"<<observed.local_status<<",\"owner_metadata_bytes\":"<<w.metadata+r.metadata_capacity<<",\"owner_explicit_event_count\":"<<device_count.weight+device_count.row+4<<",\"observed_ring_event_count\":"<<ring_events<<",\"driver_event_private_bytes\":null,\"construction_attempts\":"<<construction_attempts<<",\"construction_ms\":"<<construction_ms<<",\"loaded_runtime_modules\":"<<modules()<<",\"primary_aligned_read\":"<<w.aligned_read<<",\"primary_issued_read\":"<<w.issued_read<<",\"primary_issued_reads\":"<<w.issued_reads<<",\"primary_input_h2d\":"<<w.input_h2d<<",\"primary_output_d2h\":"<<w.output_d2h<<",\"primary_gpu_hits\":"<<w.gpu_hits<<",\"primary_ram_hits\":"<<w.ram_hits<<",\"primary_ssd_misses\":"<<w.ssd_misses<<",\"primary_device_owned\":"<<w.device_owned<<",\"primary_host_owned\":"<<w.host_owned<<",\"row_requested_read\":"<<r.requested_read<<",\"row_received\":"<<r.received<<",\"row_issued\":"<<r.issued<<",\"row_issued_requested\":"<<r.issued_requested<<",\"row_gpu_hits\":"<<r.gpu_hits<<",\"row_ram_hits\":"<<r.ram_hits<<",\"row_ssd_misses\":"<<r.ssd_misses<<",\"row_device_owned\":"<<r.device_owned<<",\"row_host_owned\":"<<r.host_payload<<",\"core_storage_device_owned\":"<<c.storage_device_owned<<",\"core_constant_source_bytes\":"<<c.constant_source_bytes<<",\"core_storage_upload_bytes\":"<<c.storage_upload_bytes<<",\"primary_pinned_known\":"<<(w.pinned_known?"true":"false")<<",\"primary_pinned_observed\":"<<(w.pinned_observed?"true":"false")<<",\"primary_pinned_subset\":"<<(w.pinned_known?std::to_string(w.pinned_subset):"null")<<",\"row_pinned_known\":"<<(r.pinned_known?"true":"false")<<",\"row_pinned_observed\":"<<(r.pinned_observed?"true":"false")<<",\"row_pinned_subset\":"<<(r.pinned_known?std::to_string(r.pinned_subset):"null")<<",\"primary_received\":null"<<",\"measurement_available_device_bytes\":"<<(observed.device?std::to_string(*observed.device):"null")<<",\"measurement_available_host_bytes\":"<<(observed.host?std::to_string(*observed.host):"null")<<",\"declared_device_cache_payload_bytes\":"<<(config.device_cache_payload_bytes?std::to_string(*config.device_cache_payload_bytes):"null")<<",\"declared_ram_cache_payload_bytes\":"<<(config.ram_cache_payload_bytes?std::to_string(*config.ram_cache_payload_bytes):"null")<<",\"auto_cache_fraction\":"<<config.auto_cache_fraction<<",\"auto_row_fraction\":"<<config.auto_row_fraction<<",\"weight_tile_bytes\":"<<config.tile_bytes<<",\"working_minimum_payload_bytes\":"<<config.tile_bytes+264<<",\"resolved_device_cache_target_bytes\":"<<device_count.bytes+device_count.unused<<",\"resolved_ram_cache_target_bytes\":"<<ram_count.bytes+ram_count.unused<<",\"auto_extra_reduced_after_allocation_failure\":"<<(construction_attempts>2?"true":"false")<<cache_info()<<prefill_preparation_info(c)<<",\"physical_peak\":null}";return o.str();}
};
struct StopControl {bool valid=false,unscoped=false;std::string id;uint64_t epoch=0;int reason=1;};
StopControl parse_stop(const std::string&line){
 StopControl c;std::istringstream f(line);std::string command,part;f>>command;if(command!="STOP")return c;
 std::map<std::string,std::string>fields;while(f>>part){auto at=part.find('=');if(at==std::string::npos||!fields.emplace(part.substr(0,at),part.substr(at+1)).second)return c;}
 if(fields.empty()){c.valid=true;c.unscoped=true;return c;}
 if(fields.size()<2||fields.size()>3||!fields.count("request_id")||!fields.count("epoch")||fields["request_id"].empty())return c;
 for(const auto&v:fields)if(v.first!="request_id"&&v.first!="epoch"&&v.first!="reason")return c;
 try{c.epoch=number(fields["epoch"]);}catch(...){return c;}
 if(fields.count("reason")){if(fields["reason"]=="recipe_stop")c.reason=2;else if(fields["reason"]!="user_cancel")return c;}
 c.id=fields["request_id"];c.valid=true;return c;
}
struct Request {routing::Config routing;std::string id;uint64_t maximum=0;std::vector<uint32_t>prompt;SamplingOptions sampling;std::optional<uint64_t>seed;};
Request parse_request(const std::string&line,uint64_t epoch,const routing::Config&defaults={}){std::istringstream f(line);std::string command,max;f>>command>>max;need(command=="GEN","unknown generation command");Request r;r.routing=defaults;r.maximum=number(max);need(r.maximum>0&&r.maximum<=393216,"resolved output cap");std::string part;std::map<std::string,std::string>options;
 while(f>>part){auto p=part.find('=');if(p==std::string::npos){need(r.prompt.empty(),"multiple prompt bodies");r.prompt=ids(part);}else need(options.emplace(part.substr(0,p),part.substr(p+1)).second,"duplicate GEN option");}
 need(!r.prompt.empty(),"missing prompt IDs");auto take=[&](const char*n)->std::optional<std::string>{auto it=options.find(n);if(it==options.end())return {};auto value=it->second;options.erase(it);return value;};
 auto id=take("request_id"),ep=take("epoch");need(id&&ep&&number(*ep)==epoch&&!id->empty(),"request transport binding");r.id=*id;for(auto field:{std::pair<const char*,float*>{"routing_primary_bonus",&r.routing.primary},{"routing_secondary_bonus",&r.routing.secondary},{"routing_ssd_penalty",&r.routing.ssd}})if(auto v=take(field.first))*field.second=routing::coefficient(*v);
 for(auto entry:{std::pair<const char*,double*>{"temperature",&r.sampling.temperature},{"top_p",&r.sampling.top_p},{"min_p",&r.sampling.min_p},{"penalty_repeat",&r.sampling.repetition_penalty},{"penalty_freq",&r.sampling.frequency_penalty},{"penalty_present",&r.sampling.presence_penalty}})if(auto v=take(entry.first))*entry.second=real(*v);
 if(auto v=take("top_k"))r.sampling.top_k=int64_t(number(*v));if(auto v=take("seed")){r.seed=number(*v);need(*r.seed<(uint64_t(1)<<63),"official seed range");}if(auto v=take("penalty_last_n")){size_t n;r.sampling.penalty_last_n=std::stoll(*v,&n);need(n==v->size(),"penalty history integer");}if(auto v=take("logprobs")){need(*v=="0"||*v=="1","LP flag");r.sampling.logprobs=*v=="1";}if(auto v=take("top_logprobs")){auto n=number(*v);need(n<=20,"official top LP count");r.sampling.top_logprobs=uint32_t(n);}if(auto v=take("logit_bias")){std::istringstream b(*v);std::string pair;while(std::getline(b,pair,',')){auto p=pair.find(':');need(p!=std::string::npos,"bias format");auto n=number(pair.substr(0,p));need(n<129280,"bias original ID");r.sampling.logit_bias.emplace_back(uint32_t(n),real(pair.substr(p+1)));}}
 need(options.empty(),"unknown GEN option");(void)sample_logits(std::vector<float>(129280),r.prompt,r.sampling,0);return r;}
// Actual normal roots; unknown completion retains this entire object, not just Core.
struct NormalActorOwners {
 std::unique_ptr<Artifact> artifact;std::unique_ptr<engram::Config> engram;
 std::unique_ptr<Owners> owners;t38::Asset asset;ProducerConfig config;
 std::unique_ptr<t38::DraftNetwork> network;
 std::unique_ptr<t38::NetworkActorDraft> draft;std::unique_ptr<t38::ActorTarget> target;
 t38::RequestBinding binding;uint64_t generation=0;bool sequence_healthy=false,sequence_started=false,restart_required=false;
 void release_request(){
  require_normal_reusable(restart_required);
  if(target&&!target->completion_known()||draft&&!draft->completion_known()){restart_required=true;require_normal_reusable(true);}
  target.reset();draft.reset();
 }
 void make_network(int device){
  require_normal_reusable(restart_required);release_request();
  if(network){try{network->drain();}catch(...){restart_required=true;throw;}network.reset();}
  need(generation<UINT64_MAX,"DSpark owner generation overflow");binding={++generation,config.runtime_epoch,config.bundle_id};
  network=std::make_unique<t38::DraftNetwork>(config.dspark_draft,asset,*artifact,binding,device,*config.dspark_draft_credit,*config.dspark_target_credit);
  network->prepare_workspace(config.dspark_width);network->drain();sequence_healthy=false;sequence_started=false;
 }
 bool begin_request(const Request&r,const std::atomic<int>&stop,const PrefillControl&progress){
  release_request();
  if(!network||!prepared_prefix_matches(owners->position(),network->processed_cursor(),sequence_healthy))owners->prefix.invalidate();
  auto choice=owners->prepare_prefix_request(r.id,r.prompt,stop);
  if(stop.load()!=0){sequence_healthy=false;owners->prefix.invalidate();return false;}
  if(choice.action==PrefixAction::Fresh){if(!network||sequence_started||network->processed_cursor()!=0)make_network(owners->device);}
  t38::PreparedPrefix prepared;prepared.processed=owners->prefix_reused;
  if(choice.action==PrefixAction::Logits){prepared.logits=owners->prefix.logits();owners->cached_request_logits=true;}
  need(network&&network->processed_cursor()==prepared.processed&&owners->position()==prepared.processed,"normal prepared common cursor");
  sequence_started=true;sequence_healthy=false;
  draft=std::make_unique<t38::NetworkActorDraft>(*network);
  if(owners->compute&&owners->compute->split)target=std::make_unique<t38::LayerSplitActorTarget>(*owners->compute->split,identity(config,r.id),binding,owners->device,*network,[this]{owners->invalidate_math();},progress,std::move(prepared));
  else target=std::make_unique<t38::CoreTargetAdapter>(owners->compute?*owners->compute->core:*owners->core,identity(config,r.id),binding,owners->device,*network,[this]{owners->invalidate_math();},progress,std::move(prepared),[this]{owners->quiesce();});
  return true;
 }
 bool finish_request(const Request&r,const t38::ActorResult&result,bool healthy){
  bool cache_known=false;try{if(result.completion_known)cache_known=owners->idle_drain(identity(config,r.id));}catch(...){}
  if(retain_actor_owners(target&&target->completion_known(),draft&&draft->completion_known(),result.completion_known,cache_known)){restart_required=true;owners->prefix.invalidate();require_normal_reusable(true);}
  sequence_healthy=healthy&&result.context_valid;
  if(sequence_healthy){
   need(result.known_target_cursor==result.ledger.cursor&&result.draft_cursor==result.ledger.cursor&&owners->position()==result.ledger.cursor,"normal Actor final processed cursor");
   if(owners->prefix_enabled){try{
    for(size_t n=size_t(owners->prefix_reused);n<r.prompt.size();++n)owners->prefix.processed(r.prompt[n]);
    for(auto id:result.ledger.processed)owners->prefix.processed(id);
    need(owners->prefix.processed_count()==owners->position(),"normal Actor prefix committed cursor");
   }catch(...){sequence_healthy=false;owners->invalidate_math();throw;}}
   owners->prefix_new=r.prompt.size()-owners->prefix_reused;
  }
  if(owners->finish_prefix(r.id,sequence_healthy))owners->publish_prefix(target->logits());
  return cache_known;
 }
 std::string info()const{
  auto text=owners->info();if(!dspark_enabled(config))return text;
  need(!text.empty()&&text.back()=='}',"normal DSpark INFO object");text.pop_back();auto transfer=target?target->transfer_stats():t38::ActorTransferStats{};
  text+=",\"dspark_tap_primary_device_owned\":"+std::to_string(transfer.primary_device_owned)+",\"dspark_tap_secondary_device_owned\":"+std::to_string(transfer.secondary_device_owned)+",\"dspark_tap_bounce_host_owned\":"+std::to_string(transfer.bounce_host_owned)+",\"dspark_tap_peer_bytes\":"+std::to_string(transfer.peer_bytes)+",\"dspark_tap_bounce_d2h\":"+std::to_string(transfer.bounce_d2h)+",\"dspark_tap_bounce_h2d\":"+std::to_string(transfer.bounce_h2d)+",\"dspark_tap_physical_peak\":null";
  return text+",\"dspark_enabled\":true,\"dspark_width\":"+std::to_string(config.dspark_width)+",\"dspark_draft_credit\":"+std::to_string(*config.dspark_draft_credit)+",\"dspark_target_credit\":"+std::to_string(*config.dspark_target_credit)+",\"dspark_device_owned\":"+std::to_string(network?network->explicit_owned_bytes():0)+",\"dspark_completion_known\":"+(restart_required?"false":"true")+"}";
 }
};
std::unique_ptr<NormalActorOwners> normal_owners(const ProducerConfig&config,int device){
 auto root=std::make_unique<NormalActorOwners>();NormalRootRetention<NormalActorOwners>retention{root};root->config=config;
 root->artifact=std::make_unique<Artifact>(load(config));auto first=config.native_paths.empty()?config.artifact_root/source_specs[0].name:config.native_paths[0];root->engram=std::make_unique<engram::Config>(engram::inspect_metadata(first));
 if(dspark_enabled(config)){
  std::ifstream file(std::filesystem::u8path(config.dspark_prefix),std::ios::binary|std::ios::ate);need(bool(file),"DSpark accepted prefix metadata open");auto bytes=file.tellg();need(bytes>0&&bytes<=65536,"DSpark finite prefix metadata length");std::vector<uint8_t>prefix(size_t(bytes),uint8_t{});file.seekg(0);file.read(reinterpret_cast<char*>(prefix.data()),bytes);need(bool(file),"DSpark prefix metadata short read");
  root->asset=t38::inspect_prefix(prefix,t38::artifact_bytes);need(std::filesystem::file_size(std::filesystem::u8path(config.dspark_draft))==t38::artifact_bytes,"DSpark fixed asset size");
  auto credit=dspark_credits(config,root->asset,root->artifact->source_tensor("token_embd.weight").span.row_bytes,root->artifact->source_tensor("output.weight").span.row_bytes);
  root->config.dspark_draft_credit=credit.draft;root->config.dspark_target_credit=credit.target;root->config.dspark_deferred_host_bytes=credit.host_deferred;
  // Full persistent Network width residency precedes cache measurement. It is
  // already absent from available bytes, never subtracted again as a cache budget.
  retention.armed=true;root->make_network(device);retention.armed=false;
 }
 retention.armed=true;
 try{root->owners=std::make_unique<Owners>(*root->artifact,*root->engram,root->config,device);retention.armed=false;}
 catch(...){auto error=std::current_exception();if(!construction_unknown(error)){try{if(root->network)root->network->drain();retention.armed=false;}catch(...){}}std::rethrow_exception(error);}
 return root;
}
}
#ifdef STRATA_T28_CONSTRUCTION_TEST
}
namespace strata_ext::cache {bool t28_primary_drain_decision(int);bool t28_row_drain_decision(int);}
namespace strata_ext::deepseek41 {
int construction_policy_test(){
 unsigned checks=0;auto require=[&](bool value){++checks;need(value,"construction retry policy");};
 auto test=[&](std::exception_ptr e,bool allocation,bool unknown){require(construction_allocation(e)==allocation);require(construction_unknown(e)==unknown);uint64_t dt=1000,ht=1400;bool reduced=reduce_auto_allocation(e,true,true,200,dt,ht);require(reduced==(allocation&&!unknown));require(dt==(reduced?600:1000)&&ht==(reduced?800:1400));dt=1000;ht=1400;require(!reduce_auto_allocation(e,false,false,200,dt,ht)&&dt==1000&&ht==1400);};
 test(std::make_exception_ptr(strata::core::CudaError("cudaMalloc OOM",int(hipErrorOutOfMemory))),true,false);
 test(std::make_exception_ptr(std::bad_alloc{}),true,false);
 test(std::make_exception_ptr(std::bad_array_new_length{}),false,false);
 for(auto message:{"I/O buffer allocation","row IO allocation",hipGetErrorString(hipErrorOutOfMemory)})test(std::make_exception_ptr(std::runtime_error(message)),true,false);
 for(auto message:{"row full source actual size","shape geometry mismatch","row checked device pointer","unknown source out of memory",hipGetErrorString(hipErrorInvalidDevice)})test(std::make_exception_ptr(std::runtime_error(message)),false,false);
 test(std::make_exception_ptr(strata::core::CudaError("other device failure",int(hipErrorInvalidDevice))),false,false);
 test(std::make_exception_ptr(std::runtime_error("Row owner construction completion unknown; child restart required")),false,true);
 auto secondary_init=std::make_exception_ptr(std::bad_alloc{});for(auto cleanup:{std::exception_ptr{},secondary_init,std::make_exception_ptr(strata::core::CudaError("cleanup OOM",int(hipErrorOutOfMemory)))})try{cache::secondary_construction_result(secondary_init,false,cleanup);}catch(...){test(std::current_exception(),false,true);}
 uint64_t dt=1000,ht=1400;auto oom=std::make_exception_ptr(std::bad_alloc{});require(reduce_auto_allocation(oom,true,false,200,dt,ht)&&dt==600&&ht==1400);dt=ht=200;require(!reduce_auto_allocation(oom,true,true,200,dt,ht));
 auto source=std::make_exception_ptr(std::runtime_error("row full source actual size"));std::string message;try{std::rethrow_exception(source);}catch(const std::exception&x){message=x.what();}require(message=="row full source actual size");
 std::cout<<"{\"assertions\":"<<checks<<",\"actual_allocation_failure\":false,\"pure_failure_classification\":true}\n";return 0;
}
int construction_test(const ProducerConfig&c,const std::string&point){
 int n=0;hip(hipGetDeviceCount(&n));int device=-1;for(int i=0;i<n;++i){char pci[32]{};hip(hipDeviceGetPCIBusId(pci,32,i));if(c.primary_pci==pci)device=i;}need(device>=0,"test PCI absent");hip(hipSetDevice(device));auto artifact=load(c);
 bool primary=point.rfind("primary:",0)==0,row=point.rfind("row:",0)==0;need(primary||row,"test owner point");auto source=artifact.source_tensor("per_layer_token_embd.weight").source;
 auto make_primary=[&]{return std::make_unique<cache::PrimarySupply>(cache::SupplyConfig{1,1,65536,4,4,device,true});};
 auto make_row=[&]{return std::make_unique<cache::RowSupply>(cache::RowConfig{1,1,1,1,device},artifact,cache::RowSourceViews({{source,{source.original_path,0,source.original_size}}}));};
 std::cerr<<"T28_PHASE failed\n";_putenv_s("STRATA_T28_CTOR_FAULT",point.c_str());bool caught=false;try{if(primary){auto owner=make_primary();need(owner->try_close(),"unexpected constructed owner close");}else{auto owner=make_row();need(owner->try_close(),"unexpected constructed row close");}}catch(const std::exception&x){caught=std::string(x.what())=="injected construction checkpoint";} _putenv_s("STRATA_T28_CTOR_FAULT","");need(caught,"constructor fault not observed");
 std::cerr<<"T28_PHASE fresh\n";uint64_t owned=0;if(primary){auto owner=make_primary();owned=owner->stats().device_owned;need(owner->try_close(),"fresh Primary drain/close");}else{auto owner=make_row();owned=owner->stats().device_owned;need(owner->try_close(),"fresh Row drain/close");}
 need(cache::t28_primary_drain_decision(hipSuccess)&&!cache::t28_primary_drain_decision(hipErrorUnknown)&&cache::t28_row_drain_decision(hipSuccess)&&!cache::t28_row_drain_decision(hipErrorUnknown),"pure unknown-drain decision");
 std::cout<<"{\"fault\":"<<quote(point)<<",\"caught\":true,\"fresh_closed\":true,\"fresh_device_owned\":"<<owned<<",\"pure_unknown_control\":true,\"actual_driver_fault\":false,\"loaded_runtime_modules\":"<<modules()<<"}\n";return 0;
}
#ifdef STRATA_T38_SEED_CONSTRUCTION
#ifdef STRATA_T38_GLOBAL_FIXTURE
// T38_GLOBAL_LIFETIME_BEGIN -- actual native path, also finite CPU-extractable.
template<class Group>void fixture_global_complete_current(Group&g,bool context_valid){
 // A Body result selects healthy-vs-invalid cleanup only. Actual owners prove completion.
 need(g.target->completion_known()&&g.draft->completion_known(),"global fixture completion unknown");
 if(context_valid&&g.owners->request_valid()){g.target->drain();g.draft->drain();}
 else{g.target->invalidate_and_drain();g.draft->invalidate_and_drain();}
 need(g.target->completion_known()&&g.draft->completion_known(),"global fixture drain incomplete");
 g.network->drain();
 need(g.owners->idle_drain(g.full_identity),"global fixture Primary/Row drain unknown");
 need(g.owners->core->retire_projection_graph(),"global fixture graph retirement unknown");
}
template<class Group,class Next,class Construct>void fixture_global_start_next(Group&g,Next&&next,Construct construct){
 // The old Core remains alive until all three referencing native owners are gone.
 g.target.reset();g.draft.reset();g.network.reset();
 g.body=std::move(next.body);g.request_id=std::move(next.request_id);g.binding=std::move(next.binding);
 g.owners->request(g.request_id); // actual fresh Core; retain Primary/Row cache owners
 construct();
}
// T38_GLOBAL_LIFETIME_END
#endif
t38::ActorResult t38_actual_fixture(const ProducerConfig&c,const std::string&request_id,
 const std::string&draft_path,const t38::Asset&asset,uint64_t draft_credit,uint64_t target_credit,
 t38::RequestBinding binding,T38FixtureBody body
#ifdef STRATA_T38_GLOBAL_FIXTURE
 ,std::optional<T38FixtureNext> next
#endif
 ){
 need(c.mode=="single"&&!request_id.empty()&&!draft_path.empty()&&draft_credit&&target_credit&&bool(body),"seed fixture explicit caller");
 need(binding.owner&&binding.epoch==c.runtime_epoch&&binding.bundle==c.bundle_id&&!c.bundle_id.empty(),"seed fixture request binding");
#ifdef STRATA_T38_GLOBAL_FIXTURE
 if(next)need(!next->request_id.empty()&&next->request_id!=request_id&&bool(next->body)&&next->binding.owner&&next->binding.owner!=binding.owner&&next->binding.epoch==c.runtime_epoch&&next->binding.bundle==c.bundle_id,"global fixture explicit Next binding");
#endif
 struct Group {
  ProducerConfig config;std::string request_id,draft_path;t38::Asset asset;
  measurement::Identity full_identity;t38::RequestBinding binding;T38FixtureBody body;
#ifdef STRATA_T38_GLOBAL_FIXTURE
  std::optional<T38FixtureNext> next; // root held BEFORE any asynchronous construction
#endif
  std::unique_ptr<Artifact> artifact;std::unique_ptr<engram::Config> engram;
  std::unique_ptr<Owners> owners;std::unique_ptr<t38::DraftNetwork> network;
  std::unique_ptr<t38::NetworkActorDraft> draft;std::unique_ptr<t38::ActorTarget> target;
 };
 auto group=std::make_unique<Group>();
 struct Retain {std::unique_ptr<Group>&group;bool armed=false;~Retain()noexcept{if(armed)(void)group.release();}}retain{group};
 group->config=c;group->request_id=request_id;group->draft_path=draft_path;group->asset=asset;
 group->full_identity=identity(group->config,group->request_id);group->binding=std::move(binding);group->body=std::move(body);
#ifdef STRATA_T38_GLOBAL_FIXTURE
 group->next=std::move(next);
#endif
 int count=0,device=-1;hip(hipGetDeviceCount(&count));for(int i=0;i<count;++i){char pci[32]{};hip(hipDeviceGetPCIBusId(pci,32,i));if(group->config.primary_pci==pci)device=i;}
 need(device==0&&group->config.primary_pci=="0000:07:00.0","seed fixture actual ordinal/PCI binding");hip(hipSetDevice(device));
 group->artifact=std::make_unique<Artifact>(load(group->config));
 auto first=group->config.native_paths.empty()?group->config.artifact_root/source_specs[0].name:group->config.native_paths[0];
 group->engram=std::make_unique<engram::Config>(engram::inspect_metadata(first));
 // Arm BEFORE the constructor expression: Owners may retain partial members
 // that still reference these roots even when make_unique never returns.
 retain.armed=true;
 group->owners=std::make_unique<Owners>(*group->artifact,*group->engram,group->config,device);
 group->owners->request(group->request_id);
 group->network=std::make_unique<t38::DraftNetwork>(group->draft_path,group->asset,*group->artifact,group->binding,device,draft_credit,target_credit);
 group->draft=std::make_unique<t38::NetworkActorDraft>(*group->network);
 auto*stable=group.get();
 group->target=std::make_unique<t38::CoreTargetAdapter>(*group->owners->core,group->full_identity,group->binding,device,*group->network,[stable]{stable->owners->invalidate_math();});
 auto result=group->body(*group->target,*group->draft,*group->network,group->binding);
#ifdef STRATA_T38_GLOBAL_FIXTURE
 fixture_global_complete_current(*group,result.context_valid);
 if(group->next){
  // Keep the whole Group retention armed through second construction/Body/cleanup.
  auto following=std::move(*group->next);group->next.reset();
  fixture_global_start_next(*group,std::move(following),[&]{
   group->full_identity=identity(group->config,group->request_id);
   group->network=std::make_unique<t38::DraftNetwork>(group->draft_path,group->asset,*group->artifact,group->binding,device,draft_credit,target_credit);
   group->draft=std::make_unique<t38::NetworkActorDraft>(*group->network);
   group->target=std::make_unique<t38::CoreTargetAdapter>(*group->owners->core,group->full_identity,group->binding,device,*group->network,[stable]{stable->owners->invalidate_math();});
  });
  result=group->body(*group->target,*group->draft,*group->network,group->binding);
  fixture_global_complete_current(*group,result.context_valid);
 }
#else
 // The Body's ActorResult is diagnostic, never an owner completion proof.
 need(group->target->completion_known()&&group->draft->completion_known(),"seed body completion unknown");
 group->target->drain();group->draft->drain();group->network->drain();
 need(group->target->completion_known()&&group->draft->completion_known(),"seed actual drains incomplete");
 need(group->owners->idle_drain(group->full_identity),"seed actual Primary/Row drain unknown");
 need(group->owners->core->retire_projection_graph(),"seed actual graph retirement unknown");
#endif
 group->body={};group->target.reset();group->draft.reset();group->network.reset();
 need(group->owners->clear(group->request_id),"seed source owner close unknown");group->owners.reset();
 retain.armed=false;return result;
}
namespace seed_prefix_fixture {
constexpr uint64_t metadata_limit=4*1024*1024; // finite fixture only, not a normal setting
struct Read {std::string path,sha;std::vector<uint8_t>bytes;BY_HANDLE_FILE_INFORMATION stamp{};};
bool same_stamp(const BY_HANDLE_FILE_INFORMATION&a,const BY_HANDLE_FILE_INFORMATION&b){return a.dwVolumeSerialNumber==b.dwVolumeSerialNumber&&a.nFileIndexHigh==b.nFileIndexHigh&&a.nFileIndexLow==b.nFileIndexLow&&a.nFileSizeHigh==b.nFileSizeHigh&&a.nFileSizeLow==b.nFileSizeLow&&CompareFileTime(&a.ftLastWriteTime,&b.ftLastWriteTime)==0;}
std::string hash(const std::vector<uint8_t>&bytes){
 BCRYPT_ALG_HANDLE algorithm=nullptr;BCRYPT_HASH_HANDLE value=nullptr;DWORD size=0,written=0;std::vector<uint8_t>object;
 struct Close{BCRYPT_ALG_HANDLE&a;BCRYPT_HASH_HANDLE&h;~Close(){if(h)BCryptDestroyHash(h);if(a)BCryptCloseAlgorithmProvider(a,0);}}close{algorithm,value};
 need(BCryptOpenAlgorithmProvider(&algorithm,BCRYPT_SHA256_ALGORITHM,nullptr,0)>=0,"seed prefix SHA provider");need(BCryptGetProperty(algorithm,BCRYPT_OBJECT_LENGTH,reinterpret_cast<PUCHAR>(&size),sizeof(size),&written,0)>=0,"seed prefix SHA object length");object.resize(size);std::array<uint8_t,32>digest{};
 need(BCryptCreateHash(algorithm,&value,object.data(),size,nullptr,0,0)>=0,"seed prefix SHA create");need(bytes.size()<=ULONG_MAX&&BCryptHashData(value,const_cast<PUCHAR>(bytes.data()),ULONG(bytes.size()),0)>=0,"seed prefix SHA bytes");need(BCryptFinishHash(value,digest.data(),ULONG(digest.size()),0)>=0,"seed prefix SHA finish");
 const char*hex="0123456789abcdef";std::string result;for(auto b:digest){result+=hex[b>>4];result+=hex[b&15];}return result;
}
Read read(const std::string&path,uint64_t maximum){
 auto p=std::filesystem::u8path(path);need(p.is_absolute(),"seed prefix absolute metadata path");HANDLE file=CreateFileW(p.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);need(file!=INVALID_HANDLE_VALUE,"seed prefix metadata open");struct Close{HANDLE file;~Close(){CloseHandle(file);}}close{file};
 Read result;result.path=path;BY_HANDLE_FILE_INFORMATION after{};need(GetFileInformationByHandle(file,&result.stamp),"seed prefix metadata before stamp");uint64_t size=(uint64_t(result.stamp.nFileSizeHigh)<<32)|result.stamp.nFileSizeLow;
 need(size&&size<=maximum&&size<=UINT32_MAX,"seed prefix finite metadata length");result.bytes.resize(size_t(size));DWORD count=0;need(ReadFile(file,result.bytes.data(),DWORD(size),&count,nullptr)&&count==size,"seed prefix metadata short read");need(GetFileInformationByHandle(file,&after)&&same_stamp(result.stamp,after),"seed prefix metadata changed during read");result.sha=hash(result.bytes);return result;
}
void same_read(const Read&a,const Read&b){need(a.path==b.path&&a.sha==b.sha&&a.bytes==b.bytes&&same_stamp(a.stamp,b.stamp),"seed prefix input replaced or changed");}
void utf8(const std::vector<uint8_t>&bytes){need(!bytes.empty()&&bytes.size()<=INT_MAX&&std::find(bytes.begin(),bytes.end(),0)==bytes.end(),"seed prefix empty/NUL input");need(!(bytes.size()>=3&&bytes[0]==0xef&&bytes[1]==0xbb&&bytes[2]==0xbf),"seed prefix UTF8 BOM");need(MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,reinterpret_cast<const char*>(bytes.data()),int(bytes.size()),nullptr,0)>0,"seed prefix invalid UTF8");}
struct Input {Read manifest;ProducerConfig config;std::map<std::string,std::string>caller;std::map<std::string,std::pair<std::string,std::string>>receipts;std::vector<Read>authorities;t38::Asset asset;t38::RequestBinding binding;};
Input parse(Read manifest){
 utf8(manifest.bytes);Input input;input.manifest=std::move(manifest);std::map<std::string,std::string>producer,identity_fields;
 const std::set<std::string>pk={"artifact_root","primary_pci","bundle_id","runtime_epoch","context","tile_bytes","tile_rows","active_batch","device_cache_payload_bytes","ram_cache_payload_bytes","mode","source1","source2","source3","source4","source5","source6","source7","source8","source9"},ck={"request_id","draft_path","draft_prefix_path","draft_credit","target_credit","owner","epoch","bundle","device_ordinal"},ik={"fixture_sha256","asset_sha256","bundle_sha256","request_id","epoch","phase"},rk={"target","draft","draft_prefix","input_lineage"};
 bool schema=false,prompt=false;std::istringstream lines(std::string(input.manifest.bytes.begin(),input.manifest.bytes.end()));std::string line;
 while(std::getline(lines,line)){if(!line.empty()&&line.back()=='\r')line.pop_back();need(!line.empty()&&line.back()!='\t',"seed prefix empty/trailing field");std::vector<std::string>v;std::istringstream fields(line);std::string field;while(std::getline(fields,field,'\t')){need(!field.empty()&&field.find_first_of("\r\n")==std::string::npos,"seed prefix field control/empty");v.push_back(field);}
  if(v[0]=="schema"){need(!schema&&v.size()==2&&v[1]=="T38-seed-input-v1","seed prefix schema");schema=true;}
  else if(v[0]=="prompt"){need(!prompt&&v==std::vector<std::string>({"prompt","3","37","1024"}),"seed prefix P3");prompt=true;}
  else if(v[0]=="receipt"){need(v.size()==4&&rk.count(v[1])&&std::filesystem::u8path(v[2]).is_absolute()&&v[3].size()==64&&v[3].find_first_not_of("0123456789abcdef")==std::string::npos,"seed prefix receipt row");need(input.receipts.emplace(v[1],std::make_pair(v[2],v[3])).second,"seed prefix duplicate receipt");}
  else{need(v.size()==3,"seed prefix field columns");auto*out=v[0]=="producer"?&producer:v[0]=="caller"?&input.caller:v[0]=="identity"?&identity_fields:nullptr;const auto*keys=v[0]=="producer"?&pk:v[0]=="caller"?&ck:v[0]=="identity"?&ik:nullptr;need(out&&keys&&keys->count(v[1]),"seed prefix unknown row/field");need(out->emplace(v[1],v[2]).second,"seed prefix duplicate row");}
 }
 need(schema&&prompt&&producer.size()==pk.size()&&input.caller.size()==ck.size()&&identity_fields.size()==ik.size()&&input.receipts.size()==rk.size(),"seed prefix missing rows");auto&c=input.caller;auto&i=identity_fields;auto&p=producer;
 need(p.at("mode")=="single"&&p.at("primary_pci")=="0000:07:00.0"&&c.at("device_ordinal")=="0"&&i.at("phase")=="prefill","seed prefix finite mode/device/phase");
 for(auto k:{"runtime_epoch","context","tile_bytes","tile_rows","active_batch","device_cache_payload_bytes","ram_cache_payload_bytes"})need(number(p.at(k))>0,"seed prefix positive producer value");for(auto k:{"owner","epoch","draft_credit","target_credit"})need(number(c.at(k))>0,"seed prefix positive caller value");
 need(number(p.at("context"))>=3&&c.at("epoch")==p.at("runtime_epoch")&&i.at("epoch")==c.at("epoch")&&c.at("bundle")==p.at("bundle_id")&&i.at("request_id")==c.at("request_id"),"seed prefix identity binding");for(auto k:{"fixture_sha256","asset_sha256","bundle_sha256"})need(i.at(k)==c.at("bundle"),"seed prefix full Identity");
 for(auto k:{"draft_path","draft_prefix_path"})need(std::filesystem::u8path(c.at(k)).is_absolute(),"seed prefix caller absolute path");need(c.at("draft_prefix_path")==input.receipts.at("draft_prefix").first,"seed prefix prefix receipt path");
 auto&cfg=input.config;cfg.artifact_root=std::filesystem::u8path(p.at("artifact_root"));need(cfg.artifact_root.is_absolute(),"seed prefix artifact root");cfg.primary_pci=p.at("primary_pci");cfg.bundle_id=p.at("bundle_id");cfg.mode=p.at("mode");cfg.runtime_epoch=number(p.at("runtime_epoch"));cfg.context=number(p.at("context"));cfg.tile_bytes=number(p.at("tile_bytes"));cfg.tile_rows=number(p.at("tile_rows"));cfg.active_batch=number(p.at("active_batch"));cfg.device_cache_payload_bytes=number(p.at("device_cache_payload_bytes"));cfg.ram_cache_payload_bytes=number(p.at("ram_cache_payload_bytes"));
 for(unsigned n=1;n<=9;++n){auto path=std::filesystem::u8path(p.at("source"+std::to_string(n)));need(path.is_absolute(),"seed prefix native absolute path");cfg.native_paths.push_back(std::move(path));}input.binding={number(c.at("owner")),number(c.at("epoch")),c.at("bundle")};return input;
}
// Only the eight-field fixture binding object: no product JSON/parser API.
struct BindingJson {
 const std::string&text;size_t at=0;
 void space(){while(at<text.size()&&(text[at]==' '||text[at]=='\t'||text[at]=='\r'||text[at]=='\n'))++at;}
 void take(char c){space();need(at<text.size()&&text[at++]==c,"seed prefix binding JSON punctuation");}
 uint32_t hex4(){need(at+4<=text.size(),"seed prefix binding unicode short");uint32_t value=0;for(unsigned n=0;n<4;++n){char c=text[at++];unsigned x=c>='0'&&c<='9'?unsigned(c-'0'):c>='a'&&c<='f'?unsigned(c-'a'+10):c>='A'&&c<='F'?unsigned(c-'A'+10):16;need(x<16,"seed prefix binding unicode hex");value=value*16+x;}return value;}
 void codepoint(std::string&out,uint32_t c){if(c<0x80)out+=char(c);else if(c<0x800){out+=char(0xc0|(c>>6));out+=char(0x80|(c&63));}else if(c<0x10000){out+=char(0xe0|(c>>12));out+=char(0x80|((c>>6)&63));out+=char(0x80|(c&63));}else{out+=char(0xf0|(c>>18));out+=char(0x80|((c>>12)&63));out+=char(0x80|((c>>6)&63));out+=char(0x80|(c&63));}}
 std::string string(){take('"');std::string out;while(at<text.size()){unsigned char c=text[at++];if(c=='"')return out;need(c>=32,"seed prefix binding JSON control");if(c!='\\'){out+=char(c);continue;}need(at<text.size(),"seed prefix binding escape short");char e=text[at++];if(e=='"'||e=='\\'||e=='/')out+=e;else if(e=='b')out+='\b';else if(e=='f')out+='\f';else if(e=='n')out+='\n';else if(e=='r')out+='\r';else if(e=='t')out+='\t';else if(e=='u'){auto u=hex4();if(u>=0xd800&&u<=0xdbff){need(at+2<=text.size()&&text[at]=='\\'&&text[at+1]=='u',"seed prefix binding surrogate pair");at+=2;auto lo=hex4();need(lo>=0xdc00&&lo<=0xdfff,"seed prefix binding low surrogate");u=0x10000+((u-0xd800)<<10)+lo-0xdc00;}else need(u<0xdc00||u>0xdfff,"seed prefix binding lone surrogate");codepoint(out,u);}else need(false,"seed prefix binding escape");}throw std::runtime_error("seed prefix binding unterminated string");}
 std::map<std::string,std::string> object(){std::map<std::string,std::string>out;const std::set<std::string>strings={"schema","manifest_path","manifest_bytes_dec","manifest_sha256","volume_serial_dec","file_id_dec","last_write_FILETIME_dec"};bool same=false;take('{');for(unsigned n=0;;++n){space();if(at<text.size()&&text[at]=='}'){++at;break;}if(n)take(',');auto key=string();take(':');space();if(key=="read_identity_before_after_equal"){need(!same&&text.compare(at,4,"true")==0,"seed prefix binding identity Boolean");at+=4;same=true;}else{need(strings.count(key)&&out.emplace(key,string()).second,"seed prefix binding unknown/duplicate key");}}space();need(at==text.size()&&same&&out.size()==strings.size(),"seed prefix binding exact object");return out;}
};
void verify_binding(const Read&initial,const Read&final,const Read&saved,const Read&binding){
 same_read(initial,final);need(saved.sha==initial.sha&&saved.bytes==initial.bytes,"seed prefix saved manifest copy");utf8(binding.bytes);std::string text(binding.bytes.begin(),binding.bytes.end());auto values=BindingJson{text}.object();
 need(values.at("schema")=="T38-seed-input-binding-v1"&&values.at("manifest_path")==initial.path&&values.at("manifest_sha256")==initial.sha,"seed prefix factory binding strings");
 auto file_id=(uint64_t(initial.stamp.nFileIndexHigh)<<32)|initial.stamp.nFileIndexLow;auto modified=(uint64_t(initial.stamp.ftLastWriteTime.dwHighDateTime)<<32)|initial.stamp.ftLastWriteTime.dwLowDateTime;
 need(number(values.at("manifest_bytes_dec"))==initial.bytes.size()&&number(values.at("volume_serial_dec"))<=UINT32_MAX&&number(values.at("volume_serial_dec"))==initial.stamp.dwVolumeSerialNumber&&number(values.at("file_id_dec"))==file_id&&number(values.at("last_write_FILETIME_dec"))==modified,"seed prefix factory binding exact integers");
}
}
int t38_seed_fixture_entry(const std::string&manifest_path,const std::string&output_directory){
 using namespace seed_prefix_fixture;auto input=std::make_shared<Input>(parse(read(manifest_path,65536)));auto output=std::filesystem::u8path(output_directory);need(output.is_absolute()&&!std::filesystem::exists(output),"seed prefix new absolute output");
 for(const auto&entry:input->receipts){auto path=std::filesystem::u8path(entry.second.first).lexically_normal();need(_wcsicmp(path.c_str(),std::filesystem::u8path(input->caller.at("draft_path")).lexically_normal().c_str())!=0,"seed receipt cannot be original draft body");for(const auto&source:input->config.native_paths)need(_wcsicmp(path.c_str(),source.lexically_normal().c_str())!=0,"seed receipt cannot be original target body");auto authority=read(entry.second.first,metadata_limit);need(authority.sha==entry.second.second,"seed prefix authority receipt changed");if(entry.first=="draft_prefix")input->asset=t38::inspect_prefix(authority.bytes,t38::artifact_bytes);input->authorities.push_back(std::move(authority));}
 same_read(input->manifest,read(manifest_path,65536));
#ifdef STRATA_T38_GLOBAL_FIXTURE
 auto global=make_t38_global_fixture(manifest_path,output_directory);
 input->config.fixture_audit_root=std::move(global.audit);
 auto factory=std::move(global.body);auto next=std::move(global.next);
 if(next){
  auto expected=next->binding;auto callback=std::move(next->body);
  next->body=[input,expected,callback=std::move(callback)](t38::ActorTarget&a,t38::ActorDraft&d,t38::DraftNetwork&n,const t38::RequestBinding&binding){need(binding.owner==expected.owner&&binding.epoch==expected.epoch&&binding.bundle==expected.bundle,"global prefix Next binding");return callback(a,d,n,binding);};
 }
#else
 auto factory=make_t38_seed_body(manifest_path,output_directory);
#endif
 need(bool(factory),"seed prefix empty factory body");
 verify_binding(input->manifest,read(manifest_path,65536),read((output/"input-manifest.tsv").u8string(),65536),read((output/"input-binding.json").u8string(),metadata_limit));
 // Copies retain PREFIX receipt bytes and leaf shared callback state together.
 T38FixtureBody body=[input,factory=std::move(factory)](t38::ActorTarget&a,t38::ActorDraft&d,t38::DraftNetwork&n,const t38::RequestBinding&binding){need(binding.owner==input->binding.owner&&binding.epoch==input->binding.epoch&&binding.bundle==input->binding.bundle,"seed prefix body binding");return factory(a,d,n,binding);};
 auto result=t38_actual_fixture(input->config,input->caller.at("request_id"),input->caller.at("draft_path"),input->asset,number(input->caller.at("draft_credit")),number(input->caller.at("target_credit")),input->binding,std::move(body)
#ifdef STRATA_T38_GLOBAL_FIXTURE
 ,std::move(next)
#endif
 );
 std::cout<<"{\"seed_fixture_bridge\":true,\"actor_ledger_success_claimed\":false,\"known_target_cursor\":"<<result.known_target_cursor<<",\"draft_cursor\":"<<result.draft_cursor<<",\"body_completion_known\":"<<(result.completion_known?"true":"false")<<"}\n";need(bool(std::cout),"seed prefix fixture diagnostic output");return 0;
}
#endif
int prefill_control_test(const ProducerConfig&c,const std::filesystem::path&output){
 int n=0;hip(hipGetDeviceCount(&n));int device=-1;for(int i=0;i<n;++i){char pci[32]{};hip(hipDeviceGetPCIBusId(pci,32,i));if(c.primary_pci==pci)device=i;}need(device>=0,"test PCI absent");hip(hipSetDevice(device));auto artifact=load(c);auto first=c.native_paths.empty()?c.artifact_root/source_specs[0].name:c.native_paths[0];auto e=engram::inspect_metadata(first);
 ProducerConfig fixed=c;fixed.device_cache_payload_bytes=fixed.tile_bytes+264;fixed.ram_cache_payload_bytes=fixed.tile_bytes+264;Owners owners(artifact,e,fixed,device);std::vector<uint32_t>tokens{0,128803,128804,128822};uint64_t checks=0;
 auto require=[&](bool b){++checks;need(b,"prefill control assertion");};
 auto invalid=[&]{bool caught=false;try{owners.core->step(0,owners.core->position());}catch(const std::exception&){caught=true;}require(caught);};
 owners.request("before-first");auto cancelled=owners.core->prefill(tokens,0,{},[](uint64_t,uint64_t){return false;});require(cancelled.cancelled&&cancelled.processed==0&&cancelled.rows==0&&cancelled.logits.empty()&&owners.core->position()==0);require(owners.core->runtime_stats().requested_output_or_fixture_download_bytes==0);invalid();
 owners.request("callback-error");bool error=false;try{owners.core->prefill(tokens,0,{},[](uint64_t,uint64_t)->bool{throw std::runtime_error("controlled callback error");});}catch(const std::exception&x){error=std::string(x.what())=="controlled callback error";}require(error);invalid();
 owners.request("within-layer-cancel");uint64_t layer_calls=0;cancelled=owners.core->prefill(tokens,0,{},[&](uint64_t done,uint64_t total){require(done==0&&total==tokens.size());return ++layer_calls<2;});
 require(cancelled.cancelled&&cancelled.processed==0&&cancelled.rows==0&&owners.core->position()==0&&layer_calls==2);auto partial=owners.core->runtime_stats();require(partial.state_positions[0]==1&&partial.state_positions[1]==0);require(partial.requested_output_or_fixture_download_bytes==0);invalid();
 owners.request("within-layer-error");uint64_t error_calls=0;error=false;try{owners.core->prefill(tokens,0,{},[&](uint64_t done,uint64_t total)->bool{require(done==0&&total==tokens.size());if(++error_calls==2)throw std::runtime_error("controlled layer callback error");return true;});}catch(const std::exception&x){error=std::string(x.what())=="controlled layer callback error";}
 require(error&&error_calls==2);partial=owners.core->runtime_stats();require(partial.state_positions[0]==1&&partial.requested_output_or_fixture_download_bytes==0);invalid();
 owners.request("after-one");std::vector<uint64_t>progress;cancelled=owners.core->prefill(tokens,0,{},[&](uint64_t done,uint64_t total){require(total==tokens.size());progress.push_back(done);return done<1;});
 require(cancelled.cancelled&&cancelled.processed==1&&cancelled.rows==0&&cancelled.logits.empty()&&owners.core->position()==1);require(progress.size()==42&&std::all_of(progress.begin(),progress.end()-1,[](uint64_t n){return n==0;})&&progress.back()==1);require(owners.core->runtime_stats().requested_output_or_fixture_download_bytes==0);invalid();
 owners.request("fresh-after-cancel");auto normal=owners.core->prefill({tokens[0],tokens[1]},0);require(!normal.cancelled&&normal.processed==2&&normal.rows==1&&normal.vocabulary==129280&&normal.logits.size()==129280&&owners.core->position()==2);require(owners.core->runtime_stats().requested_output_or_fixture_download_bytes==129280*4);
 std::ofstream file(output,std::ios::binary);file.write(reinterpret_cast<const char*>(normal.logits.data()),std::streamsize(normal.logits.size()*4));need(bool(file),"prefill fixture output write");
 std::cout<<"{\"assertions\":"<<checks<<",\"layer_cancelled_processed\":0,\"layer_cancelled_position\":0,\"layer_callback_count\":2,\"layer0_real_state_position\":1,\"layer_exception\":true,\"after_one_callback_count\":"<<progress.size()<<",\"cancelled_processed\":1,\"cancelled_position\":1,\"cancelled_logits_d2h\":0,\"fresh_processed\":2,\"fresh_rows\":1,\"fresh_logits_d2h\":517120,\"normal_full_logits\":false,\"loaded_runtime_modules\":"<<modules()<<"}\n";return 0;
}

#endif
int serve(const ProducerConfig&c){
 // Validate the existing DTO context before any allocation or worker start.
 protocol::GenerationEmitter startup_binding({"startup",c.runtime_epoch,c.bundle_id,revision,"100a9451a0244c0138ae893760da2853a90592933a8ecc993ac3ebd60b9e2924","deepseek41","gpt2","joyai-llm",129280},true);
 int count=0;hip(hipGetDeviceCount(&count));int selected=-1;for(int i=0;i<count;++i){char pci[32]{};hip(hipDeviceGetPCIBusId(pci,sizeof(pci),i));if(c.primary_pci==pci)selected=i;}need(selected>=0,"requested actual primary PCI absent");hip(hipSetDevice(selected));
 validate_dspark_config(c);auto normal=normal_owners(c,selected);NormalRootRetention<NormalActorOwners>normal_retention{normal};auto&owners=*normal->owners;
 std::mutex output,control;std::string current;std::atomic<int>stop{0};std::atomic<bool>busy{false};std::thread worker;
 auto emit=[&](const std::string&s){std::lock_guard<std::mutex>lock(output);std::cout<<s<<std::endl;if(!std::cout)throw std::runtime_error("native output write/flush failed");};
 owners.graph_complete_request(true,false);emit("INFO "+normal->info());emit("READY "+std::to_string(c.context)+" stop");std::string line;
 while(std::getline(std::cin,line)){
  std::istringstream fields(line);std::string command;fields>>command;
  if(command=="STOP"||command=="QUIT"){
   auto request=parse_stop(line);bool applies=command=="QUIT";
   {std::lock_guard<std::mutex>lock(control);applies=applies||(request.valid&&(request.unscoped||(request.id==current&&request.epoch==c.runtime_epoch)));if(applies&&busy){if(command=="QUIT"||request.reason==1)stop.store(1);else{int expected=0;stop.compare_exchange_strong(expected,2);}}}
   if(command=="QUIT")break;continue;
  }
  if(command=="INFO"){if(!busy)emit("INFO "+normal->info());continue;}
  if(command!="GEN"){emit("ERR unknown command");continue;}
  if(busy){emit("ERR request already active");continue;}if(worker.joinable())worker.join();
  Request request;try{require_normal_reusable(normal->restart_required);request=parse_request(line,c.runtime_epoch,c.routing);need(request.prompt.size()<c.context&&request.maximum<=c.context-request.prompt.size(),"prompt plus resolved output exceeds context");}catch(const std::exception&x){emit("ERR "+std::string(x.what()));continue;}
  {std::lock_guard<std::mutex>lock(control);current=request.id;stop.store(0);busy=true;}
  worker=std::thread([&,r=std::move(request)]{protocol::Context context{r.id,c.runtime_epoch,c.bundle_id,revision,"100a9451a0244c0138ae893760da2853a90592933a8ecc993ac3ebd60b9e2924","deepseek41","gpt2","joyai-llm",129280};protocol::GenerationEmitter emitter(context,true);emit(emitter.begin());protocol::Finish finish=protocol::Finish::Error;std::string origin="error";uint64_t generated=0;bool graph_completion_known=false;owners.graph_begin_request();
   try{hip(hipSetDevice(selected));owners.begin_routing(r.routing,r.id);if(!r.routing.exact())emit("INFO "+owners.info());uint64_t seed=r.seed?*r.seed:(uint64_t(std::random_device{}())<<32)^std::random_device{}();
    if(dspark_enabled(c)){
     auto progress=[&](uint64_t done,uint64_t total){emit("PP "+std::to_string(done)+" "+std::to_string(total));return stop.load()==0;};
     if(normal->begin_request(r,stop,progress)){
      owners.graph_tap_selected=true;
      t38::RequestActor actor(*normal->target,*normal->draft,normal->binding,seed);
      auto result=actor.run(r.prompt,r.maximum,c.dspark_width,r.sampling,[&]{return actor_stop(stop.load());},[&](const SampledToken&token){if(r.sampling.logprobs)emit(emitter.tokens({token.id},{{token.logprob,token.alternatives}}));else emit(emitter.tokens({token.id}));++generated;});
      need(generated==result.ledger.emitted.size(),"Actor acknowledged emission count mismatch");auto terminal=actor_finish(result.ledger.finish,stop.load(),result.error);finish=terminal.finish;origin=terminal.origin;
      const bool cache_known=finish_actor_boundary(result.ledger.finish==t38::Finish::Invalid,result.error,emit,[&]{return normal->finish_request(r,result,terminal.healthy);});
      graph_completion_known=result.completion_known&&normal->target->completion_known()&&normal->draft->completion_known()&&cache_known;
     }else{auto terminal=actor_finish(t38::Finish::Cancel,stop.load(),{});finish=terminal.finish;origin=terminal.origin;}
    }else{
    auto history=r.prompt;history.reserve(size_t(c.context));owners.last_request_history_capacity_bytes=history.capacity()*4;RequestSampler sampler(seed);
    auto prefill=owners.prefill_request(r.id,r.prompt,[&](uint64_t done,uint64_t total){emit("PP "+std::to_string(done)+" "+std::to_string(total));return stop.load()==0;},stop);auto logits=std::move(prefill.logits);const auto*raw=owners.cached_request_logits?&owners.prefix.logits():&logits;owners.last_request_raw_logit_capacity_bytes=logits.capacity()*4;
    while(!prefill.cancelled&&generated<r.maximum&&stop.load()==0){auto token=sampler.sample(*raw,history,r.sampling);if(r.sampling.logprobs)emit(emitter.tokens({token.id},{{token.logprob,token.alternatives}}));else emit(emitter.tokens({token.id}));++generated;history.push_back(token.id);if(token.id==1){finish=protocol::Finish::Stop;origin="eos";break;}if(generated==r.maximum){finish=protocol::Finish::Length;origin="limit";break;}if(stop.load()!=0)break;logits=owners.step(token.id);owners.processed_step(token.id);raw=&logits;owners.last_request_raw_logit_capacity_bytes=logits.capacity()*4;}
    if(stop.load()){finish=stop.load()==1?protocol::Finish::Cancel:protocol::Finish::Stop;origin=stop.load()==1?"user_cancel":"recipe";}
    const bool healthy=!prefill.cancelled&&stop.load()==0&&(finish==protocol::Finish::Stop||finish==protocol::Finish::Length);
    if(owners.finish_prefix(r.id,healthy))owners.publish_prefix(*raw);
    graph_completion_known=true;
    }
   owners.finish_routing(graph_completion_known);
   }catch(const std::exception&x){graph_completion_known=false;owners.prefix.invalidate();std::string message=x.what();finish=message.find("nonfinite")!=std::string::npos?protocol::Finish::NonFinite:protocol::Finish::Error;origin=finish==protocol::Finish::NonFinite?"nonfinite":"error";emit("ERR "+message);if(!normal->restart_required){try{if(!owners.idle_drain(identity(c,r.id)))normal->restart_required=true;}catch(...){normal->restart_required=true;}}if(normal->restart_required)emit("ERR owner completion unknown; restart required");}
   owners.graph_complete_request(graph_completion_known,true);
   {std::lock_guard<std::mutex>lock(control);try{if(stop.load()!=0||finish==protocol::Finish::Error||finish==protocol::Finish::NonFinite)owners.prefix.invalidate();if(stop.load()==1&&finish!=protocol::Finish::Error&&finish!=protocol::Finish::NonFinite){finish=protocol::Finish::Cancel;origin="user_cancel";}if(!owners.graph_frame.empty())emit(owners.graph_frame);emit(emitter.finish(finish,origin));emit("DONE "+std::to_string(generated));current.clear();busy=false;}catch(...){owners.prefix.invalidate();throw;}}
  });
 }
 if(busy)stop.store(1);if(worker.joinable())worker.join();return 0;
}
}
int main(int argc,char**argv){try{
 if(argc==2&&std::string(argv[1])=="--identity"){std::cout<<"{\"source_set_sha256\":\""<<T28_SOURCE_ID<<"\",\"graph_math_abi\":\""<<STRATA_GRAPH_BUILD_ABI<<"\",\"normal_audit_d2h\":false}\n";return 0;}
 #ifdef STRATA_T28_CONSTRUCTION_TEST
#ifdef STRATA_T38_SEED_CONSTRUCTION
 if(argc==5&&std::string(argv[1])=="--t38-seed-input"&&std::string(argv[3])=="--t38-seed-output")return strata_ext::deepseek41::t38_seed_fixture_entry(argv[2],argv[4]);
#endif
 if(argc==2&&std::string(argv[1])=="--construction-policy-test")return strata_ext::deepseek41::construction_policy_test();
 if(argc==3&&std::string(argv[1])=="--parse-stop"){
  auto c=strata_ext::deepseek41::parse_stop(argv[2]);std::cout<<"{\"valid\":"<<(c.valid?"true":"false")<<",\"unscoped\":"<<(c.unscoped?"true":"false")<<",\"matches_current\":"<<(c.valid&&(c.unscoped||(c.id=="current"&&c.epoch==1))?"true":"false")<<",\"reason\":"<<c.reason<<"}\n";return 0;
 }
 if(argc==3&&std::string(argv[1])=="--parse-gen"){
  auto r=strata_ext::deepseek41::parse_request(argv[2],1);auto sampled=strata_ext::deepseek41::sample_logits(std::vector<float>(129280),r.prompt,r.sampling,.999999);
  std::cout<<"{\"top_k\":"<<r.sampling.top_k<<",\"seed\":"<<(r.seed?std::to_string(*r.seed):"null")<<",\"frequency_penalty\":"<<r.sampling.frequency_penalty<<",\"presence_penalty\":"<<r.sampling.presence_penalty<<",\"sampled_tail\":"<<sampled.id<<",\"last_n_present\":"<<(r.sampling.penalty_last_n?"true":"false")<<"}\n";return 0;
 }
#endif
 strata_ext::deepseek41::ProducerConfig c;bool run=false;std::map<std::string,std::string>o;
#ifdef STRATA_T28_CONSTRUCTION_TEST
 if(argc==2&&std::string(argv[1])=="--mode-policy-test")return strata_ext::deepseek41::mode_policy_test();
 if(argc==2&&std::string(argv[1])=="--mode-failure-test")return strata_ext::deepseek41::mode_failure_test();
#endif
 for(int i=1;i<argc;++i){std::string key=argv[i];if(key=="--serve"){run=true;continue;}if(i+1>=argc||!o.emplace(key,argv[++i]).second)throw std::runtime_error("command option/value");}
 auto take=[&](const char*k,std::string def=""){auto it=o.find(k);if(it==o.end())return def;auto s=it->second;o.erase(it);return s;};
 c.projection_graph=strata_ext::deepseek41::projection_graph_choice(take("--projection-graph","off"));c.mode=take("--mode","single");c.routing.primary=strata_ext::deepseek41::routing::coefficient(take("--routing-primary-bonus","0"));c.routing.secondary=strata_ext::deepseek41::routing::coefficient(take("--routing-secondary-bonus","0"));c.routing.ssd=strata_ext::deepseek41::routing::coefficient(take("--routing-ssd-penalty","0"));c.secondary_pci=take("--secondary-pci");c.artifact_root=std::filesystem::u8path(take("--artifact-root"));c.primary_pci=take("--primary-pci");c.bundle_id=take("--bundle-id");c.runtime_epoch=std::stoull(take("--runtime-epoch"));c.context=std::stoull(take("--context"));c.tile_bytes=std::stoull(take("--tile-bytes","2097152"));c.tile_rows=std::stoull(take("--tile-rows","256"));c.active_batch=std::stoull(take("--active-batch","8"));
 if(o.count("--secondary-experts"))c.secondary_experts=strata_ext::deepseek41::expert_ids(take("--secondary-experts"));
 if(o.count("--layer-cut")){auto cut=strata_ext::deepseek41::number(take("--layer-cut"));if(cut<1||cut>39)throw std::runtime_error("layer cut 1..39");c.layer_cut=uint32_t(cut);}
 strata_ext::deepseek41::mode_options(c);
 for(unsigned i=1;i<=9;++i){auto name="--source"+std::to_string(i);auto path=take(name.c_str());if(!path.empty())c.native_paths.push_back(std::filesystem::u8path(path));}
 auto budget=[&](const char*k){auto x=take(k,"auto");return x=="auto"?std::optional<uint64_t>{}:std::optional<uint64_t>{std::stoull(x)};};c.device_cache_payload_bytes=budget("--device-cache-payload-bytes");c.ram_cache_payload_bytes=budget("--ram-cache-payload-bytes");{auto value=take("--secondary-device-cache-payload-bytes","auto");if(value!="auto"){auto bytes=strata_ext::deepseek41::number(value);if(!bytes)throw std::runtime_error("secondary payload bytes positive");c.secondary_device_cache_payload_bytes=bytes;}}c.auto_cache_fraction=std::stod(take("--auto-cache-fraction","0.5"));c.auto_row_fraction=std::stod(take("--auto-row-fraction","0.015625"));
 for(auto it=o.begin();it!=o.end();){if(strata_ext::deepseek41::parse_dspark_option(c,it->first,it->second))it=o.erase(it);else ++it;}strata_ext::deepseek41::validate_dspark_config(c);
 #ifdef STRATA_T28_CONSTRUCTION_TEST
 auto prefill=take("--prefill-control-test");if(!prefill.empty()){if(!o.empty())throw std::runtime_error("unknown test option");return strata_ext::deepseek41::prefill_control_test(c,std::filesystem::u8path(prefill));}
 auto construction=take("--constructor-test");if(!construction.empty()){if(!o.empty())throw std::runtime_error("unknown test option");return strata_ext::deepseek41::construction_test(c,construction);}
#endif
 if(!o.empty()||!run)throw std::runtime_error("normal --serve/known options required");return strata_ext::deepseek41::serve(c);
}catch(const strata_ext::cache::SecondaryConstructionUnknown&x){std::cerr<<x.what()<<'\n';for(auto cause:{x.initialization_error(),x.cleanup_error()}){if(!cause)continue;try{std::rethrow_exception(cause);}catch(const std::exception&e){std::cerr<<"retained construction cause: "<<e.what()<<'\n';}catch(...){std::cerr<<"retained construction non-standard cause\n";}}return 1;}catch(const std::exception&x){std::cerr<<x.what()<<'\n';return 1;}}


