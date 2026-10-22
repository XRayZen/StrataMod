#pragma once
#include "primary_supply.hpp"
#include "../device/roles.hpp"
#include <optional>
#include <exception>
namespace strata_ext::cache {
struct SecondaryCapacity {size_t slots=0;uint64_t unit=0,capacity=0,unused=0;};
SecondaryCapacity secondary_capacity(uint64_t requested,uint64_t tile_bytes);
enum class CacheFailure {Allocation,CopyDrained,CrossUnknown,Source,Shape,Primary};
enum class CacheRecovery {Bypass,BypassRetained,Error,ErrorRetain};
CacheRecovery cache_recovery(CacheFailure,int primary_drain,bool retained,bool disjoint);
class SecondaryConstructionUnknown final:public std::exception {
 std::exception_ptr initialization_,cleanup_;
public:
 SecondaryConstructionUnknown(std::exception_ptr initialization,std::exception_ptr cleanup)noexcept:initialization_(std::move(initialization)),cleanup_(std::move(cleanup)){}
 const char*what()const noexcept override{return "secondary construction completion unknown; initialization/cleanup causes retained";}
 const std::exception_ptr&initialization_error()const noexcept{return initialization_;}
 const std::exception_ptr&cleanup_error()const noexcept{return cleanup_;}
};
[[noreturn]]void secondary_construction_result(std::exception_ptr initialization,bool cleanup_complete,std::exception_ptr cleanup={});
#ifdef STRATA_T22_TEST
// Test executable only: fail after an actual hit copy reaches Ready.
void test_fail_hit_ready_once();
void test_unknown_hit_ready_once();
struct SecondaryTestState {uintptr_t working=0,fallback=0;uint64_t working_capacity=0,fallback_capacity=0,readers=0,jobs=0;bool retained=false,disabled=false,disjoint=false;};
#endif
struct CacheTrace {
 measurement::Identity identity;std::string key,event;uint64_t operation=0,slot=0,generation=0;
 int source_device=-1,destination_device=-1;device::TransferStats transfer;
};
struct CacheAudit {virtual~CacheAudit()=default;virtual void event(const CacheTrace&)noexcept=0;};
struct SecondaryConfig {
 int primary=-1,secondary=-1;size_t slots=1;uint64_t tile_bytes=0;
 device::Policy policy=device::Policy::Auto;bool prefer_pinned=true;CacheAudit*audit=nullptr;
};
struct SecondaryStats {
 uint64_t hits=0,misses=0,fills=0,evictions=0,bypasses=0;
 uint64_t snapshot_d2d=0,fill_bytes=0,hit_bytes=0,peer_bytes=0,bounce_d2h=0,bounce_h2d=0;
 uint64_t primary_device_owned=0,secondary_device_owned=0,host_owned=0,metadata=0;
 uint64_t retained_device_bytes=0,retained_host_bytes=0;
 uint64_t slot_capacity=0,slots=0,valid_slots=0,created_streams=0,created_events=0;
 uint64_t pinned_subset=0;bool pinned_known=false,pinned_observed=false,available=true;
 int pin_status=-1,pin_type=-1,primary_drain_status=-1,secondary_drain_status=-1;
 std::string bypass_reason;
};
// Serialized production storage-only owner. No model arithmetic runs on S.
// One finite P working allocation is aliased by cold snapshot and hot execution;
// its physical storage is independent of every PrimarySupply execution slot.
// CopyTask owns all copy readers/writers until actual event/consumer return.
class SecondaryCache {
public:
 explicit SecondaryCache(SecondaryConfig);
 ~SecondaryCache();
 SecondaryCache(const SecondaryCache&)=delete;SecondaryCache&operator=(const SecondaryCache&)=delete;
 routing::Snapshot routing_snapshot()const; // metadata only, unlike contains()
 bool contains(const SupplyMatrix&)const;
 // Only a true unissued Primary miss may be cancelled by the Core coordinator.
 // This method does not mutate/cancel the caller's Primary owner or issue reads.
 bool project_hit(const SupplyMatrix&,const measurement::Identity&,
   const float*input,uint64_t input_bytes,float*output,uint64_t output_bytes,
   size_t batch,size_t output_stride,void*stream,const quant::ProjectionLease&activation);
 // Reads and validates the actual live Ready descriptor against expected source
 // and Identity, then releases the Primary reader at local-snapshot completion
 // BEFORE issuing any cross-device copy. No source reread for cache population.
 void populate(PrimarySupply&,const SupplyMatrix&,const measurement::Identity&);
 bool evict(size_t);void cancel_and_drain();bool try_close();SecondaryStats stats()const;
 static uint64_t slot_metadata_bytes();
#ifdef STRATA_T22_TEST
 SecondaryTestState test_state()const;
 void test_late_complete();
 void test_cleanup_proven_idle();
#endif
private:struct Impl;std::unique_ptr<Impl>p_;
};
}
