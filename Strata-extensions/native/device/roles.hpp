#pragma once
#include "../cache/lease_queue.hpp"
#include <hip/hip_runtime.h>
#include <memory>
#include <string>
#include <vector>
namespace strata_ext::device {
struct Physical { int ordinal=-1;std::string pci,name,arch,uuid,luid;int property_status=-1,uuid_status=-1,luid_status=-1; };
struct Roles { Physical primary;std::optional<Physical> secondary; };
std::vector<Physical> inventory();
Roles resolve(const std::vector<Physical>&,const std::string& primary,const std::optional<std::string>& secondary);
void check_extent(uint64_t bytes,uint64_t capacity);
enum class Policy { Auto,HostBounce };
enum class Phase { Idle,CopyPending,Ready,ConsumerPending,Done,Quarantined };
enum class ReturnDisposition { Recorded,Drained,Retain };
ReturnDisposition return_disposition(int record_status,int drain_status);
struct Endpoint { void* pointer=nullptr;uint64_t capacity=0;int device=-1;hipStream_t stream=nullptr;cache::ResidentSlot* slot=nullptr;uint64_t owner=0,generation=0; };
struct TransferStats {
 uint64_t bytes=0,peer_bytes=0,local_d2d=0,bounce_d2h=0,bounce_h2d=0;
 int capability_status=-1,can_access=-1,enable_status=-1,peer_copy_status=-1,disable_status=-1;
 int return_record_status=-1,return_drain_status=-1;
 bool owned_enable=false,cancelled=false;const char* path="none";
};
// Serialized caller. Endpoint slots, buffers, streams and the bounce region live
// through all outstanding/quarantined leases. No destination audit/readback is
// performed here. The caller records consumer use before returning its stream.
class CopyTask {
public:
 CopyTask(Endpoint source,Endpoint destination,void* bounce,uint64_t bounce_capacity,Policy);
 ~CopyTask();
 CopyTask(const CopyTask&)=delete;CopyTask& operator=(const CopyTask&)=delete;
 void submit(uint64_t bytes);
 void poll();
 void consumer_done_on(hipStream_t);
 // Ready cancellation keeps the output lease until consumer_done_on(actual
 // last-use stream) and poll. With no issued consumer, return an idle stream.
 // An unknown/unreturned consumer never becomes safe merely by cancelling.
 void cancel();
 bool try_close();
 Phase phase()const;TransferStats stats()const;
 static uint64_t metadata_bytes();
private:struct Impl;std::unique_ptr<Impl> p_;
};
}
