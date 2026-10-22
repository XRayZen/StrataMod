#include "primary_supply.hpp"
#include "../quant/quant.hpp"
#include "../io/span_provider.hpp"
#include <strata/core/device.hpp>
#include <strata/core/pinned_ring.hpp>
#include <hip/hip_runtime.h>
#include <cstdlib>
#if defined(STRATA_T39_NORMAL_OBSERVER) && STRATA_T39_NORMAL_OBSERVER
#include <cstdio>
#endif
#include <cmath>
#include <cstring>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <iostream>
#include <cstdlib>
namespace strata_ext::cache {
#ifdef STRATA_PRIMARY_REUSE_TEST
extern "C" void strata_t35_provider_trace(const char*,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t,uint64_t) noexcept;
#endif
namespace {
// Test checkpoints are absent from the ordinary binary. No normal fault ENV.
void construction_trace(const char*action,const char*kind,const void*p){
#ifdef STRATA_T28_CONSTRUCTION_TEST
 std::cerr<<"T28_CTOR primary "<<action<<' '<<kind<<' '<<reinterpret_cast<uintptr_t>(p)<<'\n';
#else
 (void)action;(void)kind;(void)p;
#endif
}
void construction_fault(const char*stage){
#ifdef STRATA_T28_CONSTRUCTION_TEST
 const char*point=std::getenv("STRATA_T28_CTOR_FAULT");if(point&&std::string(point)==std::string("primary:")+stage)throw std::runtime_error("injected construction checkpoint");
#else
 (void)stage;
#endif
}
bool construction_drain_permitted(hipError_t status){return status==hipSuccess;}
struct ConstructionBufferFree {void operator()(void*p)const{if(p){construction_trace("free","unregistered-io",p);_aligned_free(p);}}};
void check(hipError_t e){if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));}
void need(bool b,const char* msg){if(!b)throw std::runtime_error(msg);}
uint64_t add(uint64_t a,uint64_t b){need(b<=UINT64_MAX-a,"capacity overflow");return a+b;}
#if defined(STRATA_T39_NORMAL_OBSERVER) && STRATA_T39_NORMAL_OBSERVER
// Synchronous borrowed metadata only. Output failure is fixture evidence loss,
// never a request/math failure; no request/lease pointer survives this call.
void t39_first_replay_record(const graph::Launch&r,uintptr_t lastuse)noexcept{
 try{
  std::ostringstream o;
  auto quoted=[&](const std::string&s){o<<'"';for(unsigned char c:s){if(c=='"'||c=='\\')o<<'\\'<<char(c);else if(c<32){const char*h="0123456789abcdef";o<<"\\u00"<<h[c>>4]<<h[c&15];}else o<<char(c);}o<<'"';};
  auto identity=[&](const measurement::Identity&i){o<<"{\"fixture_sha256\":";quoted(i.fixture_sha256);o<<",\"asset_sha256\":";quoted(i.asset_sha256);o<<",\"bundle_sha256\":";quoted(i.bundle_sha256);o<<",\"request_id\":";quoted(i.request_id);o<<",\"epoch\":"<<i.epoch<<",\"phase\":"<<unsigned(i.phase)<<'}';};
  const auto&k=r.key;const auto&l=*r.reader;const auto&s=*l.slot;
  o<<"{\"event\":\"t39_first_actual_replay\",\"key\":{\"source\":";quoted(k.source);o<<",\"abi\":";quoted(k.abi);
  o<<",\"packed\":"<<k.packed<<",\"input\":"<<k.input<<",\"output\":"<<k.output<<",\"stream\":"<<k.stream<<",\"slot\":"<<k.slot
   <<",\"packed_bytes\":"<<k.packed_bytes<<",\"input_bytes\":"<<k.input_bytes<<",\"output_bytes\":"<<k.output_bytes<<",\"rows\":"<<k.rows<<",\"k\":"<<k.k<<",\"batch\":"<<k.batch<<",\"stride\":"<<k.stride
   <<",\"type\":"<<k.type<<",\"device\":"<<k.device<<",\"resident_owner\":"<<k.resident_owner<<",\"slot_generation\":"<<k.slot_generation<<",\"activation_incarnation\":"<<k.activation_incarnation<<",\"activation_generation\":"<<k.activation_generation<<"},\"request\":";identity(*r.request);o<<",\"current\":";identity(*r.current);
  o<<",\"reader_address\":"<<reinterpret_cast<uintptr_t>(r.reader)<<",\"reader_active\":"<<(l.active?"true":"false")<<",\"reader_owner\":"<<l.owner<<",\"reader_generation\":"<<l.generation
   <<",\"slot_address\":"<<reinterpret_cast<uintptr_t>(&s)<<",\"slot_payload\":"<<s.address<<",\"slot_owner\":"<<s.owner<<",\"slot_payload_generation\":"<<s.generation<<",\"slot_readers\":"<<s.readers
   <<",\"projection_lease_address\":"<<reinterpret_cast<uintptr_t>(r.packed_lease)<<",\"projection_lease_active\":"<<(r.packed_lease->active?"true":"false")<<",\"projection_lease_request_generation\":"<<r.packed_lease->generation
   <<",\"activation_lease_address\":"<<reinterpret_cast<uintptr_t>(r.activation)<<",\"activation_active\":"<<(r.activation->active?"true":"false")<<",\"activation_generation\":"<<r.activation->generation
   <<",\"lastuse_event\":"<<lastuse<<",\"lastuse_record_enqueued\":true,\"lastuse_completion_observed\":false}";
  const auto text=o.str();(void)std::fwrite(text.data(),1,text.size(),stderr);(void)std::fputc('\n',stderr);(void)std::fflush(stderr);
 }catch(...){/* incomplete fixture record only */}
}
#endif
bool same(const measurement::Identity&a,const measurement::Identity&b){return a.request_id==b.request_id&&a.epoch==b.epoch&&a.phase==b.phase&&a.fixture_sha256==b.fixture_sha256&&a.asset_sha256==b.asset_sha256&&a.bundle_sha256==b.bundle_sha256;}
uint64_t aligned(uint64_t n){need(n<=UINT64_MAX-255,"alignment overflow");return (n+255)&~uint64_t(255);}
void validate(const SupplyMatrix& m){
 quant::validate_projection_shape(m.type,m.rows,m.k,1);
 need(m.bytes==quant::packed_bytes(m.type,m.rows*m.k)&&m.offset<=m.original.source.original_size&&m.bytes<=m.original.source.original_size-m.offset,"matrix original range");
 const auto& t=m.original.span;
 need(t.type_id==m.type&&m.original.source.shard_index==t.shard_index&&(t.dims_ggml.size()==2||t.dims_ggml.size()==3)&&t.dims_ggml[0]==m.k&&t.row_bytes==quant::packed_bytes(m.type,m.k),"matrix original shape/layout");
 need(m.offset>=t.absolute_offset&&m.offset-t.absolute_offset<=t.bytes&&m.bytes<=t.bytes-(m.offset-t.absolute_offset),"matrix original tensor slice");
 if(m.row_tile){uint64_t rows=t.dims_ggml[1],matrices=t.dims_ggml.size()==3?t.dims_ggml[2]:1;
  need(rows&&m.original_matrix<matrices&&m.output_row_first<rows&&m.rows<=rows-m.output_row_first,"original output row tile");
  need(m.original_matrix<=UINT64_MAX/rows,"matrix index overflow");uint64_t index=add(m.original_matrix*rows,m.output_row_first);need(index<=UINT64_MAX/t.row_bytes,"row tile offset overflow");need(m.offset==add(t.absolute_offset,index*t.row_bytes),"original row tile absolute offset");
 }else need(t.dims_ggml[1]==m.rows&&(m.offset-t.absolute_offset)%m.bytes==0,"whole original matrix/expert slice");
}
}
routing::Record routing_record(const SupplyMatrix&m)noexcept{
 routing::Record r;const auto&name=m.original.span.name;if(name.size()<7||name.compare(0,4,"blk.")!=0)return r;
 size_t i=4;unsigned layer=0;while(i<name.size()&&name[i]>='0'&&name[i]<='9'){if(layer>=40)return r;layer=layer*10+unsigned(name[i++]-'0');}
 if(i==4||i>=name.size()||name[i++]!='.'||layer>=40)return r;
 const char*names[]={"ffn_gate_exps.weight","ffn_up_exps.weight","ffn_down_exps.weight"};unsigned kind=0;for(;kind<3;++kind)if(name.compare(i,std::string::npos,names[kind])==0)break;if(kind==3)return r;
 r.relevant=true;auto&source=m.original.source;
 if(source.revision.empty()||source.revision.size()>64||source.revision.find('\0')!=std::string::npos||source.lfs_sha256.empty()||source.lfs_sha256.size()>64||source.lfs_sha256.find('\0')!=std::string::npos||!m.bytes||m.offset>UINT64_MAX-m.bytes)return r;
 std::memcpy(r.revision.data(),source.revision.data(),source.revision.size());std::memcpy(r.lfs.data(),source.lfs_sha256.data(),source.lfs_sha256.size());
 r.source_size=source.original_size;r.shard=source.shard_index;r.layer=layer;r.kind=kind;r.type=m.type;r.k=m.k;r.offset=m.offset;r.bytes=m.bytes;r.known=true;return r;
}
routing::Span routing_span(const routing::Record&r,routing::Tier tier){
 if(!r.relevant||!r.known)return {};const char*names[]={"ffn_gate_exps.weight","ffn_up_exps.weight","ffn_down_exps.weight"};
 return {std::string(r.revision.data())+"|"+r.lfs.data()+"|"+std::to_string(r.shard)+"|"+std::to_string(r.source_size)+"|"+std::to_string(r.type)+"|"+std::to_string(r.k),"blk."+std::to_string(r.layer)+"."+names[r.kind],r.offset,r.bytes,tier};
}
routing::Span routing_span(const SupplyMatrix&m,routing::Tier tier){return routing_span(routing_record(m),tier);}
std::string SupplyMatrix::key()const {
 std::ostringstream s;s<<original.source.revision<<'|'<<original.source.lfs_sha256<<'|'<<original.source.original_path.u8string()<<'|'<<original.span.name<<'|'<<type<<'|'<<rows<<'|'<<k<<'|'<<offset<<'|'<<bytes;return s.str();
}
#ifdef STRATA_T28_CONSTRUCTION_TEST
bool t28_primary_drain_decision(int status){return construction_drain_permitted(static_cast<hipError_t>(status));}
#endif
struct PrimarySupply::Impl {
 struct DeviceSlot { ResidentSlot lease;std::string key;routing::Record route;hipEvent_t filled=nullptr; };
 struct RamSlot { std::vector<uint8_t> bytes;std::string key;routing::Record route;bool valid=false,busy=false; };
 struct Fill {
  SupplyState state=SupplyState::Idle;bool prefetch=false,cancelled=false;
  SupplyMatrix matrix;measurement::Identity identity;routing::Record route_device,route_ram;size_t selected=0,ram_selected=0;uint64_t issued_read=0,completed=0,window_bytes=0,accounted_logical=0,accounted_requested=0;ResidentLease lease;
  std::vector<artifact::FixtureView> views;std::vector<io::Span> spans;
  std::unique_ptr<io::SpanProvider> provider;std::optional<io::Ticket> ticket;
 } filling;
 struct GraphState {
  std::vector<std::unique_ptr<graph::PrimaryProjection>> entries;
  uint64_t serial=0,live=0;bool retiring=false;
  PrimaryGraphStats counters;
#if defined(STRATA_T39_NORMAL_OBSERVER) && STRATA_T39_NORMAL_OBSERVER
  bool sampled_replay=false;
#endif
 };
 std::unique_ptr<GraphState> graphs;
 bool resident_hit=false;
 SupplyConfig config;std::unique_ptr<strata::core::DeviceArena> arena;strata::core::PinnedRing ring;
 std::vector<DeviceSlot> slots;std::vector<RamSlot> ram;std::vector<io::Buffer> io_buffers;
 hipStream_t stream=nullptr,producer=nullptr;hipEvent_t lastuse=nullptr,returned=nullptr;
 float* input=nullptr;float* output=nullptr;std::vector<float> host_output;
 SupplyState state=SupplyState::Idle;SupplyMatrix matrix;measurement::Identity identity;ResidentLease lease;
 quant::ProjectionLease projection_lease{1,false};const quant::ProjectionLease* activation_lease=nullptr;uint64_t activation_generation=0;bool device_consumer=false;hipStream_t active_stream=nullptr;SupplyStats stats;
 size_t selected=0,batch=0;uint64_t generation=0;bool cancelled=false,closed=false,ring_ready=false;
 const uint64_t owner=reinterpret_cast<uintptr_t>(this);
 explicit Impl(SupplyConfig c):config(c) {}
 void initialize(){auto c=config;
  need(c.device_slots&&c.ram_slots&&c.weight_capacity&&c.input_capacity&&c.output_capacity,"actual capacity configuration");
  need(c.device_slots<=UINT64_MAX/aligned(c.weight_capacity)&&c.ram_slots<=UINT64_MAX/c.weight_capacity,"slot capacity overflow");
  uint64_t bytes=add(add(c.device_slots*aligned(c.weight_capacity),aligned(c.input_capacity)),aligned(c.output_capacity));
  check(hipSetDevice(c.device));arena=std::make_unique<strata::core::DeviceArena>(bytes,c.device);
  slots.resize(c.device_slots);for(auto& s:slots)s.lease={reinterpret_cast<uintptr_t>(arena->alloc(c.weight_capacity)),c.weight_capacity,owner};
  input=static_cast<float*>(arena->alloc(c.input_capacity));output=static_cast<float*>(arena->alloc(c.output_capacity));
  ram.resize(c.ram_slots);for(auto& s:ram)s.bytes.resize(c.weight_capacity);
#ifdef STRATA_PRIMARY_IO128_TEST
  // Trial-only: preserve the same 131072-byte aggregate allocation. A permit
  // window is one real contiguous buffer; the nonpermit layout stays 2x64KiB.
  const unsigned io_count=c.permit_only?1:2;
  const uint64_t io_capacity=c.permit_only?131072:65536;
  io_buffers.reserve(io_count);
  for(unsigned i=0;i<io_count;++i){std::unique_ptr<void,ConstructionBufferFree> p(_aligned_malloc(io_capacity,4096));need(p!=nullptr,"I/O buffer allocation");construction_trace("create","io",p.get());construction_fault("io-unregistered");io_buffers.push_back({p.get(),io_capacity});p.release();construction_fault("io-registered");}
#else
  io_buffers.reserve(2);
  for(unsigned i=0;i<2;++i){std::unique_ptr<void,ConstructionBufferFree> p(_aligned_malloc(65536,4096));need(p!=nullptr,"I/O buffer allocation");construction_trace("create","io",p.get());construction_fault("io-unregistered");io_buffers.push_back({p.get(),65536});p.release();construction_fault("io-registered");}
#endif
  check(hipStreamCreateWithFlags(&stream,hipStreamNonBlocking));construction_trace("create","stream",stream);construction_fault("stream");check(hipStreamCreateWithFlags(&producer,hipStreamNonBlocking));construction_trace("create","stream",producer);
  for(auto& s:slots){check(hipEventCreateWithFlags(&s.filled,hipEventDisableTiming));construction_trace("create","event",s.filled);construction_fault("event");}
  for(auto e:{&lastuse,&returned}){check(hipEventCreateWithFlags(e,hipEventDisableTiming));construction_trace("create","event",*e);}
  ring.reserve(c.weight_capacity); // reserve(true) alone is NOT pinned evidence
  uint64_t stage_owned=0;bool all_pinned=true;
  for(unsigned i=0;i<4;++i){
   void* stage=ring.acquire(c.weight_capacity);SupplyStage observation;
   if(stage){observation.address=reinterpret_cast<uintptr_t>(stage);observation.capacity=std::max<uint64_t>(c.weight_capacity,65536);observation.attempted=true;
    hipPointerAttribute_t a{};auto status=hipPointerGetAttributes(&a,stage);observation.status=int(status);
    if(status==hipSuccess){observation.type=int(a.type);if(a.type==hipMemoryTypeHost)stats.pinned_subset+=observation.capacity;}else{hipGetLastError();stats.pinned_known=false;}
    all_pinned&=status==hipSuccess&&a.type==hipMemoryTypeHost;stage_owned+=observation.capacity;
    check(ring.submit(reinterpret_cast<void*>(slots[0].lease.address),stage,0,producer));construction_fault("ring-submit");
   }else all_pinned=false;
   stats.stages.push_back(observation);
  }
  check(hipStreamSynchronize(producer));stats.pinned_observed=all_pinned;ring_ready=all_pinned;
  stats.device_owned=arena->capacity();stats.host_owned=c.ram_slots*c.weight_capacity+131072+stage_owned;
  stats.metadata=sizeof(*this)+slots.capacity()*sizeof(DeviceSlot)+ram.capacity()*sizeof(RamSlot);
 }
 bool construction_cleanup()noexcept{
  // initialize can have recorded zero-byte stage events. Prove all existing
  // streams idle before releasing ANY registered storage/ring or HIP handle.
  for(auto stream_handle:{stream,producer})if(stream_handle){auto status=hipStreamSynchronize(stream_handle);construction_trace(status==hipSuccess?"drain":"unknown","stream",stream_handle);if(!construction_drain_permitted(status))return false;}
  ring.release();construction_trace("release","ring",this);
  for(auto& slot:slots)if(slot.filled){auto handle=slot.filled;if(hipEventDestroy(handle)!=hipSuccess)return false;slot.filled=nullptr;construction_trace("free","event",handle);}
  for(auto e:{&lastuse,&returned})if(*e){auto handle=*e;if(hipEventDestroy(handle)!=hipSuccess)return false;*e=nullptr;construction_trace("free","event",handle);}
  for(auto stream_pointer:{&stream,&producer})if(*stream_pointer){auto handle=*stream_pointer;if(hipStreamDestroy(handle)!=hipSuccess)return false;*stream_pointer=nullptr;construction_trace("free","stream",handle);}
  for(auto b:io_buffers){construction_trace("free","io",b.data);_aligned_free(b.data);}io_buffers.clear();arena.reset();closed=true;return true;
 }
 ~Impl(){if(!closed)std::terminate();}
 void absorb_graph(const graph::Stats&s){auto&d=graphs->counters.module;
  d.eager=add(d.eager,s.eager);d.replays=add(d.replays,s.replays);d.captures=add(d.captures,s.captures);
  d.recaptures=add(d.recaptures,s.recaptures);d.capture_fallbacks=add(d.capture_fallbacks,s.capture_fallbacks);
 }
 bool retire_graph_slot(size_t i){
  if(!graphs||!graphs->entries[i])return true;
  auto&entry=graphs->entries[i];
  try{if(!entry->close()){graphs->retiring=true;return false;}}
  catch(...){graphs->retiring=true;throw;}
  absorb_graph(entry->stats());entry.reset();return true;
 }
 void current()const{int d=-1;check(hipGetDevice(&d));need(d==config.device,"owner current device mismatch");}
 bool ready_event(hipEvent_t event){auto e=hipEventQuery(event);if(e==hipErrorNotReady){++stats.event_not_ready;return false;}check(e);return true;}
 void provider_event(const char*name)const{
#ifdef STRATA_PRIMARY_REUSE_TEST
  const auto&f=filling;io::Stats s{};if(f.provider)s=f.provider->stats();strata_t35_provider_trace(name,reinterpret_cast<uintptr_t>(f.provider.get()),f.completed,f.window_bytes,s.logical_delivered,s.read_requested,s.metadata_capacity,generation);
#else
  (void)name;
#endif
 }
 void close_source(){auto&f=filling;if(!f.provider)return;need(!f.ticket,"source ticket still owned");need(f.provider->try_close(),"source drain");provider_event("close");f.provider.reset();}
 std::optional<size_t> hit(const SupplyMatrix& m)const{
  const auto lookup_key=m.key();
  for(size_t i=0;i<slots.size();++i)if(slots[i].key==lookup_key&&slots[i].lease.valid&&!slots[i].lease.quarantined)return i;
  return std::nullopt;
 }
 void finish_fill(){
  auto& f=filling;need(!f.provider&&!f.ticket,"fill source closed before publication");bool published=complete_resident(f.lease,owner,true,!f.cancelled);
  if(published){slots[f.selected].key=f.matrix.key();slots[f.selected].route=f.route_device;slots[f.selected].route.generation=slots[f.selected].lease.generation;}
  if(f.prefetch)f.state=published?SupplyState::Done:SupplyState::Cancelled;
  else{selected=f.selected;if(published){auto held=borrow_resident(slots[selected].lease,owner);need(bool(held),"Ready demand resident lease");lease=std::move(*held);}state=published?SupplyState::Ready:SupplyState::Cancelled;filling=Fill{};}
 }
 void upload(){
  auto& f=filling;auto& r=ram[f.ram_selected];
  try {
  void* stage=ring_ready?ring.acquire(f.matrix.bytes):nullptr;
  if(stage){std::memcpy(stage,r.bytes.data(),f.matrix.bytes);check(ring.submit(reinterpret_cast<void*>(slots[f.selected].lease.address),stage,f.matrix.bytes,producer));}
  else check(strata::core::PinnedRing::direct(reinterpret_cast<void*>(slots[f.selected].lease.address),r.bytes.data(),f.matrix.bytes,producer));
  r.busy=false;stats.weight_h2d+=f.matrix.bytes;check(hipEventRecord(slots[f.selected].filled,producer));f.state=SupplyState::Dma;
  if(!f.prefetch)state=SupplyState::Dma;
  }catch(...){
   // No completion is invented after a HIP error. A successful real stream
   // drain cancels this reservation; an unprovable drain retains both owners.
   if(hipStreamSynchronize(producer)==hipSuccess){r.busy=false;f.cancelled=true;finish_fill();}
   else{quarantine_resident(f.lease,owner);f.state=SupplyState::Quarantined;if(!f.prefetch)state=SupplyState::Quarantined;}
   throw;
  }
 }
 bool start_fill(const SupplyMatrix& m,const measurement::Identity& id,bool prefetch){
  need(filling.state==SupplyState::Idle,"single producer window still owned");
  const auto lookup_key=m.key();
  auto& f=filling;f.prefetch=prefetch;f.matrix=m;f.identity=id;f.route_device=routing_record(m);f.route_ram=f.route_device;
  size_t eligible=0;for(auto& s:slots)eligible+=!s.lease.writer&&!s.lease.readers&&!s.lease.quarantined;
  // An active consumer already holds the demand reservation. Otherwise leave
  // one idle slot available to demand. One-slot operation never speculates.
  bool consumer_holds=lease.active;
  if(prefetch&&(slots.size()==1||eligible<=(consumer_holds?0u:1u))){filling=Fill{};return false;}
  bool found=false;
  for(unsigned pass=0;pass<2&&!found;++pass)for(size_t i=0;i<slots.size();++i){
   if(slots[i].lease.valid!=(pass==1))continue;
   // Retire BEFORE reserve_fill mutates slot generation/validity. Disabled path unchanged.
   if(graphs&&graphs->entries[i]&&!slots[i].lease.writer&&!slots[i].lease.readers&&!slots[i].lease.quarantined){
    if(!retire_graph_slot(i)){filling=Fill{};throw std::runtime_error("graph slot retirement unknown; owner retained");}
   }
   auto reservation=reserve_fill(slots[i].lease,owner,m.bytes);
   if(reservation){f.lease=std::move(*reservation);f.selected=i;found=true;break;}
  }
  if(!found){filling=Fill{};return false;}
  for(size_t i=0;i<ram.size();++i)if(!ram[i].busy&&ram[i].valid&&ram[i].key==lookup_key){
   f.ram_selected=i;ram[i].busy=true;++stats.ram_hits;upload();return true;
  }
  bool ram_found=false;
  for(unsigned pass=0;pass<2&&!ram_found;++pass)for(size_t i=0;i<ram.size();++i)if(!ram[i].busy&&ram[i].valid==(pass==1)){f.ram_selected=i;ram_found=true;break;}
  if(!ram_found){complete_resident(f.lease,owner,true,false);filling=Fill{};return false;}
  auto& target=ram[f.ram_selected];target.valid=false;target.busy=true;
  try{
   f.views={{m.original.source.original_path,0,m.original.source.original_size}};
   io::Config c;c.request_slots=1;c.max_outstanding=prefetch?1:2;c.max_chunk=65536;c.max_outstanding_bytes=prefetch?65536:131072;
   if(!config.permit_only){f.provider=std::make_unique<io::SpanProvider>(f.views,io_buffers,c);provider_event("create");f.spans={{0,m.offset,m.bytes,0}};f.window_bytes=m.bytes;
   f.ticket=f.provider->enqueue(f.spans,{target.bytes.data(),target.bytes.size()},f.identity);need(bool(f.ticket),"bounded I/O admission");}f.state=SupplyState::Reading;if(!prefetch)state=SupplyState::Reading;++stats.ssd_misses;return true;
  }catch(...){
   if(f.provider)close_source();
   target.busy=false;complete_resident(f.lease,owner,true,false);f.cancelled=true;f.state=SupplyState::Cancelled;
   if(!prefetch){cancelled=true;state=SupplyState::Cancelled;filling=Fill{};}
   throw;
  }
 }
 void consumer_error(){
  cancelled=true;
  if(hipStreamSynchronize(active_stream?active_stream:stream)==hipSuccess){
   if(lease.active)complete_resident(lease,owner,true,false);
   projection_lease.active=false;state=SupplyState::Cancelled;
  }else{
   if(lease.active)quarantine_resident(lease,owner);
   state=SupplyState::Quarantined;
  }
 }
 void close_resources(){
  ring.release();for(auto& s:slots)check(hipEventDestroy(s.filled));for(auto e:{lastuse,returned})check(hipEventDestroy(e));
  check(hipStreamDestroy(producer));check(hipStreamDestroy(stream));stream=nullptr;producer=nullptr;
  for(auto b:io_buffers)_aligned_free(b.data);io_buffers.clear();arena.reset();closed=true;
 }
};
PrimarySupply::PrimarySupply(SupplyConfig c):p_(std::make_unique<Impl>(c)){
 try{p_->initialize();}catch(...){if(!p_->construction_cleanup()){(void)p_.release();throw std::runtime_error("Primary owner construction completion unknown; child restart required");}throw;}
}
PrimarySupply::~PrimarySupply(){if(p_&&!p_->closed&&!try_close())std::terminate();}
bool PrimarySupply::begin(const SupplyMatrix& m,const measurement::Identity& id,bool prefetch){
 auto& p=*p_;need(!p.closed,"closed supply");need(!p.graphs||!p.graphs->retiring,"graph retirement requires activation close");need(p.state!=SupplyState::Quarantined&&p.filling.state!=SupplyState::Quarantined,"owner retains undrained quarantined storage");p.current();validate(m);
 if(m.bytes>p.config.weight_capacity)return false;
 if(prefetch){
  if(p.filling.state!=SupplyState::Idle)return false;
  if(p.hit(m)){p.filling.prefetch=true;p.filling.identity=id;p.filling.matrix=m;p.filling.state=SupplyState::Done;return true;}
  return p.start_fill(m,id,true);
 }
 if(p.state!=SupplyState::Idle)return false;
 auto hit=p.hit(m);
 if(!hit&&p.filling.state!=SupplyState::Idle){
  // Speculation cannot block a newly arrived miss indefinitely: request its
  // bounded issued window's cancellation, retain all owners until real drain.
  if(p.filling.prefetch)cancel_prefetch();return false;
 }
 need(p.generation!=UINT64_MAX,"request generation exhausted");p.matrix=m;p.identity=id;p.cancelled=false;p.resident_hit=bool(hit);++p.generation;
 if(hit){auto held=borrow_resident(p.slots[*hit].lease,p.owner);need(bool(held),"Ready cache hit resident lease");p.lease=std::move(*held);p.selected=*hit;++p.stats.gpu_hits;p.state=SupplyState::Ready;return true;}
 return p.start_fill(m,id,false);
}
uint64_t PrimarySupply::issue_reads(uint32_t operations,uint64_t bytes){auto&p=*p_;p.current();need(p.config.permit_only,"explicit permit owner configuration");auto&f=p.filling;
 if(!operations||bytes<4096||f.state!=SupplyState::Reading||f.cancelled||f.ticket)return 0;
#ifdef STRATA_PRIMARY_IO128_TEST
 const uint64_t retained=p.io_buffers.empty()?0:p.io_buffers.front().capacity;
 uint64_t capacity=std::min<uint64_t>(retained,bytes&~uint64_t(4095));uint64_t offset=add(f.matrix.offset,f.completed),padding=offset%4096;
#else
 uint64_t capacity=std::min<uint64_t>(65536,bytes&~uint64_t(4095));uint64_t offset=add(f.matrix.offset,f.completed),padding=offset%4096;
#endif
 uint64_t logical=std::min(f.matrix.bytes-f.completed,capacity-padding);need(logical,"bounded source window finite progress");
#ifdef STRATA_PRIMARY_IO128_TEST
 io::Config c;c.request_slots=1;c.max_outstanding=1;c.max_chunk=retained;c.max_outstanding_bytes=retained;
#else
 io::Config c;c.request_slots=1;c.max_outstanding=1;c.max_chunk=65536;c.max_outstanding_bytes=65536;
#endif
 f.window_bytes=logical;f.spans={{0,offset,logical,0}};auto&ram=p.ram[f.ram_selected];if(!f.provider){f.provider=std::make_unique<io::SpanProvider>(f.views,p.io_buffers,c);p.provider_event("create");}
 f.ticket=f.provider->enqueue(f.spans,{ram.bytes.data()+f.completed,logical},f.identity);need(bool(f.ticket),"permit window admission");
 auto before=f.provider->stats().read_requested;auto issued=f.provider->issue();uint64_t delta=f.provider->stats().read_requested-before;
 need(issued<=operations&&delta<=bytes,"actual read permit exceeded");f.issued_read=add(f.issued_read,delta);p.stats.issued_read=add(p.stats.issued_read,delta);p.stats.issued_reads+=issued;p.provider_event("issue");return delta;
}
void PrimarySupply::poll_io(int timeout){auto&p=*p_;p.current();auto&f=p.filling;if(f.state!=SupplyState::Reading)return;
 if(!f.ticket){if(f.cancelled){p.provider_event("cancel-idle");p.close_source();p.ram[f.ram_selected].busy=false;p.finish_fill();}return;}
 need(bool(f.provider),"source ticket provider owner");
 f.provider->poll(timeout);if(!f.provider->done(*f.ticket))return;
 auto result=f.provider->take(*f.ticket,f.identity);f.ticket.reset();auto stats=f.provider->stats();need(stats.logical_delivered>=f.accounted_logical&&stats.read_requested>=f.accounted_requested,"source cumulative counter regression");p.stats.weight_read=add(p.stats.weight_read,stats.logical_delivered-f.accounted_logical);p.stats.aligned_read=add(p.stats.aligned_read,stats.read_requested-f.accounted_requested);f.accounted_logical=stats.logical_delivered;f.accounted_requested=stats.read_requested;p.provider_event("take");
 if(f.cancelled||result.cancelled){f.cancelled=true;p.close_source();p.ram[f.ram_selected].busy=false;p.finish_fill();return;}
 if(!result.ok||result.bytes!=f.window_bytes){p.close_source();p.ram[f.ram_selected].busy=false;f.cancelled=true;p.finish_fill();throw std::runtime_error("source exact read");}
 f.completed=add(f.completed,f.window_bytes);if(f.completed<f.matrix.bytes)return;
 p.close_source();
 auto&r=p.ram[f.ram_selected];r.key=f.matrix.key();r.route=f.route_ram;r.valid=true;p.upload();
}
void PrimarySupply::poll_device(){auto&p=*p_;p.current();auto&f=p.filling;
 if(f.state==SupplyState::Dma&&p.ready_event(p.slots[f.selected].filled))p.finish_fill();
 try{if(p.state==SupplyState::Kernel&&p.ready_event(p.lastuse)){
  if(p.device_consumer)need(p.activation_lease&&p.activation_lease->active&&p.activation_lease->generation==p.activation_generation,"activation lease ended before last use");
  complete_resident(p.lease,p.owner,true,!p.cancelled);p.projection_lease.active=false;p.state=p.cancelled?SupplyState::Cancelled:p.device_consumer?SupplyState::Done:SupplyState::Download;
 }else if(p.state==SupplyState::Download&&p.cancelled)p.state=SupplyState::Cancelled;}catch(...){p.consumer_error();throw;}
}
void PrimarySupply::advance_fill(){auto&p=*p_;p.current();auto&f=p.filling;if(f.state==SupplyState::Reading&&!p.config.permit_only&&f.provider){auto before=f.provider->stats().read_requested;auto issued=f.provider->issue();auto delta=f.provider->stats().read_requested-before;f.issued_read+=delta;p.stats.issued_read+=delta;p.stats.issued_reads+=issued;}poll_io(10);if(f.state==SupplyState::Dma&&p.ready_event(p.slots[f.selected].filled))p.finish_fill();}
void PrimarySupply::advance(){advance_fill();poll_device();}
void PrimarySupply::launch_device(size_t batch,const float*input,uint64_t input_bytes,float*output,uint64_t output_bytes,size_t output_stride,void*stream,const quant::ProjectionLease&activation,const measurement::Identity*graph_current){auto&p=*p_;p.current();need(p.state==SupplyState::Ready&&stream&&activation.active&&activation.generation,"device consumer Ready/activation");
 need(p.lease.active&&p.lease.slot==&p.slots[p.selected].lease&&p.lease.generation==p.slots[p.selected].lease.generation&&p.slots[p.selected].key==p.matrix.key(),"continuous device Ready lease");
 p.projection_lease={p.generation,true};p.batch=batch;p.device_consumer=true;p.activation_lease=&activation;p.activation_generation=activation.generation;p.active_stream=reinterpret_cast<hipStream_t>(stream);
 try{check(hipStreamWaitEvent(p.active_stream,p.slots[p.selected].filled,0));auto binding=quant::checked_projection_strided({reinterpret_cast<uint8_t*>(p.slots[p.selected].lease.address),p.matrix.type,p.matrix.rows,p.matrix.k,p.matrix.bytes,p.config.device},input,input_bytes,output,output_bytes,output_stride,stream,p.projection_lease);if(!p.config.projection_graph)quant::project_into(binding,batch);
  else{
   need(p.graphs&&p.graphs->live&&!p.graphs->retiring&&graph_current,"graph activation/current request required");
   auto&entry=p.graphs->entries[p.selected];
   if(!entry)entry=std::make_unique<graph::PrimaryProjection>(true);
   graph::Key key;key.source=p.matrix.key()+"|"+std::to_string(p.matrix.row_tile)+"|"+std::to_string(p.matrix.original_matrix)+"|"+std::to_string(p.matrix.output_row_first);
   key.abi=p.config.projection_graph_abi;
   key.packed=p.slots[p.selected].lease.address;key.input=reinterpret_cast<uintptr_t>(input);key.output=reinterpret_cast<uintptr_t>(output);
   key.packed_bytes=p.matrix.bytes;key.input_bytes=input_bytes;key.output_bytes=output_bytes;
   key.rows=p.matrix.rows;key.k=p.matrix.k;key.batch=batch;key.stride=output_stride;key.type=p.matrix.type;key.device=p.config.device;
   key.stream=reinterpret_cast<uintptr_t>(stream);key.slot=reinterpret_cast<uintptr_t>(&p.slots[p.selected].lease);
   key.resident_owner=p.owner;key.slot_generation=p.slots[p.selected].lease.generation;
   key.activation_incarnation=p.graphs->live;key.activation_generation=activation.generation;
   graph::Launch launch{std::move(key),&p.lease,&p.projection_lease,&activation,&p.identity,graph_current,p.resident_hit,p.cancelled};
   auto decision=entry->dispatch(launch);
   need(decision!=graph::Decision::Cancelled,"cancelled graph launch must not publish Kernel");
   if(!p.resident_hit)++p.graphs->counters.resident_fill_eager;
   else if(decision==graph::Decision::Prepare)++p.graphs->counters.prepare_eager;
   else if(decision==graph::Decision::Replay)++p.graphs->counters.replayed;
#if defined(STRATA_T39_NORMAL_OBSERVER) && STRATA_T39_NORMAL_OBSERVER
   // Same recorded-event transition as common path; launch stays in scope.
   check(hipEventRecord(p.lastuse,p.active_stream));p.state=SupplyState::Kernel;
   if(decision==graph::Decision::Replay&&!p.graphs->sampled_replay){
    p.graphs->sampled_replay=true;t39_first_replay_record(launch,reinterpret_cast<uintptr_t>(p.lastuse));
   }
   return;
#endif
  }
  check(hipEventRecord(p.lastuse,p.active_stream));p.state=SupplyState::Kernel;}catch(...){p.consumer_error();throw;}
}
uint64_t PrimarySupply::begin_graph_activation(){auto&p=*p_;
 if(!p.config.projection_graph)return 0;
 need(!p.closed&&p.state==SupplyState::Idle&&!p.device_consumer,"graph activation requires idle Primary");
 need(!p.config.projection_graph_abi.empty(),"explicit graph math/source ABI required");
 if(!p.graphs){auto pending=std::make_unique<Impl::GraphState>();pending->entries.resize(p.slots.size());p.graphs=std::move(pending);}
 need(!p.graphs->live&&!p.graphs->retiring&&p.graphs->serial!=UINT64_MAX,"graph activation lifetime");
 p.graphs->live=++p.graphs->serial;++p.graphs->counters.activation_scopes;return p.graphs->live;
}
bool PrimarySupply::end_graph_activation(uint64_t token){auto&p=*p_;
 if(!token)return !p.config.projection_graph;
 need(p.graphs&&p.graphs->live==token,"foreign/stale graph activation retirement");
 if(p.state!=SupplyState::Idle||p.device_consumer)return false;
 check(hipSetDevice(p.config.device));p.graphs->retiring=true;
 for(size_t i=0;i<p.graphs->entries.size();++i)if(!p.retire_graph_slot(i))return false;
 p.graphs->live=0;p.graphs->retiring=false;return true;
}
PrimaryGraphStats PrimarySupply::projection_graph_stats()const{const auto&p=*p_;PrimaryGraphStats result;
 if(!p.graphs)return result;
 result=p.graphs->counters;
 auto&d=result.module;d.metadata_bytes=sizeof(Impl::GraphState)+p.graphs->entries.capacity()*sizeof(std::unique_ptr<graph::PrimaryProjection>)+p.config.projection_graph_abi.capacity()+1;
 for(const auto&e:p.graphs->entries)if(e){auto s=e->stats();
  d.eager=add(d.eager,s.eager);d.replays=add(d.replays,s.replays);d.captures=add(d.captures,s.captures);d.recaptures=add(d.recaptures,s.recaptures);d.capture_fallbacks=add(d.capture_fallbacks,s.capture_fallbacks);
  d.metadata_bytes=add(d.metadata_bytes,s.metadata_bytes);d.aliased_payload_bytes=add(d.aliased_payload_bytes,s.aliased_payload_bytes);d.retained|=s.retained;
 }
 return result;
}
void PrimarySupply::decode_device(float*output,uint64_t output_bytes,void*stream,const quant::ProjectionLease&activation){auto&p=*p_;p.current();need(p.state==SupplyState::Ready&&stream&&activation.active&&activation.generation,"decode consumer Ready/activation");need(p.lease.active&&p.lease.slot==&p.slots[p.selected].lease&&p.lease.generation==p.slots[p.selected].lease.generation&&p.slots[p.selected].key==p.matrix.key(),"decode continuous Ready lease");p.projection_lease={p.generation,true};p.device_consumer=true;p.activation_lease=&activation;p.activation_generation=activation.generation;p.active_stream=reinterpret_cast<hipStream_t>(stream);
 try{check(hipStreamWaitEvent(p.active_stream,p.slots[p.selected].filled,0));quant::decode_into({reinterpret_cast<uint8_t*>(p.slots[p.selected].lease.address),p.matrix.type,p.matrix.rows,p.matrix.k,p.matrix.bytes,p.config.device},output,output_bytes,stream,p.projection_lease);check(hipEventRecord(p.lastuse,p.active_stream));p.state=SupplyState::Kernel;}catch(...){p.consumer_error();throw;}}
