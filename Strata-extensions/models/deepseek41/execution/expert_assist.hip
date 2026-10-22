#include "expert_assist.hpp"
#include "../../../native/cache/secondary_cache.hpp"
#include <hip/hip_runtime.h>
#include "strata/core/device.hpp"
#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <exception>
#include <mutex>
#include <set>
#include <thread>
namespace strata_ext::deepseek41 {
namespace {
void require(bool v,const char*s){if(!v)throw std::runtime_error(s);}
void checked(hipError_t e){if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));}
struct On {int before=-1;explicit On(int device){checked(hipGetDevice(&before));checked(hipSetDevice(device));}~On(){if(before>=0)hipSetDevice(before);}};
DeviceView rows(DeviceView v,uint64_t n){require(n&&n<=v.rows,"expert finite row extent");v.rows=n;return v;}
bool same(const measurement::Identity&a,const measurement::Identity&b){return a.request_id==b.request_id&&a.epoch==b.epoch&&a.phase==b.phase&&a.fixture_sha256==b.fixture_sha256&&a.asset_sha256==b.asset_sha256&&a.bundle_sha256==b.bundle_sha256;}
bool key(const ExpertTicket&a,const ExpertTicket&b){return a.instance&&a.instance==b.instance&&a.generation==b.generation&&a.slot==b.slot&&a.layer==b.layer&&a.expert==b.expert&&a.pairs==b.pairs&&a.positions==b.positions&&same(a.identity,b.identity);}
struct Interrupted {};
[[noreturn]]void startup_result(std::exception_ptr initialization,bool closed,std::exception_ptr cleanup){
 if(!closed||cleanup)throw cache::SecondaryConstructionUnknown(std::move(initialization),std::move(cleanup));
 std::rethrow_exception(initialization);
}
}
#ifdef STRATA_T28_CONSTRUCTION_TEST
void t46_expert_startup_result(std::exception_ptr initialization,bool closed,std::exception_ptr cleanup){startup_result(std::move(initialization),closed,std::move(cleanup));}
#endif
struct ExpertAssist::Impl {
 const Artifact& artifact;std::shared_ptr<const uint8_t> instance=std::make_shared<const uint8_t>(0);ExpertAssistConfig config;std::set<uint32_t> assignment;
 enum class Published { Free,Reserved,Ready,Failed };
 struct Mailbox {
  Published state=Published::Free;ExpertTicket ticket;bool reserve=false,input_notice=false,return_notice=false,cancel=false,adopted=false;
  void*stream=nullptr;void*returned_stream=nullptr;void*cancel_stream=nullptr;DeviceView input,route,result;hipEvent_t input_ready=nullptr;std::exception_ptr failure;
 };
 struct Job {
  enum class State { Free,Snapshot,Copying,Ready,Returning,Failed }state=State::Free;
  ExpertTicket ticket;bool remote=false,cancel=false,ready_published=false;void*primary_stream=nullptr;void*returned_stream=nullptr;void*cancel_stream=nullptr;
  DeviceView pinput,proute,pdown,sinput,sroute,sdown;ExpertWorkspace workspace;
  cache::ResidentSlot pi,pr,pd,si,sr,sd;cache::ResidentLease input_writer,route_writer,down_writer,local_reader;
  hipEvent_t input_ready=nullptr,local_done=nullptr;
  std::unique_ptr<device::CopyTask> input_copy,route_copy,down_copy;
  std::vector<uint8_t> bounce;bool input_notice=false,return_notice=false;
 };
 mutable std::mutex mutex;std::condition_variable wake;std::thread worker;
 std::vector<Mailbox> boxes;std::vector<std::unique_ptr<Job>> jobs;
 std::unique_ptr<CoreStorage> primary,secondary;std::unique_ptr<cache::PrimarySupply> weights;
 // One bounded worker-owned activation domain, retained only for the same request.
 std::unique_ptr<CoreProjection> projection;measurement::Identity projection_identity;
 uint64_t retire_requested=0,retire_ack=0;
 uint64_t snapshot_issued=0;ExpertAssistStats observed,published_stats;std::exception_ptr startup_failure,startup_cleanup_failure,fatal;
 bool startup=false,stop=false,closed=false,quarantined=false,retain_on_stop=false;void*last_primary_stream=nullptr;
 Impl(const Artifact&a,ExpertAssistConfig c):artifact(a),config(std::move(c)),boxes(config.slots){
  require(config.roles.secondary&&config.roles.primary.ordinal>=0&&config.roles.secondary->ordinal>=0&&config.roles.primary.ordinal!=config.roles.secondary->ordinal,"distinct physical expert compute roles");
  require(config.slots&&config.slots<=UINT32_MAX&&config.max_batch&&config.max_batch<=UINT32_MAX,"expert declared finite capacity");
  for(auto e:config.secondary_experts)require(e<384&&assignment.insert(e).second,"expert assignment range/duplicate");
  require(config.secondary_weights.device==config.roles.secondary->ordinal&&config.secondary_core.device==config.roles.secondary->ordinal&&config.secondary_weights.permit_only,"secondary owner device/permit binding");
  config.secondary_core.audit=nullptr;config.secondary_core.experts=nullptr;
  for(const auto*role:{&config.roles.primary,&*config.roles.secondary}){char pci[64]{};checked(hipDeviceGetPCIBusId(pci,sizeof(pci),role->ordinal));require(role->pci==pci,"expert actual physical role binding");auto problem=strata::core::gpu_arch_problem(role->ordinal);require(problem.empty(),problem.c_str());}
 }
 static void slot(cache::ResidentSlot&slot,const DeviceView&view,uint64_t owner){slot.address=reinterpret_cast<uintptr_t>(view.data);slot.capacity=view.bytes;slot.owner=owner;}
 void event(const ExpertTicket&t,const char*name){if(config.audit)config.audit->event(t,name);}
 void publish_stats(){observed.secondary_graph=weights->projection_graph_stats();observed.secondary_request_generation=weights->generation();observed.secondary_known=!quarantined&&weights->state()==cache::SupplyState::Idle&&weights->prefetch_state()==cache::SupplyState::Idle&&!observed.secondary_graph.module.retained;observed.secondary_weights=weights->stats();observed.secondary_weight_owned=observed.secondary_weights.device_owned;observed.quarantined=quarantined;std::lock_guard<std::mutex>lock(mutex);observed.primary_snapshot_d2d_issued=snapshot_issued;published_stats=observed;}
 // The worker is the sole owner of projection, Supply and all HIP operations.
 // A false retire retains the projection AND its original activation storage.
 void retire_projection(){
  if(!projection)return;
  require(projection->retire_graph(),"expert graph retirement unknown");
  projection.reset();projection_identity={};
 }
 bool projection_ready(size_t i){
  auto&j=*jobs[i];
  if(projection&&!same(projection_identity,j.ticket.identity)){
   // Old job copies/readers must be known before changing the activation domain.
   for(size_t k=0;k<jobs.size();++k)if(k!=i&&jobs[k]->state!=Job::State::Free&&!same(jobs[k]->ticket.identity,j.ticket.identity))return false;
   retire_projection();
  }
  if(!projection){
   projection=std::make_unique<CoreProjection>(*weights,j.ticket.identity,CoreIoGrant{1,weights->read_window_capacity()});
   projection_identity=j.ticket.identity;
  }
  return true;
 }
 void retire_if_idle(){
  uint64_t requested=0;
  {std::lock_guard<std::mutex>lock(mutex);requested=retire_requested;}
  if(requested==retire_ack)return;
  for(const auto&j:jobs)if(j->state!=Job::State::Free)return;
  retire_projection();publish_stats();
  {std::lock_guard<std::mutex>lock(mutex);retire_ack=requested;}
  wake.notify_all();
 }
 bool cancelled(size_t i){std::lock_guard<std::mutex>lock(mutex);return boxes[i].cancel||stop;}
 void initialize(){
  On current(config.roles.secondary->ordinal);secondary=std::make_unique<CoreStorage>(config.roles.secondary->ordinal);weights=std::make_unique<cache::PrimarySupply>(config.secondary_weights);
  primary=std::make_unique<CoreStorage>(config.roles.primary.ordinal);
  for(size_t i=0;i<config.slots;++i){
   jobs.push_back(std::make_unique<Job>());auto&j=jobs.back();auto name=std::to_string(i)+"-";const auto n=config.max_batch;
   {On p(config.roles.primary.ordinal);j->pinput=primary->allocate(name+"input",n,5120,DeviceScalar::Bfloat16InFloat32);j->proute=primary->allocate(name+"route",n,1,DeviceScalar::Float32);j->pdown=primary->allocate(name+"down",n,5120,DeviceScalar::Bfloat16InFloat32);checked(hipEventCreateWithFlags(&j->input_ready,hipEventDisableTiming));checked(hipEventCreateWithFlags(&j->local_done,hipEventDisableTiming));}
   {On s(config.roles.secondary->ordinal);j->sinput=secondary->allocate(name+"input",n,5120,DeviceScalar::Bfloat16InFloat32);j->sroute=secondary->allocate(name+"route",n,1,DeviceScalar::Float32);j->sdown=secondary->allocate(name+"down",n,5120,DeviceScalar::Bfloat16InFloat32);
    auto f=[&](const char*label,uint64_t k,DeviceScalar scalar){return secondary->allocate(name+label,n,k,scalar);};
    j->workspace={f("qdq",5120,DeviceScalar::Float32),f("gate",2304,DeviceScalar::Bfloat16InFloat32),f("up",2304,DeviceScalar::Bfloat16InFloat32),f("hidden",2304,DeviceScalar::Bfloat16InFloat32),f("down-qdq",2304,DeviceScalar::Float32),f("dot",5120,DeviceScalar::Float32)};
   }
   const uint64_t owner=uint64_t(i)+1;slot(j->pi,j->pinput,owner);slot(j->pr,j->proute,owner);slot(j->pd,j->pdown,owner);slot(j->si,j->sinput,owner);slot(j->sr,j->sroute,owner);slot(j->sd,j->sdown,owner);
   j->bounce.resize(size_t(config.max_batch*5120*4));observed.bounce_host_owned+=j->bounce.size();
  }
  observed.primary_device_owned=primary->explicit_owned_bytes();observed.secondary_workspace_owned=secondary->explicit_owned_bytes();publish_stats();
 }
 void reserve(size_t i,const Mailbox&message){
  auto&j=*jobs[i];require(j.state==Job::State::Free,"reserved live expert slot");
  require(j.ticket.generation!=UINT64_MAX,"expert generation exhausted");auto generation=j.ticket.generation+1;j.ticket=message.ticket;j.ticket.slot=uint32_t(i);j.ticket.generation=generation;
  j.ready_published=false;j.returned_stream=nullptr;j.cancel_stream=nullptr;j.primary_stream=message.stream;j.remote=assignment.count(j.ticket.expert)!=0;j.cancel=false;j.input_notice=false;j.return_notice=false;
  auto iw=cache::reserve_fill(j.pi,j.pi.owner,j.ticket.pairs.size()/2*5120*4),rw=cache::reserve_fill(j.pr,j.pr.owner,j.ticket.pairs.size()/2*4);
  require(iw&&rw,"expert snapshot reservation");j.input_writer=std::move(*iw);j.route_writer=std::move(*rw);
  if(!j.remote){auto dw=cache::reserve_fill(j.pd,j.pd.owner,j.ticket.pairs.size()/2*5120*4);require(bool(dw),"expert local result reservation");j.down_writer=std::move(*dw);}
  j.state=Job::State::Snapshot;
  event(j.ticket,"reserved");{std::lock_guard<std::mutex>lock(mutex);auto&b=boxes[i];b.ticket=j.ticket;b.input=rows(j.pinput,j.ticket.pairs.size()/2);b.route=rows(j.proute,j.ticket.pairs.size()/2);b.result=rows(j.pdown,j.ticket.pairs.size()/2);b.input_ready=j.input_ready;b.state=Published::Reserved;}
  wake.notify_all();
 }
 device::Endpoint endpoint(const DeviceView&v,cache::ResidentSlot&s,void*stream){return {v.data,v.bytes,v.device,reinterpret_cast<hipStream_t>(stream),&s,s.owner,s.generation};}
 void start_copy(std::unique_ptr<device::CopyTask>&copy,const DeviceView&src,cache::ResidentSlot&ss,void*srcstream,const DeviceView&dst,cache::ResidentSlot&ds,void*dststream,Job&j,uint64_t bytes){
  On on(dst.device);copy=std::make_unique<device::CopyTask>(endpoint(src,ss,srcstream),endpoint(dst,ds,dststream),j.bounce.data(),j.bounce.size(),config.copy_policy);copy->submit(bytes);
 }
 bool ready(std::unique_ptr<device::CopyTask>&copy,int device){On on(device);copy->poll();require(copy->phase()!=device::Phase::Quarantined,"expert copy unknown completion");return copy->phase()==device::Phase::Ready;}
 void account(const device::TransferStats&s){observed.peer_bytes+=s.peer_bytes;observed.bounce_d2h+=s.bounce_d2h;observed.bounce_h2d+=s.bounce_h2d;}
 void close_copy(std::unique_ptr<device::CopyTask>&copy,int device,void*last,bool cancel,const ExpertTicket&ticket,const char*direction){
  if(!copy)return;On on(device);if(cancel)copy->cancel();
  while(copy->phase()!=device::Phase::Done){if(copy->phase()==device::Phase::Ready)copy->consumer_done_on(reinterpret_cast<hipStream_t>(last));else copy->poll();require(copy->phase()!=device::Phase::Quarantined,"expert copy quarantine");std::this_thread::yield();}
  require(copy->try_close(),"expert copy close after actual completion");auto count=copy->stats();account(count);if(config.audit)config.audit->transfer(ticket,direction,count);copy.reset();
 }
 void release_writer(cache::ResidentLease&lease,bool publish){if(lease.active)require(cache::complete_resident(lease,lease.owner,true,publish)==publish,"expert writer release");}
 void retire(size_t i,bool cancel){
  auto&j=*jobs[i];
  // Caller has stopped submissions/use before cancellation. Normal consumed
  // waits cover the actual scatter stream; neither path infers completion.
  if(cancel){On p(config.roles.primary.ordinal);checked(hipStreamSynchronize(reinterpret_cast<hipStream_t>(j.primary_stream)));if(j.returned_stream&&j.returned_stream!=j.primary_stream)checked(hipStreamSynchronize(reinterpret_cast<hipStream_t>(j.returned_stream)));if(j.cancel_stream&&j.cancel_stream!=j.primary_stream&&j.cancel_stream!=j.returned_stream)checked(hipStreamSynchronize(reinterpret_cast<hipStream_t>(j.cancel_stream)));On s(config.roles.secondary->ordinal);checked(hipStreamSynchronize(reinterpret_cast<hipStream_t>(secondary->stream())));}
  close_copy(j.input_copy,config.roles.secondary->ordinal,secondary->stream(),cancel,j.ticket,"input");close_copy(j.route_copy,config.roles.secondary->ordinal,secondary->stream(),cancel,j.ticket,"route");close_copy(j.down_copy,config.roles.primary.ordinal,j.returned_stream?j.returned_stream:j.primary_stream,cancel,j.ticket,"down");
  release_writer(j.input_writer,false);release_writer(j.route_writer,false);release_writer(j.down_writer,false);
  if(j.local_reader.active){On p(config.roles.primary.ordinal);checked(hipEventRecord(j.local_done,reinterpret_cast<hipStream_t>(j.returned_stream?j.returned_stream:j.primary_stream)));checked(hipEventSynchronize(j.local_done));require(cache::complete_resident(j.local_reader,j.local_reader.owner,true,false)==false,"local expert last use");}
  j.state=Job::State::Free;j.cancel=false;j.input_notice=false;j.return_notice=false;
  ++observed.last_sequence;if(cancel)++observed.cancelled;else ++observed.adopted;
  if(!cancel)event(j.ticket,"last-use-complete");
  event(j.ticket,cancel?"cancel-retired":"retired");publish_stats();
  // Retirement ACK is published after last-use evidence and the matching
  // immutable stats snapshot, so a caller observing Free never reads old stats.
  {std::lock_guard<std::mutex>lock(mutex);auto&b=boxes[i];b.state=Published::Free;b.reserve=b.input_notice=b.return_notice=b.cancel=b.adopted=false;b.failure=nullptr;}
  wake.notify_all();
 }
 void advance(size_t i){
  auto&j=*jobs[i];if(j.state==Job::State::Free)return;
  if(j.cancel){retire(i,true);return;}
  if(j.state==Job::State::Snapshot&&j.input_notice){
   On p(config.roles.primary.ordinal);auto status=hipEventQuery(j.input_ready);if(status==hipErrorNotReady)return;checked(status);
   event(j.ticket,"snapshot-ready");release_writer(j.input_writer,true);release_writer(j.route_writer,true);
   const auto n=j.ticket.pairs.size()/2;
   if(!j.remote){release_writer(j.down_writer,true);auto held=cache::borrow_resident(j.pd,j.pd.owner);require(bool(held),"local result reader");j.local_reader=std::move(*held);++observed.primary_jobs;event(j.ticket,"primary-local-complete");j.state=Job::State::Ready;}
   else{start_copy(j.input_copy,j.pinput,j.pi,j.primary_stream,j.sinput,j.si,secondary->stream(),j,n*5120*4);observed.input_payload+=n*5120*4;j.state=Job::State::Copying;}
  }
  if(j.state==Job::State::Copying&&ready(j.input_copy,config.roles.secondary->ordinal)&&!j.route_copy){
   // The pageable bounce region is reused only after the preceding input H2D
   // event is complete, never while that host region is still being consumed.
   start_copy(j.route_copy,j.proute,j.pr,j.primary_stream,j.sroute,j.sr,secondary->stream(),j,j.ticket.pairs.size()/2*4);observed.route_payload+=j.ticket.pairs.size()/2*4;
  }
  if(j.state==Job::State::Copying&&j.route_copy&&ready(j.input_copy,config.roles.secondary->ordinal)&&ready(j.route_copy,config.roles.secondary->ordinal)){
   On s(config.roles.secondary->ordinal);if(!projection_ready(i))return;
   const auto n=j.ticket.pairs.size()/2;
   auto writer=cache::reserve_fill(j.sd,j.sd.owner,n*5120*4);require(bool(writer),"secondary result writer");j.down_writer=std::move(*writer);
   auto project=projection->callback();
   DeviceProject finite=[&](const SourceTile&t,const DeviceView&x,const DeviceView&y,uint64_t b,void*stream){if(cancelled(i))throw Interrupted{};project(t,x,y,b,stream);};
   event(j.ticket,"input-ready");event(j.ticket,"secondary-compute-begin");expert_forward_device(artifact,j.ticket.layer,j.ticket.expert,rows(j.sinput,n),rows(j.sroute,n),rows(j.sdown,n),j.workspace,config.secondary_core,secondary->stream(),finite);secondary->drain();event(j.ticket,"secondary-compute-complete");release_writer(j.down_writer,true);
   close_copy(j.input_copy,config.roles.secondary->ordinal,secondary->stream(),false,j.ticket,"input");close_copy(j.route_copy,config.roles.secondary->ordinal,secondary->stream(),false,j.ticket,"route");
   start_copy(j.down_copy,j.sdown,j.sd,secondary->stream(),j.pdown,j.pd,j.primary_stream,j,n*5120*4);++observed.secondary_jobs;observed.down_payload+=n*5120*4;j.state=Job::State::Returning;
  }
  if(j.state==Job::State::Returning&&ready(j.down_copy,config.roles.primary.ordinal))j.state=Job::State::Ready;
  if(j.state==Job::State::Ready){
   if(!j.ready_published){event(j.ticket,"return-ready");{std::lock_guard<std::mutex>lock(mutex);boxes[i].state=Published::Ready;}j.ready_published=true;wake.notify_all();}if(j.return_notice)retire(i,false);
  }
 }
 void cleanup(){
  if(secondary){On s(config.roles.secondary->ordinal);secondary->drain();}
  if(weights){On s(config.roles.secondary->ordinal);retire_projection();require(weights->try_close(),"secondary weight owner still active");weights.reset();}
  for(auto&j:jobs){On p(config.roles.primary.ordinal);if(j->input_ready)checked(hipEventDestroy(j->input_ready));if(j->local_done)checked(hipEventDestroy(j->local_done));j->input_ready=j->local_done=nullptr;}
  if(primary){On p(config.roles.primary.ordinal);primary->drain();primary.reset();}if(secondary){On s(config.roles.secondary->ordinal);secondary.reset();}closed=true;
 }
 void entry(){
  try{initialize();{std::lock_guard<std::mutex>lock(mutex);startup=true;}wake.notify_all();
   for(;;){
    {std::lock_guard<std::mutex>lock(mutex);require(!retain_on_stop,"unreturned expert consumer lifetime unknown");}
    bool any=false,finish=false;
    for(size_t i=0;i<jobs.size();++i){Mailbox message;bool request=false;
     {std::lock_guard<std::mutex>lock(mutex);auto&b=boxes[i];if(b.reserve){message=b;b.reserve=false;request=true;}auto&j=*jobs[i];j.input_notice=j.input_notice||b.input_notice;j.return_notice=j.return_notice||b.return_notice;if(b.return_notice)j.returned_stream=b.returned_stream;if(b.cancel)j.cancel_stream=b.cancel_stream;j.cancel=j.cancel||b.cancel||stop;}
     try{if(request)reserve(i,message);advance(i);}catch(const Interrupted&){jobs[i]->cancel=true;retire(i,true);}catch(...){if(jobs[i]->cancel)throw;auto error=std::current_exception();jobs[i]->state=Job::State::Failed;observed.secondary_known=false;std::lock_guard<std::mutex>lock(mutex);published_stats.secondary_known=false;boxes[i].failure=error;boxes[i].state=Published::Failed;wake.notify_all();}
     any=any||jobs[i]->state!=Job::State::Free;
    }
    {On s(config.roles.secondary->ordinal);retire_if_idle();}
    {std::unique_lock<std::mutex>lock(mutex);finish=stop&&!any;if(!finish)wake.wait_for(lock,std::chrono::milliseconds(1));}if(finish)break;
   }
   cleanup();
  }catch(...){auto error=std::current_exception();std::exception_ptr cleanup_error;bool known=false;if(!startup){try{cleanup();known=true;}catch(...){cleanup_error=std::current_exception();/* unknown retains the entire Impl */}}
   std::lock_guard<std::mutex>lock(mutex);fatal=error;startup_failure=startup?nullptr:error;startup_cleanup_failure=cleanup_error;quarantined=!known;published_stats.quarantined=quarantined;published_stats.secondary_known=false;startup=true;}
  wake.notify_all();
 }
 bool failed_job()const{return std::any_of(boxes.begin(),boxes.end(),[](const auto&b){return bool(b.failure);});}
 void failure_check(){fatal_check();for(const auto&b:boxes)if(b.failure)std::rethrow_exception(b.failure);}
 void fatal_check(){if(fatal)std::rethrow_exception(fatal);}
 Mailbox ticket_box(const ExpertTicket&t){std::lock_guard<std::mutex>lock(mutex);fatal_check();require(t.slot<boxes.size()&&key(t,boxes[t.slot].ticket),"stale/foreign expert result ticket");return boxes[t.slot];}
};
ExpertAssist::ExpertAssist(const Artifact&a,ExpertAssistConfig c):p_(std::make_unique<Impl>(a,std::move(c))){
 auto&p=*p_;p.worker=std::thread([&p]{p.entry();});std::unique_lock<std::mutex>lock(p.mutex);p.wake.wait(lock,[&]{return p.startup;});auto error=p.startup_failure;auto cleanup=p.startup_cleanup_failure;lock.unlock();if(error){p.worker.join();auto closed=p.closed;if(!closed||cleanup)p_.release();startup_result(std::move(error),closed,std::move(cleanup));}
}
ExpertAssist::~ExpertAssist(){
 if(!p_)return;bool unreturned=false;
 {std::lock_guard<std::mutex>lock(p_->mutex);for(const auto&b:p_->boxes)unreturned=unreturned||(b.adopted&&!b.return_notice&&!b.cancel&&b.state!=Impl::Published::Free);}
 // An adopted view may have been used on another same-device stream. Without
 // an explicit return/cancel(actual stream), do not invent its final use.
 if(!unreturned){try{On primary(p_->config.roles.primary.ordinal);cancel_and_drain(p_->last_primary_stream);}catch(...){/* worker performs final drain or retains */}}
 {std::lock_guard<std::mutex>lock(p_->mutex);p_->stop=true;p_->retain_on_stop=unreturned;for(auto&box:p_->boxes)box.cancel=true;}
 p_->wake.notify_all();if(p_->worker.joinable())p_->worker.join();
 if(!p_->closed){p_.release();std::terminate();} // unknown: whole bundle stays live, child-fatal
}
size_t ExpertAssist::capacity()const{return p_->config.slots;}
ExpertTicket ExpertAssist::submit(const ExpertFrame&f,uint32_t layer,uint32_t expert,const std::vector<uint32_t>&pairs,const DeviceView&input,const DeviceView&route,void*stream,const LocalExpert&local){
 auto&p=*p_;require(layer<40&&expert<384&&!f.identity.request_id.empty()&&!f.identity.asset_sha256.empty()&&!f.identity.bundle_sha256.empty(),"expert frame identity/layer");
 require(!pairs.empty()&&pairs.size()%2==0&&pairs.size()/2<=p.config.max_batch&&input.rows==pairs.size()/2&&route.rows==input.rows&&input.columns==5120&&route.columns==1&&input.scalar==DeviceScalar::Bfloat16InFloat32&&route.scalar==DeviceScalar::Float32,"expert selected shape");
 validate_device_view(input,p.config.roles.primary.ordinal);validate_device_view(route,p.config.roles.primary.ordinal);check_device_stream(stream,p.config.roles.primary.ordinal);
 // New cross-device boundary validates actual pointers before any reservation
 // or launch, rather than trusting mutable DeviceView device labels.
 checked_device_view(input.data,input.bytes,input.rows,input.columns,input.scalar,p.config.roles.primary.ordinal,*input.owner);checked_device_view(route.data,route.bytes,route.rows,route.columns,route.scalar,p.config.roles.primary.ordinal,*route.owner);
 std::set<uint64_t>positions;for(auto position:f.token_positions)require(positions.insert(position).second,"duplicate original expert token position");
 std::set<uint32_t>tokens;for(size_t i=0;i<pairs.size();i+=2)require(pairs[i]<f.token_positions.size()&&pairs[i+1]<6&&tokens.insert(pairs[i]).second,"expert original token/route pair");
 auto compatible=[&]{for(const auto&b:p.boxes)if((b.state!=Impl::Published::Free||b.reserve)&&!same(b.ticket.identity,f.identity))return false;return true;};
 size_t index=0;ExpertTicket request;request.instance=p.instance;request.layer=layer;request.expert=expert;request.pairs=pairs;request.positions=f.token_positions;request.identity=f.identity;
 {std::unique_lock<std::mutex>lock(p.mutex);p.failure_check();p.wake.wait(lock,[&]{return p.fatal||p.failed_job()||(p.retire_ack==p.retire_requested&&compatible()&&std::any_of(p.boxes.begin(),p.boxes.end(),[](const auto&b){return b.state==Impl::Published::Free&&!b.reserve;}));});p.failure_check();while(p.boxes[index].state!=Impl::Published::Free||p.boxes[index].reserve)++index;auto&b=p.boxes[index];b.ticket=request;b.stream=stream;b.reserve=true;b.failure=nullptr;p.last_primary_stream=stream;}
 p.wake.notify_all();Impl::Mailbox box;
 {std::unique_lock<std::mutex>lock(p.mutex);p.wake.wait(lock,[&]{return p.fatal||p.boxes[index].state!=Impl::Published::Free;});p.fatal_check();box=p.boxes[index];if(box.failure)std::rethrow_exception(box.failure);}
 try{
  checked(hipMemcpyAsync(box.input.data,input.data,input.rows*5120*4,hipMemcpyDeviceToDevice,reinterpret_cast<hipStream_t>(stream)));{std::lock_guard<std::mutex>lock(p_->mutex);p_->snapshot_issued+=input.rows*5120*4;}checked(hipMemcpyAsync(box.route.data,route.data,route.rows*4,hipMemcpyDeviceToDevice,reinterpret_cast<hipStream_t>(stream)));{std::lock_guard<std::mutex>lock(p_->mutex);p_->snapshot_issued+=route.rows*4;}
  if(!p.assignment.count(expert)){require(bool(local),"primary expert helper missing");local(box.result);}
  checked(hipEventRecord(box.input_ready,reinterpret_cast<hipStream_t>(stream)));if(!p.assignment.count(expert))p.event(box.ticket,"primary-local-enqueued");
  {std::lock_guard<std::mutex>lock(p.mutex);require(key(box.ticket,p.boxes[index].ticket),"expert snapshot ticket changed");p.boxes[index].input_notice=true;}p.wake.notify_all();return box.ticket;
 }catch(...){auto error=std::current_exception();cancel_and_drain(stream);std::rethrow_exception(error);}
}
DeviceView ExpertAssist::collect(const ExpertTicket&t){auto&p=*p_;std::unique_lock<std::mutex>lock(p.mutex);p.fatal_check();require(t.slot<p.boxes.size()&&key(t,p.boxes[t.slot].ticket)&&p.boxes[t.slot].state!=Impl::Published::Free,"expert collect key/already retired");p.wake.wait(lock,[&]{return p.fatal||p.boxes[t.slot].state==Impl::Published::Ready||p.boxes[t.slot].state==Impl::Published::Failed||p.boxes[t.slot].state==Impl::Published::Free;});p.fatal_check();auto&b=p.boxes[t.slot];require(b.state!=Impl::Published::Free,"cancelled/retired expert collect");if(b.failure)std::rethrow_exception(b.failure);require(!b.adopted,"duplicate expert adoption");b.adopted=true;return b.result;}
void ExpertAssist::consumed(const ExpertTicket&t,void*stream){auto&p=*p_;check_device_stream(stream,p.config.roles.primary.ordinal);{std::lock_guard<std::mutex>lock(p.mutex);p.fatal_check();require(t.slot<p.boxes.size()&&key(t,p.boxes[t.slot].ticket),"expert return key");auto&b=p.boxes[t.slot];require(b.state==Impl::Published::Ready&&b.adopted&&!b.return_notice,"expert result not adopted/already returned");b.returned_stream=stream;b.return_notice=true;}p.wake.notify_all();std::unique_lock<std::mutex>lock(p.mutex);p.wake.wait(lock,[&]{return p.fatal||p.boxes[t.slot].state==Impl::Published::Free||p.boxes[t.slot].state==Impl::Published::Failed;});p.failure_check();}
void ExpertAssist::cancel_and_drain(void*stream){
 auto&p=*p_;if(stream)check_device_stream(stream,p.config.roles.primary.ordinal);uint64_t requested=0;
 {std::lock_guard<std::mutex>lock(p.mutex);p.fatal_check();
  // Also retire an idle warm graph: cancel/reset must not carry it into Fresh.
  for(const auto&b:p.boxes)if(b.state!=Impl::Published::Free||b.reserve)require(stream,"expert cancel actual consumer stream");
  require(p.retire_requested!=UINT64_MAX,"expert retire generation exhausted");
  requested=++p.retire_requested;
  for(auto&b:p.boxes)if(b.state!=Impl::Published::Free||b.reserve){b.cancel_stream=stream;b.cancel=true;}
 }
 p.wake.notify_all();std::unique_lock<std::mutex>lock(p.mutex);
 p.wake.wait(lock,[&]{return p.fatal||(p.retire_ack>=requested&&std::all_of(p.boxes.begin(),p.boxes.end(),[](const auto&b){return b.state==Impl::Published::Free&&!b.reserve;}));});p.fatal_check();
}
bool ExpertAssist::request_idle()const{
 if(!p_)return false;const auto&p=*p_;std::lock_guard<std::mutex>lock(p.mutex);
 if(p.retire_ack!=p.retire_requested||!p.startup||p.startup_failure||p.startup_cleanup_failure||p.fatal||p.stop||p.closed||p.quarantined||p.retain_on_stop)return false;
 for(const auto&b:p.boxes)if(b.state!=Impl::Published::Free||b.reserve||b.input_notice||b.return_notice||b.cancel||b.adopted||b.failure)return false;
 return true;
}
void ExpertAssist::drain(){auto&p=*p_;std::unique_lock<std::mutex>lock(p.mutex);p.wake.wait(lock,[&]{return p.fatal||p.failed_job()||std::all_of(p.boxes.begin(),p.boxes.end(),[](const auto&b){return b.state==Impl::Published::Free&&!b.reserve;});});p.failure_check();}
ExpertAssistStats ExpertAssist::stats()const{std::lock_guard<std::mutex>lock(p_->mutex);p_->fatal_check();return p_->published_stats;}
}
