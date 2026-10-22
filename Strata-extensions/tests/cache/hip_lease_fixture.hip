#include "lease_queue.hpp"
#include "strata/core/device.hpp"
#include "strata/core/pinned_ring.hpp"
#include <hip/hip_runtime.h>
#include <windows.h>
#include <psapi.h>
#include <array>
#include <cstring>
#include <iostream>
#include <set>
#include <sstream>
#include <string>
#include <stdexcept>
using namespace strata_ext;
using namespace strata_ext::cache;
namespace {
void check(hipError_t e) {if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));}
void require(bool v,const char* s) {if(!v)throw std::runtime_error(s);}
std::string escape(const std::string& s){std::string out;for(char c:s){if(c=='\\'||c=='"')out+='\\';out+=c;}return out;}
std::string stage_fields(uintptr_t address,size_t capacity,bool attempted,hipError_t status,int memory_type) {
    std::ostringstream out;
    out<<"{\"address\":"<<address<<",\"capacity\":"<<capacity<<",\"query_attempted\":"<<(attempted?"true":"false")<<",\"query_status\":";
    if(attempted)out<<int(status);else out<<"null";
    out<<",\"memory_type\":";if(attempted&&status==hipSuccess)out<<memory_type;else out<<"null";
    out<<"}";return out.str();
}
__global__ void consume(uint8_t* data,uint32_t* checksum,size_t n) {
    size_t i=blockIdx.x*blockDim.x+threadIdx.x;
    if(i<n){uint8_t v=data[i]^0xa5;data[i]=v;atomicAdd(checksum,unsigned(v));}
}
}
int main(int argc,char** argv) {
 // Raw owner pointers are deleted only after checked successful drain. An error
 // retains outstanding/quarantined owners until this fixture process exits;
 // it never frees an uncertain DMA destination, resets or stops another owner.
 strata::core::DeviceArena* arena=nullptr;strata::core::PinnedRing* ring=nullptr;
 hipStream_t stream=nullptr;hipEvent_t dma=nullptr,kernel=nullptr;
 try {
    if(argc==2&&std::string(argv[1])=="--stage-format-selftest") {
      std::cout<<"{\"failed_nonzero_type\":"<<stage_fields(1,65536,true,hipErrorInvalidValue,2)
               <<",\"not_attempted_nonzero_type\":"<<stage_fields(1,65536,false,hipSuccess,2)
               <<",\"successful_host\":"<<stage_fields(1,65536,true,hipSuccess,int(hipMemoryTypeHost))<<",\"GPU_context_created\":false}"<<std::endl;return 0;
    }
    if(argc!=8||std::string(argv[1])!="--probe")throw std::runtime_error("usage --probe exactPCI fixtureSHA assetSHA bundleSHA callerID epoch");
    int count=0,selected=-1;check(hipGetDeviceCount(&count));
    for(int i=0;i<count;++i){char p[64]={};check(hipDeviceGetPCIBusId(p,sizeof(p),i));if(std::string(p)==argv[2])selected=i;}
    require(selected>=0,"exact PCI absent");check(hipSetDevice(selected));
    hipDeviceProp_t props{};check(hipGetDeviceProperties(&props,selected));
    constexpr size_t cap=65536;
    arena=new strata::core::DeviceArena(2*cap+4096,selected,false);
    auto* d0=static_cast<uint8_t*>(arena->alloc(cap));auto* d1=static_cast<uint8_t*>(arena->alloc(cap));
    auto* scratch=static_cast<uint32_t*>(arena->alloc(4096));
    ring=new strata::core::PinnedRing;
    check(hipStreamCreate(&stream));check(hipEventCreateWithFlags(&dma,hipEventDisableTiming));check(hipEventCreateWithFlags(&kernel,hipEventDisableTiming));
    bool reserve_return=ring->reserve(cap);
    std::array<void*,4> stage{};std::array<hipPointerAttribute_t,4> attributes{};bool pinned=true;
    std::array<bool,4> attribute_attempted{};std::array<hipError_t,4> attribute_status{};
    for(unsigned i=0;i<4;++i) {
        stage[i]=ring->acquire(cap);
        if(!stage[i]){pinned=false;break;}
        attribute_attempted[i]=true;attribute_status[i]=hipPointerGetAttributes(&attributes[i],stage[i]);
        if(attribute_status[i]!=hipSuccess||attributes[i].type!=hipMemoryTypeHost){hipGetLastError();pinned=false;break;}
        std::memset(stage[i],0,cap);check(ring->submit(d0,stage[i],cap,stream));check(hipStreamSynchronize(stream));
    }
    std::array<uint8_t,cap> source{},output{};
    for(size_t i=0;i<cap;++i)source[i]=uint8_t(i*37+11);
    uint64_t own_host=2*cap,own_pinned=0,own_device=arena->capacity();unsigned operations=0;bool fallback=false;
    uint64_t last_source_address=0,last_stage_address=0,last_device_address=0,last_slot_generation=0;
    if(pinned) {
      require(std::set<void*>(stage.begin(),stage.end()).size()==4,"stage pointers not distinct");own_pinned=4*cap;own_host+=own_pinned;
      std::array<Buffer,7> bindings{{{Pool::Source,reinterpret_cast<uintptr_t>(source.data()),cap},
        {Pool::Stage,reinterpret_cast<uintptr_t>(stage[0]),cap},{Pool::Stage,reinterpret_cast<uintptr_t>(stage[1]),cap},
        {Pool::Stage,reinterpret_cast<uintptr_t>(stage[2]),cap},{Pool::Stage,reinterpret_cast<uintptr_t>(stage[3]),cap},
        {Pool::Device,reinterpret_cast<uintptr_t>(d0),cap},{Pool::Device,reinterpret_cast<uintptr_t>(d1),cap}}};
      measurement::Identity id{argv[3],argv[4],argv[5],argv[6],std::stoull(argv[7]),measurement::Phase::Decode};
      LeaseQueue queue(1,bindings.data(),bindings.size());
      for(unsigned step=0;step<16;++step) {
        for(size_t i=0;i<cap;++i)source[i]=uint8_t(i*37+step);
        require(bool(queue.enqueue(id,step%2?Kind::Row:Kind::Expert,cap)),"GPU enqueue");
        // Ring owns its slots; only acquire/submit may choose/write one. Require
        // that this acquired physical slot matches the lease selected for it.
        void* actual_stage=ring->acquire(cap);
        auto ticket=queue.issue(reinterpret_cast<uintptr_t>(actual_stage));require(bool(ticket),"GPU issue");auto view=queue.view(*ticket);
        require(reinterpret_cast<uintptr_t>(actual_stage)==view.stage.address,"ring/sidecar stage binding");
        std::memcpy(actual_stage,source.data(),cap);queue.stage_copied(*ticket);
        require(queue.state(*ticket)==State::Filled,"source completion state");queue.begin_dma(*ticket,1);
        check(ring->submit(reinterpret_cast<void*>(view.device.address),actual_stage,cap,stream));check(hipEventRecord(dma,stream));
        check(hipEventSynchronize(dma));require(queue.complete_dma(*ticket,1,true,id),"fill not ready after actual DMA event");
        queue.begin_kernel(*ticket,1);check(hipMemsetAsync(scratch,0,4,stream));
        consume<<<(cap+255)/256,256,0,stream>>>(reinterpret_cast<uint8_t*>(view.device.address),scratch,cap);check(hipGetLastError());
        check(hipEventRecord(kernel,stream));check(hipEventSynchronize(kernel));
        check(hipMemcpy(output.data(),reinterpret_cast<void*>(view.device.address),cap,hipMemcpyDeviceToHost));uint32_t sum=0;check(hipMemcpy(&sum,scratch,4,hipMemcpyDeviceToHost));
        uint32_t expected=0;for(size_t i=0;i<cap;++i){uint8_t v=source[i]^0xa5;require(output[i]==v,"consumer byte mismatch");expected+=v;}
        require(sum==expected,"consumer checksum mismatch");require(queue.complete_kernel(*ticket,1,true,id),"kernel single adoption");
        require(queue.live_jobs()==0&&queue.leased_bytes()==0,"GPU operation not fully released");
        last_source_address=view.source.address;last_stage_address=view.stage.address;last_device_address=view.device.address;last_slot_generation=view.slot_generation[2];++operations;
      }
      auto gauge=queue.snapshot(id,own_host,own_pinned,argv[2],own_device);
      require(measurement::owned_total(gauge)==own_host+sizeof(queue)+own_device,"T34 owner gauge mismatch");
    } else {
      // Preserve the upstream synchronous pageable fallback. This is a separate
      // result; it never substitutes for observed pinned lease qualification.
      fallback=true;check(strata::core::PinnedRing::direct(d0,source.data(),cap,stream));check(hipMemcpy(output.data(),d0,cap,hipMemcpyDeviceToHost));
      require(output==source,"pageable fallback byte mismatch");
    }
    auto stream_address=reinterpret_cast<uintptr_t>(stream),dma_address=reinterpret_cast<uintptr_t>(dma),kernel_address=reinterpret_cast<uintptr_t>(kernel);
    check(hipStreamSynchronize(stream));check(hipEventDestroy(dma));dma=nullptr;check(hipEventDestroy(kernel));kernel=nullptr;check(hipStreamDestroy(stream));stream=nullptr;
    // All fixture operations have drained, so existing owner destructors are safe.
    delete ring;ring=nullptr;delete arena;arena=nullptr;
    HMODULE mods[1024];DWORD needed=0;require(EnumProcessModules(GetCurrentProcess(),mods,sizeof(mods),&needed)&&needed<=sizeof(mods),"loaded modules");
    std::cout<<"{\"source_id\":\""<<T16_SOURCE_ID<<"\",\"pci\":\""<<argv[2]<<"\",\"arch\":\""<<props.gcnArchName<<"\",\"reserve_return\":"<<(reserve_return?"true":"false")
             <<",\"observed_pinned\":"<<(pinned?"true":"false")<<",\"pageable_fallback\":"<<(fallback?"true":"false")<<",\"operations\":"<<operations
             <<",\"owned_host\":";if(pinned)std::cout<<own_host;else std::cout<<"null";
    std::cout<<",\"pinned_subset\":";if(pinned)std::cout<<own_pinned;else std::cout<<"null";
    std::cout<<",\"known_pageable_bytes\":"<<2*cap<<",\"owned_device\":"<<own_device
             <<",\"metadata_bytes\":"<<sizeof(LeaseQueue)<<",\"last_source_address\":"<<last_source_address<<",\"last_stage_address\":"<<last_stage_address
             <<",\"last_device_address\":"<<last_device_address<<",\"last_device_generation\":"<<last_slot_generation
             <<",\"stream\":"<<stream_address<<",\"dma_event\":"<<dma_address<<",\"kernel_event\":"<<kernel_address
             <<",\"local_owner_tag\":1,\"event_created_on_selected_ordinal\":"<<selected
             <<",\"capacity_scope\":\"successful owner allocation capacities; OS physical/commit and driver internal peak not measured\""
             <<",\"caller_identity\":{\"fixture_sha256\":\""<<argv[3]<<"\",\"asset_sha256\":\""<<argv[4]<<"\",\"bundle_sha256\":\""<<argv[5]<<"\",\"request_id\":\""<<escape(argv[6])<<"\",\"epoch\":"<<std::stoull(argv[7])<<"},\"stage_observations\":[";
    for(unsigned i=0;i<4;++i){if(i)std::cout<<",";std::cout<<stage_fields(reinterpret_cast<uintptr_t>(stage[i]),stage[i]?cap:0,attribute_attempted[i],attribute_status[i],int(attributes[i].type));}
    std::cout<<"],\"loaded_modules\":[";for(unsigned i=0;i<needed/sizeof(HMODULE);++i){char p[32768];require(GetModuleFileNameA(mods[i],p,sizeof(p))!=0,"module path");if(i)std::cout<<",";std::cout<<"\""<<escape(p)<<"\"";}
    std::cout<<"],\"owner_drained_before_free\":true,\"real_model_working_set\":false}"<<std::endl;return 0;
 } catch(const std::exception& e) {
    std::cerr<<e.what()<<"; uncertain outstanding owners retained until fixture process exit; no reset/free attempted"<<std::endl;return 2;
 }
}
