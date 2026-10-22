#include "../../models/deepseek41/prefix_state.hpp"
#include <iostream>
#include <functional>
using namespace strata_ext::deepseek41;
int prefix_policy_main(int argc,char**argv){
 try{
  if(argc!=2||std::string(argv[1])!="--policy")throw std::invalid_argument("fixture --policy required");
  uint64_t checks=0;auto require=[&](bool b){++checks;if(!b)throw std::runtime_error("prefix policy assertion "+std::to_string(checks));};
  PrefixMathKey key;key.asset="asset";key.bundle="bundle";key.mode="single";key.primary="pci";key.epoch=1;key.context=4096;
  std::vector<uint32_t>p{0,12},incoming{0,12,34};std::vector<uint8_t>m{0,0},im{0,0,0};
  auto decide=[&](const PrefixMathKey&k,bool healthy=true,bool logits=true,bool full=false,bool reset=false,uint64_t position=2){return prefix_decision(key,k,p,m,incoming,im,position,healthy,logits,full,reset);};
  auto result=decide(key);require(result.action==PrefixAction::Append&&result.reused==2);
  incoming.pop_back();im.pop_back();result=decide(key);require(result.action==PrefixAction::Logits&&result.reused==2);
  incoming.push_back(34);im.push_back(0);
  require(decide(key,false).action==PrefixAction::Fresh);require(decide(key,true,false).action==PrefixAction::Fresh);
  require(decide(key,true,true,true).action==PrefixAction::Fresh);require(decide(key,true,true,false,true).action==PrefixAction::Fresh);
  require(decide(key,true,true,false,false,3).action==PrefixAction::Fresh);
  incoming[1]=13;require(decide(key).action==PrefixAction::Fresh);incoming[1]=12;
  im[1]=1;require(decide(key).action==PrefixAction::Fresh);im[1]=0;
  incoming={0};im={0};require(decide(key).action==PrefixAction::Fresh);incoming={0,12,34};im={0,0,0};
  auto changed=[&](const std::function<void(PrefixMathKey&)>&change){auto k=key;change(k);require(decide(k).action==PrefixAction::Fresh);};
  changed([](auto&k){k.asset="other";});changed([](auto&k){k.bundle="other";});changed([](auto&k){k.epoch=2;});
  changed([](auto&k){k.context=8192;});changed([](auto&k){k.mode="layer-split";});changed([](auto&k){k.primary="other";});
  changed([](auto&k){k.secondary="other";});changed([](auto&k){k.assignment={37};});changed([](auto&k){k.cut=24;});changed([](auto&k){k.math="fast";});
  auto bad=[&](const std::function<void()>&f){bool rejected=false;try{f();}catch(const std::invalid_argument&){rejected=true;}require(rejected);};
  incoming[0]=129280;bad([&]{decide(key);});incoming[0]=0;
  im[0]=2;bad([&]{decide(key);});im[0]=0;
  m.pop_back();bad([&]{decide(key);});m.push_back(0);
  im.pop_back();bad([&]{decide(key);});im.push_back(0);
  auto k=key;k.context=0;bad([&]{decide(k);});k=key;k.epoch=0;bad([&]{decide(k);});
  k=key;k.context=2;bad([&]{decide(k);});
  p.clear();m.clear();require(decide(key,true,true,false,false,0).action==PrefixAction::Fresh);
  const uint64_t cursors[]{127,128,129},last_positions[]{126,127,128};
  for(size_t i=0;i<3;++i)require(cursors[i]-1==last_positions[i]);
  std::cout<<"{\"assertions\":"<<checks<<",\"GPU_executed\":false,\"scope\":\"production prefix_decision policy only\"}\n";
  return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}
}

