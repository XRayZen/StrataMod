#include "../../native/cache/primary_supply.hpp"
#include "../../native/quant/quant.hpp"
#include "../../native/io/span_provider.hpp"
#include <hip/hip_runtime.h>
#include <windows.h>
#include <psapi.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <cstring>
#include <cmath>
#include <functional>
#include <chrono>
#include <thread>
using namespace strata_ext;
namespace fs=std::filesystem;
namespace {
unsigned assertions=0;
std::vector<std::string> cycle_receipts,capacity_receipts,pipeline_receipts;
void need(bool x,const char* m){++assertions;if(!x)throw std::runtime_error(m);}
void hip(hipError_t e){if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));}
template<class F>void rejects(F f){bool bad=false;try{f();}catch(const std::exception&){bad=true;}need(bad,"negative accepted");}
template<class T>std::vector<T> read(const fs::path& p){std::ifstream f(p,std::ios::binary|std::ios::ate);need(bool(f),"input absent");auto n=f.tellg();need(n>=0&&n%sizeof(T)==0,"exact element bytes");std::vector<T> a(size_t(n)/sizeof(T));f.seekg(0);f.read(reinterpret_cast<char*>(a.data()),n);need(bool(f),"input short");return a;}
template<class T>void write(const fs::path& p,const std::vector<T>& a){std::ofstream f(p,std::ios::binary);f.write(reinterpret_cast<const char*>(a.data()),a.size()*sizeof(T));need(bool(f),"output short");}
std::vector<std::string> fields(std::string line){std::istringstream f(line);std::string x;std::vector<std::string> a;while(std::getline(f,x,'\t'))a.push_back(x);return a;}
std::string quote(const std::string&s){std::string o="\"";for(auto c:s){if(c=='\\'||c=='"')o+='\\';o+=c;}return o+'"';}
std::string modules(){HMODULE h[2048];DWORD n=0;need(EnumProcessModules(GetCurrentProcess(),h,sizeof(h),&n)&&n<=sizeof(h),"module list");std::string s="[";for(size_t i=0;i<n/sizeof(HMODULE);++i){char p[32768];need(GetModuleFileNameA(h[i],p,sizeof(p))!=0,"module path");if(i)s+=',';s+=quote(p);}return s+"]";}
measurement::Identity identity(const std::string& h){measurement::Identity i;i.request_id="T18-fixture";i.epoch=1;i.phase=measurement::Phase::Startup;i.fixture_sha256=h;i.asset_sha256=h;i.bundle_sha256=h;return i;}
std::vector<cache::SupplyMatrix> matrices(const fs::path& input){
 deepseek41::SourceSet sources;std::string line;std::ifstream f(input/"sources.tsv");
 while(std::getline(f,line)){auto a=fields(line);need(a.size()==5,"source columns");sources.files.push_back({uint32_t(std::stoul(a[0])),fs::u8path(a[4]),std::stoull(a[1]),a[3],a[2]});if(sources.root.empty())sources.root=fs::u8path(a[4]).parent_path();}
 std::vector<artifact::PrefixIndex> prefixes;std::ifstream pf(input/"prefixes.tsv");fs::path first;
 while(std::getline(pf,line)){auto a=fields(line);if(first.empty())first=fs::u8path(a[1]);prefixes.push_back(artifact::inspect_prefix(fs::u8path(a[1]),std::stoull(a[0])));}
 deepseek41::Artifact index(artifact::merge_prefixes(prefixes),deepseek41::inspect_metadata(first),sources);
 std::vector<cache::SupplyMatrix> out;
 auto slice=index.expert(0,"up",38);out.push_back({slice.original,slice.absolute_offset,slice.bytes,slice.original.span.type_id,size_t(slice.dims_ggml[1]),size_t(slice.dims_ggml[0])});
 for(auto name:{"blk.0.ffn_up_shexp.weight","blk.0.ffn_down_shexp.weight"}){auto t=index.source_tensor(name);out.push_back({t,t.span.absolute_offset,t.span.bytes,t.span.type_id,size_t(t.span.dims_ggml[1]),size_t(t.span.dims_ggml[0])});}
 need(out[0].offset==5051106880&&out[0].offset>UINT32_MAX&&out[0].bytes==6266880,"expert38 actual >4GiB slice");return out;
}
void resident_tests(){
 cache::ResidentSlot s{4096,8192,123};auto w=cache::reserve_fill(s,123,8192);need(bool(w)&&s.writer&&!s.valid,"fill reservation");
 need(!cache::borrow_resident(s,123)&&!cache::reserve_fill(s,123,1),"unpublished fill not readable");
 rejects([&]{cache::complete_resident(*w,124,true);});need(cache::complete_resident(*w,123,true),"publish fill");rejects([&]{cache::complete_resident(*w,123,true);});
 auto a=cache::borrow_resident(s,123),b=cache::borrow_resident(s,123);need(a&&b&&s.readers==2,"shared resident readers");need(!cache::reserve_fill(s,123,1),"reader prevents eviction");
 need(!cache::complete_resident(*a,123,true,false)&&s.readers==1,"cancel old reader reclaimed without adoption");need(!cache::reserve_fill(s,123,1),"remaining reader protected");
 need(cache::complete_resident(*b,123,true)&&s.readers==0,"lastuse release");auto next=cache::reserve_fill(s,123,1);need(next&&next->generation==2,"next generation");need(!cache::complete_resident(*next,123,true,false)&&!s.valid,"cancelled DMA not published");
 auto fault=cache::reserve_fill(s,123,1);need(bool(fault),"quarantine reserve");cache::quarantine_resident(*fault,123);need(s.writer&&s.quarantined&&!cache::reserve_fill(s,123,1),"synthetic drain failure retains capacity");
 rejects([&]{cache::reserve_fill(s,123,8193);});rejects([&]{cache::reserve_fill(s,124,1);});
 cache::ResidentSlot exhausted{4096,8192,123,UINT64_MAX};rejects([&]{cache::reserve_fill(exhausted,123,1);});
 std::vector<cache::ResidentSlot> many(33);for(size_t i=0;i<many.size();++i){many[i]={4096+i*8192,8192,123};auto t=cache::reserve_fill(many[i],123,1);need(bool(t),"cache count independent of16");cache::complete_resident(*t,123,true);}
}
void host(const fs::path& input,const fs::path& output,const std::string& hash){
 resident_tests();auto m=matrices(input);std::vector<float> readback_probe;for(const auto& matrix:m)for(size_t b:{1u,2u,4u,8u})readback_probe.resize(b*matrix.rows);auto id=identity(hash);auto raw=read<uint8_t>(input/"raw-path.bin"); // path bytes fixture table below
 std::string rawpath(raw.begin(),raw.end());auto expected=read<uint8_t>(fs::u8path(rawpath));
 void* p0=_aligned_malloc(65536,4096);void* p1=_aligned_malloc(65536,4096);need(p0&&p1,"aligned host buffers");
 std::vector<artifact::FixtureView> sources{{m[0].original.source.original_path,0,m[0].original.source.original_size}};std::vector<io::Buffer> buffers{{p0,65536},{p1,65536}};
 io::Config config;config.max_chunk=65536;config.max_outstanding_bytes=131072;
 io::SpanProvider provider(sources,buffers,config);std::vector<uint8_t> data(m[0].bytes);
 std::vector<io::Span> spans{{0,m[0].offset,m[0].bytes,0}};auto t=provider.enqueue(spans,{data.data(),data.size()},id);need(bool(t),"physical >4GiB admission");
 size_t steps=0;while(!provider.done(*t)){need(++steps<20000,"finite read progress");provider.issue();provider.poll(10);}auto result=provider.take(*t,id);need(result.ok&&result.bytes==expected.size()&&data==expected,"full file raw equals fixed expert38");need(provider.try_close(),"physical read drained");auto stats=provider.stats();write(output/"expert38-read.bin",data);_aligned_free(p0);_aligned_free(p1);
 std::cout<<"{\"source_id\":"<<quote(T18_SOURCE_ID)<<",\"assertions\":"<<assertions<<",\"readback_capacity_expected\":"<<readback_probe.capacity()*sizeof(float)<<",\"logical_read\":"<<stats.logical_delivered<<",\"aligned_read\":"<<stats.read_requested<<",\"physical_IO\":null,\"GPU_used\":false}";
}
struct Allocation{void* p=nullptr;explicit Allocation(size_t n){hip(hipMalloc(&p,n));}~Allocation(){if(p)hipFree(p);}};
void wait(cache::PrimarySupply& p,cache::SupplyState goal){auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(60);while(p.state()!=goal){need(std::chrono::steady_clock::now()<deadline,"fixture wallclock progress deadline");p.advance();if(p.state()!=goal)std::this_thread::sleep_for(std::chrono::milliseconds(1));}}
void direct_tests(int device,int other,const fs::path& input,const fs::path& output,const std::vector<cache::SupplyMatrix>& ms){
 std::ifstream rawtable(input/"raw-paths.tsv");std::vector<std::string> paths;std::string line;while(std::getline(rawtable,line))paths.push_back(line);
 for(size_t i=0;i<ms.size();++i){const auto& m=ms[i];auto raw=read<uint8_t>(fs::u8path(paths[i]));Allocation packed(raw.size()),x(163840),y(163840);hip(hipMemcpy(packed.p,raw.data(),raw.size(),hipMemcpyHostToDevice));hipStream_t stream;hip(hipStreamCreateWithFlags(&stream,hipStreamNonBlocking));quant::ProjectionLease lease;
  auto v=quant::PackedDeviceView{static_cast<uint8_t*>(packed.p),m.type,m.rows,m.k,m.bytes,device};auto binding=quant::checked_projection(v,static_cast<float*>(x.p),163840,static_cast<float*>(y.p),163840,stream,lease);
  for(size_t b:{1u,2u,4u,8u}){auto values=read<float>(input/("m"+std::to_string(i)+"-B"+std::to_string(b)+"-input.bin"));hip(hipMemcpy(x.p,values.data(),values.size()*4,hipMemcpyHostToDevice));quant::project_into(binding,b);hip(hipStreamSynchronize(stream));std::vector<float> out(b*m.rows);hip(hipMemcpy(out.data(),y.p,out.size()*4,hipMemcpyDeviceToHost));write(output/("direct-m"+std::to_string(i)+"-B"+std::to_string(b)+".bin"),out);
   auto old=quant::project(raw,m.type,m.rows,m.k,b,values);need(old.size()==out.size()&&std::memcmp(old.data(),out.data(),out.size()*4)==0,"hostwrapper device API compatibility");}
  rejects([&]{quant::checked_projection(v,static_cast<float*>(x.p),163841,static_cast<float*>(y.p),163840,stream,lease);});
  lease.active=false;rejects([&]{quant::project_into(binding,1);});lease.active=true;++lease.generation;rejects([&]{quant::project_into(binding,1);});
  if(i==0&&other>=0){hip(hipSetDevice(other));Allocation foreign(m.bytes),fx(163840),fy(163840);hipStream_t fs;hip(hipStreamCreateWithFlags(&fs,hipStreamNonBlocking));hip(hipSetDevice(device));
   auto bad=v;bad.data=static_cast<uint8_t*>(foreign.p);rejects([&]{quant::checked_projection(bad,static_cast<float*>(x.p),163840,static_cast<float*>(y.p),163840,stream,lease);});
   rejects([&]{quant::checked_projection(v,static_cast<float*>(fx.p),163840,static_cast<float*>(y.p),163840,stream,lease);});
   rejects([&]{quant::checked_projection(v,static_cast<float*>(x.p),163840,static_cast<float*>(fy.p),163840,stream,lease);});
   rejects([&]{quant::checked_projection(v,static_cast<float*>(x.p),163840,static_cast<float*>(y.p),163840,fs,lease);});
   auto valid=quant::checked_projection(v,static_cast<float*>(x.p),163840,static_cast<float*>(y.p),163840,stream,lease);hip(hipSetDevice(other));rejects([&]{quant::project_into(valid,1);});hip(hipStreamDestroy(fs));
   hip(hipSetDevice(device));quant::project_into(valid,1);hip(hipStreamSynchronize(stream));hip(hipSetDevice(other));hip(hipFree(foreign.p));foreign.p=nullptr;hip(hipFree(fx.p));fx.p=nullptr;hip(hipFree(fy.p));fy.p=nullptr;hip(hipSetDevice(device));
  }
  hip(hipStreamDestroy(stream));
 }
}
void wait_prefetch(cache::PrimarySupply& p,cache::SupplyState goal){auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(60);while(p.prefetch_state()!=goal){need(std::chrono::steady_clock::now()<deadline,"fixture prefetch progress deadline");p.advance_fill();if(p.prefetch_state()!=goal)std::this_thread::sleep_for(std::chrono::milliseconds(1));}}
std::string progress_json(cache::SupplyProgress x){std::ostringstream s;s<<"{\"consumer_kernel\":"<<(x.consumer==cache::SupplyState::Kernel?"true":"false")<<",\"consumer_ready\":"<<(x.consumer==cache::SupplyState::Ready?"true":"false")<<",\"fill_done\":"<<(x.fill==cache::SupplyState::Done?"true":"false")<<",\"consumer_slot\":"<<x.consumer_slot<<",\"fill_slot\":"<<x.fill_slot<<",\"consumer_generation\":"<<x.consumer_generation<<",\"fill_generation\":"<<x.fill_generation<<",\"consumer_readers\":"<<x.consumer_readers<<",\"fill_writer\":"<<(x.fill_writer?"true":"false")<<",\"consumer_address\":"<<x.consumer_address<<",\"fill_address\":"<<x.fill_address<<",\"consumer_stream\":"<<x.consumer_stream<<",\"producer_stream\":"<<x.producer_stream<<",\"consumer_event\":"<<x.consumer_event<<",\"fill_event\":"<<x.fill_event<<",\"issued_read_bytes\":"<<x.issued_read_bytes<<"}";return s.str();}
void pipeline_tests(cache::PrimarySupply& p,const fs::path& input,const fs::path& output,const std::vector<cache::SupplyMatrix>& ms,const measurement::Identity& id){
 auto reset=[&]{need(p.state()==cache::SupplyState::Idle&&p.prefetch_state()==cache::SupplyState::Idle,"pipeline owner idle");for(size_t i=0;i<2;++i)need(p.evict_device(i),"pipeline setup evict");p.evict_ram();};
 auto launch=[&](const cache::SupplyMatrix& m,const measurement::Identity& identity){need(p.begin(m,identity),"pipeline demand admission");wait(p,cache::SupplyState::Ready);p.launch(1,read<float>(input/(m.type==39?"m0-B1-input.bin":"m1-B1-input.bin")));};
 auto finish=[&](const std::string& name,const measurement::Identity& identity){wait(p,cache::SupplyState::Download);p.download();auto result=p.take(identity);need(!result.empty(),"pipeline consumer adoption");write(output/name,result);};
 reset();launch(ms[0],id);auto before=p.stats();need(p.begin(ms[1],id,true),"spare-slot prefetch while consumer lease live");p.advance_fill();auto issued=p.progress();
 need(issued.consumer==cache::SupplyState::Kernel&&issued.consumer_readers==1&&issued.fill_writer&&issued.consumer_slot!=issued.fill_slot&&issued.issued_read_bytes>0,"actual separate fill issued while consumer lease held");
 need(!p.evict_device(issued.consumer_slot)&&!p.evict_device(issued.fill_slot)&&!p.begin(ms[2],id)&&!p.try_close(),"consumer/fill/I/O ownership protects both slots");
 rejects([&]{p.launch(1,read<float>(input/"m0-B1-input.bin"));});auto consumer_status_before=hipEventQuery(reinterpret_cast<hipEvent_t>(issued.consumer_event));
 wait_prefetch(p,cache::SupplyState::Done);auto completed=p.progress();auto after=p.stats();
 need(completed.consumer==cache::SupplyState::Kernel&&completed.consumer_readers==1&&!completed.fill_writer&&completed.consumer_slot!=completed.fill_slot,"fill completed without consuming consumer lease");
 auto consumer_status_after=hipEventQuery(reinterpret_cast<hipEvent_t>(completed.consumer_event));auto fill_status=hipEventQuery(reinterpret_cast<hipEvent_t>(completed.fill_event));need(fill_status==hipSuccess,"actual producer fill event completed");
 need(after.weight_read-before.weight_read==ms[1].bytes&&after.weight_h2d-before.weight_h2d==ms[1].bytes,"overlap exact source/H2D bytes");need(p.take_prefetch(id),"prefetch publication");finish("overlap-m0.bin",id);
 std::ostringstream record;record<<"{\"case\":\"overlap\",\"issued\":"<<progress_json(issued)<<",\"completed\":"<<progress_json(completed)<<",\"consumer_event_status_before\":"<<int(consumer_status_before)<<",\"consumer_event_status_after\":"<<int(consumer_status_after)<<",\"fill_event_status\":"<<int(fill_status)<<",\"weight_read_delta\":"<<after.weight_read-before.weight_read<<",\"weight_h2d_delta\":"<<after.weight_h2d-before.weight_h2d<<"}";pipeline_receipts.push_back(record.str());
 for(size_t which:{1u,0u}){auto start=p.stats();launch(ms[which],id);finish("pair-m"+std::to_string(which)+".bin",id);auto end=p.stats();need(end.weight_read==start.weight_read&&end.weight_h2d==start.weight_h2d,"distinct resident units alternate GPU hit");std::ostringstream rec;rec<<"{\"case\":\"resident_pair\",\"matrix\":"<<which<<",\"weight_read_delta\":"<<end.weight_read-start.weight_read<<",\"weight_h2d_delta\":"<<end.weight_h2d-start.weight_h2d<<"}";pipeline_receipts.push_back(rec.str());}
 for(bool dma:{false,true}){
  reset();launch(ms[0],id);need(p.begin(ms[1],id,true),"cancel separate fill admission");if(dma)wait_prefetch(p,cache::SupplyState::Dma);else p.advance_fill();auto original=p.progress();need(original.consumer_readers==1&&original.fill_writer,"cancel original lease ownership");p.cancel();wait_prefetch(p,cache::SupplyState::Cancelled);auto drained=p.progress();need(drained.consumer_readers==1&&!drained.fill_writer,"cancel fill drains original lease before consumer reap");need(!p.take_prefetch(id),"cancel prefetch not adopted");wait(p,cache::SupplyState::Cancelled);auto newer=id;++newer.epoch;need(p.take(newer).empty(),"cancel old consumer not published to next epoch");launch(ms[0],newer);finish(dma?"cancel-dma-next.bin":"cancel-read-next.bin",newer);
  std::ostringstream rec;rec<<"{\"case\":\""<<(dma?"cancel_dma":"cancel_read")<<"\",\"original\":"<<progress_json(original)<<",\"drained\":"<<progress_json(drained)<<",\"not_published\":true,\"next_request\":true}";pipeline_receipts.push_back(rec.str());
 }
 reset();launch(ms[0],id);auto missing=ms[1];missing.original.source.original_path=output/"test-owned-absent-prefetch.gguf";rejects([&]{p.begin(missing,id,true);});auto error=p.progress();need(error.consumer_readers==1&&p.state()==cache::SupplyState::Kernel&&p.prefetch_state()==cache::SupplyState::Cancelled,"prefetch error retains independent consumer");need(!p.take_prefetch(id),"prefetch source error not adopted");finish("error-consumer.bin",id);launch(ms[1],id);finish("error-next.bin",id);
 pipeline_receipts.push_back("{\"case\":\"prefetch_error\",\"consumer_retained\":true,\"not_published\":true,\"next_request\":true}");
 reset();need(p.begin(ms[1],id,true),"idle speculative source admission");p.advance_fill();need(!p.begin(ms[0],id),"demand preempts bounded speculation");wait_prefetch(p,cache::SupplyState::Cancelled);auto next=id;++next.epoch;need(!p.take_prefetch(next),"late cancelled fill is not next-epoch publication");launch(ms[0],next);finish("preempt-next.bin",next);pipeline_receipts.push_back("{\"case\":\"demand_preempt\",\"not_published\":true,\"next_request\":true}");
 reset();for(size_t which:{0u,1u}){launch(ms[which],id);wait(p,cache::SupplyState::Download);p.download();need(!p.take(id).empty(),"two valid units setup");}
 need(p.begin(ms[0],id)&&p.state()==cache::SupplyState::Ready,"Ready resident demand admitted");auto ready=p.progress();need(ready.consumer_readers==1&&!p.evict_device(ready.consumer_slot),"Ready demand already owns resident lease");
 need(p.begin(ms[2],id,true),"Ready demand permits other-slot prefetch");p.advance_fill();auto protected_ready=p.progress();need(protected_ready.consumer==cache::SupplyState::Ready&&protected_ready.consumer_readers==1&&protected_ready.fill_writer&&protected_ready.consumer_slot!=protected_ready.fill_slot,"Ready reservation excludes prefetched slot");
 wait_prefetch(p,cache::SupplyState::Done);auto completed_ready=p.progress();need(completed_ready.consumer==cache::SupplyState::Ready&&completed_ready.consumer_readers==1&&!completed_ready.fill_writer&&!p.evict_device(ready.consumer_slot),"Ready lease continuously held through other fill");need(p.take_prefetch(id),"other slot prefetch accepted");p.launch(1,read<float>(input/"m0-B1-input.bin"));finish("ready-A.bin",id);launch(ms[1],id);finish("ready-next.bin",id);
 need(p.begin(ms[1],id)&&p.state()==cache::SupplyState::Ready,"Ready cancel hit admitted");auto cancel_ready=p.progress();p.cancel();need(p.state()==cache::SupplyState::Cancelled&&p.take(id).empty()&&p.evict_device(cancel_ready.consumer_slot),"Ready cancellation releases exactly its unlaunched lease");
 std::ostringstream ready_record;ready_record<<"{\"case\":\"ready_reservation\",\"issued\":"<<progress_json(protected_ready)<<",\"completed\":"<<progress_json(completed_ready)<<",\"correct_A\":true,\"next_request\":true,\"ready_cancel_released\":true}";pipeline_receipts.push_back(ready_record.str());

}
cache::SupplyStats cache_tests(int device,const fs::path& input,const fs::path& output,const std::vector<cache::SupplyMatrix>& ms,const measurement::Identity& id){
 cache::SupplyStats total{};
 {cache::PrimarySupply small({1,1,4096,128,128,device});need(!small.begin(ms[0],id),"actual below-workingunit reservation refused");need(small.try_close(),"below-workingunit owner closes without growth");}
 for(size_t slots:{2u,1u}){
  cache::PrimarySupply p({slots,2,12533760,163840,163840,device});
  try {
  for(size_t i=0;i<ms.size();++i)for(size_t b:{1u,2u,4u,8u}){
   for(size_t s=0;s<slots;++s)need(p.evict_device(s),"idle evict");p.evict_ram();auto x=read<float>(input/("m"+std::to_string(i)+"-B"+std::to_string(b)+"-input.bin"));
   for(unsigned cycle=0;cycle<4;++cycle){auto before=p.stats();need(p.begin(ms[i],id),"cache demand admitted");
    if(p.state()!=cache::SupplyState::Ready){rejects([&]{p.launch(b,x);});wait(p,cache::SupplyState::Ready);}
    p.launch(b,x);need(!p.begin(ms[i],id)&&!p.try_close(),"single I/O pair and stream held");rejects([&]{p.launch(b,x);});
    bool held=false;for(size_t s=0;s<slots;++s)held|=!p.evict_device(s);need(held,"consumer lastuse prevents eviction");
    rejects([&]{p.download();});wait(p,cache::SupplyState::Download);need(!p.begin(ms[i],id),"D2H output lease before reuse");p.download();auto out=p.take(id);write(output/("cache-S"+std::to_string(slots)+"-m"+std::to_string(i)+"-B"+std::to_string(b)+"-C"+std::to_string(cycle)+".bin"),out);
    auto after=p.stats();auto read=after.weight_read-before.weight_read,h2d=after.weight_h2d-before.weight_h2d;
    std::ostringstream cycle_record;cycle_record<<"{\"slots\":"<<slots<<",\"matrix\":"<<i<<",\"batch\":"<<b<<",\"cycle\":"<<cycle<<",\"weight_read_delta\":"<<read<<",\"weight_h2d_delta\":"<<h2d<<",\"input_h2d_delta\":"<<after.input_h2d-before.input_h2d<<",\"output_d2h_delta\":"<<after.output_d2h-before.output_d2h<<"}";cycle_receipts.push_back(cycle_record.str());
    if(cycle==1)need(read==0&&h2d==0,"GPU hit weight read/H2D delta0");
    else if(cycle==2)need(read==0&&h2d==ms[i].bytes,"RAM hit read0 and real H2D");
    else need(read==ms[i].bytes&&h2d==ms[i].bytes,"SSD miss exact logical bytes and H2D");
    if(cycle==1||cycle==2){for(size_t s=0;s<slots;++s)need(p.evict_device(s),"post-consumer evict");if(cycle==2)p.evict_ram();}
   }
  }
  // Cancellations at queued/read issued, DMA issued and consumer issued retain
  // the original lease until actual completion, then allow a normal next job.
  for(unsigned phase=0;phase<4;++phase){for(size_t s=0;s<slots;++s)need(p.evict_device(s),"cancel setup evict");p.evict_ram();need(p.begin(ms[0],id),"cancel admission");
   if(phase==1){p.advance();}
   if(phase>=2)wait(p,cache::SupplyState::Dma);
   if(phase==3){wait(p,cache::SupplyState::Ready);auto x=read<float>(input/"m0-B1-input.bin");p.launch(1,x);}
   p.cancel();wait(p,cache::SupplyState::Cancelled);need(p.take(id).empty(),"cancel does not publish");
  }
  auto bad=ms[0];bad.offset=bad.original.source.original_size;rejects([&]{p.begin(bad,id);});
  for(size_t s=0;s<slots;++s)need(p.evict_device(s),"error setup evict");p.evict_ram();
  auto missing=ms[0];missing.original.source.original_path=output/"test-owned-absent-source.gguf";
  rejects([&]{p.begin(missing,id);});need(p.state()==cache::SupplyState::Cancelled,"failed open retains returnable owner");need(p.take(id).empty(),"failed unissued reservation cancelled");
  need(p.begin(ms[0],id),"normal next request after cancel/OOB/openerror");wait(p,cache::SupplyState::Ready);p.launch(1,read<float>(input/"m0-B1-input.bin"));wait(p,cache::SupplyState::Download);p.download();need(!p.take(id).empty(),"next request completed");
  if(slots==2)pipeline_tests(p,input,output,ms,id);
  if(slots==1)need(!p.begin(ms[1],id,true),"prefetch cannot consume only demand slot");
  total=p.stats();std::ostringstream capacity_record;capacity_record<<"{\"slots\":"<<slots<<",\"device_owned\":"<<total.device_owned<<",\"host_owned_pools_plus_retained_readback\":"<<total.host_owned<<",\"pinned_subset\":"<<(total.pinned_known?std::to_string(total.pinned_subset):"null")<<",\"stage_owned\":"<<(total.host_owned-25067520-131072-total.readback_capacity)<<",\"event_not_ready_observations\":"<<total.event_not_ready<<",\"readback_owner_capacity\":"<<total.readback_capacity<<",\"full_host_peak\":null}";capacity_receipts.push_back(capacity_record.str());need(total.device_owned==slots*12533760+327680,"actual DeviceArena capacity");need(p.try_close(),"owner all events drained before free");
  }catch(const std::exception& e){
   std::cerr<<"cache fixture failure before drain: "<<e.what()<<'\n';
   if(p.state()!=cache::SupplyState::Idle){p.cancel();wait(p,cache::SupplyState::Cancelled);p.take(id);}
   if(p.prefetch_state()!=cache::SupplyState::Idle){if(p.prefetch_state()!=cache::SupplyState::Done&&p.prefetch_state()!=cache::SupplyState::Cancelled){p.cancel_prefetch();wait_prefetch(p,cache::SupplyState::Cancelled);}p.take_prefetch(id);}
   need(p.try_close(),"failed fixture owner drained");throw;
  }
 }
 return total;
}
void gpu(const std::string& pci,const fs::path& input,const fs::path& output,const std::string& hash,bool cache){
 int count=0,device=-1,other=-1;hip(hipGetDeviceCount(&count));for(int i=0;i<count;++i){char id[64];hip(hipDeviceGetPCIBusId(id,sizeof(id),i));if(pci==id)device=i;else other=i;}need(device>=0,"exact physical PCI");hip(hipSetDevice(device));hipDeviceProp_t prop;hip(hipGetDeviceProperties(&prop,device));size_t free=0,total=0;auto memory_status=hipMemGetInfo(&free,&total);
 std::ofstream observation(output/"gpu-observation.json");observation<<"{\"pci\":"<<quote(pci)<<",\"ordinal\":"<<device<<",\"arch\":"<<quote(prop.gcnArchName)<<",\"hip_memory_status\":"<<int(memory_status)<<",\"hip_free\":"<<(memory_status==hipSuccess?std::to_string(free):"null")<<",\"hip_total\":"<<(memory_status==hipSuccess?std::to_string(total):"null")<<",\"loaded_modules\":"<<modules()<<"}";observation.close();
 auto ms=matrices(input);direct_tests(device,other,input,output,ms);cache::SupplyStats stats{};if(cache)stats=cache_tests(device,input,output,ms,identity(hash));
 std::cout<<"{\"source_id\":"<<quote(T18_SOURCE_ID)<<",\"pci\":"<<quote(pci)<<",\"arch\":"<<quote(prop.gcnArchName)<<",\"assertions\":"<<assertions<<",\"cache_tested\":"<<(cache?"true":"false")<<",\"weight_read\":"<<stats.weight_read<<",\"weight_h2d\":"<<stats.weight_h2d<<",\"input_h2d\":"<<stats.input_h2d<<",\"output_d2h\":"<<stats.output_d2h<<",\"gpu_hits\":"<<stats.gpu_hits<<",\"ram_hits\":"<<stats.ram_hits<<",\"ssd_misses\":"<<stats.ssd_misses<<",\"device_owned\":"<<stats.device_owned<<",\"host_owned\":"<<stats.host_owned<<",\"pinned_subset\":"<<(stats.pinned_known?std::to_string(stats.pinned_subset):"null")<<",\"pinned_observed\":"<<(stats.pinned_observed?"true":"false")<<",\"attribute_status\":"<<(stats.attribute_status>=0?std::to_string(stats.attribute_status):"null")<<",\"metadata_lower_bound\":"<<stats.metadata<<",\"hip_memory_status\":"<<int(memory_status)<<",\"hip_free\":"<<(memory_status==hipSuccess?std::to_string(free):"null")<<",\"context_physical\":null,\"stages\":[";
 for(size_t i=0;i<stats.stages.size();++i){auto s=stats.stages[i];if(i)std::cout<<',';std::cout<<"{\"address\":"<<s.address<<",\"capacity\":"<<s.capacity<<",\"query_attempted\":"<<(s.attempted?"true":"false")<<",\"status\":"<<(s.attempted?std::to_string(s.status):"null")<<",\"type\":"<<(s.attempted&&s.status==0?std::to_string(s.type):"null")<<"}";}
 std::cout<<"],\"cycle_receipts\":[";for(size_t i=0;i<cycle_receipts.size();++i){if(i)std::cout<<',';std::cout<<cycle_receipts[i];}
 std::cout<<"],\"capacity_receipts\":[";for(size_t i=0;i<capacity_receipts.size();++i){if(i)std::cout<<',';std::cout<<capacity_receipts[i];}
 std::cout<<"],\"pipeline_receipts\":[";for(size_t i=0;i<pipeline_receipts.size();++i){if(i)std::cout<<',';std::cout<<pipeline_receipts[i];}
 std::cout<<"],\"loaded_modules\":"<<modules()<<"}";
}
}
int main(int argc,char** argv){try{if(argc==2&&std::string(argv[1])=="--identity"){std::cout<<"{\"source_id\":"<<quote(T18_SOURCE_ID)<<"}";return 0;}
 if(argc==2&&std::string(argv[1])=="--resident-selftest"){resident_tests();std::cout<<"{\"assertions\":"<<assertions<<",\"GPU_used\":false}";return 0;}
 if(argc==5&&std::string(argv[1])=="--host"){fs::create_directories(fs::u8path(argv[3]));host(fs::u8path(argv[2]),fs::u8path(argv[3]),argv[4]);return 0;}
 if(argc==6&&(std::string(argv[1])=="--gpu"||std::string(argv[1])=="--device")){fs::create_directories(fs::u8path(argv[4]));gpu(argv[2],fs::u8path(argv[3]),fs::u8path(argv[4]),argv[5],std::string(argv[1])=="--gpu");return 0;}
 throw std::runtime_error("explicit fixture mode required");}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
