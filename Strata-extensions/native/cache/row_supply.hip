#include "row_supply.hpp"
#include "../io/span_provider.hpp"
#include "../../models/deepseek41/engram.hpp"
#include <strata/core/device.hpp>
#include <strata/core/pinned_ring.hpp>
#include <hip/hip_runtime.h>
#include <algorithm>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <iostream>
#include <cstdlib>
namespace strata_ext::cache {
namespace {
// Test checkpoints are absent from the ordinary binary. No normal fault ENV.
void construction_trace(const char*action,const char*kind,const void*p){
#ifdef STRATA_T28_CONSTRUCTION_TEST
 std::cerr<<"T28_CTOR row "<<action<<' '<<kind<<' '<<reinterpret_cast<uintptr_t>(p)<<'\n';
#else
 (void)action;(void)kind;(void)p;
#endif
}
void construction_fault(const char*stage){
#ifdef STRATA_T28_CONSTRUCTION_TEST
 const char*point=std::getenv("STRATA_T28_CTOR_FAULT");if(point&&std::string(point)==std::string("row:")+stage)throw std::runtime_error("injected construction checkpoint");
#else
 (void)stage;
#endif
}
bool construction_drain_permitted(hipError_t status){return status==hipSuccess;}
struct ConstructionBufferFree {void operator()(void*p)const{if(p){construction_trace("free","unregistered-io",p);_aligned_free(p);}}};
void need(bool b,const char* text){if(!b)throw std::runtime_error(text);}
void hip(hipError_t e){if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));}
bool same(const measurement::Identity&a,const measurement::Identity&b){return a.request_id==b.request_id&&a.epoch==b.epoch&&a.phase==b.phase&&a.fixture_sha256==b.fixture_sha256&&a.asset_sha256==b.asset_sha256&&a.bundle_sha256==b.bundle_sha256;}
bool source_same(const deepseek41::Slice&a,const deepseek41::Slice&b){return a.absolute_offset==b.absolute_offset&&a.bytes==b.bytes&&a.original.source.shard_index==b.original.source.shard_index&&a.original.source.revision==b.original.source.revision&&a.original.source.lfs_sha256==b.original.source.lfs_sha256&&a.original.source.original_size==b.original.source.original_size&&a.original.source.original_path==b.original.source.original_path&&a.original.span.name==b.original.span.name&&a.original.span.type_id==b.original.span.type_id&&a.original.span.dims_ggml==b.original.span.dims_ggml&&a.original.span.row_bytes==b.original.span.row_bytes;}
uint64_t plus(uint64_t a,uint64_t b){need(b<=UINT64_MAX-a,"row capacity overflow");return a+b;}
}
#ifdef STRATA_T28_CONSTRUCTION_TEST
bool t28_row_drain_decision(int status){return construction_drain_permitted(static_cast<hipError_t>(status));}
#endif
struct RowSupply::Impl {
 struct Slot { ResidentSlot lease;uint64_t key=UINT64_MAX;hipEvent_t filled=nullptr; };
 struct Ram { std::array<uint8_t,264> data{};uint64_t key=UINT64_MAX;bool valid=false,busy=false; };
 struct Request { bool live=false,cancelled=false,from_fill=false,borrowed=false,return_pending=false;uint64_t generation=0;measurement::Identity identity;std::vector<RowLookup> lookups;std::vector<uint64_t> keys;size_t cursor=0,slot=0;RowState state=RowState::Queued;ResidentLease reader;RowResult result; };
 struct Fill {
  bool dma=false,cancelled=false,quarantined=false;size_t slot=0,ram=0;uint64_t key=0;
  // This node owns every reference borrowed by SpanProvider, independently of
  // any waiter's lifetime, including the operational Identity of first caller.
  deepseek41::Slice slice;measurement::Identity identity;std::vector<artifact::FixtureView> views;std::vector<io::Span> spans;
  std::vector<Token> waiters;ResidentLease writer;std::unique_ptr<io::SpanProvider> provider;std::optional<io::Ticket> ticket;
 };
 RowConfig config;const deepseek41::Artifact& artifact;std::vector<RowBinding> bindings;RowSourceViews full_sources;
 std::vector<Slot> slots;std::vector<Ram> ram;std::vector<Request> requests;
 std::unique_ptr<Fill> fill;std::unique_ptr<strata::core::DeviceArena> arena;
 strata::core::PinnedRing ring;std::vector<io::Buffer> buffers;
 hipStream_t producer=nullptr,consumer=nullptr;hipEvent_t consumed=nullptr,returned=nullptr;
 uint32_t* index=nullptr;float* fp32=nullptr;uint16_t* bf16=nullptr;int* error=nullptr;
 std::array<float,256> host_fp{};std::array<uint16_t,256> host_bf{};
 RowStats counters;size_t clock=0,ram_clock=0;std::optional<size_t> active;bool closed=false,ring_ready=false,quarantined=false;
 const uint64_t owner=reinterpret_cast<uintptr_t>(this);
 uint64_t metadata()const;
 uint64_t payload()const{uint64_t n=counters.host_payload;for(auto& r:requests)n+=r.result.fp32.capacity()*4+r.result.bf16.capacity()*2;return n;}
 void observe(){counters.observed_metadata_peak=std::max(counters.observed_metadata_peak,metadata());counters.observed_host_payload_peak=std::max(counters.observed_host_payload_peak,payload());}
 Impl(RowConfig c,const deepseek41::Artifact&a,std::vector<RowBinding> b,RowSourceViews sources=RowSourceViews(std::vector<RowSourceView>{})):config(c),artifact(a),bindings(std::move(b)),full_sources(std::move(sources)){}
 void initialize(){auto c=config;auto&a=artifact;auto&b=bindings;
  need(c.device_slots&&c.ram_slots&&c.request_slots&&c.wave_requests&&c.device_slots<=UINT32_MAX&&c.request_slots<=UINT32_MAX&&c.wave_requests<=SIZE_MAX/256&&c.device_slots<=UINT64_MAX/264,"row actual capacities");
  for(const auto& x:bindings)need(x.logical.bytes==264&&x.logical.original.span.type_id==43&&x.physical.source_absolute_offset<=x.logical.absolute_offset&&x.logical.absolute_offset-x.physical.source_absolute_offset<=x.physical.bytes&&264<=x.physical.bytes-(x.logical.absolute_offset-x.physical.source_absolute_offset),"row physical/source binding");
  std::vector<uint32_t> source_ids;
  for(const auto&v:full_sources.files){
   const auto&f=v.source;need(std::find(source_ids.begin(),source_ids.end(),f.shard_index)==source_ids.end(),"duplicate full row source");source_ids.push_back(f.shard_index);
   need(!f.original_path.empty()&&f.original_size&&f.revision.size()==40&&f.lfs_sha256.size()==64&&v.full_file.path==f.original_path&&v.full_file.source_absolute_offset==0&&v.full_file.bytes==f.original_size,"row full source declaration");
   std::error_code ec;auto bytes=std::filesystem::file_size(f.original_path,ec);need(!ec&&bytes==f.original_size,"row full source actual size");
  }
  hip(hipSetDevice(c.device));uint64_t bank=(c.device_slots*264+255)&~uint64_t(255);
  arena=std::make_unique<strata::core::DeviceArena>(plus(bank,2048),c.device);auto raw=static_cast<uint8_t*>(arena->alloc(c.device_slots*264));
  slots.resize(c.device_slots);for(size_t i=0;i<slots.size();++i)slots[i].lease={reinterpret_cast<uintptr_t>(raw+i*264),264,owner};
  index=static_cast<uint32_t*>(arena->alloc(4));fp32=static_cast<float*>(arena->alloc(1024));bf16=static_cast<uint16_t*>(arena->alloc(512));error=static_cast<int*>(arena->alloc(4));
  ram.resize(c.ram_slots);requests.resize(c.request_slots);
  buffers.reserve(2);
  for(unsigned i=0;i<2;++i){std::unique_ptr<void,ConstructionBufferFree> p(_aligned_malloc(4096,4096));need(p!=nullptr,"row IO allocation");construction_trace("create","io",p.get());construction_fault("io-unregistered");buffers.push_back({p.get(),4096});p.release();construction_fault("io-registered");}
  hip(hipStreamCreateWithFlags(&producer,hipStreamNonBlocking));construction_trace("create","stream",producer);construction_fault("stream");hip(hipStreamCreateWithFlags(&consumer,hipStreamNonBlocking));construction_trace("create","stream",consumer);
  for(auto& x:slots){hip(hipEventCreateWithFlags(&x.filled,hipEventDisableTiming));construction_trace("create","event",x.filled);construction_fault("event");}hip(hipEventCreateWithFlags(&consumed,hipEventDisableTiming));construction_trace("create","event",consumed);hip(hipEventCreateWithFlags(&returned,hipEventDisableTiming));construction_trace("create","event",returned);
  ring.reserve(264);bool pinned=true;
  for(unsigned i=0;i<4;++i){void* p=ring.acquire(264);int64_t status=-1,type=-1,capacity=0,address=0;
   if(p){capacity=65536;address=int64_t(reinterpret_cast<uintptr_t>(p));hipPointerAttribute_t attr{};auto e=hipPointerGetAttributes(&attr,p);status=int(e);if(e==hipSuccess){type=int(attr.type);if(attr.type==hipMemoryTypeHost)counters.pinned_subset+=capacity;}else{hipGetLastError();counters.pinned_known=false;}pinned&=e==hipSuccess&&attr.type==hipMemoryTypeHost;hip(ring.submit(raw,p,0,producer));construction_fault("ring-submit");}
   else pinned=false;
   counters.stages.push_back({address,capacity,status,type});counters.stage_owned+=capacity;
  }
  hip(hipStreamSynchronize(producer));ring_ready=counters.pinned_observed=pinned;
  // Checked once at owner creation; launches additionally check current device
  // and active slot generation. Every buffer and both streams are owner-local.
  for(auto p:{static_cast<void*>(raw),static_cast<void*>(index),static_cast<void*>(fp32),static_cast<void*>(bf16),static_cast<void*>(error)}){hipPointerAttribute_t attr{};hip(hipPointerGetAttributes(&attr,p));need(attr.type==hipMemoryTypeDevice&&attr.device==c.device,"row checked device pointer");}
  for(auto s:{producer,consumer}){int d=-1;hip(hipStreamGetDevice(s,&d));need(d==c.device,"row checked stream device");}
  counters.device_owned=arena->capacity();counters.host_payload=c.ram_slots*264+8192+counters.stage_owned+sizeof(host_fp)+sizeof(host_bf);observe();
 }
 void current()const{int d=-1;hip(hipGetDevice(&d));need(d==config.device,"row current device mismatch");}
 bool valid(Token t)const{return t.owner==owner&&t.index<requests.size()&&requests[t.index].live&&requests[t.index].generation==t.generation;}
 Request& checked(Token t){need(valid(t),"stale row request");return requests[t.index];}
 uint64_t key(const RowLookup& x)const{
  auto s=artifact.engram_row(x.layer,x.head,x.row);need(s.bytes==264&&s.original.span.type_id==43&&s.original.span.row_bytes==264&&s.dims_ggml==std::vector<uint64_t>{256},"native row layout");return s.absolute_offset;
 }
 RowBinding binding(const RowLookup& x)const{auto s=artifact.engram_row(x.layer,x.head,x.row);for(const auto& b:bindings)if(source_same(s,b.logical))return b;
  for(const auto&v:full_sources.files)if(v.source.shard_index==s.original.source.shard_index){const auto&f=s.original.source;
   need(v.source.original_path==f.original_path&&v.source.original_size==f.original_size&&v.source.revision==f.revision&&v.source.lfs_sha256==f.lfs_sha256,"lazy row source identity");
   need(s.bytes==264&&s.original.span.type_id==43&&s.original.span.row_bytes==264&&s.absolute_offset>=s.original.span.absolute_offset&&s.absolute_offset-s.original.span.absolute_offset<=s.original.span.bytes&&s.bytes<=s.original.span.bytes-(s.absolute_offset-s.original.span.absolute_offset)&&s.absolute_offset<=v.full_file.bytes&&s.bytes<=v.full_file.bytes-s.absolute_offset,"lazy row original span");return {s,v.full_file};}
  throw std::runtime_error("row source view missing");}
 std::optional<size_t> hit(uint64_t k)const{for(size_t i=0;i<slots.size();++i)if(slots[i].key==k&&slots[i].lease.valid&&!slots[i].lease.quarantined)return i;return {};}
 bool event(hipEvent_t e){auto status=hipEventQuery(e);if(status==hipErrorNotReady)return false;hip(status);return true;}
 void join(Token t){if(!fill||fill->cancelled||fill->quarantined)return;auto& r=checked(t);if(r.cursor<r.keys.size()&&r.keys[r.cursor]==fill->key&&!r.cancelled){for(auto old:fill->waiters)if(old.index==t.index&&old.generation==t.generation)return;fill->waiters.push_back(t);r.from_fill=true;++counters.dedup;observe();}}
 size_t living_waiters()const{size_t n=0;for(auto t:fill->waiters)if(valid(t)&&!requests[t.index].cancelled)++n;return n;}
 void finish_fill(){observe();auto& f=*fill;bool publish=!f.cancelled&&living_waiters();complete_resident(f.writer,owner,true,publish);if(publish)slots[f.slot].key=f.key;ram[f.ram].busy=false;fill.reset();}
 void upload(){auto& f=*fill;auto& r=ram[f.ram];void* stage=ring_ready?ring.acquire(264):nullptr;
  try{if(stage){std::memcpy(stage,r.data.data(),264);hip(ring.submit(reinterpret_cast<void*>(slots[f.slot].lease.address),stage,264,producer));}else hip(strata::core::PinnedRing::direct(reinterpret_cast<void*>(slots[f.slot].lease.address),r.data.data(),264,producer));
   r.busy=false;counters.weight_h2d+=264;hip(hipEventRecord(slots[f.slot].filled,producer));f.dma=true;observe();
  }catch(...){if(hipStreamSynchronize(producer)==hipSuccess){f.cancelled=true;finish_fill();}else{f.quarantined=true;quarantine_resident(f.writer,owner);}throw;}
 }
 void start_fill(){if(fill)return;
  for(size_t q=0;q<requests.size();++q){auto& r=requests[q];if(!r.live||r.cancelled||r.state!=RowState::Queued||r.cursor>=r.keys.size()||hit(r.keys[r.cursor]))continue;
   auto node=std::make_unique<Fill>();node->key=r.keys[r.cursor];node->identity=r.identity;auto bound=binding(r.lookups[r.cursor]);node->slice=bound.logical;node->views={bound.physical};node->spans={{0,bound.logical.absolute_offset,264,0}};
   bool selected=false;for(unsigned pass=0;pass<2&&!selected;++pass)for(size_t step=0;step<slots.size();++step){size_t i=(clock+step)%slots.size();if(slots[i].lease.valid!=(pass==1))continue;auto w=reserve_fill(slots[i].lease,owner,264);if(w){node->slot=i;node->writer=std::move(*w);clock=(i+1)%slots.size();selected=true;break;}}
   if(!selected)return;
   fill=std::move(node);fill->waiters.push_back({uint32_t(q),r.generation,owner});r.from_fill=true;
   for(size_t i=0;i<ram.size();++i)if(ram[i].valid&&!ram[i].busy&&ram[i].key==fill->key){fill->ram=i;ram[i].busy=true;++counters.ram_hits;upload();return;}
   bool found=false;for(unsigned pass=0;pass<2&&!found;++pass)for(size_t step=0;step<ram.size();++step){auto i=(ram_clock+step)%ram.size();if(!ram[i].busy&&ram[i].valid==(pass==1)){fill->ram=i;ram_clock=(i+1)%ram.size();found=true;break;}}
   need(found,"bounded RAM row reservation");auto& target=ram[fill->ram];target.busy=true;target.valid=false;
   try{io::Config c;c.max_outstanding=1;c.max_chunk=4096;c.max_outstanding_bytes=4096;c.request_slots=1;fill->provider=std::make_unique<io::SpanProvider>(fill->views,buffers,c);fill->ticket=fill->provider->enqueue(fill->spans,{target.data.data(),264},fill->identity);need(bool(fill->ticket),"row read admission");++counters.ssd_misses;observe();}
   catch(...){if(fill->provider){need(fill->provider->try_close(),"unissued row provider close");fill->provider.reset();}fill->cancelled=true;finish_fill();r.cancelled=true;r.state=RowState::Cancelled;throw;}
   for(size_t i=0;i<requests.size();++i)if(requests[i].live&&i!=q)join({uint32_t(i),requests[i].generation,owner});return;
  }
 }
 void prepare_consumer(){if(active)return;for(size_t i=0;i<requests.size();++i){auto& r=requests[i];if(!r.live||r.cancelled||r.state!=RowState::Queued)continue;auto found=hit(r.keys[r.cursor]);if(!found)continue;auto held=borrow_resident(slots[*found].lease,owner);need(bool(held),"Ready row resident lease");r.reader=std::move(*held);r.slot=*found;r.state=RowState::Ready;active=i;if(!r.from_fill)++counters.gpu_hits;return;}}
 void consumer_failure(Request& r){r.cancelled=true;if(hipStreamSynchronize(consumer)==hipSuccess){if(r.reader.active)complete_resident(r.reader,owner,true,false);r.state=RowState::Cancelled;active.reset();}else{if(r.reader.active)quarantine_resident(r.reader,owner);quarantined=true;}}
 bool close(){if(closed)return true;current();if(quarantined||fill||active)return false;for(const auto& r:requests)if(r.live)return false;for(auto& s:slots)if(s.lease.writer||s.lease.readers||s.lease.quarantined)return false;
  ring.release();for(auto& s:slots)hip(hipEventDestroy(s.filled));hip(hipEventDestroy(consumed));hip(hipEventDestroy(returned));hip(hipStreamDestroy(producer));hip(hipStreamDestroy(consumer));for(auto b:buffers)_aligned_free(b.data);buffers.clear();arena.reset();closed=true;return true;
 }
 bool construction_cleanup()noexcept{
  // initialize can have recorded zero-byte stage events. Prove all existing
  // streams idle before releasing ANY registered storage/ring or HIP handle.
  for(auto stream_handle:{producer,consumer})if(stream_handle){auto status=hipStreamSynchronize(stream_handle);construction_trace(status==hipSuccess?"drain":"unknown","stream",stream_handle);if(!construction_drain_permitted(status))return false;}
  ring.release();construction_trace("release","ring",this);
  for(auto& slot:slots)if(slot.filled){auto handle=slot.filled;if(hipEventDestroy(handle)!=hipSuccess)return false;slot.filled=nullptr;construction_trace("free","event",handle);}
  for(auto e:{&consumed,&returned})if(*e){auto handle=*e;if(hipEventDestroy(handle)!=hipSuccess)return false;*e=nullptr;construction_trace("free","event",handle);}
  for(auto stream_pointer:{&producer,&consumer})if(*stream_pointer){auto handle=*stream_pointer;if(hipStreamDestroy(handle)!=hipSuccess)return false;*stream_pointer=nullptr;construction_trace("free","stream",handle);}
  for(auto b:buffers){construction_trace("free","io",b.data);_aligned_free(b.data);}buffers.clear();arena.reset();closed=true;return true;
 }
 ~Impl(){if(!closed)std::terminate();}
};
RowSupply::RowSupply(RowConfig c,const deepseek41::Artifact&a,std::vector<RowBinding>b):p_(std::make_unique<Impl>(c,a,std::move(b))){
 try{p_->initialize();}catch(...){if(!p_->construction_cleanup()){(void)p_.release();throw std::runtime_error("Row owner construction completion unknown; child restart required");}throw;}
}
RowSupply::RowSupply(RowConfig c,const deepseek41::Artifact&a,RowSourceViews views):p_(std::make_unique<Impl>(c,a,std::vector<RowBinding>{},std::move(views))){
 try{p_->initialize();}catch(...){if(!p_->construction_cleanup()){(void)p_.release();throw std::runtime_error("Row owner construction completion unknown; child restart required");}throw;}
}
RowSupply::~RowSupply(){if(p_&&!p_->closed&&!try_close())std::terminate();}
std::optional<Token> RowSupply::enqueue(const std::vector<RowLookup>& rows,const measurement::Identity&id){auto& p=*p_;need(!p.closed&&!p.quarantined,"closed/quarantined row owner");p.current();need(!rows.empty()&&rows.size()<=p.config.wave_requests,"finite caller row window");for(const auto* value:{&id.fixture_sha256,&id.asset_sha256,&id.bundle_sha256})need(value->size()==64&&value->find_first_not_of("0123456789abcdef")==std::string::npos,"caller identity hash");need(!id.request_id.empty(),"caller request identity");std::vector<uint64_t> keys;keys.reserve(rows.size());for(auto x:rows){keys.push_back(p.key(x));p.binding(x);}for(size_t i=0;i<p.requests.size();++i){auto& r=p.requests[i];if(r.live)continue;need(r.generation!=UINT64_MAX,"row request generation exhausted");++r.generation;r.live=true;r.cancelled=false;r.from_fill=false;r.borrowed=false;r.return_pending=false;r.identity=id;r.lookups=rows;r.keys=std::move(keys);r.cursor=0;r.state=RowState::Queued;r.result={};r.result.fp32.reserve(rows.size()*256);r.result.bf16.reserve(rows.size()*256);Token t{uint32_t(i),r.generation,p.owner};p.join(t);p.prepare_consumer();p.observe();return t;}return {};}
uint64_t RowSupply::issue_reads(uint32_t operations,uint64_t bytes){auto& p=*p_;p.current();if(!operations||bytes<4096)return 0;p.start_fill();if(!p.fill||p.fill->dma||p.fill->cancelled)return 0;auto& f=*p.fill;auto before=f.provider->stats().read_requested;f.provider->issue();auto delta=f.provider->stats().read_requested-before;need(delta<=4096&&delta<=bytes,"read grant exceeded");if(delta){++p.counters.issued;p.counters.issued_requested+=delta;}return delta;}
void RowSupply::poll_io(int timeout){auto& p=*p_;p.current();if(!p.fill||p.fill->dma||p.fill->quarantined)return;auto& f=*p.fill;f.provider->poll(timeout);if(!f.provider->done(*f.ticket))return;auto result=f.provider->take(*f.ticket,f.identity);auto s=f.provider->stats();p.counters.logical_read+=s.logical_delivered;p.counters.requested_read+=s.read_requested;p.counters.received+=s.received;need(f.provider->try_close(),"row source real drain");f.provider.reset();f.ticket.reset();if(f.cancelled||result.cancelled){f.cancelled=true;p.finish_fill();return;}if(!result.ok||result.bytes!=264){for(auto t:f.waiters)if(p.valid(t)){p.requests[t.index].cancelled=true;p.requests[t.index].state=RowState::Cancelled;}f.cancelled=true;p.finish_fill();throw std::runtime_error("short/error row read");}auto& ram=p.ram[f.ram];ram.key=f.key;ram.valid=true;p.upload();}
void RowSupply::poll_device(){auto& p=*p_;p.current();if(p.fill&&p.fill->dma&&!p.fill->quarantined&&p.event(p.slots[p.fill->slot].filled))p.finish_fill();if(p.active){auto& r=p.requests[*p.active];if(r.state==RowState::Kernel&&p.event(p.consumed)){complete_resident(r.reader,p.owner,true,!r.cancelled);if(r.cancelled){r.state=RowState::Cancelled;p.active.reset();}else r.state=RowState::Download;}}if(p.active){auto&r=p.requests[*p.active];if(r.return_pending&&p.event(p.returned)){r.return_pending=false;r.borrowed=false;++r.cursor;r.from_fill=false;p.active.reset();r.state=r.cancelled?RowState::Cancelled:r.cursor==r.keys.size()?RowState::Done:RowState::Queued;}}p.prepare_consumer();}
RowState RowSupply::state(Token t)const{return p_->checked(t).state;}
void RowSupply::launch_gather(Token t){auto& p=*p_;p.current();auto& r=p.checked(t);need(r.state==RowState::Ready&&p.active&&*p.active==t.index&&r.reader.active&&r.reader.generation==p.slots[r.slot].lease.generation&&p.slots[r.slot].key==r.keys[r.cursor],"row Ready lease/one I/O pair");uint32_t slot=uint32_t(r.slot);try{hip(hipMemcpyAsync(p.index,&slot,4,hipMemcpyHostToDevice,p.consumer));hip(hipStreamSynchronize(p.consumer));p.counters.index_h2d+=4;hip(hipMemsetAsync(p.error,0,4,p.consumer));hip(hipStreamWaitEvent(p.consumer,p.slots[r.slot].filled,0));deepseek41::engram::gather_device(reinterpret_cast<uint8_t*>(p.slots[0].lease.address),p.slots.size(),p.index,1,p.fp32,p.bf16,p.error,p.consumer);hip(hipEventRecord(p.consumed,p.consumer));r.state=RowState::Kernel;}catch(...){p.consumer_failure(r);throw;}}
RowDeviceOutput RowSupply::borrow_device_output(Token t){auto&p=*p_;p.current();auto&r=p.checked(t);need(r.state==RowState::Download&&!r.cancelled&&!r.borrowed&&p.active&&*p.active==t.index,"row output borrow state");
 int error=0;hip(hipMemcpy(&error,p.error,4,hipMemcpyDeviceToHost));p.counters.control_d2h+=4;need(error==0,"resident gather row rejected");r.borrowed=true;
 return {t,r.lookups[r.cursor],r.cursor,r.generation,p.fp32,p.bf16,p.config.device};}
