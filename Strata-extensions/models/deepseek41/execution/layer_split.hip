#include "layer_split.hpp"
#include <algorithm>
#include <limits>
#include <map>
#include <set>
#include <stdexcept>
#include <thread>
namespace strata_ext::deepseek41 {
#ifdef STRATA_DEEPSEEK_T36_FIXTURE_CAPTURE
static bool t36_pair_fail_after_primary=false;
#endif
#ifdef STRATA_T45_TEST
void t45_check_last_output_guard(CorePartition&,const PartitionBoundary&);
#endif
namespace {
void require(bool ok,const char*message){if(!ok)throw std::runtime_error(message);}
void checked(hipError_t e){if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));}
struct On {int previous=-1;explicit On(int d){checked(hipGetDevice(&previous));checked(hipSetDevice(d));}~On(){if(previous>=0)hipSetDevice(previous);}};
struct SplitInterrupted{};
using SharedKey=std::pair<PartitionDataKind,uint32_t>;
std::set<SharedKey> imports(uint32_t cut){std::set<SharedKey> out;for(unsigned layer=cut;layer<40;++layer){auto r=attention_role(layer);if(r.kv_writer<cut){out.emplace(PartitionDataKind::Compressed,r.kv_writer);out.emplace(PartitionDataKind::IndexKeys,r.kv_writer);}if(r.index_writer<cut)out.emplace(PartitionDataKind::Selection,r.index_writer);if(layer==r.index_writer&&layer>=24&&20<cut)out.emplace(PartitionDataKind::Candidates,20);}return out;}
uint64_t times(uint64_t a,uint64_t b){require(!b||a<=std::numeric_limits<uint64_t>::max()/b,"split byte arithmetic overflow");return a*b;}
}
struct SplitOperationClear {bool&active;~SplitOperationClear(){active=false;}};
struct LayerSplit::Impl {
 struct Copy {cache::ResidentSlot source,destination;std::unique_ptr<device::CopyTask> task;};
 std::shared_ptr<const uint8_t>tap_instance=std::make_shared<const uint8_t>(0);
 LayerSplitTapSink*tap_sink=nullptr;
 LayerSplitConfig config;measurement::Identity identity;std::unique_ptr<CorePartition> primary,secondary;
 std::vector<unsigned char> bounce;std::vector<std::unique_ptr<Copy>> copies;
 std::map<SharedKey,uint64_t> mirrored;LayerSplitStats observed;
 PartitionBoundary first,last;bool first_live=false,last_live=false,operation_active=false,valid=true,closed=false;uint64_t cursor=0,owner=1,capacity;
 Impl(const Artifact&a,const engram::Config&e,cache::PrimarySupply&w,cache::RowSupply*r,cache::PrimarySupply&sw,cache::RowSupply*sr,measurement::Identity id,LayerSplitConfig c,uint64_t context):config(std::move(c)),identity(std::move(id)),capacity(context){
  require(config.cut>0&&config.cut<40&&config.transfer_bytes&&context&&config.roles.secondary,"two partition roles/cut/working unit");require(config.copy_policy==device::Policy::Auto||config.copy_policy==device::Policy::HostBounce,"declared copy policy");require(config.roles.primary.ordinal==config.primary.device&&config.roles.secondary->ordinal==config.secondary.device&&config.primary.device!=config.secondary.device,"actual partition role/device binding");
  auto physical=device::resolve(device::inventory(),config.roles.primary.pci,config.roles.secondary->pci);require(physical.primary.ordinal==config.primary.device&&physical.secondary->ordinal==config.secondary.device,"current physical roles");
  bounce.resize(config.transfer_bytes);primary=std::make_unique<CorePartition>(a,e,w,r,identity,config.primary,context,PartitionSpec{0,config.cut});secondary=std::make_unique<CorePartition>(a,e,sw,sr,identity,config.secondary,context,PartitionSpec{config.cut,40},primary.get());
 }
 LayerSplitTapBinding tap_binding(uint64_t position,bool executing=false)const{
  require(valid&&!closed&&(!operation_active||executing)&&!first_live&&!last_live&&copies.empty()&&position==cursor,"healthy split tap boundary");
  LayerSplitTapBinding b;b.identity=identity;b.instance=tap_instance;b.position=position;b.cut=config.cut;b.primary=primary->prepare_partition_tap(position);b.secondary=secondary->prepare_partition_tap(position);return b;
 }
 struct Collector:CoreTapSink {
  LayerSplitTapBinding binding;LayerSplitTapSink&sink;unsigned captured=0;
  Collector(LayerSplitTapBinding b,LayerSplitTapSink&s):binding(std::move(b)),sink(s){}
  void capture(const CoreTapFrame&f)override{layer_tap_detail::validate_capture(f,binding,captured);require(f.residual.scalar==DeviceScalar::Bfloat16InFloat32,"split tap semantic BF16");sink.capture(f);++captured;}
  void processed(const CoreTapToken&)override{throw std::logic_error("partition cannot publish paired completion");}
 };
 void account(const device::TransferStats&s){observed.peer_bytes+=s.peer_bytes;observed.bounce_d2h+=s.bounce_d2h;observed.bounce_h2d+=s.bounce_h2d;}
 void copy_bytes(const DeviceView&s,const DeviceView&d,void*ss,void*ds,uint64_t offset,uint64_t bytes){
  require(offset<=s.bytes&&bytes<=s.bytes-offset&&offset<=d.bytes&&bytes<=d.bytes-offset,"split source/destination byte extent");
  for(uint64_t done=0;done<bytes;){auto count=std::min<uint64_t>(bytes-done,bounce.size());auto held=std::make_unique<Copy>();copies.push_back(std::move(held));auto&job=*copies.back();
   auto*sp=static_cast<unsigned char*>(s.data)+offset+done;auto*dp=static_cast<unsigned char*>(d.data)+offset+done;
   require(owner<std::numeric_limits<uint64_t>::max()-2,"split transfer generation overflow");job.source={reinterpret_cast<uintptr_t>(sp),count,owner++,1,0,false,true,false};job.destination={reinterpret_cast<uintptr_t>(dp),count,owner++,0,0,false,false,false};
   device::Endpoint se{sp,count,s.device,reinterpret_cast<hipStream_t>(ss),&job.source,job.source.owner,job.source.generation},de{dp,count,d.device,reinterpret_cast<hipStream_t>(ds),&job.destination,job.destination.owner,job.destination.generation};
   On current(d.device);job.task=std::make_unique<device::CopyTask>(se,de,bounce.data(),bounce.size(),config.copy_policy);job.task->submit(count);
   // Ready proves the bounce bytes are no longer in flight. The output reader
   // remains held until the actual downstream Core stream has consumed them.
   while(job.task->phase()!=device::Phase::Ready){job.task->poll();require(job.task->phase()!=device::Phase::Quarantined&&job.task->phase()!=device::Phase::Done,"split copy did not publish");std::this_thread::yield();}done+=count;
  }
 }
 void close_copies(bool cancel){On current(config.secondary.device);for(auto&job:copies){if(!job->task)continue;auto&task=*job->task;if(cancel)task.cancel();while(task.phase()!=device::Phase::Done){if(task.phase()==device::Phase::Ready)task.consumer_done_on(reinterpret_cast<hipStream_t>(first_live?secondary_stream():nullptr));else task.poll();require(task.phase()!=device::Phase::Quarantined,"split unknown copy completion");std::this_thread::yield();}require(task.try_close(),"split actual copy return");auto stats=task.stats();account(stats);job->task.reset();if(!cancel&&config.audit)config.audit->transfer(first,&job-&copies[0],stats);}copies.clear();}
 void* target_stream=nullptr;
 void*secondary_stream()const{return target_stream;}
 void release_boundaries(){if(last_live){secondary->retire_boundary(last.generation,last.stream);last_live=false;last={};}if(first_live){primary->retire_boundary(first.generation,first.stream);first_live=false;first={};}target_stream=nullptr;}
 void abort(){valid=false;primary->invalidate_and_drain();secondary->invalidate_and_drain();close_copies(true);release_boundaries();}
 std::vector<float> advance(uint32_t token,uint64_t position,bool image,bool emit,const std::function<void()>&progress){
  require(valid&&!closed&&!first_live&&!last_live&&position==cursor&&cursor<capacity&&token<129280,"live paired split input/order");
  std::unique_ptr<Collector>collector;if(tap_sink)collector=std::make_unique<Collector>(tap_binding(position,true),*tap_sink);
  try{first=collector?primary->advance_tapped(token,position,image,nullptr,false,progress,collector->binding.primary,*collector):primary->advance(token,position,image,nullptr,false,progress);first_live=true;auto required=imports(config.cut);first.shared.erase(std::remove_if(first.shared.begin(),first.shared.end(),[&](const auto&v){return !required.count({v.kind,v.writer});}),first.shared.end());for(auto&item:first.shared)validate_split_shared(item,identity,position,config.cut);auto target=secondary->targets(first);target_stream=target.stream;if(config.audit)config.audit->event(cursor,"primary-ready");
   copy_bytes(first.residual,target.residual,first.stream,target.stream,0,20480*4);copy_bytes(first.pre,target.pre,first.stream,target.stream,0,4*4);observed.boundary_payload+=20480*4+4*4;
   for(size_t i=0;i<first.shared.size();++i){auto&s=first.shared[i];auto&d=target.shared[i];auto key=SharedKey{s.kind,s.writer};uint64_t begin=0,bytes=0;
    if(s.kind==PartitionDataKind::Compressed||s.kind==PartitionDataKind::IndexKeys){auto old=mirrored[key];require(old<=s.published_rows,"split monotonic published rows");auto row=times(s.value.columns,scalar_bytes(s.value.scalar));begin=times(old,row);bytes=times(s.published_rows-old,row);if(s.kind==PartitionDataKind::Compressed)observed.new_kv+=bytes;else observed.new_keys+=bytes;}
    else{bytes=times(s.value.rows,times(s.value.columns,scalar_bytes(s.value.scalar)));if(s.kind==PartitionDataKind::Selection)observed.selected+=bytes;else observed.candidates+=bytes;}
    copy_bytes(s.value,d.value,first.stream,target.stream,begin,bytes);observed.boundary_payload+=bytes;
   }
   if(config.audit){config.audit->boundary(first,target);config.audit->event(cursor,"boundary-copy-ready");}last=collector?secondary->advance_tapped(token,position,image,&target,emit,progress,collector->binding.secondary,*collector):secondary->advance(token,position,image,&target,emit,progress);last_live=true;if(config.audit)config.audit->event(cursor,"secondary-complete");std::vector<float>result;if(emit){result=secondary->download_logits(last);observed.requested_logits_d2h+=times(result.size(),4);}

#ifdef STRATA_T45_TEST
   if(emit)t45_check_last_output_guard(*secondary,last);
#endif
   close_copies(false);if(collector){layer_tap_detail::validate_processed(collector->binding,collector->captured,primary->position(),secondary->position(),copies.empty());LayerSplitTapToken done;done.identity=identity;done.instance=tap_instance;done.primary=collector->binding.primary;done.secondary=collector->binding.secondary;done.position=position;done.cursor_after=position+1;tap_sink->processed(done);}
   for(auto&s:first.shared)if(s.kind==PartitionDataKind::Compressed||s.kind==PartitionDataKind::IndexKeys)mirrored[{s.kind,s.writer}]=s.published_rows;release_boundaries();if(config.audit)config.audit->event(cursor,"retired");++cursor;return result;
  }catch(...){auto original=std::current_exception();try{abort();}catch(...){std::terminate();}std::rethrow_exception(original);}
 }
};
void validate_split_shared(const PartitionShared&s,const measurement::Identity&id,uint64_t position,uint32_t cut){
 require(cut>0&&cut<40&&position<UINT64_MAX&&id.epoch&&s.valid&&s.epoch==id.epoch&&s.position==position,"current split shared metadata");require(imports(cut).count({s.kind,s.writer})!=0,"actual cross-cut writer/kind");
 auto role=attention_role(s.writer);require(s.compressor==role.kv_writer&&s.ratio==role.ratio&&s.ratio&&s.published_rows==(position+1)/s.ratio,"split compressor/source/ratio/valid rows");
 require(s.value.owner&&s.value.owner->active&&s.value.generation==s.value.owner->generation&&s.value.generation&&s.value.data,"shared borrowed owner/generation");
 if(s.kind==PartitionDataKind::Compressed||s.kind==PartitionDataKind::IndexKeys)require(s.value.scalar==DeviceScalar::Bfloat16InFloat32&&s.value.rows==s.published_rows&&s.value.columns==(s.kind==PartitionDataKind::Compressed?512:128),"valid cache/key prefix geometry");
 else require(s.value.rows==1&&s.value.columns==(s.kind==PartitionDataKind::Selection?std::min<uint64_t>(512,s.published_rows):s.published_rows)&&s.value.scalar==(s.kind==PartitionDataKind::Selection?DeviceScalar::Int32:DeviceScalar::Float32),"current selected/candidate prefix geometry");
 require(times(s.value.rows,times(s.value.columns,scalar_bytes(s.value.scalar)))<=s.value.bytes,"shared valid byte capacity");
}
void validate_layer_tap(const LayerTapView&t,const measurement::Identity&id,const std::vector<uint64_t>&positions,int device){
 require(t.identity.request_id==id.request_id&&t.identity.epoch==id.epoch&&t.identity.phase==id.phase&&t.identity.fixture_sha256==id.fixture_sha256&&t.identity.asset_sha256==id.asset_sha256&&t.identity.bundle_sha256==id.bundle_sha256,"tap original Identity");
 require(t.batch&&t.sequence&&t.generation&&t.positions==positions&&positions.size()==times(t.batch,t.sequence)&&t.layers==std::array<uint32_t,3>{37,38,39},"tap target stages/positions/generation");
 require(t.value.scalar==DeviceScalar::Bfloat16InFloat32&&t.value.rows==times(t.batch,t.sequence)&&t.value.columns==15360&&t.value.bytes==times(t.value.rows,15360*4)&&t.generation==t.value.generation,"tap physical FP32/semantic BF16 geometry");On current(device);validate_device_view(t.value,device);check_device_stream(t.producer_stream,device);
}
LayerSplit::LayerSplit(const Artifact&a,const engram::Config&e,cache::PrimarySupply&w,cache::RowSupply*r,cache::PrimarySupply&sw,cache::RowSupply*sr,measurement::Identity id,LayerSplitConfig c,uint64_t context):p_(std::make_unique<Impl>(a,e,w,r,sw,sr,std::move(id),std::move(c),context)){}
LayerSplit::~LayerSplit(){if(!p_)return;try{if(!p_->closed){p_->abort();p_->closed=true;}p_.reset();}catch(...){p_.release();std::terminate();}}
void LayerSplit::routing_policy(std::shared_ptr<routing::Policy>policy){if(!policy){p_->primary->routing_policy({});p_->secondary->routing_policy({});return;}quiesce();p_->primary->routing_policy(policy);p_->secondary->routing_policy(std::move(policy));}
std::vector<float> LayerSplit::step(uint32_t token,uint64_t pos,bool image){
 require(p_&&!p_->operation_active,"nested split operation");
 p_->primary->routing_decode(true);p_->secondary->routing_decode(true);
 struct Reset{Impl&p;~Reset(){if(p.primary)p.primary->routing_decode(false);if(p.secondary)p.secondary->routing_decode(false);}}reset{*p_};require(!p_->operation_active,"nested split operation");p_->operation_active=true;SplitOperationClear operation{p_->operation_active};try{return p_->advance(token,pos,image,true,{});}catch(...){if(p_->first_live||p_->last_live){p_.release();std::terminate();}throw;}}
