#pragma once
#include "../core.hpp"
#include "../../../native/device/roles.hpp"
namespace strata_ext::deepseek41 {
struct LayerSplitAudit {
 virtual ~LayerSplitAudit()=default;
 virtual void boundary(const PartitionBoundary&,const PartitionBoundary&)=0;
 virtual void transfer(const PartitionBoundary&,uint64_t ordinal,const device::TransferStats&)=0;
 virtual void event(uint64_t position,const char*name)=0;
};
struct LayerSplitConfig {
 device::Roles roles;uint32_t cut=24;uint64_t transfer_bytes=2*1024*1024;
 CoreConfig primary,secondary;device::Policy copy_policy=device::Policy::Auto;LayerSplitAudit*audit=nullptr;
};
// Physical FP32 container of BF16-rounded HC means, target attention-input37/38/39.
struct LayerTapView { measurement::Identity identity;DeviceView value;std::vector<uint64_t>positions;uint64_t batch=1,sequence=1,generation=0;std::array<uint32_t,3>layers{37,38,39};void*producer_stream=nullptr; };
void validate_layer_tap(const LayerTapView&,const measurement::Identity&,const std::vector<uint64_t>&positions,int device);
void validate_split_shared(const PartitionShared&,const measurement::Identity&,uint64_t position,uint32_t cut);
struct LayerSplitTapBinding {
 measurement::Identity identity;std::shared_ptr<const uint8_t> instance;
 CorePartitionTapBinding primary,secondary;uint64_t position=0;uint32_t cut=0;
};
struct LayerSplitTapToken {
 measurement::Identity identity;std::shared_ptr<const uint8_t> instance;
 CorePartitionTapBinding primary,secondary;uint64_t position=0,cursor_after=0;
};
struct LayerSplitTapSink {
 virtual ~LayerSplitTapSink()=default;
 virtual void capture(const CoreTapFrame&)=0;
 // Both producer streams and boundary copies have completed. The consumer
 // must return all its own CopyTask/mean-slot last uses before returning.
 virtual void processed(const LayerSplitTapToken&)=0;
};
namespace layer_tap_detail {
template<class A,class B>bool identity_equal(const A&a,const B&b){return a.request_id==b.request_id&&a.epoch==b.epoch&&a.phase==b.phase&&a.fixture_sha256==b.fixture_sha256&&a.asset_sha256==b.asset_sha256&&a.bundle_sha256==b.bundle_sha256;}
template<class Frame,class Binding>void validate_capture(const Frame&f,const Binding&b,unsigned captured){
 if(captured>=3||f.target_layer!=37+captured||f.capture_after_layer+1!=f.target_layer||!identity_equal(f.identity,b.identity)||f.position!=b.position||f.hc!=4||f.hidden!=5120)throw std::invalid_argument("split tap identity/position/order");
 const auto&side=f.target_layer<b.cut?b.primary:b.secondary;const auto&v=f.residual;
 if(!f.instance||f.instance!=side.instance||f.partition_first!=side.range.first||f.partition_end!=side.range.end||f.target_layer<side.range.first||f.target_layer>=side.range.end||f.activation_generation!=side.activation_generation||!side.owner||!side.owner->active||side.owner_generation!=side.owner->generation||v.owner!=side.owner||v.generation!=side.owner_generation||v.device!=side.device||!f.stream||f.stream!=side.stream||!v.data||v.rows!=1||v.columns!=20480||v.bytes<81920)throw std::invalid_argument("split tap partition/owner/activation/device/stream");
}
template<class Binding>void validate_processed(const Binding&b,unsigned captured,uint64_t primary_cursor,uint64_t secondary_cursor,bool copies_closed){
 if(captured!=3||b.position==UINT64_MAX||primary_cursor!=b.position+1||secondary_cursor!=b.position+1||!copies_closed)throw std::invalid_argument("split tap incomplete token/copies");
}
}
struct LayerSplitStats {
 uint64_t boundary_payload=0,new_kv=0,new_keys=0,selected=0,candidates=0;
 uint64_t peer_bytes=0,bounce_d2h=0,bounce_h2d=0,requested_logits_d2h=0;
 uint64_t primary_device_owned=0,secondary_device_owned=0,bounce_host_owned=0;
 CoreRuntimeStats primary,secondary;
};
class LayerSplit {
#ifdef STRATA_DEEPSEEK_T36_FIXTURE_CAPTURE
 friend struct T36PairFixture;
#endif
 struct Impl;std::unique_ptr<Impl> p_;
 void cancel_and_drain_internal();
public:
 LayerSplit(const Artifact&,const engram::Config&,cache::PrimarySupply&primary,cache::RowSupply*primary_rows,cache::PrimarySupply&secondary,cache::RowSupply*secondary_rows,measurement::Identity,LayerSplitConfig,uint64_t context);
 ~LayerSplit();
 LayerSplit(const LayerSplit&)=delete;LayerSplit&operator=(const LayerSplit&)=delete;
 std::vector<float>step(uint32_t raw_token,uint64_t position,bool image=false);
 CoreOutput prefill(const std::vector<uint32_t>&raw_tokens,uint64_t position,const std::vector<uint8_t>&image_mask={},const PrefillControl&control={});
 // Mathematical validity only; shared owner drain is still required for fresh.
 bool request_valid()const noexcept;
 LayerSplitTapBinding prepare_tap(uint64_t expected_position)const;
 std::vector<float>step_tapped(uint32_t,uint64_t,const LayerSplitTapBinding&,LayerSplitTapSink&);
 CoreOutput prefill_tapped(const std::vector<uint32_t>&,uint64_t,const std::vector<uint8_t>&,const LayerSplitTapBinding&,LayerSplitTapSink&,const PrefillControl&control={});
 void routing_policy(std::shared_ptr<routing::Policy>);
 bool retire_projection_graphs();
 void quiesce();void continue_request(const measurement::Identity&,uint64_t expected_position);
 void cancel_and_drain();bool try_close();uint64_t position()const;LayerSplitStats stats()const;
 };
#ifdef STRATA_DEEPSEEK_T36_FIXTURE_CAPTURE
// Existing fixture coordinator only: serialized healthy pair, no pointer escape.
struct T36PairFixture {
 struct Stamp {measurement::Identity root,primary,secondary;std::shared_ptr<const uint8_t>primary_instance,secondary_instance;uint64_t cursor=0,primary_cursor=0,secondary_cursor=0;bool valid=false;};
 static Stamp stamp(LayerSplit&);
 static void visit(LayerSplit&,bool primary,const FixtureStateVisitor&);
 static void fail_next_prepare_after_primary();
 static void probe_old_descriptor(LayerSplit&,const PartitionBoundary&old,const PartitionBoundary&current);
 static void probe_old_output(LayerSplit&,const std::shared_ptr<const uint8_t>&old_instance);
};
#endif
}
