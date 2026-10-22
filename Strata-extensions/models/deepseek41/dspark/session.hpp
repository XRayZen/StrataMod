#pragma once
#include "draft.hpp"
#include "target_adapter.hpp"
#include "../sampling.hpp"
#include <array>
#include <optional>
#include <random>
#include <string>
#include <vector>
namespace strata_ext::dspark::t38 {
using Probabilities=std::vector<double>;
void validate_distribution(const Probabilities&);
uint32_t draw_distribution(const Probabilities&,double uniform);
struct Decision {bool accepted=false;uint32_t id=0;double acceptance=0;};
Decision verify(const Probabilities&p,const Probabilities&q,uint32_t proposal,double accept_u,double residual_u);
Decision verify_lazy(const Probabilities&,const Probabilities&,uint32_t,double accept_u,const std::function<double()>& residual_uniform);
Probabilities residual_distribution(const Probabilities&,const Probabilities&);
enum class RngSpace:unsigned {Target,Proposal,Accept,Residual,Bonus};
#ifdef STRATA_T38_SESSION_TRACE
struct FixtureTraceEvent;
// Synchronous borrowed observation only. A sink must preown its finite storage;
// overflow is diagnostic and must never change the actor or consume RNG.
struct FixtureTraceSink {
 void*context=nullptr;
 void(*record)(void*,const FixtureTraceEvent&)noexcept=nullptr;
 void publish(const FixtureTraceEvent&e)const noexcept{if(record)record(context,e);}
};
#endif
class NamespaceRng {
 std::array<std::mt19937_64,5> random_;
#ifdef STRATA_T38_SESSION_TRACE
 FixtureTraceSink trace_;std::array<uint64_t,5>trace_ordinals_{};
#endif
public:
 explicit NamespaceRng(uint64_t seed);
 uint64_t draw53(RngSpace);double uniform(RngSpace);
#ifdef STRATA_T38_SESSION_TRACE
 void set_fixture_trace(FixtureTraceSink sink)noexcept{trace_=sink;}
#endif
};
enum class Finish {Running,Length,Eos,Cancel,RecipeStop,Invalid};
struct Ledger {
 uint64_t prompt=0,processed_generated=0,cursor=0;
 std::vector<uint32_t> emitted,processed;
 std::optional<uint32_t> pending;
 Finish finish=Finish::Running;
};
#ifdef STRATA_T38_SESSION_TRACE
enum class FixtureTraceKind {Draw,Proposal,Verify,Bonus,Emit,Processed,Terminal};
struct FixtureTraceEvent {
 FixtureTraceKind kind;RngSpace space=RngSpace::Target;
 uint64_t ordinal=0,word53=0,index=0;uint32_t id=0;
 bool accepted=false,incomplete=false;double acceptance=0;
 const Probabilities*p=nullptr,*q=nullptr;const Ledger*ledger=nullptr;
};
#endif
class Session {
 RequestBinding binding_;uint64_t maximum_;uint32_t vocabulary_;Ledger ledger_;
 friend class RequestActor;
 void prepare_emit(uint32_t id);
 void commit_emit(uint32_t id)noexcept;
 void finish_emit(bool cancel)noexcept;
public:
 Session(RequestBinding,uint64_t prompt_processed,uint64_t maximum,uint32_t vocabulary=129280);
 const Ledger& ledger()const noexcept{return ledger_;}
 void emit(uint32_t id,bool cancel_after_emit=false);
 void cancel_before_emit();
 void advance_pending(TargetAdapter&); // successes only; terminal pending is never stepped
 void invalidate()noexcept;
 void cancel_final()noexcept;
 void recipe_stop_final()noexcept;
};
const char* finish_name(Finish);
enum class ActorStop {Continue,Cancel,RecipeStop};
// completion_known=false requires caller-held actual owners; do not free/rebind.
struct ActorResult {Ledger ledger;uint64_t known_target_cursor=0,draft_cursor=0;bool context_valid=false,completion_known=false;std::string error;};
class RequestActor {
 ActorTarget&target_;ActorDraft&draft_;RequestBinding binding_;NamespaceRng rng_;bool used_=false;
#ifdef STRATA_T38_SESSION_TRACE
 FixtureTraceSink trace_;
#endif
public:
 RequestActor(ActorTarget&,ActorDraft&,RequestBinding,uint64_t seed);
#ifdef STRATA_T38_SESSION_TRACE
 void set_fixture_trace(FixtureTraceSink sink)noexcept{trace_=sink;rng_.set_fixture_trace(sink);}
#endif
 ActorResult run(const std::vector<uint32_t>&prompt,uint64_t maximum,uint64_t width,
  const strata_ext::deepseek41::SamplingOptions&,
  const std::function<ActorStop()>&stop,const std::function<void(const strata_ext::deepseek41::SampledToken&)>&emit);
};

}
