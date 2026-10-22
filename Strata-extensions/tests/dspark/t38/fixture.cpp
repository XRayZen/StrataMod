#ifdef T38_ACTUAL_BODY_ONLY
// Isolated construction fixture only. This branch deliberately defines no main.
#include "../../../models/deepseek41/dspark/session.hpp"
#include "../../../models/deepseek41/dspark/draft.hpp"
#include "../../../models/deepseek41/device_ops.hpp"
#include <filesystem>
#include <fstream>
#include <map>
#include <set>
#include <sstream>
#include <algorithm>
#include <cstring>
#include <cmath>
#ifdef STRATA_T38_GLOBAL_FIXTURE
#include "../../../models/deepseek41/core.hpp"
#endif
#if defined(T38_PROPOSAL_BODY) && (!defined(STRATA_T28_CONSTRUCTION_TEST) || !defined(STRATA_T38_SEED_CONSTRUCTION))
#error Proposal fixture requires both dedicated construction guards
#endif
#if defined(T38_ACTOR_BODY) && (!defined(STRATA_T28_CONSTRUCTION_TEST) || !defined(STRATA_T38_SEED_CONSTRUCTION) || defined(T38_PROPOSAL_BODY))
#error Actor fixture requires both construction guards and an exclusive body mode
#endif
#include <windows.h>
#include <bcrypt.h>
#ifndef T38_SEED_CPU_VALIDATOR
#include "../../../models/deepseek41/producer.hpp"
#include <hip/hip_runtime.h>
#endif
namespace strata_ext::deepseek41::seed_fixture_detail {
namespace fs=std::filesystem;
using namespace strata_ext::dspark::t38;
void require(bool ok,const char*message){if(!ok)throw std::invalid_argument(message);}
uint64_t decimal(const std::string&s){require(!s.empty()&&s.find_first_not_of("0123456789")==std::string::npos,"seed unsigned decimal");size_t n=0;auto x=std::stoull(s,&n);require(n==s.size(),"seed decimal trailing");return x;}
std::string quote(const std::string&s){std::string x="\"";for(unsigned char c:s){if(c=='\\'||c=='\"'){x+='\\';x+=char(c);}else if(c<32)throw std::invalid_argument("seed JSON control");else x+=char(c);}return x+'\"';}
std::string hash(const std::vector<uint8_t>&bytes){
 BCRYPT_ALG_HANDLE a=nullptr;BCRYPT_HASH_HANDLE h=nullptr;DWORD n=0,size=0;std::vector<uint8_t>object;std::array<uint8_t,32>digest{};
 struct Close{BCRYPT_ALG_HANDLE&a;BCRYPT_HASH_HANDLE&h;~Close(){if(h)BCryptDestroyHash(h);if(a)BCryptCloseAlgorithmProvider(a,0);}}close{a,h};
 require(BCryptOpenAlgorithmProvider(&a,BCRYPT_SHA256_ALGORITHM,nullptr,0)>=0,"seed hash algorithm");require(BCryptGetProperty(a,BCRYPT_OBJECT_LENGTH,reinterpret_cast<PUCHAR>(&size),sizeof(size),&n,0)>=0,"seed hash property");object.resize(size);
 require(BCryptCreateHash(a,&h,object.data(),size,nullptr,0,0)>=0,"seed hash create");require(BCryptHashData(h,const_cast<PUCHAR>(bytes.data()),ULONG(bytes.size()),0)>=0,"seed hash bytes");require(BCryptFinishHash(h,digest.data(),ULONG(digest.size()),0)>=0,"seed hash finish");
 const char*hex="0123456789abcdef";std::string result;for(auto b:digest){result+=hex[b>>4];result+=hex[b&15];}return result;
}
struct Read {std::string path,sha;std::vector<uint8_t>bytes;BY_HANDLE_FILE_INFORMATION stamp{};};
bool same_stamp(const BY_HANDLE_FILE_INFORMATION&a,const BY_HANDLE_FILE_INFORMATION&b){return a.dwVolumeSerialNumber==b.dwVolumeSerialNumber&&a.nFileIndexHigh==b.nFileIndexHigh&&a.nFileIndexLow==b.nFileIndexLow&&a.nFileSizeHigh==b.nFileSizeHigh&&a.nFileSizeLow==b.nFileSizeLow&&CompareFileTime(&a.ftLastWriteTime,&b.ftLastWriteTime)==0;}
Read read_metadata(const std::string&path,uint64_t maximum){
 auto p=fs::u8path(path);require(p.is_absolute(),"seed absolute path");HANDLE f=CreateFileW(p.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);require(f!=INVALID_HANDLE_VALUE,"seed metadata open");struct Close{HANDLE f;~Close(){CloseHandle(f);}}close{f};Read r;r.path=path;BY_HANDLE_FILE_INFORMATION after{};
 require(GetFileInformationByHandle(f,&r.stamp),"seed metadata before identity");auto size=(uint64_t(r.stamp.nFileSizeHigh)<<32)|r.stamp.nFileSizeLow;require(size&&size<=maximum,"seed finite metadata length");r.bytes.resize(size_t(size));DWORD n=0;require(ReadFile(f,r.bytes.data(),DWORD(size),&n,nullptr)&&n==size,"seed metadata short read");require(GetFileInformationByHandle(f,&after)&&same_stamp(r.stamp,after),"seed metadata changed during read");r.sha=hash(r.bytes);return r;
}
void create_file(const fs::path&p,const std::vector<uint8_t>&bytes){HANDLE f=CreateFileW(p.c_str(),GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);require(f!=INVALID_HANDLE_VALUE,"seed create-only output");struct Close{HANDLE f;~Close(){CloseHandle(f);}}close{f};DWORD n=0;require(WriteFile(f,bytes.data(),DWORD(bytes.size()),&n,nullptr)&&n==bytes.size(),"seed output write");}
void create_text(const fs::path&p,const std::string&text){create_file(p,std::vector<uint8_t>(text.begin(),text.end()));}
std::string input_binding_json(const Read&r){auto file_id=(uint64_t(r.stamp.nFileIndexHigh)<<32)|r.stamp.nFileIndexLow;auto write_time=(uint64_t(r.stamp.ftLastWriteTime.dwHighDateTime)<<32)|r.stamp.ftLastWriteTime.dwLowDateTime;return "{\"schema\":\"T38-seed-input-binding-v1\",\"manifest_path\":"+quote(r.path)+",\"manifest_bytes_dec\":"+quote(std::to_string(r.bytes.size()))+",\"manifest_sha256\":"+quote(r.sha)+",\"volume_serial_dec\":"+quote(std::to_string(r.stamp.dwVolumeSerialNumber))+",\"file_id_dec\":"+quote(std::to_string(file_id))+",\"last_write_FILETIME_dec\":"+quote(std::to_string(write_time))+",\"read_identity_before_after_equal\":true}\n";}
struct Manifest {Read original;std::map<std::string,std::string>producer,caller,identity;std::map<std::string,std::pair<std::string,std::string>>receipts;};
const std::set<std::string>producer_keys={"artifact_root","primary_pci","bundle_id","runtime_epoch","context","tile_bytes","tile_rows","active_batch","device_cache_payload_bytes","ram_cache_payload_bytes","mode","source1","source2","source3","source4","source5","source6","source7","source8","source9"};
const std::set<std::string>caller_keys={"request_id","draft_path","draft_prefix_path","draft_credit","target_credit","owner","epoch","bundle","device_ordinal"};
const std::set<std::string>identity_keys={"fixture_sha256","asset_sha256","bundle_sha256","request_id","epoch","phase"};
const std::set<std::string>receipt_keys={"target","draft","draft_prefix","input_lineage"};
Manifest parse(Read input){
 Manifest m;m.original=std::move(input);require(std::find(m.original.bytes.begin(),m.original.bytes.end(),0)==m.original.bytes.end(),"seed manifest NUL");require(MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,reinterpret_cast<const char*>(m.original.bytes.data()),int(m.original.bytes.size()),nullptr,0)>0,"seed manifest UTF8");std::istringstream text(std::string(m.original.bytes.begin(),m.original.bytes.end()));std::string line;bool schema=false,prompt=false;
 while(std::getline(text,line)){if(!line.empty()&&line.back()=='\r')line.pop_back();require(!line.empty(),"seed empty line");std::vector<std::string>v;std::istringstream fields(line);std::string x;while(std::getline(fields,x,'\t'))v.push_back(x);require(!line.empty()&&line.back()!='\t',"seed trailing field");for(const auto&f:v)require(!f.empty()&&f.find_first_of("\r\n")==std::string::npos,"seed empty/control field");
  if(v[0]=="schema"){require(v.size()==2&&!schema&&v[1]=="T38-seed-input-v1","seed schema");schema=true;}
  else if(v[0]=="prompt"){require(v==std::vector<std::string>({"prompt","3","37","1024"})&&!prompt,"seed P3 exact");prompt=true;}
  else if(v[0]=="receipt"){require(v.size()==4&&receipt_keys.count(v[1])&&v[3].size()==64&&v[3].find_first_not_of("0123456789abcdef")==std::string::npos&&fs::u8path(v[2]).is_absolute(),"seed receipt schema");require(m.receipts.emplace(v[1],std::make_pair(v[2],v[3])).second,"seed duplicate receipt");}
  else {require(v.size()==3,"seed field columns");auto*p=v[0]=="producer"?&m.producer:v[0]=="caller"?&m.caller:v[0]=="identity"?&m.identity:nullptr;const auto*k=v[0]=="producer"?&producer_keys:v[0]=="caller"?&caller_keys:v[0]=="identity"?&identity_keys:nullptr;require(p&&k&&k->count(v[1]),"seed unknown field");require(p->emplace(v[1],v[2]).second,"seed duplicate field");}
 }
 require(schema&&prompt&&m.producer.size()==producer_keys.size()&&m.caller.size()==caller_keys.size()&&m.identity.size()==identity_keys.size()&&m.receipts.size()==receipt_keys.size(),"seed required fields");
 auto&p=m.producer;auto&c=m.caller;auto&i=m.identity;require(p.at("mode")=="single"&&p.at("primary_pci")=="0000:07:00.0"&&c.at("device_ordinal")=="0"&&i.at("phase")=="prefill","seed finite mode/device/phase");
 for(const char*k:{"runtime_epoch","context","tile_bytes","tile_rows","active_batch","device_cache_payload_bytes","ram_cache_payload_bytes"})require(decimal(p.at(k))>0,"seed positive producer value");require(decimal(p.at("context"))>=3,"seed P3 context");
 for(const char*k:{"owner","epoch","draft_credit","target_credit"})require(decimal(c.at(k))>0,"seed positive caller value");
 require(c.at("epoch")==p.at("runtime_epoch")&&i.at("epoch")==c.at("epoch")&&c.at("bundle")==p.at("bundle_id")&&i.at("request_id")==c.at("request_id"),"seed identity binding");
 for(const char*k:{"fixture_sha256","asset_sha256","bundle_sha256"})require(i.at(k)==c.at("bundle"),"seed full measurement identity");
 require(fs::u8path(p.at("artifact_root")).is_absolute()&&fs::u8path(c.at("draft_path")).is_absolute()&&fs::u8path(c.at("draft_prefix_path")).is_absolute(),"seed source absolute paths");for(unsigned n=1;n<=9;++n)require(fs::u8path(p.at("source"+std::to_string(n))).is_absolute(),"seed native source absolute path");require(c.at("draft_prefix_path")==m.receipts.at("draft_prefix").first,"seed prefix receipt path");return m;
}
void validate_completion(uint64_t pos,const RequestBinding&binding,const DraftDeviceMetadata&metadata,const RequestBinding&expected){
 require(pos==2&&binding.owner==expected.owner&&binding.epoch==expected.epoch&&binding.bundle==expected.bundle,"seed callback binding/position");require(metadata.valid&&metadata.owner==expected.owner&&metadata.epoch==expected.epoch&&metadata.cursor==3&&metadata.stage_cursor==std::array<uint64_t,3>{3,3,3}&&metadata.processed_prior&&*metadata.processed_prior==1024,"seed completed metadata");
}
void validate_view(const DeviceView&v,uint64_t rows,uint64_t columns,int device){require(v.data&&reinterpret_cast<uintptr_t>(v.data)%alignof(float)==0&&v.rows==rows&&v.columns==columns&&v.bytes==rows*columns*4&&v.scalar==DeviceScalar::Bfloat16InFloat32&&v.device==device&&v.owner&&v.owner->active&&v.generation==v.owner->generation,"seed actual view/lease/shape");}
struct State {Manifest manifest;fs::path output;RequestBinding expected;bool entered=false,captured=false,copy_unknown=false;std::array<std::vector<uint8_t>,5>host;};
// State owns every host allocation before copy. Failure keeps copy_unknown=true.
template<class Copy,class Drain>void copy_completed(State&s,const std::array<DeviceView,5>&views,Copy copy,Drain drain){for(unsigned n=0;n<5;++n)s.host[n].resize(size_t(views[n].bytes));s.copy_unknown=true;for(unsigned n=0;n<5;++n){copy(s.host[n].data(),views[n]);drain();}s.copy_unknown=false;}
#if defined(T38_PROPOSAL_BODY) && defined(STRATA_T28_CONSTRUCTION_TEST) && defined(STRATA_T38_SEED_CONSTRUCTION)
struct ProposalSpec {const char*name;uint64_t rows,columns,bytes;DeviceScalar scalar;};
const std::array<ProposalSpec,6>proposal_specs{{{"stage0-residual",5,20480,409600,DeviceScalar::Bfloat16InFloat32},{"stage1-residual",5,20480,409600,DeviceScalar::Bfloat16InFloat32},{"stage2-residual",5,20480,409600,DeviceScalar::Bfloat16InFloat32},{"tail-collapsed",5,5120,102400,DeviceScalar::Bfloat16InFloat32},{"head-normalized",5,5120,102400,DeviceScalar::Bfloat16InFloat32},{"head-pre-markov",5,129280,2585600,DeviceScalar::Float32}}};
const std::array<const char*,9>proposal_names{{"stage0-residual","stage1-residual","stage2-residual","tail-collapsed","head-normalized","head-pre-markov","q","ids","raw-confidence"}};
struct ProposalState {std::shared_ptr<State>base;std::array<std::vector<uint8_t>,6>host;unsigned events=0;bool copy_unknown=false;uintptr_t weights_stream_identity=0;std::array<std::string,6>descriptors,event_metadata;};
void require_proposal_complete(const ProposalState&s){require(s.events==6&&!s.copy_unknown,"proposal six positive completed captures");}
void validate_proposal_stream(ProposalState&s,unsigned event,void*stream){auto id=reinterpret_cast<uintptr_t>(stream);require(id!=0,"proposal actual stream identity");if(event==0)s.weights_stream_identity=id;else if(event<5)require(id==s.weights_stream_identity,"proposal stage/tail weights stream");else require(event==5&&s.weights_stream_identity&&id!=s.weights_stream_identity,"proposal head must use distinct TargetWeightSupply producer stream");}
void validate_proposal_event(unsigned event,unsigned completed,const RequestBinding&binding,const RequestBinding&expected,uint64_t cursor,const DeviceView&v,void*stream){
 require(event<6&&event==completed,"proposal missing/duplicate/out-of-order event");require(binding.owner==expected.owner&&binding.epoch==expected.epoch&&binding.bundle==expected.bundle&&cursor==3,"proposal actual binding/cursor");const auto&s=proposal_specs[event];require(stream&&v.data&&reinterpret_cast<uintptr_t>(v.data)%alignof(float)==0&&v.rows==s.rows&&v.columns==s.columns&&v.bytes==s.bytes&&v.scalar==s.scalar&&v.device==0&&v.owner&&v.owner->active&&v.generation==v.owner->generation,"proposal actual view/lease/scalar/shape");
}
template<class Copy,class Drain>void copy_proposal_event(ProposalState&s,unsigned event,const DeviceView&v,Copy copy,Drain drain){require(event<6&&s.host[event].size()==v.bytes,"proposal preowned destination");s.copy_unknown=true;copy(s.host[event].data(),v);drain();s.copy_unknown=false;}
std::string save_chunks(const fs::path&path,const std::vector<std::pair<const void*,uint64_t>>&chunks){
 HANDLE file=CreateFileW(path.c_str(),GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);require(file!=INVALID_HANDLE_VALUE,"proposal create-only result");struct CloseFile{HANDLE f;~CloseFile(){CloseHandle(f);}}close_file{file};BCRYPT_ALG_HANDLE a=nullptr;BCRYPT_HASH_HANDLE h=nullptr;DWORD n=0,size=0;std::vector<uint8_t>object;std::array<uint8_t,32>digest{};struct CloseHash{BCRYPT_ALG_HANDLE&a;BCRYPT_HASH_HANDLE&h;~CloseHash(){if(h)BCryptDestroyHash(h);if(a)BCryptCloseAlgorithmProvider(a,0);}}close_hash{a,h};
 require(BCryptOpenAlgorithmProvider(&a,BCRYPT_SHA256_ALGORITHM,nullptr,0)>=0&&BCryptGetProperty(a,BCRYPT_OBJECT_LENGTH,reinterpret_cast<PUCHAR>(&size),sizeof(size),&n,0)>=0,"proposal hash init");object.resize(size);require(BCryptCreateHash(a,&h,object.data(),size,nullptr,0,0)>=0,"proposal hash create");
 for(const auto&chunk:chunks){require(chunk.first&&chunk.second&&chunk.second<=UINT32_MAX,"proposal finite result chunk");require(WriteFile(file,chunk.first,DWORD(chunk.second),&n,nullptr)&&n==chunk.second,"proposal result write");require(BCryptHashData(h,reinterpret_cast<PUCHAR>(const_cast<void*>(chunk.first)),ULONG(chunk.second),0)>=0,"proposal result hash");}require(BCryptFinishHash(h,digest.data(),ULONG(digest.size()),0)>=0,"proposal result finish");const char*hex="0123456789abcdef";std::string result;for(auto b:digest){result+=hex[b>>4];result+=hex[b&15];}return result;
}
void validate_public_proposal(const DraftProposal&p){require(!p.seed_only&&p.ids.size()==5&&p.q.size()==5&&p.raw_confidence.size()==5,"proposal public result width");for(const auto&row:p.q)require(row.size()==129280,"proposal full vocabulary result");}
std::string result_descriptor(const char*name,uint64_t rows,uint64_t columns,const char*dtype,uint64_t bytes,const std::string&sha){return "{\"name\":"+quote(name)+",\"rows\":"+std::to_string(rows)+",\"columns\":"+std::to_string(columns)+",\"dtype\":"+quote(dtype)+",\"bytes\":"+std::to_string(bytes)+",\"sha256\":"+quote(sha)+"}";}
std::string save_public_proposal(const fs::path&out,const DraftProposal&p){
 static_assert(sizeof(double)==8&&sizeof(float)==4&&sizeof(uint32_t)==4,"proposal exact storage widths");uint32_t one=1;require(*reinterpret_cast<uint8_t*>(&one)==1,"proposal little-endian host");validate_public_proposal(p);std::vector<std::pair<const void*,uint64_t>>rows;for(const auto&row:p.q)rows.emplace_back(row.data(),row.size()*8);auto q=save_chunks(out/"q.bin",rows);auto ids=save_chunks(out/"ids.bin",{{p.ids.data(),20}});auto confidence=save_chunks(out/"raw-confidence.bin",{{p.raw_confidence.data(),20}});return result_descriptor("q",5,129280,"<f8",5171200,q)+','+result_descriptor("ids",1,5,"<u4",20,ids)+','+result_descriptor("raw-confidence",1,5,"<f4",20,confidence);
}
// Finite immutable metadata references; no expected output binary is opened here.
void proposal_lineage(const Manifest&m){
 const auto&receipt=m.receipts.at("input_lineage");auto lineage=read_metadata(receipt.first,1024*1024);require(lineage.sha==receipt.second,"proposal lineage receipt");std::istringstream text(std::string(lineage.bytes.begin(),lineage.bytes.end()));std::string line;std::map<std::string,std::string>values;std::map<std::string,std::pair<std::string,std::string>>refs;std::set<std::string>fields;
 while(std::getline(text,line)){if(!line.empty()&&line.back()=='\r')line.pop_back();std::istringstream in(line);std::vector<std::string>v;std::string x;while(std::getline(in,x,'\t'))v.push_back(x);require(!line.empty()&&line.back()!='\t',"proposal lineage line");if(v.size()==2)require(values.emplace(v[0],v[1]).second,"proposal duplicate lineage value");else if(v.size()==4&&v[0]=="ref")require(refs.emplace(v[1],std::make_pair(v[2],v[3])).second,"proposal duplicate reference");else if(v.size()==6&&v[0]=="field"){require(fields.insert(v[1]).second,"proposal duplicate lineage field");auto it=std::find(proposal_names.begin(),proposal_names.end(),v[1]);require(it!=proposal_names.end(),"proposal unknown lineage field");auto n=size_t(it-proposal_names.begin());uint64_t r=n<6?proposal_specs[n].rows:n==6?5:1,c=n<6?proposal_specs[n].columns:n==6?129280:5,b=n<6?proposal_specs[n].bytes:n==6?5171200:20;const char*type=n==6?"<f8":n==7?"<u4":"<f4";require(decimal(v[2])==r&&decimal(v[3])==c&&v[4]==type&&decimal(v[5])==b,"proposal field descriptor");}else throw std::invalid_argument("proposal lineage schema");}
 require(values.size()==10&&values.at("schema")=="T38-proposal-lineage-v1"&&values.at("fixture_kind")=="proposal"&&values.at("source_origin_sha256")=="fc5b8c8d26eb1f89f1b18cf4e983f615ffcb757104b491c386f7d350889392ae"&&fields.size()==9&&refs.size()==5,"proposal explicit lineage kind/source/fields");
 for(const char*k:{"owner","epoch","bundle","request_id"})require(values.at(k)==m.caller.at(k),"proposal lineage caller binding");for(const char*k:{"target","draft","draft_prefix"})require(values.at(std::string(k)+"_receipt_sha256")==m.receipts.at(k).second,"proposal original input receipt binding");
 const std::map<std::string,std::string>fixed{{"proposal_seal","303a67d088174b1d422bd3d64f826dbbc34213272c7fcc58b83b0d082933f81e"},{"proposal_manifest","8200b3a8772ff03eac71e423472dce2643cc0dd86bb6db3a2db62cb68c9c3d29"},{"seed_seal","2057666abb7a2d7b162f6fb9752c6a4ccaab9d80181952d8fd4abfe5e6985eb0"},{"seed_manifest","2e44f3e6f79f1ad511da1135e34ba3127a6c599b56efea93ee9284319acd1918"},{"seed_input_seal","59801533ef8ffc46f43d99487fabb930d4d4b05cd7b1dc7f9dd795073acf2acd"}};
 for(const auto&r:fixed){const auto&ref=refs.at(r.first);require(ref.second==r.second&&read_metadata(ref.first,1024*1024).sha==r.second,"proposal sealed expected metadata authority");}
}
#endif
#if defined(T38_ACTOR_BODY) && defined(STRATA_T28_CONSTRUCTION_TEST) && defined(STRATA_T38_SEED_CONSTRUCTION)
struct ActorCapture {
 std::shared_ptr<State>base;std::array<std::vector<uint8_t>,2>head;std::vector<uint8_t>joined;std::array<uint32_t,2>ids{};std::array<uint64_t,2>target_cursor{},draft_cursor{};unsigned emitted_count=0;bool copy_unknown=false,joined_complete=false;uint64_t prior=0,generation=0,processed_cursor=0;std::array<uint64_t,3>stage_cursor{};bool processed_valid=false;uintptr_t stream=0,allocation_owner=0;
 ActorCapture(){for(auto&h:head)h.resize(517120);joined.resize(61440);}
};
struct ActorLineage {std::map<std::string,std::string>values;std::map<std::string,std::pair<std::string,std::string>>refs;bool complete=false;};
const std::map<std::string,std::string>actor_fixed_refs{{"initial_head_handoff","4fbea4762f84ddb1c20e528189fa1d32fed17246730f5adb3e8ebcc224fe20b6"},{"initial_head_seal","6abb4ab5dbca55309c1c06a9688c7c13d92e4f96e59d2af860e0952b69c002b3"},{"initial_head_result","dd06a42a1ecf962b75790d7e7ce6bdb96dec564aca23c8c499d76b5326785b93"},{"proposal_seal","303a67d088174b1d422bd3d64f826dbbc34213272c7fcc58b83b0d082933f81e"},{"qualified_proposal_actual","e1ef3f5d309d344f2cb95598731b9ab7dab111c7732c6cb6783c10a9fda8cda9"}};
bool actor_sha(const std::string&s){return s.size()==64&&s.find_first_not_of("0123456789abcdef")==std::string::npos;}
ActorLineage actor_lineage(const Manifest&m){
 const auto&r=m.receipts.at("input_lineage");auto raw=read_metadata(r.first,1024*1024);require(raw.sha==r.second,"actor lineage receipt");ActorLineage result;std::istringstream in(std::string(raw.bytes.begin(),raw.bytes.end()));std::string line;
 while(std::getline(in,line)){if(!line.empty()&&line.back()=='\r')line.pop_back();require(!line.empty()&&line.back()!='\t',"actor lineage empty/trailing");std::istringstream parts(line);std::vector<std::string>v;std::string p;while(std::getline(parts,p,'\t')){require(!p.empty(),"actor lineage empty column");v.push_back(p);}if(v.size()==2)require(result.values.emplace(v[0],v[1]).second,"actor duplicate scalar");else if(v.size()==4&&v[0]=="ref")require(result.refs.emplace(v[1],std::make_pair(v[2],v[3])).second,"actor duplicate reference");else throw std::invalid_argument("actor lineage columns");}
 auto&v=result.values;require(v.size()==13&&v.at("schema")=="T38-actor-lineage-v1"&&v.at("fixture_kind")=="actor"&&v.at("source_origin_sha256")=="acbfe10cc8107233972d8c6cb27bbe171cf8926eea4f304a53ea77f89612cf4f","actor kind/origin/schema");for(const char*k:{"owner","epoch","bundle","request_id"})require(v.at(k)==m.caller.at(k),"actor lineage caller");for(const char*k:{"target","draft","draft_prefix"})require(v.at(std::string(k)+"_receipt_sha256")==m.receipts.at(k).second,"actor original receipts");
 result.complete=v.at("expected_status")=="complete";require(result.complete||v.at("expected_status")=="incomplete","actor expectation status");require(result.refs.size()==actor_fixed_refs.size()+(result.complete?2:0),"actor finite refs");for(const auto&f:actor_fixed_refs){const auto&ref=result.refs.at(f.first);require(ref.second==f.second&&read_metadata(ref.first,1024*1024).sha==f.second,"actor accepted fixed reference");}
 for(const char*k:{"final_expected_manifest","final_expected_seal"}){auto sha=v.at(std::string(k)+"_sha256");if(result.complete){const auto&ref=result.refs.at(k);require(actor_sha(sha)&&ref.second==sha&&read_metadata(ref.first,1024*1024).sha==sha,"actor final independent expectation reference");}else require(sha=="null","actor incomplete expected must be null");}return result;
}
void require_actor_ready(const ActorLineage&l){require(l.complete,"actor independent position3 expectation incomplete: native run prohibited");}
void validate_actor_joined(const ActorCapture&s,uint64_t pos,const RequestBinding&actual,const RequestBinding&expected,const DraftDeviceMetadata&m,const DeviceView&v,void*stream){
 require(!s.joined_complete&&!s.copy_unknown&&pos==3&&actual.owner==expected.owner&&actual.epoch==expected.epoch&&actual.bundle==expected.bundle,"actor joined binding/position/once");require(m.valid&&m.owner==expected.owner&&m.epoch==expected.epoch&&m.cursor==4&&m.stage_cursor==std::array<uint64_t,3>{4,4,4}&&m.processed_prior&&s.emitted_count==1&&*m.processed_prior==s.ids[0],"actor actual processed metadata");validate_view(v,1,15360,0);require(stream!=nullptr,"actor actual weights stream");
}
template<class Copy,class Drain>void copy_actor_joined(ActorCapture&s,const DeviceView&v,Copy copy,Drain drain){require(s.joined.size()==61440&&v.bytes==61440,"actor preowned joined");s.copy_unknown=true;copy(s.joined.data(),v);drain();s.copy_unknown=false;s.joined_complete=true;}
// Emitter performs only bounded copies and stores actual observations. No expected-ID decision or file/allocation work.
void actor_emit(ActorCapture&s,const std::vector<float>&logits,uint32_t id,uint64_t target_cursor,uint64_t draft_cursor){require(s.emitted_count<2&&logits.size()==129280&&s.head[s.emitted_count].size()==517120,"actor finite emitter slot");auto n=s.emitted_count;std::memcpy(s.head[n].data(),logits.data(),517120);s.ids[n]=id;s.target_cursor[n]=target_cursor;s.draft_cursor[n]=draft_cursor;++s.emitted_count;}
ActorResult run_actor_capture(ActorCapture&s,ActorTarget&target,ActorDraft&draft,const RequestBinding&binding){SamplingOptions o;o.temperature=0;o.top_p=1;o.top_k=0;o.min_p=0;o.repetition_penalty=1;o.frequency_penalty=0;o.presence_penalty=0;o.logprobs=false;o.top_logprobs=0;RequestActor actor(target,draft,binding,0);return actor.run({3,37,1024},2,5,o,[]{return ActorStop::Continue;},[&](const SampledToken&t){actor_emit(s,target.logits(),t.id,target.known_cursor(),draft.cursor());});}
std::string actor_ids(const std::vector<uint32_t>&ids){std::string text="[";for(size_t n=0;n<ids.size();++n){if(n)text+=',';text+=std::to_string(ids[n]);}return text+']';}
std::string actor_error_quote(const std::string&s){const char*hex="0123456789abcdef";std::string out="\"";for(unsigned char c:s){if(c=='\\'||c=='\"'){out+='\\';out+=char(c);}else if(c<32){out+="\\u00";out+=hex[c>>4];out+=hex[c&15];}else out+=char(c);}return out+'\"';}
std::string actor_result_json(const ActorResult&r){const auto&l=r.ledger;return "{\"schema\":\"T38-actual-actor-result-v1\",\"prompt\":"+std::to_string(l.prompt)+",\"processed_generated\":"+std::to_string(l.processed_generated)+",\"cursor\":"+std::to_string(l.cursor)+",\"emitted\":"+actor_ids(l.emitted)+",\"processed\":"+actor_ids(l.processed)+",\"pending\":"+(l.pending?std::to_string(*l.pending):"null")+",\"finish\":"+quote(finish_name(l.finish))+",\"known_target_cursor\":"+std::to_string(r.known_target_cursor)+",\"draft_cursor\":"+std::to_string(r.draft_cursor)+",\"context_valid\":"+(r.context_valid?"true":"false")+",\"completion_known\":"+(r.completion_known?"true":"false")+",\"error\":"+actor_error_quote(r.error)+"}\n";}
void save_actor_capture(ActorCapture&s,const ActorResult&r){auto&b=*s.base;create_text(b.output/"actor-result.json",actor_result_json(r));std::string fields="[",timing="[";bool comma=false;for(unsigned n=0;n<s.emitted_count;++n){const char*name=n?"post-step-target-logits":"initial-target-logits";create_file(b.output/(std::string(name)+".bin"),s.head[n]);if(comma)fields+=',';comma=true;fields+="{\"name\":"+quote(name)+",\"rows\":1,\"columns\":129280,\"dtype\":\"<f4\",\"bytes\":517120,\"sha256\":"+quote(hash(s.head[n]))+"}";if(n)timing+=',';timing+="{\"id\":"+std::to_string(s.ids[n])+",\"target_cursor\":"+std::to_string(s.target_cursor[n])+",\"draft_cursor\":"+std::to_string(s.draft_cursor[n])+"}";}
 if(s.joined_complete&&!s.copy_unknown){create_file(b.output/"processed-tap-joined.bin",s.joined);if(comma)fields+=',';comma=true;fields+="{\"name\":\"processed-tap-joined\",\"rows\":1,\"columns\":15360,\"dtype\":\"<f4\",\"bytes\":61440,\"sha256\":"+quote(hash(s.joined))+"}";}
 std::vector<uint8_t>idbytes(r.ledger.emitted.size()*sizeof(uint32_t));if(!idbytes.empty())std::memcpy(idbytes.data(),r.ledger.emitted.data(),idbytes.size());create_file(b.output/"emitted-ids.bin",idbytes);if(comma)fields+=',';fields+="{\"name\":\"emitted-ids\",\"rows\":1,\"columns\":"+std::to_string(r.ledger.emitted.size())+",\"dtype\":\"<u4\",\"bytes\":"+std::to_string(idbytes.size())+",\"sha256\":"+quote(hash(idbytes))+"}]";timing+=']';
 create_text(b.output/"capture.json","{\"schema\":\"T38-actual-actor-capture-v1\",\"fixture_kind\":\"actor\",\"manifest_sha256\":"+quote(b.manifest.original.sha)+",\"owner\":"+std::to_string(b.expected.owner)+",\"epoch\":"+std::to_string(b.expected.epoch)+",\"bundle\":"+quote(b.expected.bundle)+",\"request_id\":"+quote(b.manifest.caller.at("request_id"))+",\"RequestActor_run_calls\":1,\"emitter_count\":"+std::to_string(s.emitted_count)+",\"emitter_timing\":"+timing+",\"joined_complete\":"+(s.joined_complete?"true":"false")+",\"copy_unknown\":"+(s.copy_unknown?"true":"false")+",\"processed_position\":3,\"processed_prior\":"+(s.joined_complete?std::to_string(s.prior):"null")+",\"processed_cursor\":"+std::to_string(s.processed_cursor)+",\"stage_cursor\":["+std::to_string(s.stage_cursor[0])+","+std::to_string(s.stage_cursor[1])+","+std::to_string(s.stage_cursor[2])+"],\"processed_valid\":"+(s.processed_valid?"true":"false")+",\"producer_stream\":"+quote(std::to_string(s.stream))+",\"allocation_owner\":"+quote(std::to_string(s.allocation_owner))+",\"generation\":"+std::to_string(s.generation)+",\"device\":0,\"fields\":"+fields+",\"RNG_draws_measured\":false}\n");
}
#endif

