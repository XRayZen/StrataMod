// Default build is host-only. STRATA_T39_RUNTIME adds an explicitly invoked tiny
// direct-module fixture; building it never probes/initializes a GPU.
#include "../../native/graph/primary_projection.hpp"
#include <iostream>
#include <functional>
using namespace strata_ext;
using namespace strata_ext::graph;
int host_contract(){
 unsigned n=0;auto check=[&](bool v){if(!v)throw std::runtime_error("contract assertion");++n;};
 cache::ResidentSlot slot{0x10000,4096,7,3,1,false,true,false};
 cache::ResidentLease reader{&slot,3,7,false,true};
 quant::ProjectionLease packed{13,true},activation{2,true};
 measurement::Identity id{"fixture","asset","bundle","request",1,measurement::Phase::Decode};
 Key key;key.source="native-source/matrix/tile";key.abi="r4-no-fma";
 key.packed=slot.address;key.input=0x20000;key.output=0x30000;
 key.packed_bytes=256;key.input_bytes=128;key.output_bytes=128;
 key.rows=2;key.k=32;key.batch=1;key.stride=4;key.type=0;key.device=0;
 key.stream=0x40000;key.slot=reinterpret_cast<uintptr_t>(&slot);
 key.resident_owner=7;key.slot_generation=3;key.activation_incarnation=100;
 key.activation_generation=2;
 Launch request{key,&reader,&packed,&activation,&id,&id,true,false};
 auto rejects=[&](const std::function<void()>&f){try{f();}catch(const std::exception&){++n;return;}throw std::runtime_error("invalid contract accepted");};
 check(preflight(request,nullptr,true)==Decision::Prepare);
 check(preflight(request,&key,true)==Decision::Replay);
 check(preflight(request,&key,false)==Decision::Eager);
 request.resident_hit=false;check(preflight(request,&key,true)==Decision::Eager);request.resident_hit=true;
 request.cancelled=true;check(preflight(request,&key,true)==Decision::Cancelled);request.cancelled=false;
 // A new transient request/epoch uses the SAME graph only after current identity matches.
 id.request_id="next";id.epoch=2;packed.generation=14;
 check(preflight(request,&key,true)==Decision::Replay);
 measurement::Identity stale=id;stale.epoch=1;request.current=&stale;
 rejects([&]{preflight(request,&key,true);});request.current=&id;
 auto change=[&](auto mutate){Key other=key;mutate(other);check(!(other==key));};
 change([](Key&k){k.source+="new";});change([](Key&k){k.abi+="new";});
 change([](Key&k){++k.packed;});change([](Key&k){++k.input;});change([](Key&k){++k.output;});
 change([](Key&k){++k.packed_bytes;});change([](Key&k){++k.input_bytes;});change([](Key&k){++k.output_bytes;});
 change([](Key&k){++k.rows;});change([](Key&k){++k.k;});change([](Key&k){++k.batch;});
 change([](Key&k){++k.stride;});change([](Key&k){++k.type;});change([](Key&k){++k.device;});
 change([](Key&k){++k.stream;});change([](Key&k){++k.slot;});change([](Key&k){++k.resident_owner;});
 change([](Key&k){++k.slot_generation;});change([](Key&k){++k.activation_generation;});
 change([](Key&k){++k.activation_incarnation;});
 reader.active=false;rejects([&]{preflight(request,&key,true);});reader.active=true;
 slot.generation++;rejects([&]{preflight(request,&key,true);});slot.generation--;
 slot.quarantined=true;rejects([&]{preflight(request,&key,true);});slot.quarantined=false;
 slot.writer=true;rejects([&]{preflight(request,&key,true);});slot.writer=false;
 slot.readers=0;rejects([&]{preflight(request,&key,true);});slot.readers=1;
 slot.owner++;rejects([&]{preflight(request,&key,true);});slot.owner--;
 slot.address++;rejects([&]{preflight(request,&key,true);});slot.address--;
 slot.valid=false;rejects([&]{preflight(request,&key,true);});slot.valid=true;
 slot.capacity=1;rejects([&]{preflight(request,&key,true);});slot.capacity=4096;
 reader.writer=true;rejects([&]{preflight(request,&key,true);});reader.writer=false;
 reader.generation++;rejects([&]{preflight(request,&key,true);});reader.generation--;
 request.current=nullptr;rejects([&]{preflight(request,&key,true);});request.current=&id;
 activation.active=false;rejects([&]{preflight(request,&key,true);});activation.active=true;
 packed.active=false;rejects([&]{preflight(request,&key,true);});packed.active=true;
 auto bad=[&](auto mutate){Launch changed=request;mutate(changed.key);rejects([&]{preflight(changed,&key,true);});};
 bad([](Key&k){k.batch=3;});bad([](Key&k){k.batch=8;k.input_bytes=128;});
 bad([](Key&k){k.batch=8;k.input_bytes=1024;k.output_bytes=16;});
 bad([](Key&k){k.stride=1;});bad([](Key&k){k.output=k.input;});
 bad([](Key&k){k.output=k.packed;});bad([](Key&k){k.k=SIZE_MAX;});
 bad([](Key&k){k.output=UINTPTR_MAX-3;});bad([](Key&k){k.activation_incarnation=0;});
 bad([](Key&k){k.activation_generation++;});bad([](Key&k){k.packed_bytes--;});
 bad([](Key&k){k.type=99;});bad([](Key&k){k.type=39;k.k=31;});
 // Adjacent strided output tiles are legal; overlapping writes into live input are not.
 request.key.batch=2;request.key.input_bytes=256;
 check(preflight(request,nullptr,true)==Decision::Prepare);
 request.key.output=request.key.input-16;request.key.output_bytes=128;
 rejects([&]{preflight(request,nullptr,true);});request.key=key;
 for(bool submitted:{false,true})for(bool ended:{false,true})for(bool clean:{false,true})
  check(clean_eager_fallback(submitted,ended,clean)==(!submitted&&ended&&clean));
 std::cout<<"{\"assertions\":"<<n<<",\"GPU_executed\":false,\"actual_application\":false}\n";
 return 0;
}
#ifndef STRATA_T39_RUNTIME
int main(){return host_contract();}
#else
#include <hip/hip_runtime.h>
#include <chrono>
#include <cstring>
#include <cstdlib>
#include <vector>
#include <array>
#include <cmath>
#include <cstdio>
#include <process.h>