#ifndef STRATA_T36_NATIVE
int main(int argc,char**argv){return prefix_policy_main(argc,argv);}
#else
#define main historical_t20_main
#include "../core/core_fixture.cpp"
#undef main
#include <chrono>
#ifdef STRATA_DEEPSEEK_T36_FIXTURE_CAPTURE
#include "../../models/deepseek41/execution/layer_split.hpp"
#endif
namespace {
#ifdef STRATA_DEEPSEEK_T36_FIXTURE_CAPTURE
// Fixture-only synchronous stream sink. No state pointer survives callback.
// Caller creates a new checkpoint directory before this function; no overwrite.
template<class State>uint64_t capture_checkpoint(State&sequence,const fs::path&directory){try{
 must(!fs::exists(directory),"capture checkpoint output already exists");must(fs::create_directory(directory),"capture checkpoint create");
 std::ofstream manifest(directory/"state.tsv");must(bool(manifest),"capture manifest open");std::array<unsigned char,65536>chunk{};uint64_t downloaded=0;size_t index=0;
 sequence.fixture_visit_state([&](const FixtureStateRecord&r,void*stream){
  const auto filename=std::to_string(index++)+"-"+r.kind+"-"+std::to_string(r.writer)+".bin";auto bytes=r.host?r.host_bytes:r.value.bytes;
  must(!(r.host&&r.value.data),"capture host/device alias");std::ofstream out(directory/filename,std::ios::binary);must(bool(out),"capture output open");
  if(r.value.data){must(r.value.bytes==r.value.rows*r.value.columns*scalar_bytes(r.value.scalar),"capture clipped descriptor extent");for(uint64_t at=0;at<bytes;){auto n=std::min<uint64_t>(chunk.size(),bytes-at);hip_ok(hipMemcpyAsync(chunk.data(),static_cast<const char*>(r.value.data)+at,size_t(n),hipMemcpyDeviceToHost,reinterpret_cast<hipStream_t>(stream)));hip_ok(hipStreamSynchronize(reinterpret_cast<hipStream_t>(stream)));if(r.value.scalar==DeviceScalar::Float32||r.value.scalar==DeviceScalar::Bfloat16InFloat32){must(n%4==0,"capture scalar chunk");for(size_t j=0;j<n;j+=4){float x;std::memcpy(&x,chunk.data()+j,4);must(std::isfinite(x),"capture nonfinite retained FP32");}}out.write(reinterpret_cast<const char*>(chunk.data()),std::streamsize(n));must(bool(out),"capture short write");at+=n;downloaded+=n;}}
  else if(r.host){must(bytes%8==0,"capture typed host extent");for(uint64_t at=0;at<bytes;at+=8){uint64_t value;std::memcpy(&value,static_cast<const char*>(r.host)+at,8);unsigned char le[8];for(unsigned j=0;j<8;++j)le[j]=static_cast<unsigned char>(value>>(j*8));out.write(reinterpret_cast<const char*>(le),8);}}
  out.flush();must(bool(out),"capture output flush");manifest<<filename<<'\t'<<r.kind<<'\t'<<r.writer<<'\t'<<r.ratio<<'\t'<<r.position<<'\t'<<r.epoch<<'\t'<<r.rows<<'\t'<<r.valid<<'\t'<<r.value.rows<<'\t'<<r.value.columns<<'\t'<<int(r.value.scalar)<<'\t'<<bytes<<'\t'<<r.first<<'\t'<<r.end<<'\n';
  if(r.identity){std::ofstream identity(directory/"identity.tsv");identity<<r.identity->request_id<<'\t'<<r.identity->epoch<<'\t'<<int(r.identity->phase)<<'\t'<<r.identity->fixture_sha256<<'\t'<<r.identity->asset_sha256<<'\t'<<r.identity->bundle_sha256<<'\n';identity.flush();must(bool(identity),"capture identity flush");}
  manifest.flush();must(bool(manifest),"capture manifest flush");
 });return downloaded;
 }catch(...){sequence.invalidate_and_drain();throw;}
}
#endif
#ifdef STRATA_DEEPSEEK_T36_FIXTURE_CAPTURE
struct PairView {LayerSplit&pair;bool primary;void fixture_visit_state(const FixtureStateVisitor&v){T36PairFixture::visit(pair,primary,v);}void invalidate_and_drain(){pair.cancel_and_drain();}};
struct PairAudit final:LayerSplitAudit {
 LayerSplit*pair=nullptr;fs::path directory;PartitionBoundary old;std::shared_ptr<const uint8_t>old_output;uint64_t bytes=0,refusals=0,opaque_probes=0,head_probes=0;std::ofstream trace;
 explicit PairAudit(const fs::path&p):directory(p),trace(p/"pair-events.tsv"){}
 void event(uint64_t position,const char*name)override{trace<<position<<'\t'<<name<<'\n';trace.flush();must(bool(trace),"pair event flush");if(position==1&&std::string(name)=="secondary-complete"){T36PairFixture::probe_old_output(*pair,old_output);++head_probes;}}
 void transfer(const PartitionBoundary&b,uint64_t ordinal,const strata_ext::device::TransferStats&s)override{trace<<b.position<<"\tcopy-done\t"<<ordinal<<'\t'<<s.bytes<<'\t'<<s.path<<'\t'<<s.cancelled<<'\n';trace.flush();must(bool(trace),"pair copy trace");}
 void boundary(const PartitionBoundary&source,const PartitionBoundary&target)override{
  must(pair&&source.next_layer==39&&source.shared.size()==3&&target.shared.size()==3,"pair actual cut39 imports");
  if(source.position==0){old=source;auto proposed=source.identity;proposed.request_id="T36-borrowed-refused";bool refused=false;try{pair->continue_request(proposed,0);}catch(const RequestAdoptionRefused&){refused=true;}must(refused&&pair->request_valid(),"borrowed pair must refuse without abort");++refusals;}
  else{must(source.position==1&&source.generation==2,"numeric generation tied to cursor");T36PairFixture::probe_old_descriptor(*pair,old,source);opaque_probes+=3;}
  std::ofstream manifest(directory/("boundary-"+std::to_string(source.position)+".tsv"));std::array<unsigned char,32768>a{},b{};int previous=-1;hip_ok(hipGetDevice(&previous));
  auto compare=[&](const std::string&name,const DeviceView&s,const DeviceView&t){auto n=s.rows*s.columns*scalar_bytes(s.scalar);must(n<=s.bytes&&n<=t.bytes&&n==t.rows*t.columns*scalar_bytes(t.scalar)&&s.scalar==t.scalar,"borrowed mirror typed extent");auto prefix=std::to_string(source.position)+"-"+name;std::ofstream left(directory/(prefix+"-source.bin"),std::ios::binary),right(directory/(prefix+"-target.bin"),std::ios::binary);must(bool(left)&&bool(right),"pair mirror output");for(uint64_t at=0;at<n;){auto count=std::min<uint64_t>(a.size(),n-at);hip_ok(hipSetDevice(s.device));hip_ok(hipMemcpyAsync(a.data(),static_cast<const char*>(s.data)+at,size_t(count),hipMemcpyDeviceToHost,reinterpret_cast<hipStream_t>(source.stream)));hip_ok(hipStreamSynchronize(reinterpret_cast<hipStream_t>(source.stream)));hip_ok(hipSetDevice(t.device));hip_ok(hipMemcpyAsync(b.data(),static_cast<const char*>(t.data)+at,size_t(count),hipMemcpyDeviceToHost,reinterpret_cast<hipStream_t>(target.stream)));hip_ok(hipStreamSynchronize(reinterpret_cast<hipStream_t>(target.stream)));must(std::memcmp(a.data(),b.data(),size_t(count))==0,"actual borrowed source/target mismatch");if(s.scalar==DeviceScalar::Float32||s.scalar==DeviceScalar::Bfloat16InFloat32){for(size_t j=0;j<count;j+=4){float x;std::memcpy(&x,a.data()+j,4);must(std::isfinite(x),"pair borrowed nonfinite");}}left.write(reinterpret_cast<const char*>(a.data()),std::streamsize(count));right.write(reinterpret_cast<const char*>(b.data()),std::streamsize(count));must(bool(left)&&bool(right),"pair mirror short write");at+=count;bytes+=count*2;}left.flush();right.flush();must(bool(left)&&bool(right),"pair mirror flush");manifest<<name<<'\t'<<s.rows<<'\t'<<s.columns<<'\t'<<int(s.scalar)<<'\t'<<n<<'\n';};
  try{compare("residual",source.residual,target.residual);compare("pre",source.pre,target.pre);for(size_t i=0;i<3;++i){const auto&s=source.shared[i];const auto&t=target.shared[i];must(s.kind==t.kind&&s.writer==t.writer&&s.compressor==20&&s.ratio==1&&s.epoch==source.identity.epoch&&s.published_rows==source.position+1&&s.position==source.position&&s.valid&&t.valid,"pair actual shared metadata");compare(std::to_string(int(s.kind))+"-"+std::to_string(s.writer),s.value,t.value);}hip_ok(hipSetDevice(previous));}catch(...){hipSetDevice(previous);throw;}manifest.flush();must(bool(manifest),"pair mirror manifest flush");
 }
};
int prefix_paired_reference(const fs::path&input,const fs::path&output,const std::string&pci){
 using namespace strata_ext;must(!fs::exists(output),"paired reference create-only output");int count=0,dev=-1;hip_ok(hipGetDeviceCount(&count));for(int i=0;i<count;++i){char actual[64]{};hip_ok(hipDeviceGetPCIBusId(actual,sizeof(actual),i));if(pci==actual)dev=i;}must(dev>=0,"paired reference PCI");hip_ok(hipSetDevice(dev));must(fs::create_directory(output),"paired reference create");auto a=load_artifact(input);std::ifstream pf(input/"prefixes.tsv");std::string first;must(bool(std::getline(pf,first)),"paired reference metadata");auto e=engram::inspect_metadata(fs::u8path(fields(first).at(1)));auto src=a.source_tensor("per_layer_token_embd.weight").source;auto w=std::make_unique<cache::PrimarySupply>(cache::SupplyConfig{2,2,2097152,4,4,dev,true});auto r=std::make_unique<cache::RowSupply>(cache::RowConfig{24,24,1,1,dev},a,cache::RowSourceViews({{src,{src.original_path,0,src.original_size}}}));auto id=fixture_identity();id.request_id="T36-pair-reference";CoreConfig cfg;cfg.device=dev;auto core=std::make_unique<CoreSequence>(a,e,*w,*r,id,cfg,3);
 for(uint64_t pos=0;pos<2;++pos){auto raw=core->step(pos?37:3,pos);must(raw.size()==129280,"pair reference raw row");for(float value:raw)must(std::isfinite(value),"pair reference raw finite");write_file(output/(std::string("fresh")+std::to_string(pos+1)+"-logits.bin"),raw);core->quiesce();capture_checkpoint(*core,output/(std::string("state-")+std::to_string(pos+1)));}core->quiesce();core.reset();must(w->try_close()&&r->try_close(),"paired reference actual close");std::ofstream done(output/"reference-terminal.tsv");done<<"processed\t2\nsource\t"<<T20_SOURCE_ID<<'\n';done.flush();must(bool(done),"paired reference terminal flush");return 0;
}
int prefix_paired_fixture(const fs::path&input,const fs::path&output,const std::string&primary,const std::string&secondary,const fs::path&reference){
 using namespace strata_ext;must(fs::is_regular_file(reference/"reference-seal.json"),"paired reference hash seal required");must(!fs::exists(output),"pair create-only output");auto roles=device::resolve(device::inventory(),primary,secondary);must(fs::create_directory(output),"pair output create");
 auto artifact=load_artifact(input);std::ifstream pf(input/"prefixes.tsv");std::string first;must(bool(std::getline(pf,first)),"pair actual Engram metadata");auto e=engram::inspect_metadata(fs::u8path(fields(first).at(1)));auto src=artifact.source_tensor("per_layer_token_embd.weight").source;
 hip_ok(hipSetDevice(roles.primary.ordinal));auto p=std::make_unique<cache::PrimarySupply>(cache::SupplyConfig{2,2,2097152,4,4,roles.primary.ordinal,true});auto rows=std::make_unique<cache::RowSupply>(cache::RowConfig{24,24,1,1,roles.primary.ordinal},artifact,cache::RowSourceViews({{src,{src.original_path,0,src.original_size}}}));hip_ok(hipSetDevice(roles.secondary->ordinal));auto s=std::make_unique<cache::PrimarySupply>(cache::SupplyConfig{2,2,2097152,4,4,roles.secondary->ordinal,true});
 auto id=fixture_identity();id.request_id="T36-pair-old";LayerSplitConfig cfg;cfg.roles=roles;cfg.cut=39;cfg.transfer_bytes=65536;cfg.copy_policy=device::Policy::HostBounce;cfg.primary.device=roles.primary.ordinal;cfg.secondary.device=roles.secondary->ordinal;PairAudit audit(output);cfg.audit=&audit;auto pair=std::make_unique<LayerSplit>(artifact,e,*p,rows.get(),*s,nullptr,id,cfg,3);audit.pair=pair.get();
 auto initial=pair->prefill({3},0);must(!initial.cancelled&&initial.processed==1&&initial.logits.size()==129280&&pair->position()==1,"pair actual one input");write_file(output/"pair1-logits.bin",initial.logits);pair->quiesce();auto stamp=T36PairFixture::stamp(*pair);audit.old_output=stamp.secondary_instance;
 auto save=[&](const char*name){must(fs::create_directory(output/name),"pair checkpoint create");PairView pv{*pair,true},sv{*pair,false};capture_checkpoint(pv,output/name/"P");capture_checkpoint(sv,output/name/"S");};save("before-adopt-1");
 auto next=id;next.request_id="T36-pair-new";T36PairFixture::fail_next_prepare_after_primary();bool refused=false;try{pair->continue_request(next,1);}catch(const std::bad_alloc&){refused=true;}auto unchanged=T36PairFixture::stamp(*pair);auto identity_equal=[](const measurement::Identity&a,const measurement::Identity&b){return a.request_id==b.request_id&&a.epoch==b.epoch&&a.phase==b.phase&&a.fixture_sha256==b.fixture_sha256&&a.asset_sha256==b.asset_sha256&&a.bundle_sha256==b.bundle_sha256;};must(refused&&unchanged.valid&&unchanged.cursor==1&&unchanged.primary_cursor==1&&unchanged.secondary_cursor==1&&unchanged.primary_instance==stamp.primary_instance&&unchanged.secondary_instance==stamp.secondary_instance&&identity_equal(unchanged.root,stamp.root)&&identity_equal(unchanged.primary,stamp.primary)&&identity_equal(unchanged.secondary,stamp.secondary),"post-P preparation allocation failure changed healthy pair");
 pair->continue_request(next,1);auto adopted=T36PairFixture::stamp(*pair);must(adopted.valid&&adopted.cursor==1&&adopted.primary_instance!=stamp.primary_instance&&adopted.secondary_instance!=stamp.secondary_instance&&identity_equal(adopted.root,next)&&identity_equal(adopted.primary,next)&&identity_equal(adopted.secondary,next),"root/P/S adoption publication");save("after-adopt-1");auto raw=pair->step(37,1);must(raw.size()==129280&&pair->position()==2,"pair actual next input");write_file(output/"pair2-logits.bin",raw);pair->quiesce();save("after-step-2");auto before=pair->stats();auto cancelled=pair->prefill({1024},2,{},[](uint64_t,uint64_t){return false;});auto after=pair->stats();must(cancelled.cancelled&&!cancelled.processed&&!cancelled.rows&&cancelled.logits.empty()&&!pair->request_valid()&&after.boundary_payload==before.boundary_payload&&after.requested_logits_d2h==before.requested_logits_d2h,"pair before-issue STOP invalidation");refused=false;try{pair->continue_request(id,2);}catch(const RequestAdoptionRefused&){refused=true;}must(refused,"stopped pair rejects adoption");must(audit.refusals==1&&audit.opaque_probes==3&&audit.head_probes==1&&audit.bytes==343128,"pair literal control/count/download");must(pair->try_close(),"pair actual retired close");pair.reset();hip_ok(hipSetDevice(roles.secondary->ordinal));must(s->try_close(),"pair secondary supply close");hip_ok(hipSetDevice(roles.primary.ordinal));must(p->try_close()&&rows->try_close(),"pair primary supplies close");std::ofstream terminal(output/"pair-terminal.tsv");terminal<<"processed\t2\nfull_Core_candidate_inputs\t2\nborrowed_refusal\t1\nprepare_badalloc\t1\nsource_opaque_cookie_probes\t3\nhead_opaque_probe\t1\nactual_boundary_D2H\t343128\n";terminal.flush();must(bool(terminal),"pair terminal flush");return 0;
}
// Declared qualification case: full official130 IDs, capacity4096, greedy
// lowest-ID tie, EOS1, max2. Only the first emitted token may be fed to Core.
int prefix_capture_fixture(const fs::path&input,const fs::path&output,const std::string&pci,const fs::path&ids_path,const fs::path*reference){
 using namespace strata_ext;auto ids=read_file<uint32_t>(ids_path);must(ids.size()==130&&ids[0]==0&&ids[127]==260&&ids[128]==128804&&ids[129]==128822,"sealed official130 geometry");
 must(!fs::exists(output),"capture run output already exists");if(reference)must(fs::is_regular_file(*reference/"reference-seal.json"),"reference-first hash seal required");
 int count=0,dev=-1;hip_ok(hipGetDeviceCount(&count));for(int i=0;i<count;++i){char actual[64]{};hip_ok(hipDeviceGetPCIBusId(actual,sizeof(actual),i));if(pci==actual)dev=i;}must(dev>=0,"actual capture PCI absent");hip_ok(hipSetDevice(dev));must(fs::create_directory(output),"capture run create");
 auto artifact=load_artifact(input);std::ifstream pf(input/"prefixes.tsv");std::string first;must(bool(std::getline(pf,first)),"fixed Engram metadata");auto e=engram::inspect_metadata(fs::u8path(fields(first).at(1)));auto source=artifact.source_tensor("per_layer_token_embd.weight").source;
 auto weight=std::make_unique<cache::PrimarySupply>(cache::SupplyConfig{2,2,2097152,4,4,dev,true});auto rows=std::make_unique<cache::RowSupply>(cache::RowConfig{24,24,1,1,dev},artifact,cache::RowSourceViews({{source,{source.original_path,0,source.original_size}}}));CoreConfig cfg;cfg.device=dev;
 auto id=fixture_identity();id.request_id=reference?"T36-candidate-0":"T36-reference";std::unique_ptr<CoreSequence>sequence;std::ofstream trace(output/"run.tsv");must(bool(trace),"capture run trace");
 try{
  sequence=std::make_unique<CoreSequence>(artifact,e,*weight,*rows,id,cfg,4096);std::vector<uint32_t>prefix(ids.begin(),ids.begin()+127);auto result=sequence->prefill(prefix,0);must(!result.cancelled&&result.processed==127&&result.logits.size()==129280,"actual127 prefix");auto raw=std::move(result.logits);
  uint64_t downloaded=0,adoptions=0;auto save=[&](uint64_t cursor){must(sequence->position()==cursor&&raw.size()==129280,"capture raw/cursor");for(auto value:raw)must(std::isfinite(value),"capture raw finite");sequence->quiesce();auto folder=output/std::to_string(cursor);downloaded+=capture_checkpoint(*sequence,folder);std::ofstream out(folder/"logits.bin",std::ios::binary);out.write(reinterpret_cast<const char*>(raw.data()),std::streamsize(raw.size()*4));out.flush();must(bool(out),"capture raw write/flush");trace<<"checkpoint\t"<<cursor<<'\t'<<id.request_id<<'\n';trace.flush();must(bool(trace),"checkpoint trace flush");};
  auto adopt=[&](uint64_t cursor){if(!reference)return;id.request_id="T36-candidate-"+std::to_string(cursor);auto before=sequence->runtime_stats();sequence->continue_request(id,cursor);auto after=sequence->runtime_stats();must(sequence->position()==cursor&&after.requested_output_or_fixture_download_bytes==before.requested_output_or_fixture_download_bytes,"adoption hidden logits/math");++adoptions;};
  save(127);for(uint64_t at=127;at<130;++at){adopt(at);raw=sequence->step(ids[size_t(at)],at);save(at+1);}
  auto greedy=[](const std::vector<float>&v){return uint32_t(std::max_element(v.begin(),v.end())-v.begin());};uint32_t decode=greedy(raw);std::ofstream chosen(output/"decode.tsv");chosen<<decode<<"\tgreedy-lowest-id\t1\t2\n";chosen.flush();must(bool(chosen),"decode policy flush");
  if(decode==1){trace<<"missing\t131\teos\n";trace.flush();throw std::runtime_error("EOS at first emitted token: checkpoint131 absent, no forced EOS step");}
  if(reference){std::ifstream expected(*reference/"decode.tsv");uint32_t wanted=129280;expected>>wanted;must(bool(expected)&&wanted==decode,"candidate actual greedy token differs from sealed reference");}
  adopt(130);raw=sequence->step(decode,130);save(131);uint32_t final_emitted=greedy(raw);trace<<"terminal\t131\t"<<final_emitted<<'\t'<<adoptions<<'\t'<<downloaded<<'\t'<<T20_SOURCE_ID<<'\n';trace.flush();must(bool(trace),"capture terminal flush");sequence->quiesce();sequence.reset();must(weight->try_close()&&rows->try_close(),"capture Core before shared-owner teardown");return 0;
 }catch(...){if(sequence){try{sequence->invalidate_and_drain();}catch(...){(void)sequence.release();(void)rows.release();(void)weight.release();std::terminate();}}throw;}
}
#endif
void owner_wait(const std::function<bool()>&done,const std::function<void()>&poll){
 const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(30);
 while(!done()){must(std::chrono::steady_clock::now()<deadline,"T36 owner probe timed out; actual completion unproven");poll();}
}
int prefix_owner_fixture(const fs::path&input,const fs::path&output,const std::string&pci){
 using namespace strata_ext;int count=0,dev=-1;hip_ok(hipGetDeviceCount(&count));for(int i=0;i<count;++i){char actual[64]{};hip_ok(hipDeviceGetPCIBusId(actual,sizeof(actual),i));if(pci==actual)dev=i;}must(dev>=0,"actual Primary PCI absent");hip_ok(hipSetDevice(dev));fs::create_directories(output);
 auto artifact=load_artifact(input);std::ifstream pf(input/"prefixes.tsv");std::string first;must(bool(std::getline(pf,first)),"fixed original Engram metadata");auto engram_config=engram::inspect_metadata(fs::u8path(fields(first).at(1)));auto source=artifact.source_tensor("per_layer_token_embd.weight").source;
 auto weight=std::make_unique<cache::PrimarySupply>(cache::SupplyConfig{2,2,2097152,4,4,dev,true});auto rows=std::make_unique<cache::RowSupply>(cache::RowConfig{24,24,1,1,dev},artifact,cache::RowSourceViews({{source,{source.original_path,0,source.original_size}}}));CoreStorage consumer(dev);CoreConfig cfg;cfg.device=dev;
 auto id=fixture_identity();id.request_id="T36-reference";std::unique_ptr<CoreSequence>sequence;
 std::ofstream events(output/"owner-events.tsv");uint64_t rejected=0,adopted=0;
 try{
  // Seal the fresh two-input reference before any continuation candidate result.
  sequence=std::make_unique<CoreSequence>(artifact,engram_config,*weight,*rows,id,cfg,3);auto fresh=sequence->prefill({3,37},0);must(!fresh.cancelled&&fresh.processed==2&&fresh.rows==1&&fresh.logits.size()==129280,"fresh reference geometry");write_file(output/"fresh2-logits.bin",fresh.logits);sequence->quiesce();sequence.reset();
  id.request_id="T36-owner-old";sequence=std::make_unique<CoreSequence>(artifact,engram_config,*weight,*rows,id,cfg,3);auto first_output=sequence->prefill({3},0);must(!first_output.cancelled&&first_output.processed==1&&sequence->position()==1,"one actual healthy processed Core");write_file(output/"candidate1-logits.bin",first_output.logits);
  auto proposed=id;proposed.request_id="T36-proposed";
  auto reject=[&](const char*label){auto before=sequence->runtime_stats();bool refused=false;try{sequence->continue_request(proposed,1);}catch(const RequestAdoptionRefused&){refused=true;}must(refused&&sequence->request_valid()&&sequence->position()==1,"held old owner did not refuse safely");auto after=sequence->runtime_stats();must(before.requested_output_or_fixture_download_bytes==after.requested_output_or_fixture_download_bytes&&before.state_positions==after.state_positions,"refusal changed state/readback");events<<"reject\t"<<label<<'\t'<<id.request_id<<"\t1\n";events.flush();++rejected;};
  auto adopt=[&](const char*label){must(rows->request_idle()&&weight->state()==cache::SupplyState::Idle&&weight->prefetch_state()==cache::SupplyState::Idle,"actual owner retirement before adoption");proposed.request_id="T36-adopt-"+std::to_string(adopted);auto before=sequence->runtime_stats();sequence->continue_request(proposed,1);id=proposed;auto after=sequence->runtime_stats();must(sequence->request_valid()&&sequence->position()==1&&after.requested_output_or_fixture_download_bytes==before.requested_output_or_fixture_download_bytes,"exact continuation performed hidden head/readback");events<<"adopt\t"<<label<<'\t'<<id.request_id<<"\t1\n";events.flush();++adopted;};
  auto token=artifact.source_tensor("token_embd.weight");auto tile=source_tile(token,0,3,1);cache::SupplyMatrix matrix{tile.original,tile.absolute_offset,tile.bytes,tile.type,1,size_t(tile.k)};matrix.row_tile=true;matrix.output_row_first=3;
  must(weight->begin(matrix,id),"old Primary demand admission");reject("primary-demand");weight->cancel();owner_wait([&]{auto s=weight->state();return s==cache::SupplyState::Cancelled||s==cache::SupplyState::Done;},[&]{weight->poll_io(10);weight->poll_device();});must(weight->take(id).empty(),"cancelled demand take");adopt("primary-demand-retired");
  must(weight->begin(matrix,id,true),"old prefetch admission");reject("primary-prefetch");weight->cancel_prefetch();owner_wait([&]{auto s=weight->prefetch_state();return s==cache::SupplyState::Cancelled||s==cache::SupplyState::Done;},[&]{weight->poll_io(10);weight->poll_device();});must(!weight->take_prefetch(id),"cancelled prefetch take");adopt("prefetch-retired");
  must(rows->evict({1,0,0}),"idle Row eviction before queued probe");rows->evict_ram();auto queued=rows->enqueue({{1,0,0}},id);must(bool(queued)&&rows->state(*queued)==cache::RowState::Queued,"old Row queued admission");reject("row-queued");rows->cancel(*queued);must(rows->take(*queued,id).cancelled,"cancelled queued Row take");adopt("row-queued-retired");
  auto row=rows->enqueue({{1,0,0}},id);must(bool(row),"old Row output admission");cache::DemandOrder order;owner_wait([&]{return rows->state(*row)==cache::RowState::Ready;},[&]{advance_core_io(*weight,*rows,order,{1,weight->read_window_capacity()},cache::Kind::Expert,10);});reject("row-ready");rows->launch_gather(*row);owner_wait([&]{return rows->state(*row)==cache::RowState::Download;},[&]{rows->poll_device();});auto borrowed=rows->borrow_device_output(*row);reject("row-borrowed");
  // Return on the actual same-device consumer stream. No poll before the pending proof.
  rows->return_device_output(*row,borrowed,consumer.stream());reject("row-return-pending");owner_wait([&]{return rows->state(*row)==cache::RowState::Done;},[&]{rows->poll_io(0);rows->poll_device();});reject("row-done-untaken");must(!rows->take(*row,id).cancelled,"actual returned Row take");adopt("row-returned-taken");
  auto next=sequence->step(37,1);must(next.size()==129280&&sequence->position()==2,"one actual continued next input");write_file(output/"continued2-logits.bin",next);must(std::memcmp(fresh.logits.data(),next.data(),129280*4)==0,"fresh-vs-continued all raw FP32 logits differ");sequence->quiesce();auto state=sequence->runtime_stats();must(std::all_of(state.state_positions.begin(),state.state_positions.end(),[](uint64_t p){return p==2;}),"all40 position counters");must(rejected==7&&adopted==4,"literal owner probe counts");
  events<<"terminal\tall-raw-logits-equal\t"<<id.request_id<<"\t2\n";events.flush();sequence.reset();consumer.drain();must(weight->try_close()&&rows->try_close(),"actual Core before shared-owner teardown");
  std::cout<<"{\"source_id\":\""<<T20_SOURCE_ID<<"\",\"actual_owner_probe\":true,\"rejections\":"<<rejected<<",\"adoptions\":"<<adopted<<",\"full_Core_fed_inputs\":4,\"raw_FP32_values_compared\":129280,\"full_state_payload_verified\":false,\"Expert_retained_pair_HTTP_verified\":false}\n";return 0;
 }catch(...){
  // Test failure must never destroy a possibly borrowed/unknown bundle. This
  // bounded fixture is a child process; preserve all implicated owners until
  // its fatal exit rather than claiming driver/lease recovery.
  (void)sequence.release();(void)rows.release();(void)weight.release();std::terminate();
 }
}
}
int main(int argc,char**argv){try{if(argc==2&&std::string(argv[1])=="--policy")return prefix_policy_main(argc,argv);
#ifdef STRATA_DEEPSEEK_T36_FIXTURE_CAPTURE
if(argc==5&&std::string(argv[1])=="--paired-reference")return prefix_paired_reference(fs::u8path(argv[2]),fs::u8path(argv[3]),argv[4]);
if(argc==7&&std::string(argv[1])=="--paired")return prefix_paired_fixture(fs::u8path(argv[2]),fs::u8path(argv[3]),argv[4],argv[5],fs::u8path(argv[6]));
if(argc==6&&std::string(argv[1])=="--capture-reference")return prefix_capture_fixture(fs::u8path(argv[2]),fs::u8path(argv[3]),argv[4],fs::u8path(argv[5]),nullptr);
if(argc==7&&std::string(argv[1])=="--capture-candidate"){auto reference=fs::u8path(argv[6]);return prefix_capture_fixture(fs::u8path(argv[2]),fs::u8path(argv[3]),argv[4],fs::u8path(argv[5]),&reference);}
#endif
must(argc==5&&std::string(argv[1])=="--owners","--owners fixedInput output primaryPCI required; no implicit GPU run");return prefix_owner_fixture(fs::u8path(argv[2]),fs::u8path(argv[3]),argv[4]);}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
#endif