#ifdef T38_REMAINING_BODY
#ifndef STRATA_T38_SESSION_TRACE
#error Remaining fixture requires the same trace guard in every target TU
#endif
// Bounded observer storage is owned by the Body's shared root before any copy.
struct RemainingRecord {
 FixtureTraceEvent event{FixtureTraceKind::Draw};int p=-1,q=-1;
 uint64_t prompt=0,generated=0,cursor=0;std::array<uint32_t,3>emitted{},processed{};
 unsigned emitted_count=0,processed_count=0;std::optional<uint32_t>pending;Finish finish=Finish::Running;
};
struct RemainingCapture {
 std::shared_ptr<State>base;std::string selected;unsigned maximum;
 std::array<RemainingRecord,128>records{};unsigned count=0;bool overflow=false;
 std::array<std::vector<double>,3>p,q;unsigned p_count=0,q_count=0;int last_q=-1;
 std::array<std::vector<uint8_t>,3>heads;unsigned emitted=0;bool five_complete=false;
 uint64_t position=0,cursor=0,prior=0,generation=0;std::array<uint64_t,3>stage{};uintptr_t stream=0,owner=0;
 RemainingCapture(std::shared_ptr<State>b,std::string c):base(std::move(b)),selected(std::move(c)),maximum(selected=="C"?2:3){
  for(unsigned n=0;n<maximum;++n){p[n].resize(129280);q[n].resize(129280);heads[n].resize(517120);}
  const std::array<size_t,5>sizes{61440,20480,262144,262144,262144};for(unsigned n=0;n<5;++n)base->host[n].resize(sizes[n]);
 }
 static void observe(void*context,const FixtureTraceEvent&e)noexcept{
  auto&s=*static_cast<RemainingCapture*>(context);if(e.incomplete)s.overflow=true;if(s.count==s.records.size()){s.overflow=true;return;}
  auto&r=s.records[s.count++];r.event=e;r.event.p=nullptr;r.event.q=nullptr;r.event.ledger=nullptr;
  if(e.q&&e.kind==FixtureTraceKind::Proposal){if(s.q_count>=s.maximum||e.q->size()!=129280){s.overflow=true;return;}r.q=int(s.q_count++);s.last_q=r.q;std::copy(e.q->begin(),e.q->end(),s.q[r.q].begin());}
  else if(e.q)r.q=s.last_q;
  if(e.p){if(s.p_count>=s.maximum||e.p->size()!=129280){s.overflow=true;return;}r.p=int(s.p_count++);std::copy(e.p->begin(),e.p->end(),s.p[r.p].begin());}
  if(e.ledger){const auto&l=*e.ledger;if(l.emitted.size()>3||l.processed.size()>3){s.overflow=true;return;}r.prompt=l.prompt;r.generated=l.processed_generated;r.cursor=l.cursor;r.emitted_count=unsigned(l.emitted.size());r.processed_count=unsigned(l.processed.size());std::copy(l.emitted.begin(),l.emitted.end(),r.emitted.begin());std::copy(l.processed.begin(),l.processed.end(),r.processed.begin());r.pending=l.pending;r.finish=l.finish;}
 }
};
std::string remaining_case(const Manifest&m){
 const auto&ref=m.receipts.at("input_lineage");auto body=read_metadata(ref.first,65536);require(body.sha==ref.second,"remaining lineage receipt");std::map<std::string,std::string>v;std::istringstream in(std::string(body.bytes.begin(),body.bytes.end()));std::string line;
 while(std::getline(in,line)){if(!line.empty()&&line.back()=='\r')line.pop_back();auto at=line.find('\t');require(at!=std::string::npos&&line.find('\t',at+1)==std::string::npos&&at&&at+1<line.size()&&v.emplace(line.substr(0,at),line.substr(at+1)).second,"remaining exact lineage columns");}
 require(v.size()==5&&v.at("schema")=="T38-remaining-lineage-v1"&&v.at("plan_sha256")=="cc8a70390ea11a93f3cf03ad6fee7b03422819bf89da6aefd6e79fbf27e199a8"&&v.at("source_origin_sha256")=="a85b75acc84cdf710843efb7ae1fd6555748dd3f1bcc70222aa3ef8896cc6e7b"&&v.at("numeric_scope")=="independent-P3-P4;P5-relative;captured-pq-conditional","remaining fixed lineage");
 auto c=v.at("case");require(c=="A"||c=="B-fresh"||c=="C","remaining finite case");return c;
}
std::string remaining_ledger(const RemainingRecord&r){
 std::vector<uint32_t>e(r.emitted.begin(),r.emitted.begin()+r.emitted_count),p(r.processed.begin(),r.processed.begin()+r.processed_count);
 return "{\"prompt\":"+std::to_string(r.prompt)+",\"processed_generated\":"+std::to_string(r.generated)+",\"cursor\":"+std::to_string(r.cursor)+",\"emitted\":"+actor_ids(e)+",\"processed\":"+actor_ids(p)+",\"pending\":"+(r.pending?std::to_string(*r.pending):"null")+",\"finish\":"+quote(finish_name(r.finish))+"}";
}
void save_remaining(RemainingCapture&s,const ActorResult&result){
 auto&out=s.base->output;const char*names[]={"Draw","Proposal","Verify","Bonus","Emit","Processed","Terminal"};
 for(unsigned side=0;side<2;++side){auto&pool=side?s.q:s.p;auto count=side?s.q_count:s.p_count;for(unsigned n=0;n<count;++n){std::vector<uint8_t>bytes(129280*8);std::memcpy(bytes.data(),pool[n].data(),bytes.size());create_file(out/((side?"q-":"p-")+std::to_string(n)+".bin"),bytes);}}
 std::ostringstream json;json.precision(17);json<<"{\"schema\":\"T38-session-trace-v1\",\"seed\":0,\"prompt\":3,\"maximum\":"<<s.maximum<<",\"width\":1,\"overflow\":"<<(s.overflow?"true":"false")<<",\"events\":[";
 for(unsigned n=0;n<s.count;++n){auto&r=s.records[n];auto&e=r.event;if(n)json<<',';json<<"{\"kind\":"<<quote(names[unsigned(e.kind)])<<",\"space\":"<<unsigned(e.space)<<",\"ordinal\":"<<e.ordinal<<",\"word53\":"<<e.word53<<",\"index\":"<<e.index<<",\"id\":"<<e.id<<",\"accepted\":"<<(e.accepted?"true":"false")<<",\"acceptance\":"<<e.acceptance<<",\"p_file\":"<<(r.p<0?"null":quote("p-"+std::to_string(r.p)+".bin"))<<",\"q_file\":"<<(r.q<0?"null":quote("q-"+std::to_string(r.q)+".bin"))<<",\"ledger\":"<<((e.kind==FixtureTraceKind::Emit||e.kind==FixtureTraceKind::Processed||e.kind==FixtureTraceKind::Terminal)?remaining_ledger(r):"null")<<'}';}json<<"]}\n";
 create_text(out/"trace.json",json.str());create_text(out/"actor-result.json",actor_result_json(result));
 for(unsigned n=0;n<s.emitted;++n)create_file(out/("target-head-"+std::to_string(n)+".bin"),s.heads[n]);
 if(s.five_complete&&!s.base->copy_unknown){const char*field[]={"joined","main","ring0","ring1","ring2"};for(unsigned n=0;n<5;++n)create_file(out/(std::string(field[n])+".bin"),s.base->host[n]);}
 create_text(out/"capture.json","{\"schema\":\"T38-remaining-capture-v1\",\"case\":"+quote(s.selected)+",\"position\":"+std::to_string(s.position)+",\"cursor\":"+std::to_string(s.cursor)+",\"prior\":"+std::to_string(s.prior)+",\"stage_cursor\":["+std::to_string(s.stage[0])+","+std::to_string(s.stage[1])+","+std::to_string(s.stage[2])+"],\"five_complete\":"+(s.five_complete?"true":"false")+",\"copy_unknown\":"+(s.base->copy_unknown?"true":"false")+",\"stream\":"+quote(std::to_string(s.stream))+",\"allocation_owner\":"+quote(std::to_string(s.owner))+",\"generation\":"+std::to_string(s.generation)+",\"trace_overflow\":"+(s.overflow?"true":"false")+",\"model_independent_Q_extended\":false,\"learned_accept_bonus_reached\":null,\"sampler_bit_qualified\":false}\n");
}
#endif
#ifdef STRATA_T38_GLOBAL_FIXTURE
// Dedicated bounded global fixture. Every borrow is copied and positively drained.
struct GlobalCapture;
struct GlobalAudit final:DeviceAudit {
 std::weak_ptr<GlobalCapture> root;uint64_t position=0;uint32_t layer=0;
 void frame(uint64_t p,uint32_t l)override{position=p;layer=l;}
 void stage(const std::string&,const DeviceView&,void*)override;
};
struct GlobalTraceRecord {FixtureTraceEvent event{FixtureTraceKind::Draw};int p=-1,q=-1;Ledger ledger;};
struct GlobalCapture:std::enable_shared_from_this<GlobalCapture> {
 std::shared_ptr<State> base;std::string selected,phase="candidate";uint64_t maximum=0,width=0;bool overflow=false,unsafe=false,candidate_done=false;
 std::vector<uint32_t> prefix,reference_prefix;std::set<uint64_t> cursors;
 std::array<GlobalTraceRecord,32> trace;size_t count=0,p_count=0,q_count=0,raw_count=0,emitted=0,cycles=0;
 std::array<std::vector<double>,5> p;std::array<std::vector<double>,6> q,raw_q;
 std::array<uint32_t,6> raw_ids{};std::array<float,6> raw_conf{};
 std::vector<std::shared_ptr<std::vector<uint8_t>>> pending_downloads;
 std::unique_ptr<CoreStorage> replay_storage;DeviceView owned_mean;StepProof owned_proof;uint32_t owned_id=0;bool replay_ready=false;
 std::shared_ptr<GlobalAudit> audit;
 explicit GlobalCapture(std::shared_ptr<State>b,std::string c):base(std::move(b)),selected(std::move(c)){
  maximum=selected=="Rmid"?3:selected=="All"?5:4;width=selected=="A4"?1:3;
  for(auto&v:p)v.resize(129280);for(auto&v:q)v.resize(129280);for(auto&v:raw_q)v.resize(129280);
  for(auto&r:trace){r.ledger.emitted.reserve(5);r.ledger.processed.reserve(4);}
 }
 fs::path directory(const std::string&label){auto d=base->output/phase/label;fs::create_directories(d);return d;}
 std::vector<uint8_t> download(const DeviceView&v,void*stream){
  validate_device_view(v,0);check_device_stream(stream,0);auto b=std::make_shared<std::vector<uint8_t>>(size_t(v.bytes));pending_downloads.push_back(b);unsafe=true;
  auto e=hipMemcpyAsync(b->data(),v.data,size_t(v.bytes),hipMemcpyDeviceToHost,reinterpret_cast<hipStream_t>(stream));require(e==hipSuccess,"global D2H enqueue");require(hipStreamSynchronize(reinterpret_cast<hipStream_t>(stream))==hipSuccess,"global D2H completion");unsafe=false;pending_downloads.pop_back();return std::move(*b);
 }
 std::string field(const fs::path&d,const std::string&name,const DeviceView&v,void*stream){
  auto b=download(v,stream);create_file(d/(name+".bin"),b);return "{\"name\":"+quote(name)+",\"bytes\":"+std::to_string(b.size())+",\"rows\":"+std::to_string(v.rows)+",\"columns\":"+std::to_string(v.columns)+",\"scalar\":"+std::to_string(unsigned(v.scalar))+",\"device\":"+std::to_string(v.device)+",\"owner\":"+quote(std::to_string(reinterpret_cast<uintptr_t>(v.owner)))+",\"generation\":"+std::to_string(v.generation)+",\"sha256\":"+quote(hash(b))+"}";
 }
 static void observe(void*ctx,const FixtureTraceEvent&e)noexcept{
  auto&s=*static_cast<GlobalCapture*>(ctx);if(e.incomplete)s.overflow=true;if(s.count==s.trace.size()){s.overflow=true;return;}auto&r=s.trace[s.count++];r.event=e;r.event.p=nullptr;r.event.q=nullptr;r.event.ledger=nullptr;
  if(e.p){if(s.p_count==s.p.size()||e.p->size()!=129280){s.overflow=true;return;}r.p=int(s.p_count++);std::copy(e.p->begin(),e.p->end(),s.p[r.p].begin());}
  if(e.kind==FixtureTraceKind::Proposal){if(!e.q||s.q_count==s.q.size()||e.q->size()!=129280){s.overflow=true;return;}r.q=int(s.q_count++);std::copy(e.q->begin(),e.q->end(),s.q[r.q].begin());}
  else if(e.q){if(e.index>=s.width||s.q_count<s.width){s.overflow=true;return;}r.q=int(s.q_count-s.width+e.index);}
  if(e.ledger){if(e.ledger->emitted.size()>5||e.ledger->processed.size()>4){s.overflow=true;return;}r.ledger=*e.ledger;}
 }
 void save_trace(const ActorResult&result){
  const char*names[]={"Draw","Proposal","Verify","Bonus","Emit","Processed","Terminal"};auto d=directory("trace");
  for(unsigned side=0;side<2;++side){auto n=side?q_count:p_count;for(size_t i=0;i<n;++i){const auto&v=side?q[i]:p[i];std::vector<uint8_t>b(v.size()*8);std::memcpy(b.data(),v.data(),b.size());create_file(d/((side?"q-":"p-")+std::to_string(i)+".bin"),b);}}
  for(size_t i=0;i<raw_count;++i){std::vector<uint8_t>b(raw_q[i].size()*8);std::memcpy(b.data(),raw_q[i].data(),b.size());create_file(d/("raw-learned-q-"+std::to_string(i)+".bin"),b);}
  std::ostringstream j;j.precision(17);j<<"{\"schema\":\"T38-global-trace-v1\",\"case\":"<<quote(selected)<<",\"q_domain\":"<<quote(selected=="A4"?"learned":"controlled-onehot")<<",\"seed\":0,\"prompt\":3,\"maximum\":"<<maximum<<",\"width\":"<<width<<",\"overflow\":"<<(overflow?"true":"false")<<",\"raw_learned_rows\":[";
  for(size_t i=0;i<raw_count;++i){if(i)j<<',';j<<"{\"id\":"<<raw_ids[i]<<",\"confidence\":"<<raw_conf[i]<<",\"q_file\":"<<quote("raw-learned-q-"+std::to_string(i)+".bin")<<"}";}j<<"],\"events\":[";
  for(size_t i=0;i<count;++i){auto&r=trace[i];auto&e=r.event;if(i)j<<',';j<<"{\"kind\":"<<quote(names[unsigned(e.kind)])<<",\"space\":"<<unsigned(e.space)<<",\"ordinal\":"<<e.ordinal<<",\"word53\":"<<e.word53<<",\"index\":"<<e.index<<",\"id\":"<<e.id<<",\"accepted\":"<<(e.accepted?"true":"false")<<",\"acceptance\":"<<e.acceptance<<",\"p_file\":"<<(r.p<0?"null":quote("p-"+std::to_string(r.p)+".bin"))<<",\"q_file\":"<<(r.q<0?"null":quote("q-"+std::to_string(r.q)+".bin"))<<",\"ledger\":";
   if(e.kind==FixtureTraceKind::Emit||e.kind==FixtureTraceKind::Processed||e.kind==FixtureTraceKind::Terminal){ActorResult x;x.ledger=r.ledger;auto&l=r.ledger;j<<"{\"prompt\":"<<l.prompt<<",\"processed_generated\":"<<l.processed_generated<<",\"cursor\":"<<l.cursor<<",\"emitted\":"<<actor_ids(l.emitted)<<",\"processed\":"<<actor_ids(l.processed)<<",\"pending\":"<<(l.pending?std::to_string(*l.pending):"null")<<",\"finish\":"<<quote(finish_name(l.finish))<<"}";}else j<<"null";j<<'}';}j<<"]}\n";create_text(d/"trace.json",j.str());create_text(directory("result")/"actor-result.json",actor_result_json(result));
 }
 void math(DraftNetwork&network,const std::string&label){auto d=directory(label);network.fixture_visit_math([&](const RequestBinding&b,const DraftDeviceMetadata&m,const DeviceView&features,const std::array<DeviceView,3>&rings,void*s){
  require(m.valid&&m.owner==b.owner&&m.epoch==b.epoch&&m.stage_cursor==std::array<uint64_t,3>{m.cursor,m.cursor,m.cursor},"global draft mathematical metadata");std::string f="["+field(d,"features",features,s);for(unsigned i=0;i<3;++i)f+=','+field(d,"ring"+std::to_string(i),rings[i],s);f+=']';create_text(d/"draft.json","{\"owner\":"+std::to_string(m.owner)+",\"epoch\":"+std::to_string(m.epoch)+",\"cursor\":"+std::to_string(m.cursor)+",\"stage_cursor\":["+std::to_string(m.stage_cursor[0])+","+std::to_string(m.stage_cursor[1])+","+std::to_string(m.stage_cursor[2])+"],\"prior\":"+(m.processed_prior?std::to_string(*m.processed_prior):"null")+",\"valid\":true,\"fields\":"+f+"}\n");});}
 void snapshot(ActorTarget&target,DraftNetwork&network,uint64_t cursor){
  require(target.known_cursor()==cursor&&network.processed_cursor()==cursor&&target.completion_known(),"global same healthy processed cursor");auto label="c"+std::to_string(cursor);auto d=directory(label);require(target.logits().size()==129280,"global full head");std::vector<uint8_t>head(517120);std::memcpy(head.data(),target.logits().data(),head.size());create_file(d/"head.bin",head);math(network,label+"-draft");
  auto*actual=dynamic_cast<CoreTargetAdapter*>(&target);require(actual,"global actual Core adapter");std::string records="[";size_t n=0;std::set<unsigned>swa;
  actual->fixture_visit_state([&](const FixtureStateRecord&r,void*s){require(r.kind,"global typed kind");auto kind=std::string(r.kind);if(kind=="core")require(r.first==0&&r.end==40&&r.position==cursor&&r.valid,"global full forty core range");if(kind=="swa"){require(r.writer<40&&swa.insert(r.writer).second,"global unique forty SWA");}
   std::vector<uint8_t>b;if(r.value.data)b=download(r.value,s);else if(r.host_bytes){require(r.host,"global typed host payload");b.resize(r.host_bytes);std::memcpy(b.data(),r.host,b.size());}
   auto name=std::to_string(n)+"-"+kind+"-"+std::to_string(r.writer)+".bin";create_file(d/name,b);if(n++)records+=',';records+="{\"kind\":"+quote(kind)+",\"writer\":"+std::to_string(r.writer)+",\"ratio\":"+std::to_string(r.ratio)+",\"position\":"+std::to_string(r.position)+",\"epoch\":"+std::to_string(r.epoch)+",\"rows\":"+std::to_string(r.rows)+",\"valid\":"+(r.valid?"true":"false")+",\"first\":"+std::to_string(r.first)+",\"end\":"+std::to_string(r.end)+",\"value_rows\":"+std::to_string(r.value.rows)+",\"columns\":"+std::to_string(r.value.columns)+",\"scalar\":"+std::to_string(unsigned(r.value.scalar))+",\"bytes\":"+std::to_string(b.size())+",\"file\":"+quote(name)+",\"sha256\":"+quote(hash(b))+"}";});require(swa.size()==40,"global all forty state observed");records+=']';create_text(d/"state.json","{\"schema\":\"T38-global-state-v1\",\"cursor\":"+std::to_string(cursor)+",\"records\":"+records+"}\n");if(phase=="candidate")cursors.insert(cursor);
 }
 uint32_t greedy(const ActorTarget&t){const auto&h=t.logits();require(h.size()==129280,"global greedy current head");uint32_t best=0;for(uint32_t i=0;i<h.size();++i){require(std::isfinite(h[i]),"global finite greedy");if(h[i]>h[best])best=i;}return best;}
 void proposal(const DraftProposal&p,const std::string&label){require(p.ids.size()==5&&p.q.size()==5&&p.raw_confidence.size()==5&&!p.seed_only,"global long proposal five rows");auto d=directory(label);create_text(d/"ids.json",actor_ids(p.ids));std::vector<uint8_t>c(20);std::memcpy(c.data(),p.raw_confidence.data(),20);create_file(d/"confidence.bin",c);for(unsigned i=0;i<5;++i){require(p.q[i].size()==129280,"global long vocabulary");std::vector<uint8_t>b(1034240);std::memcpy(b.data(),p.q[i].data(),b.size());create_file(d/("q-"+std::to_string(i)+".bin"),b);}}
};
void GlobalAudit::stage(const std::string&name,const DeviceView&v,void*s){auto r=root.lock();if(!r)return;if(name!="ffn_router_ids"&&name!="ffn_router_weights")return;bool selected=r->selected=="L130"?(position>=126&&position<=130):(position>=2&&position<=6);if(!selected)return;require(layer<40,"global route layer");auto d=r->directory("routes");auto label=std::to_string(position)+"-"+std::to_string(layer)+"-"+name;auto bytes=r->download(v,s);create_file(d/(label+".bin"),bytes);create_text(d/(label+".json"),"{\"position\":"+std::to_string(position)+",\"layer\":"+std::to_string(layer)+",\"rows\":"+std::to_string(v.rows)+",\"columns\":"+std::to_string(v.columns)+",\"bytes\":"+std::to_string(bytes.size())+",\"scalar\":"+std::to_string(unsigned(v.scalar))+",\"sha256\":"+quote(hash(bytes))+"}\n");}
struct GlobalControlledDraft final:ActorDraft {
 ActorDraft&actual;ActorTarget&target;std::shared_ptr<GlobalCapture>root;
 GlobalControlledDraft(ActorDraft&a,ActorTarget&t,std::shared_ptr<GlobalCapture>r):actual(a),target(t),root(std::move(r)){}
 DraftProposal propose(uint64_t width,const SamplingOptions&o,const std::vector<uint32_t>&history,NamespaceRng&rng,const ContinueWork&work)override{
  auto raw=actual.propose(width,o,history,rng,work);auto&s=*root;require(width==3&&raw.ids.size()==3&&raw.q.size()==3&&raw.raw_confidence.size()==3&&!raw.seed_only&&s.cycles<2,"global controlled real width three");
  for(unsigned i=0;i<3;++i){require(raw.q[i].size()==129280&&s.raw_count<6,"global bounded learned archive");s.raw_ids[s.raw_count]=raw.ids[i];s.raw_conf[s.raw_count]=raw.raw_confidence[i];std::copy(raw.q[i].begin(),raw.q[i].end(),s.raw_q[s.raw_count++].begin());}
  std::array<uint32_t,3>ids{};if(!s.cycles)ids=s.selected=="Rmid"?std::array<uint32_t,3>{288,0,0}:s.selected=="Rlast"?std::array<uint32_t,3>{288,16,0}:std::array<uint32_t,3>{288,16,342};else ids={s.selected=="Rmid"?342:s.greedy(target),0,0};++s.cycles;
  DraftProposal p;p.ids.assign(ids.begin(),ids.end());p.raw_confidence.assign(3,0.f);for(auto id:ids){p.q.emplace_back(129280,0.);p.q.back()[id]=1.;}return p;
 }
 uint64_t cursor()const override{return actual.cursor();}void drain()override{actual.drain();}void invalidate_and_drain()noexcept override{actual.invalidate_and_drain();}bool completion_known()const noexcept override{return actual.completion_known();}
};
#endif

}
#ifndef T38_SEED_CPU_VALIDATOR
namespace strata_ext::deepseek41 {
#ifdef STRATA_T38_GLOBAL_FIXTURE
T38GlobalFixture make_t38_global_fixture(std::string input_manifest,std::string output_directory){
 using namespace seed_fixture_detail;auto base=std::make_shared<State>();base->manifest=parse(read_metadata(input_manifest,65536));base->output=fs::u8path(output_directory);require(base->output.is_absolute()&&!fs::exists(base->output)&&fs::create_directory(base->output),"global create-only output");
 for(const auto&r:base->manifest.receipts){auto value=read_metadata(r.second.first,1024*1024);require(value.sha==r.second.second,"global receipt authority");}
 auto&c=base->manifest.caller;base->expected={decimal(c.at("owner")),decimal(c.at("epoch")),c.at("bundle")};create_file(base->output/"input-manifest.tsv",base->manifest.original.bytes);create_text(base->output/"input-binding.json",input_binding_json(base->manifest.original));
 auto receipt=base->manifest.receipts.at("input_lineage");auto line=read_metadata(receipt.first,65536);require(line.sha==receipt.second,"global lineage SHA");std::map<std::string,std::string>v;std::istringstream in(std::string(line.bytes.begin(),line.bytes.end()));std::string item;
 while(std::getline(in,item)){if(!item.empty()&&item.back()=='\r')item.pop_back();auto at=item.find('\t');require(at!=std::string::npos&&item.find('\t',at+1)==std::string::npos&&at&&at+1<item.size()&&v.emplace(item.substr(0,at),item.substr(at+1)).second,"global lineage unique scalars");}
 require(v.at("schema")=="T38-global-lineage-v1"&&v.at("plan_sha256")=="726b1d7993bd407f22cd335eda9dff76a0c3370b02b0772387b01e74ce942d39","global accepted recipe");auto selected=v.at("case");require(selected=="Rmid"||selected=="Rlast"||selected=="All"||selected=="A4"||selected=="L130","global five cases");require(decimal(base->manifest.producer.at("context"))==(selected=="L130"?4096:8),"global finite context");
 auto root=std::make_shared<GlobalCapture>(base,selected);root->audit=std::make_shared<GlobalAudit>();root->audit->root=root;
 if(selected=="L130"){require(v.size()==4&&fs::u8path(v.at("ids_file")).is_absolute(),"global complete L130 input");auto ids=read_metadata(v.at("ids_file"),520);require(ids.bytes.size()==520&&ids.sha=="61dd9087c7c09bf66321cf8be324df62771a9d17961e6f08001f8dd6c1bcda68","global original official130");root->prefix.resize(130);std::memcpy(root->prefix.data(),ids.bytes.data(),520);for(auto id:root->prefix)require(id<129280,"global original IDs");}else{require(v.size()==3,"global short lineage fields");root->prefix={3,37,1024};}
 auto candidate=[root](ActorTarget&target,ActorDraft&draft,DraftNetwork&network,const RequestBinding&binding){
  require(!root->candidate_done&&binding.owner==root->base->expected.owner&&binding.epoch==root->base->expected.epoch&&binding.bundle==root->base->expected.bundle,"global candidate identity");root->phase="candidate";ActorResult result;
  if(root->selected!="L130"){
   SamplingOptions o;o.temperature=0;o.top_p=1;o.top_k=0;o.min_p=0;o.repetition_penalty=1;o.frequency_penalty=0;o.presence_penalty=0;o.logprobs=false;o.top_logprobs=0;
   GlobalControlledDraft controlled(draft,target,root);ActorDraft&selected=root->selected=="A4"?draft:static_cast<ActorDraft&>(controlled);RequestActor actor(target,selected,binding,0);actor.set_fixture_trace({root.get(),&GlobalCapture::observe});
   result=actor.run({3,37,1024},root->maximum,root->width,o,[]{return ActorStop::Continue;},[&](const SampledToken&){root->snapshot(target,network,target.known_cursor());++root->emitted;});root->save_trace(result);require(result.context_valid&&result.completion_known&&result.error.empty()&&!root->overflow&&!root->unsafe,"global complete finite actor");root->reference_prefix=root->prefix;root->reference_prefix.insert(root->reference_prefix.end(),result.ledger.processed.begin(),result.ledger.processed.end());
  }else{
   network.set_fixture_seed_observer(std::array<uint64_t,5>{126,127,128,129,130},[root](uint64_t pos,const RequestBinding&b,const DraftDeviceMetadata&m,const DeviceView&features,const DeviceView&main,const std::array<DeviceView,3>&rings,void*s){require(m.valid&&m.cursor==pos+1&&m.owner==b.owner,"global long fivepoint seed");auto d=root->directory("seed-"+std::to_string(pos+1));std::string fields="["+root->field(d,"features",features,s)+','+root->field(d,"main",main,s);for(unsigned i=0;i<3;++i)fields+=','+root->field(d,"ring"+std::to_string(i),rings[i],s);create_text(d/"fields.json",fields+"]\n");});
   std::vector<uint32_t>initial(root->prefix.begin(),root->prefix.begin()+127);target.prefill(initial);target.drain();draft.drain();root->snapshot(target,network,127);
   SamplingOptions options;options.temperature=0;options.top_p=1;options.top_k=0;options.min_p=0;options.repetition_penalty=1;options.frequency_penalty=0;options.presence_penalty=0;options.logprobs=false;options.top_logprobs=0;
   auto propose=[&](const std::string&name,const std::vector<uint32_t>&history){NamespaceRng rng(0);auto p=network.propose(5,options,history,rng);root->proposal(p,name);};
   propose("proposal-127",initial);network.begin_checkpoint();target.step(root->prefix[127],127);target.drain();draft.drain();root->snapshot(target,network,128);
   auto*actual=dynamic_cast<CoreTargetAdapter*>(&target);require(actual,"global real long adapter");root->replay_storage=std::make_unique<CoreStorage>(0);root->owned_mean=root->replay_storage->allocate("global-owned-last-mean",1,15360,DeviceScalar::Bfloat16InFloat32);
   actual->fixture_visit_last_processed_mean([&](uint32_t id,const StepProof&p,const DeviceView&mean,void*s){require(id==root->prefix[127]&&p.before==127&&p.after==128&&p.binding.owner==binding.owner,"global actual replay ID/proof");validate_view(mean,1,15360,0);root->unsafe=true;require(hipMemcpyAsync(root->owned_mean.data,mean.data,61440,hipMemcpyDeviceToDevice,reinterpret_cast<hipStream_t>(s))==hipSuccess,"global owned mean enqueue");require(hipStreamSynchronize(reinterpret_cast<hipStream_t>(s))==hipSuccess,"global owned mean ready");root->unsafe=false;root->owned_id=id;root->owned_proof=p;root->replay_ready=true;});
   std::vector<uint32_t>h128(root->prefix.begin(),root->prefix.begin()+128);propose("proposal-128-before",h128);network.restore_checkpoint();root->math(network,"restore-127");require(root->replay_ready&&!root->unsafe,"global positive owned replay completion");std::array<DeviceView,3>slices;std::array<const DeviceView*,3>views;for(unsigned i=0;i<3;++i){slices[i]=root->owned_mean;slices[i].data=(float*)root->owned_mean.data+i*5120;slices[i].columns=5120;slices[i].bytes=20480;views[i]=&slices[i];}
   network.record_processed(root->owned_id,127,binding,root->owned_proof.taps,views,root->replay_storage->stream());network.drain();root->math(network,"replay-128");propose("proposal-128-after",h128);network.commit_checkpoint();require(target.known_cursor()==network.processed_cursor()&&network.processed_cursor()==128,"global rejoined after mathematical restore");root->replay_storage->drain();root->replay_ready=false;
   for(unsigned pos=128;pos<130;++pos){target.step(root->prefix[pos],pos);target.drain();draft.drain();root->snapshot(target,network,pos+1);if(pos==128){std::vector<uint32_t>history(root->prefix.begin(),root->prefix.begin()+129);propose("proposal-129",history);}}
   root->reference_prefix=root->prefix;auto first=root->greedy(target);result.ledger.prompt=130;result.ledger.cursor=130;result.ledger.emitted.push_back(first);result.ledger.pending=first;if(first==1)result.ledger.finish=Finish::Eos;else{target.step(first,130);target.drain();draft.drain();root->reference_prefix.push_back(first);root->snapshot(target,network,131);auto second=root->greedy(target);result.ledger.processed.push_back(first);result.ledger.processed_generated=1;result.ledger.cursor=131;result.ledger.emitted.push_back(second);result.ledger.pending=second;result.ledger.finish=second==1?Finish::Eos:Finish::Length;}
   result.known_target_cursor=target.known_cursor();result.draft_cursor=draft.cursor();result.context_valid=true;result.completion_known=target.completion_known()&&draft.completion_known();create_text(root->directory("result")/"actor-result.json",actor_result_json(result));
  }
  target.drain();draft.drain();require(result.completion_known&&result.context_valid&&!root->unsafe,"global known candidate to fresh");create_text(root->base->output/"processed-prefix.json",actor_ids(root->reference_prefix));root->candidate_done=true;return result;
 };
 auto fresh=[root](ActorTarget&target,ActorDraft&draft,DraftNetwork&network,const RequestBinding&binding){require(root->candidate_done&&binding.owner!=root->base->expected.owner&&binding.epoch==root->base->expected.epoch&&binding.bundle==root->base->expected.bundle&&target.known_cursor()==0&&draft.cursor()==0,"global distinct fresh context");root->phase="fresh";auto initial=root->selected=="L130"?127u:3u;std::vector<uint32_t>prompt(root->reference_prefix.begin(),root->reference_prefix.begin()+initial);target.prefill(prompt);target.drain();draft.drain();if(root->cursors.count(initial))root->snapshot(target,network,initial);for(size_t i=initial;i<root->reference_prefix.size();++i){target.step(root->reference_prefix[i],i);target.drain();draft.drain();if(root->cursors.count(i+1))root->snapshot(target,network,i+1);}
  require(!root->unsafe&&target.completion_known()&&draft.completion_known(),"global known fresh reference");ActorResult r;r.context_valid=true;r.completion_known=true;r.known_target_cursor=target.known_cursor();r.draft_cursor=draft.cursor();create_text(root->base->output/"fresh-completion.json","{\"new_owner\":"+std::to_string(binding.owner)+",\"candidate_owner\":"+std::to_string(root->base->expected.owner)+",\"epoch\":"+std::to_string(binding.epoch)+",\"cursor\":"+std::to_string(r.known_target_cursor)+",\"completion_known\":true,\"old_pending_replayed\":false}\n");return r;};
 require(base->expected.owner<UINT64_MAX,"global next owner overflow");T38FixtureNext next{c.at("request_id")+"-fresh",RequestBinding{base->expected.owner+1,base->expected.epoch,base->expected.bundle},fresh};return T38GlobalFixture{candidate,next,root->audit};
}
#endif

T38FixtureBody make_t38_seed_body(std::string input_manifest,std::string output_directory){
 using namespace seed_fixture_detail;auto state=std::make_shared<State>();state->manifest=parse(read_metadata(input_manifest,65536));state->output=fs::u8path(output_directory);require(state->output.is_absolute()&&!fs::exists(state->output),"seed new absolute output");require(fs::create_directory(state->output),"seed output create");
 for(const auto&r:state->manifest.receipts){auto saved=read_metadata(r.second.first,1024*1024);require(saved.sha==r.second.second,"seed authority receipt changed");}
 auto&c=state->manifest.caller;state->expected={decimal(c.at("owner")),decimal(c.at("epoch")),c.at("bundle")};auto&r=state->manifest.original;create_file(state->output/"input-manifest.tsv",r.bytes);
 create_text(state->output/"input-binding.json",input_binding_json(r));
#ifdef T38_REMAINING_BODY
 require(decimal(state->manifest.producer.at("context"))==6,"remaining finite context6");auto observed=std::make_shared<RemainingCapture>(state,remaining_case(state->manifest));
 return [observed](t38::ActorTarget&target,t38::ActorDraft&draft,t38::DraftNetwork&network,const t38::RequestBinding&binding){
  auto&s=*observed->base;require(!s.entered&&binding.owner==s.expected.owner&&binding.epoch==s.expected.epoch&&binding.bundle==s.expected.bundle,"remaining fresh body binding");s.entered=true;auto selected=observed->selected=="C"?3u:4u;
  network.set_fixture_seed_observer(selected,[observed,selected](uint64_t pos,const RequestBinding&actual,const DraftDeviceMetadata&m,const DeviceView&joined,const DeviceView&main,const std::array<DeviceView,3>&rings,void*stream){
   auto&s=*observed->base;require(!observed->five_complete&&!s.copy_unknown&&pos==selected&&m.valid&&actual.owner==s.expected.owner&&actual.epoch==s.expected.epoch&&actual.bundle==s.expected.bundle&&m.owner==actual.owner&&m.epoch==actual.epoch&&m.cursor==pos+1&&m.stage_cursor==std::array<uint64_t,3>{pos+1,pos+1,pos+1}&&m.processed_prior,"remaining processed five-view provenance");
   std::array<DeviceView,5>views{joined,main,rings[0],rings[1],rings[2]};for(unsigned n=0;n<5;++n){validate_view(views[n],n<2?1:128,n==0?15360:n==1?5120:512,0);require(views[n].owner==views[0].owner&&views[n].generation==views[0].generation,"remaining same owner/generation");}check_device_stream(stream,0);
   auto checked=[](hipError_t e){if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));};copy_completed(s,views,[&](void*host,const DeviceView&v){checked(hipMemcpyAsync(host,v.data,size_t(v.bytes),hipMemcpyDeviceToHost,reinterpret_cast<hipStream_t>(stream)));},[&]{checked(hipStreamSynchronize(reinterpret_cast<hipStream_t>(stream)));});observed->five_complete=true;observed->position=pos;observed->cursor=m.cursor;observed->prior=*m.processed_prior;observed->stage=m.stage_cursor;observed->stream=reinterpret_cast<uintptr_t>(stream);observed->owner=reinterpret_cast<uintptr_t>(joined.owner);observed->generation=joined.generation;
  });
  ActorResult result;
  if(observed->selected=="B-fresh"){target.prefill({3,37,1024,288,16});target.drain();draft.drain();require(target.completion_known()&&draft.completion_known()&&target.known_cursor()==5&&draft.cursor()==5,"remaining fresh P5 complete");require(target.logits().size()==129280,"remaining full target head");std::memcpy(observed->heads[0].data(),target.logits().data(),517120);observed->emitted=1;result.known_target_cursor=5;result.draft_cursor=5;result.completion_known=true;result.context_valid=true;}
  else{SamplingOptions options;options.temperature=observed->selected=="C"?1:0;options.top_p=1;options.top_k=0;options.min_p=0;options.repetition_penalty=1;options.frequency_penalty=0;options.presence_penalty=0;options.logprobs=false;options.top_logprobs=0;
   RequestActor actor(target,draft,binding,0);actor.set_fixture_trace({observed.get(),&RemainingCapture::observe});result=actor.run({3,37,1024},observed->maximum,1,options,[]{return ActorStop::Continue;},[&](const SampledToken&token){(void)token;require(observed->emitted<observed->maximum&&target.logits().size()==129280,"remaining bounded actual emitter head");std::memcpy(observed->heads[observed->emitted++].data(),target.logits().data(),517120);});}
  save_remaining(*observed,result);return result;
 };