namespace {
using Clock=std::chrono::steady_clock;
void diagnostic_marker(const char*stage,const char*point,int status=-1) noexcept {
 auto stamp=std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count();
 if(std::fprintf(stderr,"{\"event\":\"t39_diagnostic\",\"pid\":%d,\"steady_ns\":%lld,\"stage\":\"%s\",\"point\":\"%s\",\"hip_status\":%d}\n",_getpid(),static_cast<long long>(stamp),stage,point,status)<0||std::fflush(stderr)!=0)std::_Exit(66);
}
void hip_error(hipError_t e){if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));}
#define hip_ok(operation) do {diagnostic_marker(#operation,"before");auto diagnostic_status=(operation);diagnostic_marker(#operation,"after",int(diagnostic_status));hip_error(diagnostic_status);} while(0)
uint32_t bits(float x){uint32_t b;std::memcpy(&b,&x,4);return b;}
struct Buffers {
 void*packed=nullptr;void*input=nullptr;void*output=nullptr;
 hipStream_t stream=nullptr;hipEvent_t start=nullptr,stop=nullptr;
 Buffers(){try{
  hip_ok(hipMalloc(&packed,512));hip_ok(hipMalloc(&input,256));hip_ok(hipMalloc(&output,64));
  hip_ok(hipStreamCreateWithFlags(&stream,hipStreamNonBlocking));hip_ok(hipEventCreate(&start));hip_ok(hipEventCreate(&stop));
 }catch(...){release();throw;}}
 void release(){
  if(stream){diagnostic_marker("release.stream_drain","before");auto status=hipStreamSynchronize(stream);diagnostic_marker("release.stream_drain","after",int(status));if(status!=hipSuccess)std::_Exit(3);}
  if(start){hip_ok(hipEventDestroy(start));start=nullptr;}if(stop){hip_ok(hipEventDestroy(stop));stop=nullptr;}
  if(output){hip_ok(hipFree(output));output=nullptr;}if(input){hip_ok(hipFree(input));input=nullptr;}if(packed){hip_ok(hipFree(packed));packed=nullptr;}
  if(stream){hip_ok(hipStreamDestroy(stream));stream=nullptr;}
 }
 ~Buffers(){try{release();}catch(...){std::_Exit(3);}}
};
struct Measurement {int64_t host_ns=0;float stream_ms=0;};
template<class F> Measurement timed(Buffers&b,F operation){
 hip_ok(hipEventRecord(b.start,b.stream));auto begin=Clock::now();operation();auto end=Clock::now();
 hip_ok(hipEventRecord(b.stop,b.stream));hip_ok(hipEventSynchronize(b.stop));float ms=0;hip_ok(hipEventElapsedTime(&ms,b.start,b.stop));
 if(!std::isfinite(ms)||ms<0)throw std::runtime_error("invalid event interval");
 return {std::chrono::duration_cast<std::chrono::nanoseconds>(end-begin).count(),ms};
}
void emit_bits(const std::vector<float>&v){std::cout<<'[';for(size_t i=0;i<v.size();++i){if(i)std::cout<<',';std::cout<<bits(v[i]);}std::cout<<']';}
struct Stage {std::string name;Measurement time;std::vector<float>actual,expected;int decision=-1;};
bool run_case(unsigned type,int device,bool comma){
 constexpr size_t rows=3,k=32,batch=2,stride=5;
 diagnostic_marker(type==0?"case.F32.buffers":"case.MXFP4.buffers","before");Buffers buffers;diagnostic_marker("case.buffers","after");
 std::vector<float>weights(rows*k);std::vector<uint8_t>packed(type==0?rows*k*4:rows*17);
 // Independently generated native values, not quant::decode or graph output.
 const float table[8]={0,.5f,1,1.5f,2,3,4,6};
 for(size_t r=0;r<rows;++r)for(size_t j=0;j<k;++j){
  if(type==0)weights[r*k+j]=float(int((r*3+j)%7)-3)*.5f;
  else {unsigned code=unsigned((r*7+j)%15+1);weights[r*k+j]=(code&8?-1.f:1.f)*table[code&7];
   if((code&7)==0)weights[r*k+j]=0.f;
   packed[r*17]=127;auto&v=packed[r*17+1+j%16];if(j<16)v=uint8_t((v&0xf0)|code);else v=uint8_t((v&15)|(code<<4));}
 }
 if(type==0)std::memcpy(packed.data(),weights.data(),packed.size());
 hip_ok(hipMemcpyAsync(buffers.packed,packed.data(),packed.size(),hipMemcpyHostToDevice,buffers.stream));
 hip_ok(hipStreamSynchronize(buffers.stream));
 cache::ResidentSlot slot{reinterpret_cast<uintptr_t>(buffers.packed),512,17,1,0,false,true,false};
 quant::ProjectionLease activation{1,true},projection{1,true};
 measurement::Identity identity{"tiny-generated-fixture","tiny-no-model-assets","immutable-r4-quant","prepare",1,measurement::Phase::Decode};
 Key key;key.source="tiny-native-type-"+std::to_string(type);key.abi="r4-quant-63b67bc76111db2d/no-fma";
 key.packed=slot.address;key.input=reinterpret_cast<uintptr_t>(buffers.input);key.output=reinterpret_cast<uintptr_t>(buffers.output);
 key.packed_bytes=packed.size();key.input_bytes=256;key.output_bytes=40;key.rows=rows;key.k=k;key.batch=batch;key.stride=stride;key.type=type;key.device=device;
 key.stream=reinterpret_cast<uintptr_t>(buffers.stream);key.slot=reinterpret_cast<uintptr_t>(&slot);key.resident_owner=17;key.slot_generation=1;key.activation_incarnation=42;key.activation_generation=1;
 PrimaryProjection adapter(true);std::vector<Stage>stages;
 auto inputs=[](int seed){std::vector<float>x(batch*k);for(size_t i=0;i<x.size();++i)x[i]=float(int((i*5+seed*3)%11)-5)*.25f+float(seed)*.125f;return x;};
 auto expected=[&](const std::vector<float>&x){std::vector<float>y(batch*stride,-1234.f);for(size_t b=0;b<batch;++b)for(size_t r=0;r<rows;++r){float acc=0.f;for(size_t j=0;j<k;++j){float product=weights[r*k+j]*x[b*k+j];acc=acc+product;}y[b*stride+r]=acc;}return y;};
 auto check_output=[&](const std::vector<float>&q){std::vector<float>y(batch*stride);hip_ok(hipMemcpy(y.data(),buffers.output,y.size()*4,hipMemcpyDeviceToHost));
  if(std::memcmp(y.data(),q.data(),q.size()*4))throw std::runtime_error("output/padding bits differ from independent Q");
  std::vector<uint8_t>raw(packed.size());hip_ok(hipMemcpy(raw.data(),buffers.packed,raw.size(),hipMemcpyDeviceToHost));
  if(raw!=packed)throw std::runtime_error("packed input mutated");return y;};
 auto setup=[&](const std::vector<float>&x){std::vector<float>sentinel(batch*stride,-1234.f);hip_ok(hipMemcpyAsync(buffers.input,x.data(),x.size()*4,hipMemcpyHostToDevice,buffers.stream));
  hip_ok(hipMemcpyAsync(buffers.output,sentinel.data(),sentinel.size()*4,hipMemcpyHostToDevice,buffers.stream));hip_ok(hipStreamSynchronize(buffers.stream));};
 auto borrow=[&](){require(!slot.readers,"fixture reader still live");++slot.readers;return cache::ResidentLease{&slot,slot.generation,slot.owner,false,true};};
 auto release=[&](cache::ResidentLease&r){require(r.active&&r.generation==slot.generation&&slot.readers==1,"fixture original lease retirement");--slot.readers;r.active=false;};
 // Raw eager control uses the SAME existing project_into and is completed before graph timing.
 auto x=inputs(0);setup(x);auto q=expected(x);auto reader=borrow();
 auto binding=quant::checked_projection_strided({reinterpret_cast<const uint8_t*>(buffers.packed),type,rows,k,packed.size(),device},reinterpret_cast<const float*>(buffers.input),256,reinterpret_cast<float*>(buffers.output),40,stride,buffers.stream,projection);
 auto eager_time=timed(buffers,[&]{diagnostic_marker("raw.quant.project_into","before");quant::project_into(binding,batch);diagnostic_marker("raw.quant.project_into","after");});
 stages.push_back({"raw_eager_project_into",eager_time,check_output(q),q});release(reader);
 for(int seed=0;seed<3;++seed){
  x=inputs(seed);setup(x);q=expected(x);reader=borrow();identity.request_id="dynamic-"+std::to_string(seed);++identity.epoch;++projection.generation;
  Launch launch{key,&reader,&projection,&activation,&identity,&identity,true,false};Decision observed=Decision::Cancelled;
  auto measured=timed(buffers,[&]{diagnostic_marker(seed?"module.replay_attempt":"module.prepare_including_capture","before");observed=adapter.dispatch(launch);diagnostic_marker(seed?"module.replay_attempt":"module.prepare_including_capture","after",int(observed));});
  require(observed==(seed?Decision::Replay:Decision::Prepare)||adapter.stats().capture_fallbacks,"unexpected runtime decision");
  auto y=check_output(q);
  std::vector<float>read_input(x.size());hip_ok(hipMemcpy(read_input.data(),buffers.input,read_input.size()*4,hipMemcpyDeviceToHost));require(std::memcmp(read_input.data(),x.data(),x.size()*4)==0,"dynamic input mutated");
  stages.push_back({seed?"dynamic_attempt_"+std::to_string(seed):"prepare_including_capture_and_eager",measured,y,q,int(observed)});release(reader);
 }
 require(stages[1].expected!=stages[2].expected&&stages[2].expected!=stages[3].expected,"fixture dynamic outputs not distinct");
 auto stats=adapter.stats();bool pass=stats.replays>=2&&stats.captures==1&&stats.eager==1&&stats.capture_fallbacks==0;
 diagnostic_marker("module.close","before");require(adapter.close(),"actual graph close did not drain");diagnostic_marker("module.close","after");activation.active=false;projection.active=false;
 require(!slot.readers,"fixture lease remains live");
 if(comma)std::cout<<',';
 std::cout<<"{\"type\":"<<type<<",\"rows\":3,\"K\":32,\"batch\":2,\"stride\":5,\"explicit_device_owned_bytes\":832,\"eager\":"<<stats.eager<<",\"captures\":"<<stats.captures<<",\"replays\":"<<stats.replays<<",\"capture_fallbacks\":"<<stats.capture_fallbacks<<",\"closed\":true,\"graph_pass\":"<<(pass?"true":"false")<<",\"HIP_graph_internal_bytes\":null,\"capture_only_cost_ns\":null,\"capture_only_cost_reason\":\"module preparation includes validation/capture/instantiate/eager submission\",\"stages\":[";
 for(size_t i=0;i<stages.size();++i){const auto&s=stages[i];if(i)std::cout<<',';std::cout<<"{\"name\":\""<<s.name<<"\",\"module_decision_enum\":"<<s.decision<<",\"host_dispatch_ns\":"<<s.time.host_ns<<",\"device_stream_envelope_ms\":"<<s.time.stream_ms<<",\"actual_bits\":";emit_bits(s.actual);std::cout<<",\"independent_expected_bits\":";emit_bits(s.expected);std::cout<<'}';}
 std::cout<<"]}";return pass;
}
}
extern "C" void strata_t39_graph_trace(const char*stage,const char*point,int status) noexcept {diagnostic_marker(stage,point,status);}
int main(int argc,char**argv){
 diagnostic_marker("main.ENTRY","before_first_HIP");
 if(argc!=3||std::string(argv[1])!="--runtime"){std::cerr<<"explicit --runtime DEVICE required; no GPU queried\n";return 64;}
 char*end=nullptr;long selected=std::strtol(argv[2],&end,10);if(!end||*end||selected<0||selected>INT32_MAX)return 64;
 try{
  // FIRST runtime call. Supervisor must allocate the short resource window BEFORE invoking this binary.
  hip_ok(hipSetDevice(int(selected)));
  std::cout<<"{\"schema\":\"t39-tiny-direct-module-runtime/v1\",\"device\":"<<selected<<",\"GPU_executed\":true,\"actual_Core_application\":false,\"host_clock\":\"steady_clock\",\"device_clock\":\"HIP same-stream event envelope; includes possible host idle, not isolated kernel latency\",\"cases\":[";
  bool a=run_case(0,int(selected),false),b=run_case(39,int(selected),true);std::cout<<"],\"graph_pass\":"<<(a&&b?"true":"false")<<"}\n";diagnostic_marker("main.RETURN","after",a&&b?0:2);return a&&b?0:2;
 }catch(const std::exception&e){diagnostic_marker("main.CATCH","exception");std::cerr<<"runtime fixture failed: "<<e.what()<<'\n';return 1;}
}
#endif
