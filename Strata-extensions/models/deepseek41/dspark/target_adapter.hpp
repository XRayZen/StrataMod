#pragma once
#include <array>
#include <cstdint>
#include <string>
#include <functional>
#include <memory>
#include <vector>
#include <stdexcept>
namespace strata_ext::deepseek41 {class CoreSequence;class LayerSplit;struct CoreOutput;struct SamplingOptions;}
#ifdef STRATA_T38_GLOBAL_FIXTURE
#if !defined(STRATA_T28_CONSTRUCTION_TEST) || !defined(STRATA_T38_SEED_CONSTRUCTION) || !defined(STRATA_DEEPSEEK_T36_FIXTURE_CAPTURE) || !defined(STRATA_T38_SESSION_TRACE)
#error STRATA_T38_GLOBAL_FIXTURE requires all dedicated construction, state capture and trace guards
#endif
namespace strata_ext::deepseek41 {struct DeviceView;struct FixtureStateRecord;}
#endif
namespace strata_ext::measurement {struct Identity;}
namespace strata_ext::dspark::t38 {
// Metadata proof interface for bounded CPU fixtures. It does not implement Core tap APIs.
struct RequestBinding {uint64_t owner=0,epoch=0;std::string bundle;};
struct TapProof {uint64_t owner=0,epoch=0,position=0;uint32_t layer=0,hc=4,hidden=5120;};
struct StepProof {RequestBinding binding;uint64_t before=0,after=0;std::array<TapProof,3> taps;};
#ifdef STRATA_T38_GLOBAL_FIXTURE
// Synchronous borrow of the LAST successfully processed token's actual mean/proof.
// Copy into an independent owner and positively synchronize before returning.
using FixtureProcessedMeanVisitor=std::function<void(uint32_t,const StepProof&,const strata_ext::deepseek41::DeviceView&,void*)>;
#endif
class TargetAdapter {
public:
 virtual ~TargetAdapter()=default;
 virtual StepProof step(uint32_t original_id,uint64_t position)=0;
 virtual void invalidate_and_drain() noexcept=0;
};
using ContinueWork=std::function<bool()>;
class DraftCancelled final:public std::runtime_error {public:DraftCancelled():std::runtime_error("request cancelled at owned work boundary") {}};
struct DraftProposal;class NamespaceRng;class DraftNetwork;
// Coordinator contacts. The real implementation below owns one mean slot, no queue.
struct ActorTransferStats {uint64_t primary_device_owned=0,secondary_device_owned=0,bounce_host_owned=0,peer_bytes=0,bounce_d2h=0,bounce_h2d=0;};
class ActorTarget:public TargetAdapter {
public:
 virtual void prefill(const std::vector<uint32_t>&)=0;
 virtual const std::vector<float>& logits()const=0;
 virtual uint64_t known_cursor()const noexcept=0;
 virtual void set_control(ContinueWork)=0;
 virtual void drain()=0;
 virtual bool completion_known()const noexcept=0;
 virtual ActorTransferStats transfer_stats()const{return {};}
};
class ActorDraft {
public:
 virtual ~ActorDraft()=default;
 virtual DraftProposal propose(uint64_t,const strata_ext::deepseek41::SamplingOptions&,const std::vector<uint32_t>&,NamespaceRng&,const ContinueWork&)=0;
 virtual uint64_t cursor()const=0;
 virtual void drain()=0;
 virtual void invalidate_and_drain()noexcept=0;
 virtual bool completion_known()const noexcept=0;
};
class NetworkActorDraft final:public ActorDraft {
 DraftNetwork&network_;bool complete_=true;
public:
 explicit NetworkActorDraft(DraftNetwork&);
 DraftProposal propose(uint64_t,const strata_ext::deepseek41::SamplingOptions&,const std::vector<uint32_t>&,NamespaceRng&,const ContinueWork&)override;
 uint64_t cursor()const override;void drain()override;void invalidate_and_drain()noexcept override;
 bool completion_known()const noexcept override{return complete_;}
};
namespace detail {
template<class Identity>bool same_actor_identity(const Identity&a,const Identity&b){return a.fixture_sha256==b.fixture_sha256&&a.asset_sha256==b.asset_sha256&&a.bundle_sha256==b.bundle_sha256&&a.request_id==b.request_id&&a.epoch==b.epoch&&a.phase==b.phase;}
template<class Frame,class Identity,class Instance,class Scalar>
void validate_actor_capture(const Frame&f,const Identity&i,const Instance&instance,uint64_t position,unsigned captured,int device,Scalar scalar,bool armed,void*producer){
 if(!armed||!same_actor_identity(f.identity,i)||!f.instance||(instance&&instance!=f.instance)||f.position!=position||captured>=3||f.target_layer!=37+captured||f.capture_after_layer!=36+captured||f.hc!=4||f.hidden!=5120||!f.stream||(producer&&producer!=f.stream))throw std::invalid_argument("actual actor tap identity/order/layout");
 const auto&v=f.residual;if(!v.data||v.device!=device||v.rows!=1||v.columns!=20480||v.scalar!=scalar||v.bytes<81920||!v.owner||!v.owner->active||v.generation!=v.owner->generation)throw std::invalid_argument("actual actor tap owner/geometry");
}
template<class Token,class Identity,class Instance>
void validate_actor_processed(const Token&t,const Identity&i,const Instance&instance,uint64_t position,unsigned captured,void*producer,bool armed){
 if(!armed||captured!=3||!same_actor_identity(t.identity,i)||!instance||t.instance!=instance||t.position!=position||position==UINT64_MAX||t.cursor_after!=position+1||!producer||t.stream!=producer)throw std::invalid_argument("actual actor processed boundary");
}
}
// Caller proves exact healthy processed prefix before constructing this request adapter.
struct PreparedPrefix {uint64_t processed=0;std::vector<float> logits;};
class CoreTargetAdapter final:public ActorTarget {
 struct Impl;std::unique_ptr<Impl> p_;
public:
 CoreTargetAdapter(strata_ext::deepseek41::CoreSequence&,const strata_ext::measurement::Identity&,
  RequestBinding,int device,DraftNetwork&,std::function<void()> idle_invalidate_target,
  std::function<bool(uint64_t,uint64_t)> prefill_control={},PreparedPrefix prepared={},std::function<void()> quiesce_target={});
 ~CoreTargetAdapter();CoreTargetAdapter(const CoreTargetAdapter&)=delete;
#ifdef STRATA_T38_GLOBAL_FIXTURE
 void fixture_visit_last_processed_mean(const FixtureProcessedMeanVisitor&);
 void fixture_visit_state(const std::function<void(const strata_ext::deepseek41::FixtureStateRecord&,void*)>&);
#endif
 void prefill(const std::vector<uint32_t>&)override;
 StepProof step(uint32_t,uint64_t)override;
 const std::vector<float>& logits()const override;
 const strata_ext::deepseek41::CoreOutput& prefill_output()const;
 uint64_t known_cursor()const noexcept override;
 void set_control(ContinueWork)override;void drain()override;
 void invalidate_and_drain()noexcept override;bool completion_known()const noexcept override;
 ActorTransferStats transfer_stats()const override;
};
class LayerSplitActorTarget final:public ActorTarget {
 struct Impl;std::unique_ptr<Impl> p_;
public:
 LayerSplitActorTarget(strata_ext::deepseek41::LayerSplit&,const strata_ext::measurement::Identity&,
  RequestBinding,int device,DraftNetwork&,std::function<void()> idle_invalidate_target,
  std::function<bool(uint64_t,uint64_t)> prefill_control={},PreparedPrefix prepared={},std::function<void()> quiesce_target={});
 ~LayerSplitActorTarget();LayerSplitActorTarget(const LayerSplitActorTarget&)=delete;
 void prefill(const std::vector<uint32_t>&)override;
 StepProof step(uint32_t,uint64_t)override;
 const std::vector<float>& logits()const override;

 uint64_t known_cursor()const noexcept override;
 void set_control(ContinueWork)override;void drain()override;
 void invalidate_and_drain()noexcept override;bool completion_known()const noexcept override;
 ActorTransferStats transfer_stats()const override;
};

}