#elif defined(T38_ACTOR_BODY)
 auto lineage=actor_lineage(state->manifest);require(decimal(state->manifest.producer.at("context"))>=4,"actor context permits position3");require_actor_ready(lineage);auto observed=std::make_shared<ActorCapture>();observed->base=state;
 return [observed](t38::ActorTarget&target,t38::ActorDraft&draft,t38::DraftNetwork&network,const t38::RequestBinding&binding){
  auto&s=*observed->base;require(!s.entered&&binding.owner==s.expected.owner&&binding.epoch==s.expected.epoch&&binding.bundle==s.expected.bundle,"actor fresh body binding");s.entered=true;
  network.set_fixture_seed_observer(3,[observed](uint64_t pos,const RequestBinding&actual,const DraftDeviceMetadata&m,const DeviceView&joined,const DeviceView&,const std::array<DeviceView,3>&,void*stream){
   validate_actor_joined(*observed,pos,actual,observed->base->expected,m,joined,stream);check_device_stream(stream,0);auto checked=[](hipError_t e){if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));};copy_actor_joined(*observed,joined,[&](void*host,const DeviceView&v){checked(hipMemcpyAsync(host,v.data,size_t(v.bytes),hipMemcpyDeviceToHost,reinterpret_cast<hipStream_t>(stream)));},[&]{checked(hipStreamSynchronize(reinterpret_cast<hipStream_t>(stream)));});observed->prior=*m.processed_prior;observed->processed_cursor=m.cursor;observed->stage_cursor=m.stage_cursor;observed->processed_valid=m.valid;observed->stream=reinterpret_cast<uintptr_t>(stream);observed->allocation_owner=reinterpret_cast<uintptr_t>(joined.owner);observed->generation=joined.generation;
  });
  auto result=run_actor_capture(*observed,target,draft,binding);save_actor_capture(*observed,result);return result;
 };