void RowSupply::return_device_output(Token t,const RowDeviceOutput&v,void* stream){auto&p=*p_;p.current();auto&r=p.checked(t);need(r.borrowed&&!r.return_pending&&r.state==RowState::Download&&p.active&&*p.active==t.index&&v.request.owner==t.owner&&v.request.index==t.index&&v.request.generation==t.generation&&v.owner_generation==r.generation&&v.cursor==r.cursor&&v.fp32==p.fp32&&v.bf16==p.bf16&&v.device==p.config.device&&v.lookup.layer==r.lookups[r.cursor].layer&&v.lookup.head==r.lookups[r.cursor].head&&v.lookup.row==r.lookups[r.cursor].row&&stream,"row borrowed output identity");
 int device=-1;hip(hipStreamGetDevice(reinterpret_cast<hipStream_t>(stream),&device));need(device==p.config.device,"row return stream device");auto external=reinterpret_cast<hipStream_t>(stream);auto status=hipEventRecord(p.returned,external);
 if(status!=hipSuccess){r.cancelled=true;if(hipStreamSynchronize(external)==hipSuccess){r.borrowed=false;r.return_pending=false;r.state=RowState::Cancelled;p.active.reset();}else p.quarantined=true;hip(status);}r.return_pending=true;}
void RowSupply::download(Token t){auto& p=*p_;p.current();auto& r=p.checked(t);need(r.state==RowState::Download&&!r.borrowed,"row output before completion/borrow return");int error=0;try{hip(hipMemcpyAsync(p.host_fp.data(),p.fp32,1024,hipMemcpyDeviceToHost,p.consumer));hip(hipMemcpyAsync(p.host_bf.data(),p.bf16,512,hipMemcpyDeviceToHost,p.consumer));hip(hipMemcpyAsync(&error,p.error,4,hipMemcpyDeviceToHost,p.consumer));hip(hipEventRecord(p.returned,p.consumer));hip(hipEventSynchronize(p.returned));need(error==0,"resident gather row rejected");p.counters.output_d2h+=1540;r.result.fp32.insert(r.result.fp32.end(),p.host_fp.begin(),p.host_fp.end());r.result.bf16.insert(r.result.bf16.end(),p.host_bf.begin(),p.host_bf.end());++r.cursor;r.from_fill=false;p.active.reset();r.state=r.cursor==r.keys.size()?RowState::Done:RowState::Queued;p.prepare_consumer();}catch(...){p.consumer_failure(r);throw;}}
RowResult RowSupply::take(Token t,const measurement::Identity& current){auto& p=*p_;auto& r=p.checked(t);p.observe();need(r.state==RowState::Done||r.state==RowState::Cancelled,"row still live");bool keep=!r.cancelled&&same(r.identity,current);RowResult result;if(keep)result=std::move(r.result);else result.cancelled=true;r.live=false;r.lookups.clear();r.keys.clear();r.result={};return result;}
void RowSupply::cancel(Token t){auto& p=*p_;auto& r=p.checked(t);r.cancelled=true;if(r.state==RowState::Ready){complete_resident(r.reader,p.owner,true,false);p.active.reset();r.state=RowState::Cancelled;}else if(r.state!=RowState::Kernel&&!r.borrowed){if(p.active&&*p.active==t.index)p.active.reset();r.state=RowState::Cancelled;}if(p.fill&&!p.living_waiters()){p.fill->cancelled=true;if(p.fill->provider)p.fill->provider->cancel(*p.fill->ticket);}}
std::vector<Token> RowSupply::cancel_all(){auto& p=*p_;std::vector<Token> tokens;for(size_t i=0;i<p.requests.size();++i)if(p.requests[i].live)tokens.push_back({uint32_t(i),p.requests[i].generation,p.owner});for(auto t:tokens)cancel(t);return tokens;}
bool RowSupply::evict(const RowLookup& lookup){auto& p=*p_;auto found=p.hit(p.key(lookup));if(!found)return true;auto w=reserve_fill(p.slots[*found].lease,p.owner,264);if(!w)return false;complete_resident(*w,p.owner,true,false);p.slots[*found].key=UINT64_MAX;return true;}
void RowSupply::evict_ram(){for(auto& r:p_->ram)need(!r.busy,"RAM row source still live");for(auto& r:p_->ram)r.valid=false;}
bool RowSupply::try_close(){return p_->close();}
RowProgress RowSupply::progress(Token t)const{const auto& r=p_->checked(t);RowProgress x;x.slot=r.slot;if(r.reader.active){const auto& s=p_->slots[r.slot];x.generation=r.reader.generation;x.readers=s.lease.readers;x.writer=s.lease.writer;x.address=s.lease.address;}return x;}
bool RowSupply::request_idle()const{
 if(!p_)return false;const auto&p=*p_;
 if(p.closed||p.quarantined||p.fill||p.active)return false;
 for(const auto&r:p.requests)if(r.live||r.borrowed||r.return_pending||r.reader.active)return false;
 for(const auto&s:p.slots)if(s.lease.writer||s.lease.readers||s.lease.quarantined)return false;
 for(const auto&r:p.ram)if(r.busy)return false;
 return true;
}
bool RowSupply::fill_pending()const{return bool(p_->fill);}
bool RowSupply::fill_dma()const{return p_->fill&&p_->fill->dma;}
std::array<uint64_t,6> RowSupply::metadata_layout(){return {sizeof(RowSupply)+sizeof(Impl)-1536,sizeof(Impl::Slot),sizeof(Impl::Ram)-264,sizeof(Impl::Request),sizeof(RowBinding),sizeof(io::Buffer)};}
namespace {
template<class T>uint64_t heap_string(const T& x){auto p=reinterpret_cast<uintptr_t>(x.data()),a=reinterpret_cast<uintptr_t>(&x);return p>=a&&p<a+sizeof(x)?0:(x.capacity()+1)*sizeof(typename T::value_type);}
uint64_t identity_heap(const measurement::Identity& x){return heap_string(x.request_id)+heap_string(x.fixture_sha256)+heap_string(x.asset_sha256)+heap_string(x.bundle_sha256);}
uint64_t binding_heap(const RowBinding& x){return heap_string(x.physical.path.native())+heap_string(x.logical.original.source.original_path.native())+heap_string(x.logical.original.source.revision)+heap_string(x.logical.original.source.lfs_sha256)+heap_string(x.logical.original.span.name)+x.logical.original.span.dims_ggml.capacity()*8+x.logical.dims_ggml.capacity()*8;}
}
uint64_t RowSupply::Impl::metadata()const{auto layout=RowSupply::metadata_layout();uint64_t n=layout[0]+slots.capacity()*layout[1]+ram.capacity()*layout[2]+requests.capacity()*layout[3]+bindings.capacity()*layout[4]+buffers.capacity()*layout[5]+counters.stages.capacity()*sizeof(std::array<int64_t,4>);
 n+=full_sources.files.capacity()*sizeof(RowSourceView);
   for(const auto&v:full_sources.files)n+=heap_string(v.source.original_path.native())+heap_string(v.source.revision)+heap_string(v.source.lfs_sha256)+heap_string(v.full_file.path.native());
   for(const auto& b:bindings)n+=binding_heap(b);for(const auto& r:requests)n+=r.lookups.capacity()*sizeof(RowLookup)+r.keys.capacity()*8+identity_heap(r.identity);
 if(fill){const auto& f=*fill;n+=sizeof(Fill)+f.views.capacity()*sizeof(artifact::FixtureView)+f.spans.capacity()*sizeof(io::Span)+f.waiters.capacity()*sizeof(Token)+identity_heap(f.identity);n+=heap_string(f.slice.original.source.original_path.native())+heap_string(f.slice.original.source.revision)+heap_string(f.slice.original.source.lfs_sha256)+heap_string(f.slice.original.span.name)+f.slice.original.span.dims_ggml.capacity()*8+f.slice.dims_ggml.capacity()*8;for(auto& v:f.views)n+=heap_string(v.path.native());if(f.provider)n+=sizeof(io::SpanProvider)+f.provider->stats().metadata_capacity;}
 return n;}
RowStats RowSupply::stats()const{auto& p=*p_;p.observe();auto s=p.counters;if(p.fill&&p.fill->provider){auto io=p.fill->provider->stats();s.outstanding_reads=io.outstanding;s.outstanding_read_bytes=io.outstanding_bytes;}s.metadata_capacity=p.metadata();s.host_payload=p.payload();if(p.fill&&p.fill->provider)s.active_io_wrapper_metadata=p.fill->provider->stats().metadata_capacity;
 for(auto& b:p.bindings)s.binding_heap+=binding_heap(b);for(auto& r:p.requests){s.lookup_capacity+=r.lookups.capacity();s.key_capacity+=r.keys.capacity();s.identity_heap+=identity_heap(r.identity);}return s;}
}
