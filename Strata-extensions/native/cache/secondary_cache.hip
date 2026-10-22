#include "secondary_cache.hpp"
#include <strata/core/device.hpp>
#include <hip/hip_runtime.h>
#include <algorithm>
#include <atomic>
#include <limits>
#include <thread>
#include <cstdlib>
namespace strata_ext::cache {
namespace {
void need(bool v,const char*m){if(!v)throw std::runtime_error(m);}
void hip(hipError_t e){if(e!=hipSuccess)throw strata::core::CudaError(hipGetErrorString(e),int(e));}
struct On{int prior=-1;explicit On(int d){hip(hipGetDevice(&prior));hip(hipSetDevice(d));}~On(){if(prior>=0)hipSetDevice(prior);}};
uint64_t add(uint64_t a,uint64_t b){need(b<=UINT64_MAX-a,"secondary byte overflow");return a+b;}
uint64_t mul(uint64_t a,uint64_t b){need(!b||a<=UINT64_MAX/b,"secondary capacity overflow");return a*b;}
uint64_t string_heap(const std::string&s){auto data=reinterpret_cast<uintptr_t>(s.data()),object=reinterpret_cast<uintptr_t>(&s);return data>=object&&data-object<sizeof(s)?0:add(s.capacity(),1);}
bool same(const measurement::Identity&a,const measurement::Identity&b){return a.asset_sha256==b.asset_sha256&&a.bundle_sha256==b.bundle_sha256&&a.fixture_sha256==b.fixture_sha256&&a.request_id==b.request_id&&a.epoch==b.epoch&&a.phase==b.phase;}
std::atomic<uint64_t> next_owner{1};
#ifdef STRATA_T22_TEST
bool fail_hit_ready_once=false;
bool unknown_hit_ready_once=false;
#endif
}
#ifdef STRATA_T22_TEST
void test_fail_hit_ready_once(){fail_hit_ready_once=true;}
void test_unknown_hit_ready_once(){unknown_hit_ready_once=true;}
#endif
SecondaryCapacity secondary_capacity(uint64_t target,uint64_t tile){need(tile&&tile<=UINT64_MAX-255,"secondary aligned unit");auto unit=(tile+255)&~uint64_t(255);need(target>=unit,"secondary explicit target below working minimum");auto count=target/unit;need(count<=SIZE_MAX,"secondary slot count");return {size_t(count),unit,count*unit,target-count*unit};}
CacheRecovery cache_recovery(CacheFailure f,int primary_drain,bool retained,bool separate){if(f==CacheFailure::CrossUnknown)return primary_drain==0&&retained&&separate?CacheRecovery::BypassRetained:CacheRecovery::ErrorRetain;if(f==CacheFailure::Allocation||f==CacheFailure::CopyDrained)return primary_drain==0&&separate?CacheRecovery::Bypass:CacheRecovery::ErrorRetain;return CacheRecovery::Error;}
[[noreturn]]void secondary_construction_result(std::exception_ptr initialization,bool cleanup_complete,std::exception_ptr cleanup){if(cleanup_complete&&!cleanup)std::rethrow_exception(initialization);throw SecondaryConstructionUnknown(std::move(initialization),std::move(cleanup));}
struct SecondaryCache::Impl {
 struct Slot{ResidentSlot resident;std::string key;routing::Record route;};
 struct Job{std::unique_ptr<device::CopyTask>copy;int source=-1,destination=-1;void*consumer=nullptr;std::string kind;bool accounted=false;};
 SecondaryConfig config;uint64_t owner=0,unit=0,operation=0;bool closed=false,retained=false,disabled=false;
 std::unique_ptr<strata::core::DeviceArena> p_arena,s_arena;ResidentSlot working;
 std::vector<Slot>slots;std::vector<std::unique_ptr<Job>>jobs;std::vector<uint8_t>pageable;
 void*bounce=nullptr;bool pinned=false;hipStream_t p_stream=nullptr,s_stream=nullptr;
 SecondaryStats count;measurement::Identity current;std::string current_key;size_t selected=0,next_victim=0;
 std::exception_ptr initialization_failure,cleanup_failure;
#ifdef STRATA_T22_TEST
 bool controlled_unknown=false,fallback_disjoint=false;uintptr_t fallback_address=0;uint64_t fallback_capacity=0;
#endif
 explicit Impl(SecondaryConfig c):config(c){need(c.primary>=0&&c.secondary>=0&&c.primary!=c.secondary&&c.slots&&c.tile_bytes,"secondary actual roles/capacity");need(c.policy==device::Policy::Auto||c.policy==device::Policy::HostBounce,"secondary declared copy policy");need(c.tile_bytes<=UINT64_MAX-255,"secondary aligned working unit");unit=(c.tile_bytes+255)&~uint64_t(255);need(c.slots<=SIZE_MAX/sizeof(Slot),"secondary metadata overflow");owner=next_owner.fetch_add(1);need(owner&&owner!=UINT64_MAX,"secondary owner exhausted");slots.resize(c.slots);jobs.reserve(2);count.slots=c.slots;count.slot_capacity=unit;}
 void initialize(){
  {On p(config.primary);p_arena=std::make_unique<strata::core::DeviceArena>(unit,config.primary);auto*a=p_arena->alloc(unit);working={reinterpret_cast<uintptr_t>(a),unit,owner,0,0,false,false,false};hip(hipStreamCreateWithFlags(&p_stream,hipStreamNonBlocking));++count.created_streams;
   if(config.prefer_pinned){auto e=hipHostMalloc(&bounce,size_t(unit),hipHostMallocPortable);if(e==hipSuccess)pinned=true;else{bounce=nullptr;hipGetLastError();}}
   if(!bounce){pageable.resize(size_t(unit));bounce=pageable.data();}
   hipPointerAttribute_t attr{};count.pin_status=int(hipPointerGetAttributes(&attr,bounce));if(!count.pin_status)count.pin_type=int(attr.type);else hipGetLastError();count.pinned_known=count.pin_status==0;count.pinned_observed=count.pinned_known&&attr.type==hipMemoryTypeHost;count.pinned_subset=count.pinned_observed?unit:0;
  }
  {On s(config.secondary);s_arena=std::make_unique<strata::core::DeviceArena>(mul(unit,config.slots),config.secondary);for(auto&slot:slots){auto*a=s_arena->alloc(unit);slot.resident={reinterpret_cast<uintptr_t>(a),unit,owner,0,0,false,false,false};}hip(hipStreamCreateWithFlags(&s_stream,hipStreamNonBlocking));++count.created_streams;}
  count.primary_device_owned=unit;count.secondary_device_owned=mul(unit,config.slots);count.host_owned=pinned?unit:pageable.capacity();
 }
 void emit(const char*name,const device::TransferStats&t={},int source=-1,int dest=-1)const noexcept{if(config.audit)config.audit->event({current,current_key,name,operation,selected,slots[selected].resident.generation,source,dest,t});}
 std::optional<size_t> find(const SupplyMatrix&m)const{auto key=m.key();for(size_t i=0;i<slots.size();++i){auto&s=slots[i];if(s.key==key&&s.resident.valid&&!s.resident.writer&&!s.resident.quarantined)return i;}return std::nullopt;}
 void begin(const SupplyMatrix&m,const measurement::Identity&id){need(!closed&&!retained&&jobs.empty(),"secondary serialized live owner");need(id.epoch&&m.bytes&&m.bytes<=config.tile_bytes&&m.bytes==quant::packed_bytes(m.type,mul(m.rows,m.k)),"secondary original packed extent");need(m.offset<=m.original.source.original_size&&m.bytes<=m.original.source.original_size-m.offset,"secondary original source range");need(operation<UINT64_MAX,"secondary operation exhausted");++operation;current=id;current_key=m.key();}
 static device::Endpoint endpoint(ResidentSlot&slot,int device,hipStream_t stream,uint64_t bytes){return {reinterpret_cast<void*>(slot.address),bytes,device,stream,&slot,slot.owner,slot.generation};}
 Job& copy(ResidentSlot&source,int sd,hipStream_t ss,ResidentSlot&dest,int dd,hipStream_t ds,uint64_t bytes,const char*kind){
  auto job=std::make_unique<Job>();job->source=sd;job->destination=dd;job->consumer=ds;job->kind=kind;jobs.push_back(std::move(job));auto&j=*jobs.back();
  On on(dd);j.copy=std::make_unique<device::CopyTask>(endpoint(source,sd,ss,bytes),endpoint(dest,dd,ds,bytes),bounce,unit,config.policy);count.created_events+=2;j.copy->submit(bytes);
  while(j.copy->phase()!=device::Phase::Ready){j.copy->poll();need(j.copy->phase()!=device::Phase::Quarantined&&j.copy->phase()!=device::Phase::Done,"secondary copy publication failed");std::this_thread::yield();}
  emit(kind,j.copy->stats(),sd,dd);
#ifdef STRATA_T22_TEST
  if(fail_hit_ready_once&&std::string(kind)=="hit_ready"){fail_hit_ready_once=false;throw std::runtime_error("T22 test actual Ready copy interruption");}
  if(unknown_hit_ready_once&&std::string(kind)=="hit_ready"){unknown_hit_ready_once=false;controlled_unknown=true;throw std::runtime_error("T22 test Ready completion certificate unavailable");}
#endif
  return j;
 }
 void account(Job&j){if(j.accounted||!j.copy)return;auto s=j.copy->stats();count.snapshot_d2d=add(count.snapshot_d2d,s.local_d2d);if(j.kind=="fill_ready")count.fill_bytes=add(count.fill_bytes,s.bytes);else if(j.kind=="hit_ready")count.hit_bytes=add(count.hit_bytes,s.bytes);count.peer_bytes=add(count.peer_bytes,s.peer_bytes);count.bounce_d2h=add(count.bounce_d2h,s.bounce_d2h);count.bounce_h2d=add(count.bounce_h2d,s.bounce_h2d);j.accounted=true;}
 void finish(bool cancel){
  for(auto it=jobs.rbegin();it!=jobs.rend();++it){auto&j=**it;if(!j.copy)continue;On on(j.destination);auto&t=*j.copy;if(cancel)t.cancel();while(t.phase()!=device::Phase::Done){if(t.phase()==device::Phase::Ready)t.consumer_done_on(reinterpret_cast<hipStream_t>(j.consumer));else t.poll();need(t.phase()!=device::Phase::Quarantined,"secondary copy completion unknown");std::this_thread::yield();}account(j);emit("retired",t.stats(),j.source,j.destination);need(t.try_close(),"secondary copy close");j.copy.reset();}jobs.clear();
 }
 bool primary_safe(){On p(config.primary);count.primary_drain_status=int(hipStreamSynchronize(p_stream));return count.primary_drain_status==0;}
 bool fail_copy(const std::exception_ptr&original,bool primary_operation){
  // Local snapshots/kernel errors are primary operations, never secondary misses.
  if(primary_operation){try{finish(true);}catch(...){retain("primary copy completion unknown");}std::rethrow_exception(original);}
  bool safe=false;try{safe=primary_safe();}catch(...){retain("secondary failure primary context unknown");std::rethrow_exception(original);}
  try{On s(config.secondary);count.secondary_drain_status=int(hipStreamSynchronize(s_stream));}catch(...){count.secondary_drain_status=-1;}
  bool quarantine=false;for(auto&j:jobs)quarantine|=j->copy&&j->copy->phase()==device::Phase::Quarantined;
#ifdef STRATA_T22_TEST
  quarantine|=controlled_unknown;
#endif
  if(quarantine||count.secondary_drain_status!=0){retain("secondary cross-copy completion unknown");if(cache_recovery(CacheFailure::CrossUnknown,safe?0:-1,retained,true)!=CacheRecovery::BypassRetained)std::rethrow_exception(original);emit("bypass_retained");return true;}
  try{finish(true);}catch(...){retain("secondary return completion unknown");if(cache_recovery(CacheFailure::CrossUnknown,safe?0:-1,retained,true)!=CacheRecovery::BypassRetained)std::rethrow_exception(original);return true;}
  if(cache_recovery(CacheFailure::CopyDrained,safe?0:-1,false,true)!=CacheRecovery::Bypass)std::rethrow_exception(original);++count.bypasses;count.bypass_reason="copy failed; actual drained safe primary fallback";emit("bypass");return true;
 }
 void retain(const char*reason){retained=disabled=true;count.available=false;count.bypass_reason=reason;count.retained_device_bytes=add(count.primary_device_owned,count.secondary_device_owned);count.retained_host_bytes=count.host_owned;++count.bypasses;emit("quarantined");}
 bool close(){if(closed)return true;if(retained)return false;if(!jobs.empty())finish(true);
  if(p_stream){On p(config.primary);if(hipStreamSynchronize(p_stream)!=hipSuccess)return false;}
  if(s_stream){On s(config.secondary);if(hipStreamSynchronize(s_stream)!=hipSuccess)return false;}
  if(s_stream||s_arena){On s(config.secondary);if(s_stream){hip(hipStreamDestroy(s_stream));s_stream=nullptr;}s_arena.reset();}
  if(p_stream||p_arena||pinned){On p(config.primary);if(p_stream){hip(hipStreamDestroy(p_stream));p_stream=nullptr;}if(pinned&&bounce){hip(hipHostFree(bounce));bounce=nullptr;pinned=false;}p_arena.reset();}
  pageable.clear();closed=true;return true;
 }
};
SecondaryCache::SecondaryCache(SecondaryConfig c):p_(std::make_unique<Impl>(c)){try{p_->initialize();}catch(...){auto error=std::current_exception();p_->initialization_failure=error;bool complete=false;std::exception_ptr cleanup;try{complete=p_->close();}catch(...){cleanup=std::current_exception();p_->cleanup_failure=cleanup;}if(!complete||cleanup)p_.release();secondary_construction_result(std::move(error),complete,std::move(cleanup));}}
SecondaryCache::~SecondaryCache(){if(!p_)return;try{if(!p_->close()){p_.release();std::terminate();}}catch(...){p_.release();std::terminate();}}
routing::Snapshot SecondaryCache::routing_snapshot()const{
 routing::Snapshot out;if(!p_){out.complete=false;return out;}auto&p=*p_;out.owner=p.owner;out.generation=p.operation;
 out.complete=!p.closed&&!p.disabled&&!p.retained&&p.jobs.empty();for(auto&s:p.slots){if(s.resident.writer||s.resident.quarantined)out.complete=false;if(s.resident.valid&&!s.resident.writer&&!s.resident.quarantined&&!s.key.empty()&&s.route.relevant){if(!s.route.known||s.route.generation!=s.resident.generation)out.complete=false;else out.spans.push_back(routing_span(s.route,routing::Tier::Secondary));}}return out;
}
bool SecondaryCache::contains(const SupplyMatrix&m)const{if(!p_||p_->closed||p_->disabled)return false;auto hit=bool(p_->find(m));if(!hit)++p_->count.misses;return hit;}
void SecondaryCache::populate(PrimarySupply&primary,const SupplyMatrix&m,const measurement::Identity&id){auto&p=*p_;if(p.disabled||p.closed){
#ifdef STRATA_T22_TEST
 if(p.controlled_unknown&&p.retained){auto d=primary.ready_packed_descriptor();auto a=reinterpret_cast<uintptr_t>(d.data),b=p.working.address;p.fallback_disjoint=d.device==p.config.primary&&(a<=b?b-a>=d.capacity:a-b>=p.working.capacity);need(p.fallback_disjoint,"actual fallback overlaps retained working allocation");p.fallback_address=a;p.fallback_capacity=d.capacity;p.emit("fallback_primary_ready");}
#endif
 ++p.count.bypasses;return;}auto d=primary.ready_packed_descriptor();need(d.device==p.config.primary&&same(d.identity,id)&&d.matrix.key()==m.key()&&d.bytes==m.bytes&&d.data&&d.resident&&d.resident->address==reinterpret_cast<uintptr_t>(d.data)&&d.slot_generation==d.resident->generation&&d.owner==d.resident->owner,"secondary actual Ready source binding");if(p.find(m))return;auto routing_meta=routing_record(m);p.begin(m,id);
  std::optional<size_t>selected;for(size_t i=0;i<p.slots.size();++i){auto&s=p.slots[i].resident;if(s.valid||s.writer||s.readers||s.quarantined)continue;selected=i;break;}
  if(!selected){size_t i=p.next_victim;for(size_t visited=0;visited<p.slots.size();++visited){auto&s=p.slots[i].resident;if(s.valid&&!s.writer&&!s.readers&&!s.quarantined){selected=i;break;}i=i==p.slots.size()-1?0:i+1;}}
  if(!selected){++p.count.bypasses;return;}p.selected=*selected;auto&target=p.slots[*selected];bool evicted=target.resident.valid;target.key.clear();bool primary_stage=true;
  try{p.copy(*d.resident,p.config.primary,reinterpret_cast<hipStream_t>(d.stream),p.working,p.config.primary,p.p_stream,m.bytes,"snapshot_ready");primary_stage=false;p.copy(p.working,p.config.primary,p.p_stream,target.resident,p.config.secondary,p.s_stream,m.bytes,"fill_ready");p.finish(false);target.key=p.current_key;target.route=routing_meta;target.route.generation=target.resident.generation;++p.count.fills;if(evicted)++p.count.evictions;p.next_victim=*selected==p.slots.size()-1?0:*selected+1;p.emit("published");}
 catch(...){auto e=std::current_exception();p.fail_copy(e,primary_stage);}
}
bool SecondaryCache::project_hit(const SupplyMatrix&m,const measurement::Identity&id,const float*input,uint64_t input_bytes,float*output,uint64_t output_bytes,size_t batch,size_t stride,void*stream,const quant::ProjectionLease&activation){auto&p=*p_;if(p.disabled||p.closed){++p.count.bypasses;return false;}auto found=p.find(m);if(!found){++p.count.misses;return false;}p.begin(m,id);p.selected=*found;bool kernel=false;
 try{p.copy(p.slots[*found].resident,p.config.secondary,p.s_stream,p.working,p.config.primary,p.p_stream,m.bytes,"hit_ready");kernel=true;On on(p.config.primary);int actual=-1;hip(hipStreamGetDevice(reinterpret_cast<hipStream_t>(stream),&actual));need(actual==p.config.primary&&activation.active,"secondary primary activation/consumer stream");p.jobs.back()->consumer=stream;quant::ProjectionLease packed{p.working.generation,true};auto view=quant::checked_projection_strided({reinterpret_cast<const uint8_t*>(p.working.address),m.type,m.rows,m.k,size_t(m.bytes),p.config.primary},input,size_t(input_bytes),output,size_t(output_bytes),stride,stream,packed);quant::project_into(view,batch);p.emit("kernel_submitted");p.finish(false);packed.active=false;++p.count.hits;return true;}
 catch(...){auto e=std::current_exception();p.fail_copy(e,kernel);return false;}
}
bool SecondaryCache::evict(size_t i){auto&p=*p_;if(p.retained||p.disabled)return false;need(!p.closed&&i<p.slots.size(),"secondary eviction index");auto&s=p.slots[i];auto lease=reserve_fill(s.resident,p.owner,1);if(!lease)return false;complete_resident(*lease,p.owner,true,false);s.key.clear();++p.count.evictions;return true;}
void SecondaryCache::cancel_and_drain(){auto&p=*p_;if(p.closed)return;if(p.retained){need(p.primary_safe(),"retained cache primary context unknown");return;}p.finish(true);}
bool SecondaryCache::try_close(){return p_&&p_->close();}
uint64_t SecondaryCache::slot_metadata_bytes(){return sizeof(Impl::Slot);}
#ifdef STRATA_T22_TEST
SecondaryTestState SecondaryCache::test_state()const{const auto&p=*p_;return {p.working.address,p.fallback_address,p.working.capacity,p.fallback_capacity,p.working.readers,p.jobs.size(),p.retained,p.disabled,p.fallback_disjoint};}
void SecondaryCache::test_late_complete(){auto&p=*p_;need(p.controlled_unknown&&p.retained&&p.disabled,"controlled retained owner required");p.finish(true);need(p.primary_safe(),"controlled late primary drain");{On s(p.config.secondary);hip(hipStreamSynchronize(p.s_stream));}p.emit("controlled_late_retired");}
void SecondaryCache::test_cleanup_proven_idle(){auto&p=*p_;need(p.controlled_unknown&&p.retained&&p.disabled&&p.jobs.empty(),"controlled late completion required");need(p.primary_safe(),"controlled final primary drain");{On s(p.config.secondary);hip(hipStreamSynchronize(p.s_stream));}p.retained=false;need(p.close(),"controlled proven-idle cleanup");}
#endif
SecondaryStats SecondaryCache::stats()const{auto&p=*p_;auto c=p.count;c.valid_slots=0;c.metadata=add(add(sizeof(SecondaryCache),sizeof(Impl)),add(mul(p.slots.capacity(),sizeof(Impl::Slot)),mul(p.jobs.capacity(),sizeof(std::unique_ptr<Impl::Job>))));if(p.p_arena)c.metadata=add(c.metadata,sizeof(strata::core::DeviceArena));if(p.s_arena)c.metadata=add(c.metadata,sizeof(strata::core::DeviceArena));for(auto&s:p.slots){c.valid_slots+=s.resident.valid&&!s.resident.quarantined;c.metadata=add(c.metadata,string_heap(s.key));}for(const auto*text:{&p.current_key,&p.current.fixture_sha256,&p.current.asset_sha256,&p.current.bundle_sha256,&p.current.request_id,&p.count.bypass_reason})c.metadata=add(c.metadata,string_heap(*text));for(const auto&job:p.jobs){c.metadata=add(c.metadata,add(sizeof(Impl::Job),string_heap(job->kind)));if(job->copy)c.metadata=add(c.metadata,device::CopyTask::metadata_bytes());}return c;}
}