#elif defined(T38_PROPOSAL_BODY)
 proposal_lineage(state->manifest);auto observed=std::make_shared<ProposalState>();observed->base=state;for(unsigned n=0;n<6;++n)observed->host[n].resize(size_t(proposal_specs[n].bytes));
 return [observed](t38::ActorTarget&target,t38::ActorDraft&draft,t38::DraftNetwork&network,const t38::RequestBinding&binding){
  auto&s=*observed->base;require(!s.entered&&binding.owner==s.expected.owner&&binding.epoch==s.expected.epoch&&binding.bundle==s.expected.bundle,"proposal fresh body/binding");s.entered=true;
  network.set_fixture_proposal_observer([observed](FixtureProposalField field,const RequestBinding&actual,uint64_t cursor,const DeviceView&v,void*stream){
   auto n=unsigned(field);validate_proposal_event(n,observed->events,actual,observed->base->expected,cursor,v,stream);validate_proposal_stream(*observed,n,stream);check_device_stream(stream,0);auto checked=[](hipError_t e){if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));};copy_proposal_event(*observed,n,v,[&](void*host,const DeviceView&view){checked(hipMemcpyAsync(host,view.data,size_t(view.bytes),hipMemcpyDeviceToHost,reinterpret_cast<hipStream_t>(stream)));},[&]{checked(hipStreamSynchronize(reinterpret_cast<hipStream_t>(stream)));});
   const auto&spec=proposal_specs[n];create_file(observed->base->output/(std::string(spec.name)+".bin"),observed->host[n]);observed->descriptors[n]=result_descriptor(spec.name,spec.rows,spec.columns,"<f4",spec.bytes,hash(observed->host[n]));observed->event_metadata[n]="{\"field\":"+quote(spec.name)+",\"producer_stream\":"+quote(std::to_string(reinterpret_cast<uintptr_t>(stream)))+",\"allocation_owner\":"+quote(std::to_string(reinterpret_cast<uintptr_t>(v.owner)))+",\"generation\":"+std::to_string(v.generation)+",\"device\":0,\"copy_drained\":true}";++observed->events;
  });
  const std::vector<uint32_t>history{3,37,1024};target.prefill(history);target.drain();draft.drain();require(target.completion_known()&&draft.completion_known()&&target.known_cursor()==3&&draft.cursor()==3,"proposal actual P3 prefill completion");
  // Values are the finite options in immutable accepted manifest8200b3a8, whose
  // full bytes were verified by proposal_lineage before constructing native owners.
  SamplingOptions options;options.temperature=0;options.top_k=0;options.top_p=1;options.min_p=0;options.repetition_penalty=1;options.frequency_penalty=0;options.presence_penalty=0;options.logprobs=false;options.top_logprobs=0;NamespaceRng rng(0);auto proposal=draft.propose(5,options,history,rng,ContinueWork{});target.drain();draft.drain();
  require_proposal_complete(*observed);require(target.completion_known()&&draft.completion_known()&&target.known_cursor()==3&&draft.cursor()==3,"proposal six completed events/cursors");validate_public_proposal(proposal);auto result_fields=save_public_proposal(s.output,proposal);std::string fields="[",events="[";for(unsigned n=0;n<6;++n){if(n){fields+=',';events+=',';}fields+=observed->descriptors[n];events+=observed->event_metadata[n];}fields+=','+result_fields+']';events+=']';
  create_text(s.output/"capture.json","{\"schema\":\"T38-actual-proposal-capture-v1\",\"fixture_kind\":\"proposal\",\"manifest_sha256\":"+quote(s.manifest.original.sha)+",\"owner\":"+std::to_string(binding.owner)+",\"epoch\":"+std::to_string(binding.epoch)+",\"bundle\":"+quote(binding.bundle)+",\"request_id\":"+quote(s.manifest.caller.at("request_id"))+",\"processed_cursor\":3,\"position\":2,\"width\":5,\"copy_drained\":true,\"events\":"+events+",\"fields\":"+fields+",\"RNG_draws_measured\":false,\"source_RNG_callsite_contract\":{\"Proposal\":5,\"Target\":0,\"Accept\":0,\"Residual\":0,\"Bonus\":0}}\n");
  create_text(s.output/"completion.json","{\"fixture_kind\":\"proposal\",\"actual_target_cursor\":3,\"actual_draft_cursor\":3,\"completion_known\":true,\"proposal_calls\":1,\"RequestActor_run_called\":false,\"target_step_called\":false,\"ledger_success_claimed\":false}\n");ActorResult result;result.known_target_cursor=target.known_cursor();result.draft_cursor=draft.cursor();result.completion_known=true;result.context_valid=true;return result;
 };
