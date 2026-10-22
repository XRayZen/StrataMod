#include "primary_projection.hpp"
#include <hip/hip_runtime.h>
#include <exception>
#include <optional>

namespace strata_ext::graph {
namespace {
void hipcheck(hipError_t e){if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));}
}
struct PrimaryProjection::Impl {
 bool enabled=false,unknown=false,inflight=false,capturing=false,closed=false;
 std::optional<Key> key;
 hipGraph_t graph=nullptr;hipGraphExec_t executable=nullptr;
 hipStream_t stream=nullptr;
 Stats count;
 explicit Impl(bool e):enabled(e){count.metadata_bytes=sizeof(Impl);}
 void current()const{if(!stream)return;int d=-1,sd=-1;hipcheck(hipGetDevice(&d));hipcheck(hipStreamGetDevice(stream,&sd));require(d==sd,"graph close current device");}
 bool idle(){
  if(unknown||capturing)return false;
  if(!inflight)return true;
  // Only this owner's stream; destruction is never treated as a drain.
  if(hipStreamSynchronize(stream)!=hipSuccess){unknown=true;count.retained=true;return false;}
  inflight=false;return true;
 }
 bool retire(){
  if(!idle())return false;
  if(executable){if(hipGraphExecDestroy(executable)!=hipSuccess){unknown=true;count.retained=true;return false;}executable=nullptr;}
  if(graph){if(hipGraphDestroy(graph)!=hipSuccess){unknown=true;count.retained=true;return false;}graph=nullptr;}
  key.reset();stream=nullptr;count.aliased_payload_bytes=0;return true;
 }
 void observed_stream(hipStream_t s,int device){int d=-1,sd=-1;hipcheck(hipGetDevice(&d));hipcheck(hipStreamGetDevice(s,&sd));require(d==device&&sd==device,"graph current/stream device");}
 quant::DeviceProjection binding(const Launch&r){const auto&k=r.key;
  return quant::checked_projection_strided({reinterpret_cast<const uint8_t*>(k.packed),k.type,k.rows,k.k,k.packed_bytes,k.device},
   reinterpret_cast<const float*>(k.input),k.input_bytes,reinterpret_cast<float*>(k.output),k.output_bytes,k.stride,reinterpret_cast<void*>(k.stream),*r.packed_lease);
 }
 void eager(const Launch&r,const quant::DeviceProjection&b){
  // Mark submitted before calling: the launch API may report an error after enqueue.
  inflight=true;stream=reinterpret_cast<hipStream_t>(r.key.stream);
  try{quant::project_into(b,r.key.batch);++count.eager;}
  catch(...){unknown=true;count.retained=true;throw;}
 }
 bool prepare(const Launch&r,const quant::DeviceProjection&b){
  require(retire(),"graph retirement did not drain");
  key=r.key;stream=reinterpret_cast<hipStream_t>(r.key.stream);
  auto begin=hipStreamBeginCapture(stream,hipStreamCaptureModeThreadLocal);
  if(begin!=hipSuccess){
   hipStreamCaptureStatus status=hipStreamCaptureStatusNone;
   bool ended=hipStreamIsCapturing(stream,&status)==hipSuccess&&status==hipStreamCaptureStatusNone;
   bool clean=ended&&hipStreamSynchronize(stream)==hipSuccess;
   if(!clean_eager_fallback(false,ended,clean)){unknown=true;count.retained=true;throw std::runtime_error("graph begin cleanup unknown");}
   key.reset();stream=nullptr;++count.capture_fallbacks;return false;
  }
  capturing=true;std::exception_ptr error;
  try{quant::project_into(b,r.key.batch);}catch(...){error=std::current_exception();}
  // Always end capture, including a failed captured launch. Preserve any returned handle.
  auto end=hipStreamEndCapture(stream,&graph);hipStreamCaptureStatus status=hipStreamCaptureStatusActive;
  bool ended=hipStreamIsCapturing(stream,&status)==hipSuccess&&status==hipStreamCaptureStatusNone;
  capturing=!ended;
  bool clean=ended&&hipStreamSynchronize(stream)==hipSuccess;
  if(!clean_eager_fallback(false,ended,clean)){unknown=true;count.retained=true;throw std::runtime_error("graph capture cleanup unknown");}
  if(error||end!=hipSuccess||!graph){require(retire(),"graph failed capture handles retained");++count.capture_fallbacks;return false;}
  auto inst=hipGraphInstantiate(&executable,graph,nullptr,nullptr,0);
  if(inst!=hipSuccess||!executable){require(retire(),"graph instantiate handles retained");++count.capture_fallbacks;return false;}
  ++count.captures;
  count.aliased_payload_bytes=checked_add(checked_add(r.key.packed_bytes,r.key.input_bytes),r.key.output_bytes);
  return true;
 }
};
PrimaryProjection::PrimaryProjection(bool enabled):p_(std::make_unique<Impl>(enabled)){}
PrimaryProjection::~PrimaryProjection(){if(p_){try{if(!close()){p_.release();std::terminate();}}catch(...){p_.release();std::terminate();}}}
Decision PrimaryProjection::dispatch(const Launch&r){auto&p=*p_;require(!p.closed&&!p.unknown&&!p.capturing,"graph owner closed/retained");
 auto decision=preflight(r,p.key?&*p.key:nullptr,p.enabled);
 if(decision==Decision::Cancelled)return decision;
 auto s=reinterpret_cast<hipStream_t>(r.key.stream);p.observed_stream(s,r.key.device);
 p.current();
 require(p.idle(),"previous graph dispatch completion unknown");
 // Real pointer attribute/range checks happen outside capture on EVERY replay.
 auto binding=p.binding(r);
 if(decision==Decision::Replay){
  require(p.executable&&p.key&&*p.key==r.key,"graph executable/key mismatch");
  p.inflight=true;
  auto result=hipGraphLaunch(p.executable,s);
  if(result!=hipSuccess){p.unknown=true;p.count.retained=true;hipcheck(result);}
  ++p.count.replays;return decision;
 }
 if(decision==Decision::Prepare){bool replacing=p.key.has_value();p.prepare(r,binding);if(replacing)++p.count.recaptures;}
 else if(p.key&&!(*p.key==r.key))require(p.retire(),"eager miss graph retirement unknown");
 // Preparation captures arguments, never an eager execution. Miss MUST execute eager.
 p.eager(r,binding);return decision;
}
bool PrimaryProjection::close(){auto&p=*p_;if(p.closed)return true;p.current();
 // An uncertain launch is NEVER retried eagerly. Explicit close may retire it
 // only after actual capture-status and owner-stream drain proof succeeds.
 if(p.unknown||p.capturing){
  hipStreamCaptureStatus status=hipStreamCaptureStatusActive;
  if(!p.stream||hipStreamIsCapturing(p.stream,&status)!=hipSuccess||status!=hipStreamCaptureStatusNone||hipStreamSynchronize(p.stream)!=hipSuccess)return false;
  p.unknown=false;p.capturing=false;p.inflight=false;
 }
 if(!p.retire())return false;p.closed=true;p.count.retained=false;return true;}
Stats PrimaryProjection::stats()const{auto result=p_->count;
 result.metadata_bytes=sizeof(PrimaryProjection)+sizeof(Impl);
 if(p_->key)result.metadata_bytes=checked_add(result.metadata_bytes,checked_add(checked_add(p_->key->source.capacity(),1),checked_add(p_->key->abi.capacity(),1)));
 return result;}
}
