// Reuse existing task-local source loader/checked file utilities and host tests.
// The numerical executor remains the real CoreSequence implementation.
#define main historical_t20_fixture_main
#include "../core/core_fixture.cpp"
#undef main
#include "../../models/deepseek41/execution/expert_assist.hpp"
#include <mutex>
#include <set>
#include <atomic>
#include <thread>
// A failed fixture retains an unclosed owner until child exit; it never lets
// an active test request reach the owner's closed-only destructor.
template<class T>struct FixtureClose {void operator()(T*p)const noexcept{if(!p)return;try{if(p->try_close())delete p;}catch(...){/* retained through failed child exit */}};};
struct ExpertTrace final:ExpertAssistAudit {
 std::mutex mutex;std::ofstream events,transfers;uint64_t sequence=0;std::atomic<uint64_t>ready_count{0};std::atomic<bool>fail_compute{false};
 explicit ExpertTrace(const fs::path&p):events(p/"events.tsv"),transfers(p/"transfers.tsv"){}
 void event(const ExpertTicket&t,const char*name)override{if(std::string(name)=="secondary-compute-begin"&&fail_compute.exchange(false))throw std::runtime_error("fixture worker callback failure");if(std::string(name)=="return-ready")++ready_count;std::lock_guard<std::mutex>lock(mutex);events<<sequence++<<'\t'<<t.identity.request_id<<'\t'<<t.identity.epoch<<'\t'<<t.positions.at(t.pairs.at(0))<<'\t'<<t.layer<<'\t'<<t.expert<<'\t'<<t.slot<<'\t'<<t.generation<<'\t'<<name<<'\n';events.flush();}
 void transfer(const ExpertTicket&t,const char*direction,const strata_ext::device::TransferStats&s)override{std::lock_guard<std::mutex>lock(mutex);transfers<<t.identity.request_id<<'\t'<<t.identity.epoch<<'\t'<<t.positions.at(t.pairs.at(0))<<'\t'<<t.layer<<'\t'<<t.expert<<'\t'<<t.slot<<'\t'<<t.generation<<'\t'<<direction<<'\t'<<s.bytes<<'\t'<<s.path<<'\t'<<s.peer_bytes<<'\t'<<s.bounce_d2h<<'\t'<<s.bounce_h2d<<'\t'<<s.capability_status<<'\t'<<s.can_access<<'\t'<<s.enable_status<<'\t'<<s.peer_copy_status<<'\t'<<s.disable_status<<'\t'<<s.return_record_status<<'\t'<<s.return_drain_status<<'\t'<<s.cancelled<<'\n';transfers.flush();}
};
struct LayerCapture final:DeviceAudit {
 fs::path directory;uint64_t position=0;uint32_t layer=0;std::set<std::string>names;std::ofstream index;uint64_t bytes=0;
 explicit LayerCapture(fs::path p):directory(std::move(p)),index(directory/"stages.tsv"){}
 void frame(uint64_t p,uint32_t l)override{position=p;layer=l;}
 void stage(const std::string&name,const DeviceView&v,void*stream)override{
  auto key=std::to_string(position)+"-layer"+std::to_string(layer)+"-"+name;must(names.insert(key).second,"duplicate native stage");
  auto logical_rows=name=="attention_window"?std::min<uint64_t>(position+1,128):v.rows;must(logical_rows<=v.rows,"valid audit prefix");const auto n=logical_rows*v.columns*scalar_bytes(v.scalar);std::vector<uint8_t>data(static_cast<size_t>(n));hip_ok(hipMemcpyAsync(data.data(),v.data,size_t(n),hipMemcpyDeviceToHost,reinterpret_cast<hipStream_t>(stream)));hip_ok(hipStreamSynchronize(reinterpret_cast<hipStream_t>(stream)));write_file(directory/(key+".bin"),data);
  index<<position<<'\t'<<layer<<'\t'<<name<<'\t'<<logical_rows<<'\t'<<v.columns<<'\t'<<int(v.scalar)<<'\t'<<n<<'\t'<<key+".bin"<<'\n';index.flush();bytes+=n;
 }
};
void expert_stats(const fs::path&output,ExpertAssist&assist,const CoreSequence*sequence=nullptr){
 auto s=assist.stats();std::ofstream f(output/"assist-stats.tsv");
 f<<"jobs\t"<<s.primary_jobs<<'\t'<<s.secondary_jobs<<'\t'<<s.adopted<<'\t'<<s.cancelled<<'\n';
 f<<"payload\t"<<s.input_payload<<'\t'<<s.route_payload<<'\t'<<s.down_payload<<'\n';
 f<<"snapshot_d2d_issued\t"<<s.primary_snapshot_d2d_issued<<'\n';
 f<<"actual_transfer\t"<<s.peer_bytes<<'\t'<<s.bounce_d2h<<'\t'<<s.bounce_h2d<<'\n';
 f<<"owned\t"<<s.primary_device_owned<<'\t'<<s.secondary_workspace_owned<<'\t'<<s.secondary_weight_owned<<'\t'<<s.bounce_host_owned<<'\n';
 f<<"secondary_weight\t"<<s.secondary_weights.weight_read<<'\t'<<s.secondary_weights.weight_h2d<<'\t'<<s.secondary_weights.issued_reads<<'\n';
 f<<"secondary_hits\t"<<s.secondary_weights.gpu_hits<<'\t'<<s.secondary_weights.ram_hits<<'\t'<<s.secondary_weights.ssd_misses<<'\n';
 f<<"secondary_host\t"<<s.secondary_weights.host_owned<<'\t'<<s.secondary_weights.metadata<<'\t'<<s.secondary_weights.pinned_subset<<'\t'<<s.secondary_weights.pinned_known<<'\t'<<s.secondary_weights.pinned_observed<<'\n';
 std::ofstream stages(output/"secondary-stages.tsv");for(const auto&stage:s.secondary_weights.stages)stages<<stage.address<<'\t'<<stage.capacity<<'\t'<<stage.attempted<<'\t'<<stage.status<<'\t'<<stage.type<<'\n';
 if(sequence){auto c=sequence->runtime_stats();f<<"primary_total\t"<<sequence->explicit_device_owned()<<'\n';f<<"state_positions";for(auto p:c.state_positions)f<<'\t'<<p;f<<'\n';f<<"compressed";for(auto p:c.compressed_rows)f<<'\t'<<p;f<<'\n';f<<"keys";for(auto p:c.key_rows)f<<'\t'<<p;f<<'\n';}
}
int main(int argc,char**argv){try{
 if(argc==2&&std::string(argv[1])=="--host")return historical_t20_fixture_main(argc,argv);
 must(argc==7,"usage --full|--micro input output primaryPCI secondaryPCI auto|bounce");auto input=fs::u8path(argv[2]),output=fs::u8path(argv[3]);fs::create_directories(output);
 auto roles=strata_ext::device::resolve(strata_ext::device::inventory(),argv[4],std::string(argv[5]));hip_ok(hipSetDevice(roles.primary.ordinal));auto artifact=load_artifact(input);
 ExpertTrace trace(output);ExpertAssistConfig ac;ac.roles=roles;for(unsigned e=0;e<384;e+=2)ac.secondary_experts.push_back(e);ac.slots=std::string(argv[1])=="--micro1"?1:2;ac.max_batch=8;ac.secondary_weights={2,2,2097152,4,4,roles.secondary->ordinal,true};ac.secondary_core.device=roles.secondary->ordinal;ac.copy_policy=std::string(argv[6])=="bounce"?strata_ext::device::Policy::HostBounce:strata_ext::device::Policy::Auto;ac.audit=&trace;
 auto assist=std::make_unique<ExpertAssist>(artifact,ac);hip_ok(hipSetDevice(roles.primary.ordinal));
 if(std::string(argv[1])=="--full"){
  std::ifstream pf(input/"prefixes.tsv");std::string line;must(bool(std::getline(pf,line)),"Engram metadata");auto config=engram::inspect_metadata(fs::u8path(fields(line).at(1)));auto source=artifact.source_tensor("per_layer_token_embd.weight").source;
  std::unique_ptr<strata_ext::cache::PrimarySupply,FixtureClose<strata_ext::cache::PrimarySupply>> weight(new strata_ext::cache::PrimarySupply({2,2,2097152,4,4,roles.primary.ordinal,true}));std::unique_ptr<strata_ext::cache::RowSupply,FixtureClose<strata_ext::cache::RowSupply>> rows(new strata_ext::cache::RowSupply({24,24,1,1,roles.primary.ordinal},artifact,strata_ext::cache::RowSourceViews({{source,{source.original_path,0,source.original_size}}})));
  auto id=fixture_identity();id.request_id="T44-full40";LayerCapture audit(output);CoreConfig cfg;cfg.device=roles.primary.ordinal;cfg.full_logits=true;cfg.audit=&audit;cfg.experts=assist.get();
  auto sequence=std::make_unique<CoreSequence>(artifact,config,*weight,*rows,id,cfg,3);auto first=sequence->prefill({3,37},0);write_file(output/"prefill2-logits.bin",first.logits);auto last=sequence->step(1024,2);write_file(output/"append-logits.bin",last);assist->drain();expert_stats(output,*assist,sequence.get());sequence.reset();assist.reset();must(weight->try_close()&&rows->try_close(),"actual primary owner drain");
 }else{
  must(std::string(argv[1])=="--micro"||std::string(argv[1])=="--micro1","fixture mode");auto data=read_file<float>(input/"micro-input.bin"),coefficients=read_file<float>(input/"micro-route.bin");auto batch=coefficients.size();must(batch&&batch<=8&&data.size()==batch*5120,"micro source input geometry");CoreStorage storage(roles.primary.ordinal);auto x=storage.allocate("input",batch,5120,DeviceScalar::Bfloat16InFloat32),route=storage.allocate("route",batch,1,DeviceScalar::Float32);
  auto alloc=[&](const char*name,uint64_t k,DeviceScalar scalar){return storage.allocate(name,batch,k,scalar);};ExpertWorkspace workspace{alloc("qdq",5120,DeviceScalar::Float32),alloc("gate",2304,DeviceScalar::Bfloat16InFloat32),alloc("up",2304,DeviceScalar::Bfloat16InFloat32),alloc("hidden",2304,DeviceScalar::Bfloat16InFloat32),alloc("downqdq",2304,DeviceScalar::Float32),alloc("dot",5120,DeviceScalar::Float32)};
  std::unique_ptr<strata_ext::cache::PrimarySupply,FixtureClose<strata_ext::cache::PrimarySupply>> weight(new strata_ext::cache::PrimarySupply({2,2,2097152,4,4,roles.primary.ordinal,true}));auto id=fixture_identity();id.request_id="T44-micro";CoreConfig cfg;cfg.device=roles.primary.ordinal;CoreProjection projection(*weight,id,{1,weight->read_window_capacity()});
  storage.upload(x,data.data(),data.size()*4);storage.upload(route,coefficients.data(),coefficients.size()*4);ExpertFrame frame;frame.identity=id;std::vector<uint32_t>even_pairs,odd_pairs;for(uint32_t token=0;token<batch;++token){frame.token_positions.push_back(token);even_pairs.insert(even_pairs.end(),{token,0});odd_pairs.insert(odd_pairs.end(),{token,1});}
  unsigned rejections=0,positive_cases=0;auto reject=[&](const std::function<void()>&f){bool rejected=false;try{f();}catch(const std::exception&){rejected=true;}must(rejected,"invalid expert lifetime/key accepted");++rejections;};
  hipStream_t alternate=nullptr,wrong=nullptr;hip_ok(hipStreamCreateWithFlags(&alternate,hipStreamNonBlocking));hip_ok(hipSetDevice(roles.secondary->ordinal));hip_ok(hipStreamCreateWithFlags(&wrong,hipStreamNonBlocking));hip_ok(hipSetDevice(roles.primary.ordinal));
  auto collect=[&](const ExpertTicket&t,const std::string&label,bool negative=false){auto view=assist->collect(t);if(negative){reject([&]{assist->collect(t);});reject([&]{assist->consumed(t,wrong);});}std::vector<float>result(batch*5120);hip_ok(hipMemcpyAsync(result.data(),view.data,result.size()*4,hipMemcpyDeviceToHost,alternate));assist->consumed(t,alternate);write_file(output/(label+".bin"),result);++positive_cases;};
  {hip_ok(hipSetDevice(roles.secondary->ordinal));auto foreign=std::make_unique<CoreStorage>(roles.secondary->ordinal);auto sx=foreign->allocate("foreign-source",batch,5120,DeviceScalar::Bfloat16InFloat32);hip_ok(hipSetDevice(roles.primary.ordinal));auto fake=x;fake.data=sx.data;reject([&]{assist->submit(frame,0,38,even_pairs,fake,route,storage.stream(),{});});foreign.reset();hip_ok(hipSetDevice(roles.primary.ordinal));}
  auto duplicate=frame;duplicate.token_positions={0,0};reject([&]{assist->submit(duplicate,0,38,even_pairs,x,route,storage.stream(),{});});auto shape=x;++shape.rows;reject([&]{assist->submit(frame,0,38,even_pairs,shape,route,storage.stream(),{});});
  auto a=assist->submit(frame,0,38,even_pairs,x,route,storage.stream(),{});
  if(ac.slots==1)collect(a,"expert-38",true);
  auto b=assist->submit(frame,0,155,odd_pairs,x,route,storage.stream(),[&](const DeviceView&out){expert_forward_device(artifact,0,155,x,route,out,workspace,cfg,storage.stream(),projection.callback());});
  collect(b,"expert-155",true);if(ac.slots!=1)collect(a,"expert-38",true);
  reject([&]{assist->collect(a);});auto stale=b;++stale.generation;reject([&]{assist->collect(stale);});reject([&]{assist->consumed(a,alternate);});
  // Throw before local helper/snapshot publication: no secondary read/copy can
  // be issued; actual primary D2D is drained, then a real next expert succeeds.
  reject([&]{assist->submit(frame,0,155,odd_pairs,x,route,storage.stream(),[](const DeviceView&){throw std::runtime_error("fixture local callback failure");});});
  auto after_local=assist->submit(frame,0,38,even_pairs,x,route,storage.stream(),{});collect(after_local,"after-local-error");
  // Worker callback error is known/test-controlled, not a forced driver fault.
  trace.fail_compute=true;reject([&]{auto t=assist->submit(frame,0,38,even_pairs,x,route,storage.stream(),{});assist->collect(t);});assist->cancel_and_drain(storage.stream());
  auto after_worker=assist->submit(frame,0,38,even_pairs,x,route,storage.stream(),{});collect(after_worker,"after-worker-error");
  auto cancel=assist->submit(frame,0,38,even_pairs,x,route,storage.stream(),{});auto borrowed=assist->collect(cancel);std::vector<float>during_cancel(batch*5120);hip_ok(hipMemcpyAsync(during_cancel.data(),borrowed.data,during_cancel.size()*4,hipMemcpyDeviceToHost,alternate));assist->cancel_and_drain(alternate);write_file(output/"cancel-readback.bin",during_cancel);++positive_cases;reject([&]{assist->collect(cancel);});reject([&]{assist->consumed(cancel,alternate);});
  auto next=assist->submit(frame,0,38,even_pairs,x,route,storage.stream(),{});collect(next,"after-ready-cancel");
  assist->drain();expert_stats(output,*assist);fs::rename(output/"assist-stats.tsv",output/"main-assist-stats.tsv");fs::rename(output/"secondary-stages.tsv",output/"main-secondary-stages.tsv");
  // R1 regression: worker has a real ready result, no adopted consumer exists.
  // Destroy while caller current-device is secondary; shutdown must post its
  // cancellation/stop and join finitely, then a fresh component works.
  auto ready_before=trace.ready_count.load();auto shutdown=assist->submit(frame,0,38,even_pairs,x,route,storage.stream(),{});while(trace.ready_count.load()==ready_before)std::this_thread::yield();hip_ok(hipSetDevice(roles.secondary->ordinal));assist.reset();int current=-1;hip_ok(hipGetDevice(&current));must(current==roles.secondary->ordinal,"shutdown current device restoration");++positive_cases;hip_ok(hipSetDevice(roles.primary.ordinal));
  assist=std::make_unique<ExpertAssist>(artifact,ac);frame.identity.request_id="T44-micro-fresh";auto fresh=assist->submit(frame,0,38,even_pairs,x,route,storage.stream(),{});auto foreign=fresh;foreign.instance=shutdown.instance;reject([&]{assist->collect(foreign);});collect(fresh,"fresh-after-shutdown");assist->drain();
  std::ofstream control(output/"controls.tsv");control<<"rejections\t"<<rejections<<"\npositive_cases\t"<<positive_cases<<'\n';control.flush();hip_ok(hipStreamDestroy(alternate));hip_ok(hipSetDevice(roles.secondary->ordinal));hip_ok(hipStreamDestroy(wrong));hip_ok(hipSetDevice(roles.primary.ordinal));
  assist->drain();expert_stats(output,*assist);assist.reset();must(weight->try_close(),"micro primary weight close");
 }
 HMODULE handles[2048];DWORD needed=0;must(EnumProcessModules(GetCurrentProcess(),handles,sizeof(handles),&needed)&&needed<=sizeof(handles),"expert runtime modules");std::ofstream modules(output/"loaded-modules.txt");for(size_t i=0;i<needed/sizeof(HMODULE);++i){char path[32768]{};must(GetModuleFileNameA(handles[i],path,sizeof(path))>0,"expert module path");modules<<path<<'\n';}
 std::ofstream identities(output/"roles.tsv");for(const auto*role:{&roles.primary,&*roles.secondary})identities<<role->ordinal<<'\t'<<role->pci<<'\t'<<role->arch<<'\t'<<role->name<<'\n';
 std::cout<<"{\"source_id\":\""<<T20_SOURCE_ID<<"\",\"caller_comparison_required\":true,\"physical_simultaneous_occupancy_measured\":false}\n";return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
