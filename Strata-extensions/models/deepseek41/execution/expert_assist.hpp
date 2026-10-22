#pragma once
#include "../core.hpp"
#include "../../../native/device/roles.hpp"
#include <functional>
#include <memory>
namespace strata_ext::deepseek41 {
struct ExpertFrame {
 measurement::Identity identity;
 std::vector<uint64_t> token_positions;
};
// Value tickets expose stable allocations, never a pointer to mutable lease state.
struct ExpertTicket {
 std::shared_ptr<const uint8_t> instance; // small owner identity, no registry
 uint64_t generation=0;uint32_t slot=0,layer=0,expert=0;
 std::vector<uint32_t> pairs;
 std::vector<uint64_t> positions;
 measurement::Identity identity;
};
using LocalExpert=std::function<void(const DeviceView&returned_down)>;
class ExpertDispatch {
public:
 virtual ~ExpertDispatch()=default;
 virtual size_t capacity()const=0;
 virtual ExpertTicket submit(const ExpertFrame&,uint32_t layer,uint32_t expert,
  const std::vector<uint32_t>&pairs,const DeviceView&input,const DeviceView&route,
  void*primary_stream,const LocalExpert&)=0;
 // Adoption borrows the result. Return or cancel(actual stream) is required
 // before destruction; an unknown unreturned use retains storage child-fatal.
 virtual DeviceView collect(const ExpertTicket&)=0;
 virtual void consumed(const ExpertTicket&,void*actual_primary_stream)=0;
 // Caller stops submissions and retains Core buffers/streams through this drain.
 // An unprovable drain retains the component/Core owner bundle, child-fatal.
 virtual void cancel_and_drain(void*actual_primary_stream)=0;
 // Unknown dispatch implementations keep fresh inference; adoption is opt-in.
 virtual bool request_idle()const{return false;}
 virtual void drain()=0;
};
struct ExpertAssistAudit {
 virtual ~ExpertAssistAudit()=default;
 // Fixture-only sink; transfer/event callbacks may arrive from primary or
 // worker. Caller serializes the sink and retains it through worker join.
 virtual void event(const ExpertTicket&,const char*name)=0;
 virtual void transfer(const ExpertTicket&,const char*direction,const device::TransferStats&)=0;
};
struct ExpertAssistConfig {
 device::Roles roles;
 std::vector<uint32_t> secondary_experts;
 uint64_t max_batch=8;size_t slots=2;
 cache::SupplyConfig secondary_weights;
 CoreConfig secondary_core;
 device::Policy copy_policy=device::Policy::Auto;
 ExpertAssistAudit* audit=nullptr; // no normal trace allocation or audit readback
};
struct ExpertAssistStats {
 uint64_t primary_device_owned=0,secondary_workspace_owned=0,secondary_weight_owned=0;
 uint64_t bounce_host_owned=0,primary_jobs=0,secondary_jobs=0,input_payload=0,route_payload=0,down_payload=0;
 uint64_t peer_bytes=0,bounce_d2h=0,bounce_h2d=0,adopted=0,cancelled=0;
 uint64_t primary_snapshot_d2d_issued=0,last_sequence=0;bool quarantined=false;
 cache::SupplyStats secondary_weights;
 cache::PrimaryGraphStats secondary_graph;
 // This worker constructs one Supply; parent owner serial + instance binds rebuilds.
 uint64_t secondary_generation=1,secondary_request_generation=0;bool secondary_known=false;
};
// One specific secondary worker. CopyTask/ResidentSlot/ResidentLease and supply
// objects are worker-exclusive. Public calls exchange copied values under a
// short mailbox mutex; no HIP/I/O/callback/join happens under that mutex.
class ExpertAssist final:public ExpertDispatch {
 struct Impl;std::unique_ptr<Impl> p_;
public:
 ExpertAssist(const Artifact&,ExpertAssistConfig);
 ~ExpertAssist();
 ExpertAssist(const ExpertAssist&)=delete;ExpertAssist&operator=(const ExpertAssist&)=delete;
 size_t capacity()const override;
 ExpertTicket submit(const ExpertFrame&,uint32_t,uint32_t,const std::vector<uint32_t>&,
  const DeviceView&,const DeviceView&,void*,const LocalExpert&)override;
 DeviceView collect(const ExpertTicket&)override;
 void consumed(const ExpertTicket&,void*)override;
 void cancel_and_drain(void*)override;
 bool request_idle()const override;
 void drain()override;
 ExpertAssistStats stats()const;
};
}