CoreOutput LayerSplit::prefill(const std::vector<uint32_t>&tokens,uint64_t pos,const std::vector<uint8_t>&mask,const PrefillControl&control){require(p_&&!p_->operation_active&&p_->valid&&!tokens.empty()&&(mask.empty()||mask.size()==tokens.size())&&pos==p_->cursor&&tokens.size()<=p_->capacity-pos,"split prefill geometry/context");for(auto token:tokens)require(token<129280,"split raw token ID");for(auto x:mask)require(x<=1,"split image mask");p_->operation_active=true;SplitOperationClear operation{p_->operation_active};CoreOutput out;out.vocabulary=129280;
 try{auto safe=[&]{if(control&&!control(out.processed,tokens.size()))throw SplitInterrupted{};};safe();for(size_t i=0;i<tokens.size();++i){auto logits=p_->advance(tokens[i],pos+i,!mask.empty()&&mask[i],p_->config.secondary.full_logits||i+1==tokens.size(),safe);++out.processed;if(!logits.empty()){if(p_->config.secondary.full_logits)out.logits.insert(out.logits.end(),logits.begin(),logits.end());else out.logits=std::move(logits);++out.rows;}safe();}return out;
 }catch(const SplitInterrupted&){cancel_and_drain_internal();out.logits.clear();out.rows=0;out.cancelled=true;return out;}catch(...){if(p_&&(p_->first_live||p_->last_live)){p_.release();std::terminate();}throw;}}