#else
 return [state](t38::ActorTarget&target,t38::ActorDraft&draft,t38::DraftNetwork&network,const t38::RequestBinding&binding){
  require(!state->entered&&binding.owner==state->expected.owner&&binding.epoch==state->expected.epoch&&binding.bundle==state->expected.bundle,"seed body one entry/binding");state->entered=true;
  network.set_fixture_seed_observer(2,[state](uint64_t pos,const RequestBinding&actual,const DraftDeviceMetadata&m,const DeviceView&joined,const DeviceView&derived,const std::array<DeviceView,3>&rings,void*stream){
   require(!state->captured,"seed callback once");validate_completion(pos,actual,m,state->expected);std::array<DeviceView,5>views{joined,derived,rings[0],rings[1],rings[2]};for(unsigned n=0;n<5;++n)validate_view(views[n],n<2?1:128,n==0?15360:n==1?5120:512,0);for(unsigned n=1;n<5;++n)require(views[n].owner==views[0].owner&&views[n].generation==views[0].generation,"seed same actual owner lease");check_device_stream(stream,0);
   auto checked=[](hipError_t e){if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));};copy_completed(*state,views,[&](void*host,const DeviceView&v){checked(hipMemcpyAsync(host,v.data,size_t(v.bytes),hipMemcpyDeviceToHost,reinterpret_cast<hipStream_t>(stream)));},[&]{checked(hipStreamSynchronize(reinterpret_cast<hipStream_t>(stream)));});
   const std::array<std::string,5>names{"joined","main","ring0","ring1","ring2"};std::string fields="[";for(unsigned n=0;n<5;++n){create_file(state->output/(names[n]+".bin"),state->host[n]);if(n)fields+=',';fields+="{\"name\":"+quote(names[n])+",\"rows\":"+std::to_string(views[n].rows)+",\"columns\":"+std::to_string(views[n].columns)+",\"dtype\":\"BF16-in-F32\",\"bytes\":"+std::to_string(state->host[n].size())+",\"sha256\":"+quote(hash(state->host[n]))+"}";}fields+=']';
   create_text(state->output/"capture.json","{\"schema\":\"T38-actual-seed-capture-v1\",\"owner\":"+std::to_string(m.owner)+",\"epoch\":"+std::to_string(m.epoch)+",\"bundle\":"+quote(actual.bundle)+",\"request_id\":"+quote(state->manifest.caller.at("request_id"))+",\"position\":2,\"cursor\":3,\"stage_cursor\":[3,3,3],\"prior\":1024,\"valid\":true,\"producer_stream\":"+quote(std::to_string(reinterpret_cast<uintptr_t>(stream)))+",\"actual_owner\":"+quote(std::to_string(reinterpret_cast<uintptr_t>(views[0].owner)))+",\"generation\":"+std::to_string(views[0].generation)+",\"copy_drained\":true,\"manifest_sha256\":"+quote(state->manifest.original.sha)+",\"fields\":"+fields+"}\n");state->captured=true;
  });
  target.prefill({3,37,1024});target.drain();draft.drain();require(state->captured&&!state->copy_unknown&&target.completion_known()&&draft.completion_known()&&target.known_cursor()==3&&draft.cursor()==3,"seed actual prefill completion");t38::ActorResult result;result.known_target_cursor=target.known_cursor();result.draft_cursor=draft.cursor();result.completion_known=target.completion_known()&&draft.completion_known();result.context_valid=true;
  create_text(state->output/"completion.json","{\"actual_target_cursor\":3,\"actual_draft_cursor\":3,\"completion_known\":true,\"RequestActor_run_called\":false,\"propose_called\":false,\"ledger_success_claimed\":false}\n");return result;
 };