bool PrimarySupply::take_device(const measurement::Identity&current){auto&p=*p_;need(p.device_consumer&&(p.state==SupplyState::Done||p.state==SupplyState::Cancelled),"device output still live");bool adopt=!p.cancelled&&same(p.identity,current);p.state=SupplyState::Idle;p.device_consumer=false;p.activation_lease=nullptr;p.active_stream=nullptr;return adopt;}
void PrimarySupply::launch(size_t batch,const std::vector<float>& input){auto& p=*p_;p.current();need(p.state==SupplyState::Ready,"consumer before fill or I/O pair busy");
 quant::validate_projection_shape(p.matrix.type,p.matrix.rows,p.matrix.k,batch);
 need(input.size()==batch*p.matrix.k&&input.size()*4<=p.config.input_capacity&&batch*p.matrix.rows*4<=p.config.output_capacity,"actual I/O capacity");for(float v:input)need(std::isfinite(v),"nonfinite activation");
 need(p.lease.active&&p.lease.slot==&p.slots[p.selected].lease&&p.lease.generation==p.slots[p.selected].lease.generation&&p.slots[p.selected].key==p.matrix.key(),"continuous Ready resident read lease");p.projection_lease={p.generation,true};p.batch=batch;p.device_consumer=false;p.activation_lease=nullptr;p.active_stream=p.stream;
 try{
 check(hipMemcpyAsync(p.input,input.data(),input.size()*4,hipMemcpyHostToDevice,p.stream));check(hipStreamSynchronize(p.stream));p.stats.input_h2d+=input.size()*4;
 check(hipStreamWaitEvent(p.stream,p.slots[p.selected].filled,0));
 auto binding=quant::checked_projection({reinterpret_cast<uint8_t*>(p.slots[p.selected].lease.address),p.matrix.type,p.matrix.rows,p.matrix.k,p.matrix.bytes,p.config.device},p.input,p.config.input_capacity,p.output,p.config.output_capacity,p.stream,p.projection_lease);
 quant::project_into(binding,batch);check(hipEventRecord(p.lastuse,p.stream));p.state=SupplyState::Kernel;
 }catch(...){p.consumer_error();throw;}
}
void PrimarySupply::download(){auto& p=*p_;p.current();need(p.state==SupplyState::Download,"output before kernel completion");p.host_output.resize(p.batch*p.matrix.rows);
 try{check(hipMemcpyAsync(p.host_output.data(),p.output,p.host_output.size()*4,hipMemcpyDeviceToHost,p.stream));check(hipEventRecord(p.returned,p.stream));check(hipEventSynchronize(p.returned));p.stats.output_d2h+=p.host_output.size()*4;p.state=SupplyState::Done;}
 catch(...){p.consumer_error();throw;}
}
void PrimarySupply::cancel_prefetch(){auto& f=p_->filling;need(f.prefetch&&f.state!=SupplyState::Idle,"no prefetch");f.cancelled=true;
 if(f.state==SupplyState::Reading){if(f.provider&&f.ticket)f.provider->cancel(*f.ticket);}else if(f.state==SupplyState::Done)f.state=SupplyState::Cancelled;
}
void PrimarySupply::cancel(){auto& p=*p_;need(p.state!=SupplyState::Idle,"no active request");p.cancelled=true;
 if(p.filling.state!=SupplyState::Idle&&same(p.filling.identity,p.identity)){
  p.filling.cancelled=true;if(p.filling.state==SupplyState::Reading){if(p.filling.provider&&p.filling.ticket)p.filling.provider->cancel(*p.filling.ticket);}else if(p.filling.prefetch&&p.filling.state==SupplyState::Done)p.filling.state=SupplyState::Cancelled;
 }
 if(p.state==SupplyState::Ready&&p.lease.active)complete_resident(p.lease,p.owner,true,false);
 if(p.state==SupplyState::Ready||p.state==SupplyState::Done||p.state==SupplyState::Download)p.state=SupplyState::Cancelled;
}
SupplyState PrimarySupply::prefetch_state()const{return p_->filling.prefetch?p_->filling.state:SupplyState::Idle;}
bool PrimarySupply::take_prefetch(const measurement::Identity& current){auto& f=p_->filling;need(f.prefetch&&(f.state==SupplyState::Done||f.state==SupplyState::Cancelled),"prefetch still live");bool adopt=f.state==SupplyState::Done&&!f.cancelled&&same(f.identity,current);f=Impl::Fill{};return adopt;}
bool PrimarySupply::evict_device(size_t i){auto& p=*p_;need(i<p.slots.size(),"cache slot OOB");if(p.graphs&&p.graphs->entries[i]){auto&s=p.slots[i].lease;if(s.writer||s.readers||s.quarantined)return false;if(!p.retire_graph_slot(i))return false;}auto l=reserve_fill(p.slots[i].lease,p.owner,1);if(!l)return false;complete_resident(*l,p.owner,true,false);p.slots[i].key.clear();return true;}
void PrimarySupply::evict_ram(){auto& p=*p_;for(auto& r:p.ram)need(!r.busy,"RAM writer/source live");for(auto& r:p.ram)r.valid=false;}
std::vector<float> PrimarySupply::take(const measurement::Identity& current){auto& p=*p_;need(!p.device_consumer&&(p.state==SupplyState::Done||p.state==SupplyState::Cancelled),"host output/DMA/I/O still live or device result");bool adopt=!p.cancelled&&same(p.identity,current);auto result=adopt?p.host_output:std::vector<float>{};p.host_output.clear();p.state=SupplyState::Idle;return result;}
bool PrimarySupply::try_close(){auto& p=*p_;if(p.closed)return true;if(p.state==SupplyState::Quarantined||p.filling.state==SupplyState::Quarantined)return false;p.current();if(p.state!=SupplyState::Idle||p.filling.state!=SupplyState::Idle)return false;
 for(auto& s:p.slots)if(s.lease.readers||s.lease.writer||s.lease.quarantined)return false;if(p.graphs&&p.graphs->live&&!end_graph_activation(p.graphs->live))return false;p.close_resources();return true;
}
ReadyPackedDescriptor PrimarySupply::ready_packed_descriptor()const{
 auto&p=*p_;p.current();need(!p.closed&&p.state==SupplyState::Ready&&p.lease.active,"packed descriptor requires current Ready lease");
 auto&slot=p.slots[p.selected];need(p.lease.slot==&slot.lease&&p.lease.owner==p.owner&&p.lease.generation==slot.lease.generation&&slot.lease.valid&&!slot.lease.writer&&!slot.lease.quarantined&&slot.key==p.matrix.key(),"packed descriptor continuous original resident");
 ReadyPackedDescriptor out;out.matrix=p.matrix;out.identity=p.identity;out.data=reinterpret_cast<const uint8_t*>(slot.lease.address);out.bytes=p.matrix.bytes;out.capacity=slot.lease.capacity;out.request_generation=p.generation;out.device=p.config.device;out.stream=reinterpret_cast<void*>(p.producer);out.resident=&slot.lease;out.owner=p.owner;out.slot_generation=slot.lease.generation;return out;
}
SupplyState PrimarySupply::state()const{return p_->state;}
SupplyIoSnapshot PrimarySupply::io_snapshot()const{
 const auto& base=p_->stats;
 SupplyIoSnapshot s{base.outstanding_reads,base.outstanding_read_bytes,base.issued_reads,base.issued_read};
 if(p_->filling.provider){auto io=p_->filling.provider->stats();s.outstanding_reads=io.outstanding;s.outstanding_read_bytes=io.outstanding_bytes;}
 return s;
}
routing::Snapshot PrimarySupply::routing_snapshot()const{
 const auto&p=*p_;routing::Snapshot out;out.owner=p.owner;out.generation=p.generation;
 out.complete=!p.closed&&p.state!=SupplyState::Quarantined&&p.filling.state!=SupplyState::Quarantined;
 for(auto&s:p.slots){if(s.lease.writer||s.lease.quarantined)out.complete=false;if(s.lease.valid&&!s.lease.writer&&!s.lease.quarantined&&!s.key.empty()&&s.route.relevant){if(!s.route.known||s.route.generation!=s.lease.generation)out.complete=false;else out.spans.push_back(routing_span(s.route,routing::Tier::Primary));}}
 for(auto&s:p.ram){if(s.busy)out.complete=false;if(s.valid&&!s.busy&&!s.key.empty()&&s.route.relevant){if(!s.route.known)out.complete=false;else out.spans.push_back(routing_span(s.route,routing::Tier::Ram));}}
 return out;
}
SupplyStats PrimarySupply::stats()const{auto s=p_->stats;if(p_->graphs)s.metadata=add(s.metadata,projection_graph_stats().module.metadata_bytes);if(p_->filling.provider){auto io=p_->filling.provider->stats();s.outstanding_reads=io.outstanding;s.outstanding_read_bytes=io.outstanding_bytes;}s.readback_capacity=p_->host_output.capacity()*sizeof(float);s.host_owned+=s.readback_capacity;return s;}
SupplyProgress PrimarySupply::progress()const{const auto& p=*p_;SupplyProgress v;v.permit_only=p.config.permit_only;v.demand_fill=!p.filling.prefetch&&same(p.filling.identity,p.identity);v.consumer=p.state;v.fill=p.filling.state;
 v.consumer_slot=p.selected;v.fill_slot=p.filling.selected;v.consumer_stream=reinterpret_cast<uintptr_t>(p.stream);v.producer_stream=reinterpret_cast<uintptr_t>(p.producer);
 if(p.lease.active){const auto& slot=p.slots[p.selected];v.consumer_generation=p.lease.generation;v.consumer_readers=slot.lease.readers;v.consumer_address=slot.lease.address;v.consumer_event=reinterpret_cast<uintptr_t>(p.lastuse);}
 if(p.filling.state!=SupplyState::Idle){const auto& slot=p.slots[p.filling.selected];v.fill_generation=p.filling.lease.generation;v.fill_writer=slot.lease.writer;v.fill_address=slot.lease.address;v.fill_event=reinterpret_cast<uintptr_t>(slot.filled);v.issued_read_bytes=p.filling.issued_read;}
 return v;
}
void* PrimarySupply::stream_handle()const{return p_->stream;}
uint64_t PrimarySupply::generation()const{return p_->generation;}
#ifdef STRATA_PRIMARY_IO128_TEST
uint64_t PrimarySupply::read_window_capacity()const{return p_->io_buffers.empty()?0:p_->io_buffers.front().capacity;}
#else
uint64_t PrimarySupply::read_window_capacity()const{return p_->io_buffers.empty()?0:std::min<uint64_t>(65536,p_->io_buffers.front().capacity);}
#endif

}