LayerSplitTapBinding LayerSplit::prepare_tap(uint64_t position)const{return p_->tap_binding(position);}
namespace {
void validate_split_binding(const LayerSplitTapBinding&b,const LayerSplitTapBinding&e){
 auto side=[](const CorePartitionTapBinding&a,const CorePartitionTapBinding&b){return layer_tap_detail::identity_equal(a.identity,b.identity)&&a.instance==b.instance&&a.range.first==b.range.first&&a.range.end==b.range.end&&a.position==b.position&&a.activation_generation==b.activation_generation&&a.owner==b.owner&&a.owner_generation==b.owner_generation&&a.device==b.device&&a.stream==b.stream;};
 require(layer_tap_detail::identity_equal(b.identity,e.identity)&&b.instance==e.instance&&b.position==e.position&&b.cut==e.cut&&side(b.primary,e.primary)&&side(b.secondary,e.secondary),"split exact tap binding");
}
struct SplitTapClear{LayerSplitTapSink*&sink;~SplitTapClear(){sink=nullptr;}};
}
std::vector<float>LayerSplit::step_tapped(uint32_t token,uint64_t position,const LayerSplitTapBinding&binding,LayerSplitTapSink&sink){validate_split_binding(binding,prepare_tap(position));require(!p_->tap_sink,"split sink already armed");p_->tap_sink=&sink;SplitTapClear clear{p_->tap_sink};return step(token,position);}
CoreOutput LayerSplit::prefill_tapped(const std::vector<uint32_t>&tokens,uint64_t position,const std::vector<uint8_t>&mask,const LayerSplitTapBinding&binding,LayerSplitTapSink&sink,const PrefillControl&control){validate_split_binding(binding,prepare_tap(position));require(!p_->tap_sink,"split sink already armed");p_->tap_sink=&sink;SplitTapClear clear{p_->tap_sink};return prefill(tokens,position,mask,control);}
bool LayerSplit::retire_projection_graphs(){if(!p_)return false;if(p_->operation_active||p_->first_live||p_->last_live||!p_->copies.empty())return false;bool first=p_->primary->retire_projection_graph();bool last=p_->secondary->retire_projection_graph();return first&&last;}
void LayerSplit::cancel_and_drain(){if(p_&&p_->operation_active)throw RequestAdoptionRefused("cancel during active split operation");cancel_and_drain_internal();}
void LayerSplit::cancel_and_drain_internal(){require(bool(p_),"retained unknown split");if(p_->closed)return;try{p_->abort();}catch(...){p_.release();std::terminate();}}
void LayerSplit::quiesce(){
 if(!(p_&&p_->valid&&!p_->operation_active&&!p_->closed&&!p_->first_live&&!p_->last_live&&p_->copies.empty()))throw RequestAdoptionRefused("healthy paired request boundary");
 // Both owners preflight before either cache/stream retirement can mutate state.
 p_->primary->request_preflight();p_->secondary->request_preflight();
 try{p_->primary->quiesce_request();p_->secondary->quiesce_request();}
 catch(const RequestAdoptionRefused&){throw;}
 catch(...){auto error=std::current_exception();try{p_->abort();}catch(...){p_.release();std::terminate();}std::rethrow_exception(error);}
}
void LayerSplit::continue_request(const measurement::Identity&id,uint64_t position){
 quiesce();require(position&&position==p_->cursor,"paired processed request position");
 try{
  // All allocating root/P/S copies and opaque descriptor tokens precede publish.
  auto root=id;auto instance=std::make_shared<const uint8_t>(0);
  auto first=p_->primary->prepare_request(id,position);
#ifdef STRATA_DEEPSEEK_T36_FIXTURE_CAPTURE
  if(t36_pair_fail_after_primary){t36_pair_fail_after_primary=false;throw std::bad_alloc();}
#endif
  auto last=p_->secondary->prepare_request(id,position);
  p_->primary->request_preflight();p_->secondary->request_preflight();
  p_->identity.fixture_sha256.swap(root.fixture_sha256);p_->identity.asset_sha256.swap(root.asset_sha256);
  p_->identity.bundle_sha256.swap(root.bundle_sha256);p_->identity.request_id.swap(root.request_id);
  std::swap(p_->identity.epoch,root.epoch);std::swap(p_->identity.phase,root.phase);
  p_->tap_instance.swap(instance);
  p_->primary->adopt_request(std::move(first));p_->secondary->adopt_request(std::move(last));
 }catch(const RequestAdoptionRefused&){throw;}
 catch(...){auto error=std::current_exception();if(!p_->primary->request_valid()||!p_->secondary->request_valid()){try{p_->abort();}catch(...){p_.release();std::terminate();}}std::rethrow_exception(error);}
}
bool LayerSplit::try_close(){if(!p_)return false;if(p_->operation_active)return false;if(p_->closed)return true;cancel_and_drain();require(retire_projection_graphs(),"split graphs unknown completion");p_->secondary.reset();p_->primary.reset();p_->closed=true;return true;}
bool LayerSplit::request_valid()const noexcept{return p_&&p_->valid&&p_->primary->request_valid()&&p_->secondary->request_valid();}
uint64_t LayerSplit::position()const{return p_->cursor;}
LayerSplitStats LayerSplit::stats()const{auto out=p_->observed;if(p_->primary){out.primary=p_->primary->runtime_stats();out.primary_device_owned=p_->primary->explicit_device_owned();}if(p_->secondary){out.secondary=p_->secondary->runtime_stats();out.secondary_device_owned=p_->secondary->explicit_device_owned();}out.bounce_host_owned=p_->bounce.capacity();return out;}
#ifdef STRATA_DEEPSEEK_T36_FIXTURE_CAPTURE
void T36PairFixture::fail_next_prepare_after_primary(){t36_pair_fail_after_primary=true;}
void T36PairFixture::visit(LayerSplit&pair,bool primary,const FixtureStateVisitor&visitor){auto&p=*pair.p_;require(p.valid&&!p.operation_active&&!p.closed&&!p.first_live&&!p.last_live&&p.copies.empty(),"fixture healthy retired pair");p.operation_active=true;SplitOperationClear operation{p.operation_active};(primary?*p.primary:*p.secondary).fixture_visit_state(visitor);}
T36PairFixture::Stamp T36PairFixture::stamp(LayerSplit&pair){auto&p=*pair.p_;Stamp out;out.root=p.identity;out.primary_instance=p.primary->instance_;out.secondary_instance=p.secondary->instance_;out.cursor=p.cursor;out.primary_cursor=p.primary->position();out.secondary_cursor=p.secondary->position();out.valid=pair.request_valid();visit(pair,true,[&](const FixtureStateRecord&r,void*){if(r.identity)out.primary=*r.identity;});visit(pair,false,[&](const FixtureStateRecord&r,void*){if(r.identity)out.secondary=*r.identity;});return out;}
void T36PairFixture::probe_old_descriptor(LayerSplit&pair,const PartitionBoundary&old,const PartitionBoundary&current){auto&p=*pair.p_;require(p.first_live&&!p.last_live&&p.primary->instance_==current.instance&&old.instance!=current.instance,"fixture actual newly borrowed instance");
 auto reject=[&](const PartitionBoundary&boundary){bool refused=false;try{(void)p.secondary->targets(boundary);}catch(const std::runtime_error&e){require(std::string(e.what())=="boundary generation/position/token/epoch/source","unexpected descriptor exception");refused=true;}require(refused,"fixture stale descriptor accepted");};
 reject(old);auto only_instance=current;only_instance.instance=old.instance;reject(only_instance);
 bool refused=false;try{p.primary->retire_boundary(current.generation-1,current.stream);}catch(const std::runtime_error&e){require(std::string(e.what())=="live partition boundary return","unexpected return-cookie exception");refused=true;}require(refused&&pair.request_valid(),"fixture stale generation changed live pair");
}
void T36PairFixture::probe_old_output(LayerSplit&pair,const std::shared_ptr<const uint8_t>&old_instance){auto&p=*pair.p_;require(p.last_live&&p.last.instance!=old_instance,"fixture newly borrowed head instance");auto invalid=p.last;invalid.instance=old_instance;auto before=p.secondary->runtime_stats();bool refused=false;try{(void)p.secondary->download_logits(invalid);}catch(const std::runtime_error&e){require(std::string(e.what())=="requested head output","unexpected stale-head exception");refused=true;}auto after=p.secondary->runtime_stats();require(refused&&after.requested_output_or_fixture_download_bytes==before.requested_output_or_fixture_download_bytes&&pair.request_valid(),"fixture stale head consumed output");}

#endif

}