#endif // T38_PROPOSAL_BODY
}
}
#endif
#else
#include "../../../models/deepseek41/dspark/session.hpp"
#include "../../../models/deepseek41/dspark/draft_asset.hpp"
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <cstring>
#include <limits>
#include <type_traits>
#ifdef T38_SHARED_SAMPLING
#include <sampling.hpp>
#include <t38_legacy/sampling.hpp>
#include <cstdlib>
#include <new>
static long fail_allocation=-1;
void* operator new(std::size_t n){if(fail_allocation==0)throw std::bad_alloc();if(fail_allocation>0)--fail_allocation;if(void*p=std::malloc(n?n:1))return p;throw std::bad_alloc();}
void operator delete(void*p)noexcept{std::free(p);}
void operator delete(void*p,std::size_t)noexcept{std::free(p);}
#endif
#include <stdexcept>
using namespace strata_ext::dspark::t38;
namespace {
void check(bool x){if(!x)throw std::runtime_error("fixture assertion");}
std::vector<uint8_t> prefix(const std::string&p){std::ifstream f(p,std::ios::binary);if(!f)throw std::runtime_error("prefix open");std::vector<uint8_t>b(65536);f.read(reinterpret_cast<char*>(b.data()),std::streamsize(b.size()));b.resize(size_t(f.gcount()));return b;}
std::vector<double> probabilities(const char*s){std::vector<double> v;std::istringstream f(s);std::string x;while(std::getline(f,x,',')){size_t n=0;auto value=std::stod(x,&n);if(n!=x.size())throw std::invalid_argument("bad number");v.push_back(value);}return v;}
std::vector<uint32_t> ids(const char*s){std::vector<uint32_t> v;std::istringstream f(s);std::string x;while(std::getline(f,x,',')){auto n=std::stoull(x);if(n>UINT32_MAX)throw std::invalid_argument("ID overflow");v.push_back(uint32_t(n));}return v;}
void list(const std::vector<uint32_t>&v){std::cout<<'[';for(size_t i=0;i<v.size();++i){if(i)std::cout<<',';std::cout<<v[i];}std::cout<<']';}
struct Fake final:TargetAdapter {
 unsigned calls=0,bad=0;bool invalid=false;
 StepProof step(uint32_t,uint64_t pos)override{++calls;StepProof p{{7,9,"fixture"},pos,pos+1,{}};for(unsigned i=0;i<3;++i)p.taps[i]={7,9,pos,37+i,4,5120};
  if(bad==1)p.binding.owner=8;if(bad==2)p.binding.epoch=10;if(bad==3)p.before=pos+1;if(bad==4)p.after=pos+2;if(bad==5)p.taps[2].layer=38;if(bad==6)p.taps[0].position=pos+1;if(bad==7)p.taps[1].owner=8;if(bad==8)throw std::runtime_error("injected step failure");return p;}
 void invalidate_and_drain()noexcept override{invalid=true;}
};
void selftest(){unsigned count=0;auto yes=[&](bool b){check(b);++count;};auto rejects=[&](auto fn){bool bad=false;try{fn();}catch(const std::exception&){bad=true;}yes(bad);};
 // TargetSupply bounded geometry: no file/HIP calls in this contract test.
 {TargetMatrixExtent m{5120,129280,20480,64,2647654400ull,2647654464ull};
  validate_target_matrix(m,20480,40960);auto tile=target_matrix_tile(m,129279,1,40960);yes(tile.offset==2647633984ull&&tile.bytes==20480);
  rejects([&]{target_matrix_tile(m,129280,1,40960);});rejects([&]{target_matrix_tile(m,129279,2,40960);});rejects([&]{target_matrix_tile(m,0,3,40960);});rejects([&]{validate_target_matrix(m,10240,40960);});rejects([&]{validate_target_matrix(m,20480,1);});
  auto bad=m;bad.file_bytes--;rejects([&]{validate_target_matrix(bad,20480,40960);});bad=m;bad.rows=1;rejects([&]{validate_target_matrix(bad,20480,40960);});bad=m;bad.offset=UINT64_MAX;rejects([&]{validate_target_matrix(bad,20480,40960);});
 }
 // Attention-R1: reuse one allocation for increasing positions and ring wrap.
 {struct IndexView{uint64_t rows,columns,bytes;uintptr_t pointer;};
  for(uint64_t width:{1ull,5ull,7ull}){
   auto extent=noise_index_extent(1,width);IndexView storage{1,extent.capacity,extent.capacity_bytes,16};
   const uint64_t positions[]={1,2,126,127,128,129,255,1};const uint64_t prefixes[]={2,3,127,128,128,128,128,2};
   for(unsigned i=0;i<8;++i){auto requested=noise_index_extent(positions[i],width);yes(requested.capacity==extent.capacity&&requested.capacity_bytes==extent.capacity_bytes);auto logical=noise_index_logical(storage,positions[i],width);yes(logical.rows==1&&logical.columns==prefixes[i]+width&&logical.bytes==(prefixes[i]+width)*8&&logical.pointer==storage.pointer);yes(storage.columns==128+width&&storage.bytes==(128+width)*8);}
  }
  IndexView short_storage{1,133,133*8-1,16};rejects([&]{noise_index_logical(short_storage,2,5);});short_storage={1,8,133*8,16};rejects([&]{noise_index_logical(short_storage,2,5);});rejects([&]{noise_index_extent(2,0);});rejects([&]{noise_index_extent(2,UINT64_MAX);});
 }
 // Checkpoint-R1: fault at producer drain, each copy, or final drain.
 for(int fail=0;fail<6;++fail){
  DraftDeviceMetadata saved;saved.owner=7;saved.epoch=9;saved.cursor=3;saved.stage_cursor={3,3,3};saved.processed_prior=2;
  auto actual=saved;actual.cursor=8;actual.stage_cursor={8,8,8};actual.processed_prior=4;
  bool closed=false;unsigned calls=0;std::array<unsigned,4> bytes={8,8,8,8};
  auto op=[&]{yes(!actual.valid);if(int(calls++)==fail)throw std::runtime_error("injected restore failure");};
  rejects([&]{restore_checkpoint_operations(actual,saved,closed,[&]{op();},[&](unsigned i){op();bytes[i]=3;},[&]{op();});});
  yes(!actual.valid&&closed&&calls==unsigned(fail+1));yes(actual.cursor==8&&actual.processed_prior==4);
  for(unsigned i=0;i<4;++i)yes(bytes[i]==((int(i)+1<fail)?3u:8u));
  unsigned previous=calls;rejects([&]{restore_checkpoint_operations(actual,saved,closed,[&]{++calls;},[&](unsigned){++calls;},[&]{++calls;});});yes(calls==previous&&!actual.valid);
 }
 {DraftDeviceMetadata saved;saved.owner=7;saved.epoch=9;saved.cursor=3;saved.stage_cursor={3,3,3};saved.processed_prior=2;
  auto actual=saved;actual.cursor=8;bool closed=false;unsigned calls=0;
  auto op=[&]{yes(!actual.valid);++calls;};
  restore_checkpoint_operations(actual,saved,closed,[&]{op();},[&](unsigned){op();},[&]{op();});
  yes(calls==6&&actual.valid&&!closed&&actual.owner==7&&actual.epoch==9&&actual.cursor==3&&actual.stage_cursor==saved.stage_cursor&&actual.processed_prior==2);
 }
 validate_f16_alignment(reinterpret_cast<const void*>(uintptr_t(8)));yes(true);rejects([&]{validate_f16_alignment(reinterpret_cast<const void*>(uintptr_t(9)));});rejects([&]{validate_f16_alignment(nullptr);});
 
 for(auto shape:std::vector<std::pair<uint64_t,std::vector<uint32_t>>>{{3,{2,1}},{5,{4,1}},{7,{4,2,1}},{9,{8,1}}}){auto jobs=projection_wave_offsets(shape.first,15360,13,7,shape.first*15360*4,shape.first*13*4,shape.second);uint64_t count=0;for(auto j:jobs){yes(j.first==count&&j.input_bytes==count*15360*4&&j.output_bytes==count*13*4);count+=j.rows;}yes(count==shape.first);}
 rejects([&]{projection_wave_offsets(5,15360,13,7,5*15360*4,5*13*4,{4});});rejects([&]{projection_wave_offsets(5,15360,13,7,5*15360*4,5*13*4,{3,2});});rejects([&]{projection_wave_offsets(5,15360,13,7,5*15360*4,1,{4,1});});

 for(unsigned bad=1;bad<=8;++bad){Session s({7,9,"fixture"},4,4);s.emit(2);Fake f;f.bad=bad;rejects([&]{s.advance_pending(f);});yes(f.invalid&&s.ledger().finish==Finish::Invalid&&s.ledger().cursor==4&&s.ledger().pending==2);}
 Session s({7,9,"fixture"},4,2);Fake f;s.emit(2);s.advance_pending(f);s.emit(3);rejects([&]{s.advance_pending(f);});yes(f.calls==1&&s.ledger().cursor==5&&s.ledger().pending==3);
 Session eos({7,9,"fixture"},4,10);eos.emit(1,true);yes(eos.ledger().finish==Finish::Eos);rejects([&]{eos.advance_pending(f);});
 DraftState d;d.owner=7;d.epoch=9;d.cursor=4;d.stage_cursor={4,4,4};d.ring[0]={1,2,3};d.main_features={1,2};d.processed_prior=2;
 {DraftTransaction tx(d);d.ring[0][0]=99;d.main_features[0]=99;d.cursor=8;}
 yes(d.ring[0][0]==1&&d.main_features[0]==1&&d.cursor==4);
 {DraftTransaction tx(d);d.ring[0][0]=99;tx.restore();yes(d.ring[0][0]==1);DraftState next=d;next.cursor=5;next.stage_cursor={5,5,5};next.ring[0][0]=4;next.processed_prior=3;tx.commit(next);next.ring[0][0]=99;yes(d.ring[0][0]==4&&d.cursor==5);rejects([&]{tx.restore();});}
 {DraftTransaction tx(d);auto wrong=d;wrong.epoch=10;rejects([&]{tx.commit(wrong);});wrong=d;wrong.stage_cursor[0]=1;rejects([&]{tx.commit(wrong);});}
 for(uint64_t seed:{0ull,1ull}){NamespaceRng rng(seed);std::mt19937_64 old(seed);for(unsigned i=0;i<10;++i)yes(rng.draw53(RngSpace::Target)==(old()>>11));}
 rejects([&]{draw_distribution({0.,0.},0.);});rejects([&]{residual_distribution({1.,0.},{1.,0.});});rejects([&]{NamespaceRng n(0);n.uniform(static_cast<RngSpace>(5));});
 std::cout<<"{\"assertions\":"<<count<<",\"gpu_executed\":false,\"network_connected\":false}";
}
}
#ifdef T38_SHARED_SAMPLING
void sampler_test(){
 namespace N=strata_ext::deepseek41;namespace O=t38_legacy;
 static_assert(!std::is_default_constructible_v<N::EffectiveDistribution>);
 unsigned assertions=0;auto yes=[&](bool x){check(x);++assertions;};
 auto old_options=[](const N::SamplingOptions&o){O::SamplingOptions r;r.temperature=o.temperature;r.top_k=o.top_k;r.top_p=o.top_p;r.min_p=o.min_p;r.repetition_penalty=o.repetition_penalty;r.frequency_penalty=o.frequency_penalty;r.presence_penalty=o.presence_penalty;r.penalty_last_n=o.penalty_last_n;r.logit_bias=o.logit_bias;r.logprobs=o.logprobs;r.top_logprobs=o.top_logprobs;return r;};
 auto compare=[&](const auto&a,const auto&b){yes(a.id==b.id);yes(std::memcmp(&a.logprob,&b.logprob,4)==0);yes(a.alternatives.size()==b.alternatives.size());for(size_t i=0;i<a.alternatives.size();++i){yes(a.alternatives[i].first==b.alternatives[i].first);yes(std::memcmp(&a.alternatives[i].second,&b.alternatives[i].second,4)==0);}};
 auto rejects=[&](auto f){bool caught=false;try{f();}catch(const std::invalid_argument&){caught=true;}yes(caught);};
 std::vector<std::vector<float>> vectors={{0,-1000},{0,0,0,0},{1,-2,3,-4,5},{std::numeric_limits<float>::max(),-std::numeric_limits<float>::max()}};
 std::vector<double> uniforms={0.,0.125,0.5,0.75,std::nextafter(1.,0.)};
 for(auto v:vectors)for(unsigned mode=0;mode<8;++mode){N::SamplingOptions o;o.temperature=mode==0?0:mode==1?.5:1;o.top_k=mode==2?1:0;o.top_p=mode==3?.75:1;o.min_p=mode==4?.1:0;o.logprobs=mode>=5;o.top_logprobs=mode==6?uint32_t(std::min<size_t>(3,v.size())):0;if(mode==7){o.repetition_penalty=1.2;o.frequency_penalty=.5;o.presence_penalty=.1;o.logit_bias={{0,.125}};o.penalty_last_n=2;}
  std::vector<uint32_t> h={0,uint32_t(v.size()-1),0};auto oo=old_options(o);
  for(double u:uniforms){bool oldbad=false,newbad=false;O::SampledToken a;N::SampledToken b;try{a=O::sample_logits(v,h,oo,u);}catch(const std::invalid_argument&){oldbad=true;}try{b=N::sample_logits(v,h,o,u);}catch(const std::invalid_argument&){newbad=true;}yes(oldbad==newbad);if(!oldbad){compare(a,b);auto prepared=N::effective_distribution(v,h,o);compare(a,N::sample_distribution(prepared,u));auto p=prepared.probabilities();yes(p.size()==v.size());}}
 }
 N::SamplingOptions options;auto p=N::effective_distribution({0,-1000},{},options);auto mass=p.probabilities();yes(mass==std::vector<double>({1,0}));
 for(double u:{0.,std::nextafter(.5,0.),.5,std::nextafter(.5,1.),std::nextafter(1.,0.)})compare(O::sample_logits({0,0},{},O::SamplingOptions{},u),N::sample_logits({0,0},{},options,u));
 std::vector<float> big(130000,0);compare(O::sample_logits(big,{},O::SamplingOptions{},.999),N::sample_logits(big,{},options,.999));
 auto moved=std::move(p);compare(O::sample_logits({0,-1000},{},O::SamplingOptions{},.75),N::sample_distribution(moved,.75));rejects([&]{p.vocabulary();});rejects([&]{p.probabilities();});rejects([&]{N::sample_distribution(p,0.);});
 auto src=N::effective_distribution({1,2,3},{},options);auto dst=N::effective_distribution({3,2,1},{},options);auto src_before=N::sample_distribution(src,.3),dst_before=N::sample_distribution(dst,.3);unsigned failures=0;
 for(long fail=0;fail<3;++fail){fail_allocation=fail;bool oom=false;try{dst=src;}catch(const std::bad_alloc&){oom=true;}fail_allocation=-1;yes(oom);++failures;compare(src_before,N::sample_distribution(src,.3));compare(dst_before,N::sample_distribution(dst,.3));}
 dst=src;compare(src_before,N::sample_distribution(dst,.3));dst=dst;dst=std::move(dst);compare(src_before,N::sample_distribution(dst,.3));swap(dst,p);rejects([&]{N::sample_distribution(dst,0.);});compare(src_before,N::sample_distribution(p,.3));
 for(uint64_t seed:{0ull,1ull,42ull}){N::RequestSampler n(seed);O::RequestSampler o(seed);for(unsigned i=0;i<30;++i)compare(o.sample({1,2,3},{},O::SamplingOptions{}),n.sample({1,2,3},{},options));N::RequestSampler draws(seed);std::mt19937_64 raw(seed);for(unsigned i=0;i<30;++i){double expected=double(raw()>>11)*0x1.0p-53;yes(draws.next_uniform()==expected);}}
  for(uint64_t seed:{0ull,1ull,42ull}){
  N::RequestSampler n(seed);O::RequestSampler old(seed);std::mt19937_64 old_bits(seed);
  N::SamplingOptions greedy=options;greedy.temperature=0;auto old_greedy=old_options(greedy);
  compare(old.sample({1,2,3},{},old_greedy),n.sample({1,2,3},{},greedy));old_bits();
  compare(old.sample({1,2,3},{},O::SamplingOptions{}),n.sample({1,2,3},{},options));old_bits();
  double expected=double(old_bits()>>11)*0x1.0p-53;yes(n.next_uniform()==expected);
  compare(old.sample({1,2,3},{},O::SamplingOptions{}),N::sample_logits({1,2,3},{},options,expected));
  compare(old.sample({1,2,3},{},O::SamplingOptions{}),n.sample({1,2,3},{},options));
  for(unsigned i=0;i<12;++i){auto o=i%2?options:greedy;compare(old.sample({1,2,3},{},old_options(o)),n.sample({1,2,3},{},o));}
 }
for(double u:{-1.,1.,std::numeric_limits<double>::quiet_NaN()})rejects([&]{N::sample_logits({0,0},{},options,u);});
 std::cout<<"{\"assertions\":"<<assertions<<",\"copy_OOM_points\":"<<failures<<",\"legacy_bit_identity\":true,\"GPU\":false}";
}
#endif
#ifdef T38_NORMAL_PRODUCER_EXTRACT
#include "../../../models/deepseek41/device_ops.hpp"
#include "t38_normal_producer_extract.hpp"
#include "../../../models/deepseek41/prefix_state.hpp"
#include <atomic>
namespace normal_owner_cpu {
using namespace strata_ext::deepseek41;using t38_normal_production_extract::need;using t38_normal_production_extract::prepared_prefix_matches;using t38_normal_production_extract::retain_actor_owners;using t38_normal_production_extract::require_normal_reusable;
struct RequestAdoptionRefused:std::runtime_error{RequestAdoptionRefused():std::runtime_error("CPU adoption refused") {}};
struct Request{std::string id="CPU-request";std::vector<uint32_t>prompt;};using PrefillControl=std::function<bool(uint64_t,uint64_t)>;
std::string identity(const ProducerConfig&,const std::string&id){return id;}
struct Core{uint64_t cursor=0;};
struct Owners {
 PrefixState prefix;bool prefix_enabled=true,cached_request_logits=false,valid=true,refuse=false,unknown_adoption=false,cache_known=true;uint64_t prefix_reused=0,prefix_new=0;unsigned fresh=0,adopted=0,invalidated=0;const char*prefix_action="",*prefix_reason="";int device=0;std::unique_ptr<Core>core=std::make_unique<Core>();PrefixMathKey key;
 Owners(){key.asset="CPU-asset";key.bundle="CPU";key.mode="single";key.primary="0000:07:00.0";key.epoch=1;key.context=8;prefix.allocate(8);}PrefixMathKey prefix_key(){return key;}uint64_t position()const{return core->cursor;}bool request_valid()const{return valid;}void continue_request(const std::string&){++adopted;if(unknown_adoption)throw std::runtime_error("CPU completion unknown");if(refuse)throw RequestAdoptionRefused{};}void request(const std::string&){++fresh;core->cursor=0;}void invalidate_math(){++invalidated;prefix.invalidate();valid=false;}bool idle_drain(const std::string&){return cache_known;}bool finish_prefix(const std::string&,bool healthy){if(!healthy)prefix.invalidate();return healthy;}void publish_prefix(const std::vector<float>&head){prefix.publish(head,position());}
#include "prepare_prefix.inc"
};
namespace mock_t38 {
using PreparedPrefix=strata_ext::dspark::t38::PreparedPrefix;using RequestBinding=strata_ext::dspark::t38::RequestBinding;using ActorResult=strata_ext::dspark::t38::ActorResult;
struct DraftNetwork {uint64_t cursor=0;uint64_t processed_cursor()const{return cursor;}};
struct NetworkActorDraft {DraftNetwork&n;bool complete=true;explicit NetworkActorDraft(DraftNetwork&x):n(x){}bool completion_known()const{return complete;}};
struct CoreTargetAdapter {bool complete=true;PreparedPrefix prepared;std::vector<float>head;CoreTargetAdapter(Core&core,const std::string&,const RequestBinding&,int,DraftNetwork&network,std::function<void()>,PrefillControl,PreparedPrefix p):prepared(std::move(p)),head(129280,0){need(core.cursor==network.cursor&&core.cursor==prepared.processed,"CPU constructor common prefix");}bool completion_known()const{return complete;}const std::vector<float>&logits()const{return head;}};
}
namespace t38=mock_t38;
struct Normal {std::unique_ptr<Owners>owners=std::make_unique<Owners>();std::unique_ptr<t38::DraftNetwork>network=std::make_unique<t38::DraftNetwork>();std::unique_ptr<t38::NetworkActorDraft>draft;std::unique_ptr<t38::CoreTargetAdapter>target;ProducerConfig config;t38::RequestBinding binding{38,1,"CPU"};bool sequence_healthy=false,sequence_started=false,restart_required=false;unsigned rebuilt=0;
 void make_network(int){++rebuilt;++binding.owner;network=std::make_unique<t38::DraftNetwork>();sequence_started=false;}
#include "release_request.inc"
#include "begin_request.inc"
#include "finish_request.inc"
};
unsigned tests(){using AF=strata_ext::dspark::t38::Finish;using Result=strata_ext::dspark::t38::ActorResult;unsigned n=0;auto yes=[&](bool ok){if(!ok)throw std::runtime_error("normal owner actual-body CPU assertion");++n;};auto no=[&](auto fn){bool caught=false;try{fn();}catch(const std::exception&){caught=true;}yes(caught);};std::atomic<int>stop{0};auto progress=[](uint64_t,uint64_t){return true;};Normal root;Request r;r.prompt={3,4,5};yes(root.begin_request(r,stop,progress)&&root.target->prepared.processed==0&&root.owners->fresh==1);root.owners->core->cursor=4;root.network->cursor=4;Result result;result.completion_known=result.context_valid=true;result.known_target_cursor=result.draft_cursor=result.ledger.cursor=4;result.ledger.prompt=3;result.ledger.processed_generated=1;result.ledger.processed={6};result.ledger.emitted={6,7};result.ledger.pending=7;result.ledger.finish=AF::Length;root.finish_request(r,result,true);yes(root.sequence_healthy&&root.owners->prefix.processed_count()==4&&root.owners->prefix_new==3);
 r.prompt={3,4,5,6};yes(root.begin_request(r,stop,progress)&&root.target->prepared.processed==4&&root.target->prepared.logits.size()==129280&&root.owners->cached_request_logits);yes(root.owners->prefix_reused==4&&std::string(root.owners->prefix_action)=="logits");Result cached=result;cached.ledger.prompt=4;cached.ledger.processed_generated=0;cached.ledger.processed.clear();root.finish_request(r,cached,true);
 r.prompt={3,4,5,6,7};yes(root.begin_request(r,stop,progress)&&root.target->prepared.processed==4&&root.target->prepared.logits.empty()&&std::string(root.owners->prefix_action)=="append");root.owners->core->cursor=5;root.network->cursor=5;Result appended=cached;appended.known_target_cursor=appended.draft_cursor=appended.ledger.cursor=5;appended.ledger.prompt=5;root.finish_request(r,appended,true);yes(root.owners->prefix.processed_count()==5&&root.owners->prefix_new==1);
 r.prompt={3,4,5,6,8};auto old_cookie=root.binding.owner;yes(root.begin_request(r,stop,progress)&&root.target->prepared.processed==0&&root.rebuilt==1&&root.binding.owner!=old_cookie&&root.owners->fresh==2);
 // A separate healthy sequence with adoption refusal falls back to actual Fresh policy.
 Normal refused;refused.sequence_healthy=true;refused.owners->prefix.begin_fresh(refused.owners->key);refused.owners->prefix.processed({3,4,5},{0,0,0});refused.owners->prefix.publish(std::vector<float>(129280,0),3);refused.network->cursor=refused.owners->core->cursor=3;refused.owners->refuse=true;r.prompt={3,4,5,6};yes(refused.begin_request(r,stop,progress)&&refused.target->prepared.processed==0&&refused.owners->adopted==1&&refused.owners->fresh==1);
 Normal cancelled;stop.store(2);yes(!cancelled.begin_request(r,stop,progress)&&cancelled.owners->fresh==0&&!cancelled.sequence_healthy&&cancelled.owners->prefix.processed_count()==0);stop.store(0);
 Normal unknown;r.prompt={3,4,5};yes(unknown.begin_request(r,stop,progress));unknown.target->complete=false;auto ptr=unknown.target.get();no([&]{unknown.finish_request(r,result,true);});yes(unknown.restart_required&&unknown.target.get()==ptr&&unknown.owners->prefix.processed_count()==0);auto fresh=unknown.owners->fresh;no([&]{unknown.begin_request(r,stop,progress);});yes(unknown.owners->fresh==fresh&&unknown.target.get()==ptr);
 Normal zero;yes(zero.begin_request(r,stop,progress));auto zero_cookie=zero.binding.owner;yes(zero.begin_request(r,stop,progress)&&zero.rebuilt==1&&zero.binding.owner!=zero_cookie);
 Normal unadopt;unadopt.sequence_healthy=true;unadopt.network->cursor=unadopt.owners->core->cursor=3;unadopt.owners->prefix.begin_fresh(unadopt.owners->key);unadopt.owners->prefix.processed({3,4,5},{0,0,0});unadopt.owners->prefix.publish(std::vector<float>(129280,0),3);unadopt.owners->unknown_adoption=true;no([&]{unadopt.begin_request(r,stop,progress);});yes(unadopt.owners->fresh==0);
 Normal mismatch;mismatch.sequence_healthy=true;mismatch.network->cursor=2;mismatch.owners->core->cursor=3;mismatch.owners->prefix.begin_fresh(mismatch.owners->key);mismatch.owners->prefix.processed({3,4,5},{0,0,0});mismatch.owners->prefix.publish(std::vector<float>(129280,0),3);yes(mismatch.begin_request(r,stop,progress)&&mismatch.owners->fresh==1&&mismatch.target->prepared.processed==0);
 Normal metadata;yes(metadata.begin_request(r,stop,progress));metadata.owners->prefix.allocate(3);metadata.owners->prefix.begin_fresh(metadata.owners->key);metadata.owners->core->cursor=4;metadata.network->cursor=4;no([&]{metadata.finish_request(r,result,true);});yes(!metadata.sequence_healthy&&metadata.owners->invalidated==1&&metadata.owners->prefix.processed_count()==0);
 return n;
}
}
namespace normal_adapter_cpu {
using namespace strata_ext::deepseek41;using strata_ext::dspark::t38::PreparedPrefix;using strata_ext::dspark::t38::RequestBinding;using strata_ext::dspark::t38::DraftCancelled;using t38_normal_production_extract::need;
struct Identity{uint64_t epoch=1;std::string bundle_sha256="CPU",request_id="CPU-request",fixture_sha256="CPU-fixture",asset_sha256="CPU-asset";};
struct Network{uint64_t cursor=0;uint64_t processed_cursor()const{return cursor;}};
struct Output{bool cancelled=false;uint64_t rows=0,vocabulary=0,processed=0;std::vector<float>logits;};
struct Core{uint64_t cursor=0;unsigned calls=0;bool bad_metadata=false;std::vector<uint32_t>work;uint64_t position()const{return cursor;}int prepare_tap(uint64_t expected){need(cursor==expected,"CPU actual tap start");return 0;}template<class Impl,class Control>Output prefill_tapped(const std::vector<uint32_t>&suffix,uint64_t start,std::function<void()>,int,Impl&p,Control control){++calls;need(start==cursor,"CPU actual suffix start");work=suffix;Output o;o.rows=1;o.vocabulary=bad_metadata?2:129280;for(size_t n=0;n<suffix.size();++n){if(!control(n,suffix.size())){o.cancelled=true;return o;}++cursor;++p.known;++p.next;++p.network.cursor;++o.processed;}o.logits.resize(129280,0);return o;}};
void guards(RequestBinding binding,Identity identity,Core&core,Network&network,PreparedPrefix prepared,std::function<void()>invalidate_target){
#include "adapter-guards.inc"
}
struct Impl{Core&core;Network&network;uint64_t known=0,next=0;bool valid=true,armed=false,complete=true;std::vector<float>current_logits;Output prefill_result;std::function<bool()>control;std::function<bool(uint64_t,uint64_t)>prefill_control;Impl(Core&c,Network&n):core(c),network(n){}void arm(const std::vector<uint32_t>&,uint64_t pos){need(!armed&&known==pos,"CPU arm");next=pos;armed=true;}void disarm(){armed=false;}};
struct CoreTargetAdapter{std::unique_ptr<Impl>p_;unsigned invalidations=0;CoreTargetAdapter(Core&c,Network&n):p_(std::make_unique<Impl>(c,n)){}void prefill(const std::vector<uint32_t>&);void invalidate_and_drain()noexcept{++invalidations;}};
#include "adapter-prefill.inc"
unsigned tests(){unsigned n=0;auto yes=[&](bool ok){if(!ok)throw std::runtime_error("normal adapter actual-body CPU assertion");++n;};auto no=[&](auto fn){bool caught=false;try{fn();}catch(const std::exception&){caught=true;}yes(caught);};RequestBinding b{38,1,"CPU"};Identity id;
 for(unsigned failure=0;failure<10;++failure){Core c;Network net;PreparedPrefix p;auto rb=b;auto identity=id;std::function<void()>cleanup=[]{ };if(failure==0){guards(rb,identity,c,net,p,cleanup);yes(true);continue;}if(failure==1)rb.owner=0;if(failure==2)rb.epoch=2;if(failure==3)rb.bundle="different";if(failure==4)identity.request_id.clear();if(failure==5)identity.fixture_sha256.clear();if(failure==6)cleanup={};if(failure==7)c.cursor=1;if(failure==8)net.cursor=1;if(failure==9)p.logits.resize(1);no([&]{guards(rb,identity,c,net,p,cleanup);});}
 for(uint64_t start:{0ull,2ull,3ull}){Core c;c.cursor=start;Network net;net.cursor=start;CoreTargetAdapter target(c,net);target.p_->known=start;if(start==3)target.p_->current_logits.resize(129280,0);std::vector<std::pair<uint64_t,uint64_t>>progress;target.p_->prefill_control=[&](uint64_t done,uint64_t total){progress.emplace_back(done,total);return true;};target.prefill({3,4,5});yes(c.calls==(start==3?0:1)&&c.work.size()==3-start&&c.cursor==3&&target.p_->known==3);yes(!progress.empty()&&progress.front()==std::make_pair(start,uint64_t(3))&&target.invalidations==0);if(start==2)yes(c.work==std::vector<uint32_t>{5});}
 {Core c;c.cursor=3;Network net;net.cursor=3;CoreTargetAdapter target(c,net);target.p_->known=3;target.p_->current_logits.resize(129280,0);target.p_->control=[]{return false;};no([&]{target.prefill({3,4,5});});yes(c.calls==0&&target.invalidations==1&&!target.p_->valid);}
 {Core c;Network net;CoreTargetAdapter target(c,net);target.p_->prefill_control=[](uint64_t done,uint64_t){return done<1;};no([&]{target.prefill({3,4,5});});yes(c.cursor==1&&target.p_->known==1&&target.invalidations==1&&!target.p_->valid);}
 {Core c;c.bad_metadata=true;Network net;CoreTargetAdapter target(c,net);no([&]{target.prefill({3,4,5});});yes(target.invalidations==1&&!target.p_->valid);}
 return n;}
}
#include <mutex>
namespace normal_finish_cpu {
using namespace strata_ext;using namespace strata_ext::deepseek41;
struct Owners{PrefixState prefix;Owners(){prefix.allocate(3);PrefixMathKey key;key.epoch=1;key.context=3;prefix.begin_fresh(key);prefix.processed({3,4,5},{0,0,0});prefix.publish(std::vector<float>(129280,0),3);}};
void tail(Owners&owners,std::atomic<int>&stop,protocol::Finish&finish,std::string&origin,protocol::GenerationEmitter&emitter,std::vector<std::string>&frames,uint64_t generated,std::string&current,bool&busy,bool emit_failure){std::mutex control;auto emit=[&](const std::string&frame){if(emit_failure)throw std::runtime_error("CPU transport refusal");frames.push_back(frame);};
#include "worker-tail.inc"
}
struct AckActor {
 bool escape=false,mismatch=false;
 template<class Stop,class Emit>strata_ext::dspark::t38::ActorResult run(const std::vector<uint32_t>&,uint64_t,uint64_t,const SamplingOptions&,Stop,Emit emit){SampledToken token;token.id=6;token.logprob=-0.0f;emit(token);if(escape)throw std::bad_alloc{};strata_ext::dspark::t38::ActorResult result;result.ledger.emitted.assign(mismatch?0:1,6);result.ledger.finish=strata_ext::dspark::t38::Finish::Length;return result;}
};
void ack_tests(){using t38_normal_production_extract::actor_stop;using t38_normal_production_extract::actor_finish;using t38_normal_production_extract::need;unsigned passed=0;
 for(unsigned mode=0;mode<5;++mode){protocol::Context context{"CPU-ack",1,std::string(64,'a'),std::string(40,'b'),std::string(64,'c'),"deepseek41","gpt2","joyai-llm",129280};protocol::GenerationEmitter emitter(context,true);std::vector<std::string>frames;frames.reserve(8);frames.push_back(emitter.begin());uint64_t acked=0,generated=0;bool escaped=false;auto emit=[&](const std::string&frame){bool token=frame.find("\"kind\":\"token_batch\"")!=std::string::npos;if(token&&mode==2)throw std::runtime_error("CPU token transport did not acknowledge");frames.push_back(frame);if(token)++acked;};
  struct AckOwners:Owners{bool idle_drain(const std::string&){return true;}}owners;struct{bool restart_required=false;}root;auto*normal=&root;ProducerConfig c;c.dspark_width=5;struct{std::vector<uint32_t>prompt{3,4,5};uint64_t maximum=1;SamplingOptions sampling;std::string id="CPU-ack";}r;r.sampling.logprobs=mode==1;std::atomic<int>stop{0};protocol::Finish finish=protocol::Finish::Error;std::string origin="error";AckActor actor;actor.escape=mode<2;actor.mismatch=mode==4;auto identity=[](const ProducerConfig&,const std::string&id){return id;};
  try{
#include "ack-call.inc"
  }catch(const std::exception&x){escaped=true;
#include "worker-catch.inc"
  }
  bool busy=true;std::string current="CPU-ack";tail(owners,stop,finish,origin,emitter,frames,generated,current,busy,false);uint64_t expected=mode==2?0:1;bool good=acked==expected&&generated==expected&&frames.back()=="DONE "+std::to_string(expected)&&escaped==(mode!=3)&&finish==(mode==3?protocol::Finish::Length:protocol::Finish::Error);bool finish_count=false;for(const auto&f:frames)if(f.find("\"kind\":\"finish\"")!=std::string::npos)finish_count=f.find("\"generated_count\":"+std::to_string(expected))!=std::string::npos;if(mode!=2)good=good&&finish_count;
  std::cout<<"{\"ACK_case\":"<<mode<<",\"LP\":"<<(r.sampling.logprobs?"true":"false")<<",\"acked\":"<<acked<<",\"generated\":"<<generated<<",\"DONE\":\""<<frames.back()<<"\",\"finish_count_matches_ack\":"<<(finish_count?"true":"false")<<",\"escaped\":"<<(escaped?"true":"false")<<",\"passed\":"<<(good?"true":"false")<<"}\n";if(good)++passed;
 }
 if(passed!=5)throw std::runtime_error("NormalActor-ACK-R1 acknowledged count lost after Actor escape or return mismatch");std::cout<<"{\"ACK_cases\":5,\"passed\":true,\"Actor_stand_in\":true,\"actual_producer_callback_catch_tail\":true,\"native\":false,\"GPU\":false}";
}
unsigned tests(){unsigned n=0;auto yes=[&](bool ok){if(!ok)throw std::runtime_error("normal finish actual-body CPU assertion");++n;};for(unsigned mode=0;mode<4;++mode){protocol::Context context{"CPU-tail",1,std::string(64,'a'),std::string(40,'b'),std::string(64,'c'),"deepseek41","gpt2","joyai-llm",129280};protocol::GenerationEmitter emitter(context,true);(void)emitter.begin();(void)emitter.tokens({6});Owners owners;std::atomic<int>stop{mode==0?0:1};auto finish=mode==2?protocol::Finish::Error:protocol::Finish::Stop;std::string origin=mode==2?"error":"recipe";std::vector<std::string>frames;std::string current="CPU-tail";bool busy=true,caught=false;try{tail(owners,stop,finish,origin,emitter,frames,1,current,busy,mode==3);}catch(const std::exception&){caught=true;}
 if(mode==3){yes(caught&&frames.empty()&&owners.prefix.processed_count()==0);continue;}yes(!caught&&frames.size()==2&&frames[0].find("\"kind\":\"finish\"")!=std::string::npos&&frames[1]=="DONE 1"&&current.empty()&&!busy);yes(frames[0].find("\"generated_count\":1")!=std::string::npos);if(mode==1)yes(finish==protocol::Finish::Cancel&&origin=="user_cancel"&&owners.prefix.processed_count()==0);if(mode==2)yes(finish==protocol::Finish::Error&&origin=="error");bool duplicate=false;try{tail(owners,stop,finish,origin,emitter,frames,1,current,busy,false);}catch(const std::exception&){duplicate=true;}yes(duplicate&&frames.size()==2);
 }return n;}
}
#include "t38_normal_host_extract.hpp"
unsigned normal_host_transfer_tests(){using namespace t38_normal_host_extract;unsigned n=0;auto yes=[&](bool b){if(!b)throw std::runtime_error("normal host transfer CPU assertion");++n;};auto no=[&](auto fn){bool caught=false;try{fn();}catch(const std::exception&){caught=true;}yes(caught);};
 for(unsigned mode=0;mode<3;++mode){auto held=std::make_shared<DraftHostScratch>();held->ids.resize(6);held->pairs.resize(12);held->logits.resize(129280);auto before=held->logits.data();auto weak=std::weak_ptr<DraftHostScratch>(held);auto operation=[held,mode,&yes]{host_transfer(*held,[&]{yes(held->pending&&held->valid);held->ids[0]=16;held->pairs[0]=2;held->logits[0]=-0.0f;held->raw_confidence=-0.0f;held->attention_error=0;if(mode==1)throw std::runtime_error("CPU enqueue failed");if(mode==2)throw std::runtime_error("CPU sync failed");});};if(mode)no([&]{operation();});else operation();yes(held->logits.data()==before&&held->ids[0]==16);if(mode){yes(!held->valid&&held->pending);no([&]{host_transfer(*held,[]{});});}else yes(held->valid&&!held->pending);held.reset();yes(!weak.expired());}
 {auto host=std::make_unique<DraftHostScratch>();host->pending=true;unsigned drains=0;retain_unknown_host(host,[&]{++drains;});yes(host&&drains==1&&!host->pending);}
 {auto host=std::make_unique<DraftHostScratch>();host->pending=true;host->valid=false;host->logits.resize(129280);auto raw=host.get();auto ptr=raw->logits.data();retain_unknown_host(host,[]{throw std::runtime_error("CPU fence unknown");});yes(!host&&raw->pending&&!raw->valid&&raw->logits.data()==ptr);delete raw;/* mock has no pending real transfer; native roots never manually released */}
 {DraftHostScratch host;host.pending=true;no([&]{host_transfer(host,[]{});});yes(host.pending&&host.valid);}
 return n;
}
namespace normal_provider_cpu {
using namespace strata_ext::deepseek41;using strata_ext::dspark::t38::DraftHostScratch;using t38_normal_host_extract::need;
uint64_t mul(uint64_t a,uint64_t b){need(!b||a<=UINT64_MAX/b,"CPU provider dimension overflow");return a*b;}
void view(const DeviceView&v,int device,uint64_t rows,uint64_t columns,DeviceScalar type){need(v.device==device&&v.rows==rows&&v.columns==columns&&v.scalar==type,"CPU provider view");}
struct Storage{bool fail=false;unsigned uploads=0,allocations=0;const void*last_source=nullptr;DeviceView allocate(const std::string&,uint64_t rows,uint64_t columns,DeviceScalar type){++allocations;return {reinterpret_cast<void*>(0x1000),rows*columns*4,rows,columns,type,0,nullptr,0};}void upload(const DeviceView&,const void*data,uint64_t){++uploads;last_source=data;if(fail)throw std::runtime_error("CPU upload sync failed");}};
struct Impl{uint64_t credit=1024;std::vector<uint8_t>staging;bool staging_valid=true;DraftHostScratch host;Storage storage;DeviceView packed;std::map<std::string,DeviceView>workspace;};
struct DraftWeights{std::unique_ptr<Impl>p_=std::make_unique<Impl>();DraftHostScratch&host_scratch();void prepare_host(uint64_t);DeviceView workspace(const std::string&,uint64_t,uint64_t,DeviceScalar);void upload(const DeviceView&,const void*,uint64_t);};
#include "provider-methods.inc"
unsigned tests(){unsigned n=0;auto yes=[&](bool ok){if(!ok)throw std::runtime_error("normal provider actual-body CPU assertion");++n;};auto no=[&](auto fn){bool caught=false;try{fn();}catch(const std::exception&){caught=true;}yes(caught);};DraftWeights w;w.prepare_host(7);yes(w.p_->staging.size()==3584&&w.p_->host.ids.size()==21&&w.p_->host.pairs.size()==42&&w.p_->host.logits.size()==129280);auto dst=w.workspace("CPU",1,2,DeviceScalar::Float32);yes(w.p_->storage.allocations==1);uint8_t bytes[8]={1,2,3,4,5,6,7,8};w.upload(dst,bytes,8);yes(w.p_->storage.uploads==1&&w.p_->storage.last_source==w.p_->staging.data()&&w.p_->storage.last_source!=bytes&&w.p_->staging_valid);w.p_->storage.fail=true;auto ptr=w.p_->staging.data();no([&]{w.upload(dst,bytes,8);});yes(!w.p_->staging_valid&&w.p_->staging.data()==ptr);auto cap=w.p_->staging.capacity();no([&]{w.upload(dst,bytes,4096);});yes(w.p_->staging.capacity()==cap&&w.p_->storage.uploads==2);no([&]{w.workspace("CPU",1,2,DeviceScalar::Float32);});no([&]{w.host_scratch();});no([&]{w.prepare_host(8);});yes(w.p_->staging.data()==ptr&&w.p_->host.ids.size()==21);
 DraftWeights bad;bad.p_->host.valid=false;no([&]{bad.host_scratch();});no([&]{bad.workspace("CPU",1,2,DeviceScalar::Float32);});no([&]{bad.upload(dst,bytes,4096);});yes(bad.p_->staging.empty()&&bad.p_->storage.uploads==0&&bad.p_->storage.allocations==0);bad.p_->host.valid=true;bad.p_->host.pending=true;no([&]{bad.host_scratch();});return n;}
}
namespace normal_order_cpu {
using strata_ext::dspark::t38::Asset;using strata_ext::deepseek41::DeviceView;inline bool alive=false,fail=false;inline std::string order;
struct ScratchProbe: strata_ext::dspark::t38::DraftHostScratch {ScratchProbe(){alive=true;}~ScratchProbe(){order+='H';alive=false;}};using DraftHostScratch=ScratchProbe;
struct CoreStorage{~CoreStorage()noexcept{order+='S';if(!alive||fail)std::terminate();}};
struct Provider{
#include "provider-members.inc"
};
unsigned tests(){alive=false;fail=false;order.clear();{Provider root;root.host.logits.resize(4);root.staging.resize(16);}if(order!="SH"||alive)throw std::runtime_error("provider destructor order CPU assertion");return 1;}
[[noreturn]]void terminate_child(){std::set_terminate([]{std::_Exit(alive&&order=="S"?73:74);});alive=false;fail=true;order.clear();{Provider root;root.host.logits.resize(4);root.staging.resize(16);}std::_Exit(75);}
}
unsigned normal_producer_policy_tests(){using namespace t38_normal_production_extract;using namespace strata_ext::deepseek41;unsigned n=0;auto yes=[&](bool b){if(!b)throw std::runtime_error("normal producer CPU assertion");++n;};auto no=[&](auto fn){bool caught=false;try{fn();}catch(const std::exception&){caught=true;}yes(caught);};ProducerConfig c;yes(!dspark_enabled(c)&&c.dspark_width==5&&!c.dspark_draft_credit&&!c.dspark_target_credit);validate_dspark_config(c);yes(!parse_dspark_option(c,"--context","8")&&!dspark_enabled(c));
 yes(parse_dspark_option(c,"--dspark-draft","C:/CPU/draft.gguf"));yes(parse_dspark_option(c,"--dspark-prefix","C:/CPU/prefix.json"));yes(parse_dspark_option(c,"--dspark-width","7"));yes(dspark_enabled(c)&&c.dspark_width==7);validate_dspark_config(c);no([&]{parse_dspark_option(c,"--dspark-width","-1");});no([&]{parse_dspark_option(c,"--dspark-width","7x");});
 c.context=8;t38::Asset asset;asset.tensors={{"CPU-matrix",8,{5120,1},0,5440,5440},{"CPU-constant",0,{5120},0,20480,4}};c.tile_bytes=65536;auto credits=dspark_credits(c,asset,5440,21760);yes(credits.draft==65536&&credits.target==65536&&credits.host_deferred==9894720);parse_dspark_option(c,"--dspark-draft-credit","20480");parse_dspark_option(c,"--dspark-target-credit","21760");credits=dspark_credits(c,asset,5440,21760);yes(credits.draft==20480&&credits.target==21760&&credits.host_deferred==9850944);c.dspark_draft_credit=20479;no([&]{dspark_credits(c,asset,5440,21760);});c.dspark_draft_credit=20480;c.dspark_width=UINT64_MAX;no([&]{dspark_credits(c,asset,5440,21760);});c.dspark_width=0;no([&]{validate_dspark_config(c);});c.dspark_width=7;auto relative=c;relative.dspark_prefix="relative";no([&]{validate_dspark_config(relative);});ProducerConfig orphan;orphan.dspark_prefix="C:/CPU/prefix";no([&]{validate_dspark_config(orphan);});
 yes(actor_stop(0)==t38::ActorStop::Continue&&actor_stop(1)==t38::ActorStop::Cancel&&actor_stop(2)==t38::ActorStop::RecipeStop);yes(prepared_prefix_matches(3,3,true)&&!prepared_prefix_matches(3,4,true)&&!prepared_prefix_matches(3,3,false));yes(!retain_actor_owners(true,true,true,true));for(unsigned i=0;i<4;++i)yes(retain_actor_owners(i!=0,i!=1,i!=2,i!=3));
 struct Member{unsigned*destructed;~Member(){++*destructed;}};struct Root{bool restart_required=false;Member original,core,network,closure;Root(unsigned*d):original{d},core{d},network{d},closure{d}{}};
 {unsigned released=0;auto root=std::make_unique<Root>(&released);{NormalRootRetention<Root>guard{root};}yes(root!=nullptr&&released==0);root.reset();yes(released==4);}
 for(bool armed:{false,true}){unsigned released=0;auto root=std::make_unique<Root>(&released);auto raw=root.get();raw->restart_required=!armed;{NormalRootRetention<Root>guard{root,armed};}yes(!root&&released==0);no([&]{require_normal_reusable(true);});delete raw;yes(released==4);}
 using AF=t38::Finish;using PF=strata_ext::protocol::Finish;
 struct Mapping{AF input;int stop;std::string error;PF output;const char*origin;bool healthy;};
 const Mapping mappings[]={{AF::Length,0,"",PF::Length,"limit",true},{AF::Eos,0,"",PF::Stop,"eos",true},{AF::RecipeStop,0,"",PF::Stop,"recipe",false},{AF::RecipeStop,1,"",PF::Cancel,"user_cancel",false},{AF::Length,2,"",PF::Stop,"recipe",false},{AF::Cancel,0,"",PF::Cancel,"user_cancel",false},{AF::Cancel,2,"",PF::Stop,"recipe",false},{AF::Invalid,1,"broken",PF::Error,"error",false},{AF::Invalid,0,"nonfinite raw",PF::NonFinite,"nonfinite",false}};
 for(const auto&x:mappings){auto f=actor_finish(x.input,x.stop,x.error);yes(f.finish==x.output&&std::string(f.origin)==x.origin&&f.healthy==x.healthy);strata_ext::protocol::Context ctx{"CPU-normal",1,std::string(64,'a'),std::string(40,'b'),std::string(64,'c'),"deepseek41","gpt2","joyai-llm",129280};strata_ext::protocol::GenerationEmitter e(ctx,true);yes(e.begin().find("\"kind\":\"begin\"")!=std::string::npos);yes(e.tokens({6},{{-0.0f,{{6,-0.0f}}}}).find("\"ids\":[6]")!=std::string::npos);auto frame=e.finish(f.finish,f.origin);yes(frame.find("\"generated_count\":1")!=std::string::npos&&frame.find(std::string("\"stop_origin\":\"")+x.origin+'"')!=std::string::npos);no([&]{e.finish(f.finish,f.origin);});}
 n+=normal_owner_cpu::tests();n+=normal_adapter_cpu::tests();n+=normal_finish_cpu::tests();n+=normal_host_transfer_tests();n+=normal_provider_cpu::tests();n+=normal_order_cpu::tests();return n;
}
#endif
#ifdef T38_NORMAL_ACTOR_CPU
#include "../../../models/deepseek41/prefix_state.hpp"
#include "../../../native/protocol/generation.hpp"
namespace normal_actor_cpu {
using namespace strata_ext::dspark::t38;using namespace strata_ext::deepseek41;
struct Shared {uint64_t cursor=0;std::vector<uint32_t>processed;unsigned prefill_calls=0,steps=0,proposals=0,invalidations=0;bool fail_emit=false,fail_step=false,complete=true;std::vector<SampledToken>acks;ContinueWork control;};
struct Target final:ActorTarget {Shared&s;std::vector<float>head{0,0,0,0,0,0,10,0};explicit Target(Shared&x):s(x){}void prefill(const std::vector<uint32_t>&p)override{++s.prefill_calls;for(size_t n=size_t(s.cursor);n<p.size();++n){if(s.control&&!s.control())throw DraftCancelled{};s.processed.push_back(p[n]);++s.cursor;}}const std::vector<float>&logits()const override{return head;}uint64_t known_cursor()const noexcept override{return s.cursor;}void set_control(ContinueWork c)override{s.control=std::move(c);}void drain()override{}bool completion_known()const noexcept override{return s.complete;}void invalidate_and_drain()noexcept override{++s.invalidations;}
 StepProof step(uint32_t id,uint64_t pos)override{++s.steps;if(s.fail_step)throw std::runtime_error("CPU step fault");if(pos!=s.cursor)throw std::invalid_argument("CPU step position");s.processed.push_back(id);++s.cursor;StepProof p{{38,1,"CPU"},pos,pos+1,{}};for(unsigned n=0;n<3;++n)p.taps[n]={38,1,pos,37+n,4,5120};return p;}};
struct Draft final:ActorDraft {Shared&s;explicit Draft(Shared&x):s(x){}uint64_t cursor()const override{return s.cursor;}void drain()override{}void invalidate_and_drain()noexcept override{++s.invalidations;}bool completion_known()const noexcept override{return s.complete;}DraftProposal propose(uint64_t width,const SamplingOptions&,const std::vector<uint32_t>&history,NamespaceRng&r,const ContinueWork&work)override{++s.proposals;if(work&&!work())throw DraftCancelled{};if(history.size()!=s.cursor)throw std::invalid_argument("CPU new request full history");DraftProposal p;p.ids={6};p.q={{0,0,0,0,0,0,1,0}};p.raw_confidence={1};if(!width)throw std::invalid_argument("CPU width");(void)r.uniform(RngSpace::Proposal);return p;}};
void run(){unsigned count=0;auto yes=[&](bool x){if(!x)throw std::runtime_error("normal Actor CPU assertion");++count;};SamplingOptions greedy;greedy.temperature=0;greedy.logprobs=true;greedy.top_logprobs=2;RequestBinding binding{38,1,"CPU"};
 // Real RequestActor starts from prepared common cursor, uses whole request history and only unprocessed suffix.
 for(uint64_t start:{0ull,2ull,3ull}){Shared s;s.cursor=start;Target t(s);Draft d(s);PreparedPrefix p;p.processed=start;if(start==3)p.logits=t.head;RequestActor a(t,d,binding,0);auto r=a.run({3,4,5},1,5,greedy,[]{return ActorStop::Continue;},[&](const SampledToken&token){yes(s.steps==0&&s.cursor==3);s.acks.push_back(token);});yes(s.prefill_calls==1&&s.processed.size()==3-start&&s.steps==0);yes(r.ledger.prompt==3&&r.ledger.processed_generated==0&&r.ledger.cursor==3&&r.ledger.pending==6&&r.ledger.emitted==std::vector<uint32_t>{6});yes(r.context_valid&&r.completion_known&&r.ledger.finish==Finish::Length);auto expected=describe_distribution(effective_distribution(t.head,{3,4,5},greedy),6);yes(s.acks[0].id==expected.id&&s.acks[0].logprob==expected.logprob&&s.acks[0].alternatives==expected.alternatives);}
 // Each finite stop/fault uses actual RequestActor ordering, not a replacement state machine.
 for(unsigned mode=0;mode<8;++mode){Shared s;Target t(s);Draft d(s);bool emitted=false;unsigned after_stop=0;RequestActor a(t,d,binding,0);auto stop=[&]{if(mode==0)return ActorStop::RecipeStop;if(mode==1&&emitted)return ActorStop::RecipeStop;if(mode==2&&emitted)return ++after_stop==1?ActorStop::RecipeStop:ActorStop::Cancel;if(mode==3&&emitted)return ActorStop::Cancel;if(mode==4&&emitted)throw std::runtime_error("CPU stop after emit");return ActorStop::Continue;};if(mode==6)s.fail_step=true;if(mode==7)s.complete=false;auto r=a.run({3,4,5},2,5,greedy,stop,[&](const SampledToken&token){if(mode==5)throw std::runtime_error("CPU emit did not ack");s.acks.push_back(token);emitted=true;});
  if(mode==0)yes(r.ledger.finish==Finish::RecipeStop&&r.ledger.emitted.empty()&&s.prefill_calls==0);
  if(mode==1)yes(r.ledger.finish==Finish::RecipeStop&&r.ledger.emitted.size()==1&&r.ledger.pending==6&&s.steps==0);
  if(mode==2||mode==3)yes(r.ledger.finish==Finish::Cancel&&r.ledger.emitted.size()==1&&s.steps==0);
  if(mode==4)yes(r.ledger.finish==Finish::Invalid&&r.ledger.emitted.size()==1&&r.ledger.pending==6&&s.steps==0);
  if(mode==5)yes(r.ledger.finish==Finish::Invalid&&r.ledger.emitted.empty()&&!r.ledger.pending&&s.steps==0);
  if(mode==6)yes(r.ledger.finish==Finish::Invalid&&r.ledger.emitted.size()==1&&r.ledger.processed.empty()&&r.ledger.pending==6);
  if(mode==7)yes(!r.completion_known);
 }
 {Shared s;s.cursor=4;Target t(s);Draft d(s);RequestActor a(t,d,binding,0);auto r=a.run({3,4,5},1,5,greedy,[]{return ActorStop::Continue;},[](const SampledToken&){});yes(r.ledger.finish==Finish::Invalid&&s.prefill_calls==0);}

 {Shared s;Target t(s);t.head.assign(8,0);t.head[1]=10;Draft d(s);RequestActor a(t,d,binding,0);auto r=a.run({3,4,5},2,5,greedy,[]{return ActorStop::Continue;},[](const SampledToken&){});yes(r.ledger.finish==Finish::Eos&&r.ledger.emitted==std::vector<uint32_t>{1}&&r.ledger.pending==1&&s.steps==0);}
 {PrefixMathKey key;key.asset="CPU-asset";key.bundle="CPU-bundle";key.mode="single";key.primary="0000:07:00.0";key.epoch=1;key.context=8;PrefixState prefix;prefix.allocate(8);std::vector<float>head(129280,0);auto decision=[&](std::vector<uint32_t>prompt,uint64_t cursor){return prefix.decide(key,prompt,std::vector<uint8_t>(prompt.size(),0),cursor,true);};yes(decision({3,4,5},0).action==PrefixAction::Fresh);prefix.begin_fresh(key);prefix.processed({3,4,5},{0,0,0});prefix.publish(head,3);auto append=decision({3,4,5,6},3);yes(append.action==PrefixAction::Append&&append.reused==3);prefix.begin_append();prefix.processed(6);prefix.publish(head,4);yes(decision({3,4,5,6},4).action==PrefixAction::Logits);yes(decision({3,4,5,7},4).action==PrefixAction::Fresh);yes(decision({3,4},4).action==PrefixAction::Fresh);
  // Terminal pending is not committed by the previous request; it occurs once in the next prompt suffix.
  auto next=decision({3,4,5,6,6},4);yes(next.action==PrefixAction::Append&&next.reused==4);prefix.begin_append();prefix.processed(6);prefix.publish(head,5);yes(prefix.processed_count()==5&&decision({3,4,5,6,6},5).action==PrefixAction::Logits);
  prefix.begin_append();yes(decision({3,4,5,6,6,7},5).action==PrefixAction::Fresh);prefix.publish(head,5);bool fault=false;try{prefix.publish(head,6);}catch(const std::exception&){fault=true;}yes(fault&&decision({3,4,5,6,6},5).action==PrefixAction::Fresh);prefix.invalidate();yes(prefix.processed_count()==0&&decision({3,4,5},0).action==PrefixAction::Fresh);
 }
 {RequestSampler sampler(0);std::mt19937_64 bits(0);SamplingOptions o;o.temperature=0;o.logprobs=true;o.top_logprobs=2;std::vector<float>head{0,2,1};for(unsigned n=0;n<3;++n){auto expected=sample_logits(head,{0},o,double(bits()>>11)*0x1.0p-53);auto actual=sampler.sample(head,{0},o);yes(actual.id==expected.id&&actual.logprob==expected.logprob&&actual.alternatives==expected.alternatives);}yes(sampler.next_uniform()==double(bits()>>11)*0x1.0p-53);}
 yes(std::string(finish_name(Finish::RecipeStop))=="recipe_stop");
#ifdef T38_NORMAL_PRODUCER_EXTRACT
 count+=normal_producer_policy_tests();
#endif
 std::cout<<"{\"assertions\":"<<count<<",\"actual_RequestActor\":true,\"adapter_spies\":true,\"native\":false,\"GPU\":false}";
}
}
#endif
int main(int argc,char**argv){try{if(argc<2)throw std::invalid_argument("fixture command");std::cout<<std::setprecision(17);std::string command=argv[1];
 if(command=="decision"&&argc==7){auto d=verify(probabilities(argv[2]),probabilities(argv[3]),uint32_t(std::stoul(argv[4])),std::stod(argv[5]),std::stod(argv[6]));std::cout<<"{\"accepted\":"<<(d.accepted?"true":"false")<<",\"id\":"<<d.id<<",\"acceptance\":"<<d.acceptance<<'}';}
 else if(command=="run"&&argc==5){Session s({7,9,"fixture"},4,std::stoull(argv[2]));Fake f;int stop=std::stoi(argv[4]);if(stop==0)s.cancel_before_emit();for(auto id:ids(argv[3])){if(s.ledger().finish!=Finish::Running)break;s.emit(id,int(s.ledger().emitted.size()+1)==stop);if(s.ledger().finish==Finish::Running)s.advance_pending(f);}auto l=s.ledger();std::cout<<"{\"emitted\":";list(l.emitted);std::cout<<",\"processed\":";list(l.processed);std::cout<<",\"cursor\":"<<l.cursor<<",\"pending\":";list(l.pending?std::vector<uint32_t>{*l.pending}:std::vector<uint32_t>{});std::cout<<",\"finish\":\""<<finish_name(l.finish)<<"\"}";}
 else if(command=="rng"&&argc==4){NamespaceRng rng(std::stoull(argv[2]));auto n=std::stoul(argv[3]);check(n<=1000);std::cout<<'[';for(unsigned s=0;s<5;++s){if(s)std::cout<<',';std::cout<<'[';for(unsigned i=0;i<n;++i){if(i)std::cout<<',';std::cout<<rng.draw53(RngSpace(s));}std::cout<<']';}std::cout<<']';}
#ifdef T38_NORMAL_ACTOR_CPU
 else if(command=="normal-actor-selftest"&&argc==2)normal_actor_cpu::run();
#ifdef T38_NORMAL_PRODUCER_EXTRACT
 else if(command=="normal-host-terminate"&&argc==2)normal_order_cpu::terminate_child();
 else if(command=="normal-ack-selftest"&&argc==2)normal_finish_cpu::ack_tests();
#endif
#endif
 else if(command=="selftest"&&argc==2)selftest();
#ifdef T38_SHARED_SAMPLING
 else if(command=="sampler-selftest"&&argc==2)sampler_test();
#endif
 else if(command=="asset"&&argc==4){auto a=inspect_prefix(prefix(argv[2]),std::stoull(argv[3]));std::array<unsigned,40> types{};for(auto&t:a.tensors)++types[t.type];std::cout<<"{\"tensors\":"<<a.tensors.size()<<",\"data_start\":"<<a.data_start<<",\"file_bytes\":"<<a.file_bytes<<",\"types\":{\"0\":"<<types[0]<<",\"1\":"<<types[1]<<",\"8\":"<<types[8]<<",\"39\":"<<types[39]<<"}}";}
 else if(command=="span"&&argc==10){auto a=inspect_prefix(prefix(argv[2]),artifact_bytes);auto s=required_span(a,argv[4],std::stoull(argv[5]),std::stoull(argv[6]),std::stoull(argv[7]));auto b=read_span(argv[3],s,std::stoull(argv[8]));std::cout<<"{\"bytes\":"<<b.size()<<'}';}
 else if(command=="span"&&argc==9){auto a=inspect_prefix(prefix(argv[2]),artifact_bytes);auto s=required_span(a,argv[4],std::stoull(argv[5]),std::stoull(argv[6]),std::stoull(argv[7]));auto b=read_span(argv[3],s,std::stoull(argv[8]));std::cout<<"{\"bytes\":"<<b.size()<<'}';}
 else throw std::invalid_argument("unknown fixture arguments");std::cout<<'\n';return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 2;}}


#endif // T38_ACTUAL_BODY_ONLY


