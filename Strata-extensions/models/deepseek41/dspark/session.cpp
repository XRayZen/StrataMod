#include "session.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <utility>
namespace strata_ext::dspark::t38 {
namespace {
void need(bool x,const char*m){if(!x)throw std::invalid_argument(m);}
void uniform_ok(double u){need(std::isfinite(u)&&u>=0&&u<1,"uniform outside [0,1)");}
uint64_t mix(uint64_t z){z=(z^(z>>30))*0xbf58476d1ce4e5b9ull;z=(z^(z>>27))*0x94d049bb133111ebull;return z^(z>>31);}
void state_ok(const DraftState&s){need(s.valid&&s.owner&&s.epoch,"invalid draft checkpoint");for(auto p:s.stage_cursor)need(p==s.cursor,"draft stage cursor mismatch");}
}
void validate_distribution(const Probabilities&p){
 need(!p.empty()&&p.size()<=129280,"distribution vocabulary");double sum=0;
 for(auto x:p){need(std::isfinite(x)&&x>=0&&x<=1,"distribution value");sum+=x;}
 need(std::isfinite(sum)&&std::abs(sum-1)<=1.e-12,"distribution must already be normalized");
}
uint32_t draw_distribution(const Probabilities&p,double u){validate_distribution(p);uniform_ok(u);double c=0;uint32_t last=0;for(uint32_t i=0;i<p.size();++i){if(p[i]>0)last=i;c+=p[i];if(u<c)return i;}return last;}
Probabilities residual_distribution(const Probabilities&p,const Probabilities&q){
 validate_distribution(p);validate_distribution(q);need(p.size()==q.size(),"p/q vocabulary mismatch");Probabilities r(p.size());double sum=0;
 for(size_t i=0;i<p.size();++i){r[i]=std::max(p[i]-q[i],0.);sum+=r[i];}
 need(std::isfinite(sum)&&sum>0,"zero residual is unreachable after a valid rejection");for(auto&x:r)x/=sum;validate_distribution(r);return r;
}
namespace {
template<class ResidualDraw>Decision decide_verified(const Probabilities&p,const Probabilities&q,uint32_t id,double a,ResidualDraw&&draw){
 double rate=std::min(1.,p[id]/q[id]);if(a<rate)return {true,id,rate};auto residual=residual_distribution(p,q);return {false,draw_distribution(residual,draw()),rate};
}
}
Decision verify(const Probabilities&p,const Probabilities&q,uint32_t id,double a,double r){
 validate_distribution(p);validate_distribution(q);uniform_ok(a);uniform_ok(r);need(p.size()==q.size()&&id<q.size()&&q[id]>0,"proposal absent from actual q support");return decide_verified(p,q,id,a,[&]{return r;});
}
Decision verify_lazy(const Probabilities&p,const Probabilities&q,uint32_t id,double a,const std::function<double()>&draw){
 validate_distribution(p);validate_distribution(q);uniform_ok(a);need(p.size()==q.size()&&id<q.size()&&q[id]>0,"proposal absent from actual q support");return decide_verified(p,q,id,a,[&]{need(bool(draw),"residual draw required on rejection");return draw();});
}
NamespaceRng::NamespaceRng(uint64_t seed){for(unsigned i=0;i<5;++i)random_[i].seed(i==0?seed:mix(seed^i));}
uint64_t NamespaceRng::draw53(RngSpace s){auto i=unsigned(s);need(i<5,"RNG namespace");auto word=random_[i]()>>11;
#ifdef STRATA_T38_SESSION_TRACE
 FixtureTraceEvent event{FixtureTraceKind::Draw};event.space=s;event.ordinal=trace_ordinals_[i]++;event.word53=word;trace_.publish(event);
#endif
 return word;}
double NamespaceRng::uniform(RngSpace s){return double(draw53(s))*0x1.0p-53;}
Session::Session(RequestBinding b,uint64_t p,uint64_t max,uint32_t v):binding_(std::move(b)),maximum_(max),vocabulary_(v){
 need(binding_.owner&&binding_.epoch&&!binding_.bundle.empty()&&v>1&&v<=129280,"session binding");need(max<=UINT64_MAX-p,"cursor overflow");ledger_.prompt=p;ledger_.cursor=p;if(!max)ledger_.finish=Finish::Length;
}
void Session::prepare_emit(uint32_t id){need(ledger_.finish==Finish::Running&&!ledger_.pending,"emit requires a healthy no-pending boundary");need(id<vocabulary_&&ledger_.emitted.size()<maximum_,"emission vocabulary/budget");
 // Prepare exactly the next append with vector's ordinary growth strategy.
 if(ledger_.emitted.size()==ledger_.emitted.capacity()){ledger_.emitted.push_back(id);ledger_.emitted.pop_back();}
}
void Session::commit_emit(uint32_t id)noexcept{ledger_.emitted.push_back(id);ledger_.pending=id;}
void Session::finish_emit(bool cancel)noexcept{if(*ledger_.pending==1)ledger_.finish=Finish::Eos;else if(ledger_.emitted.size()==maximum_)ledger_.finish=Finish::Length;else if(cancel)ledger_.finish=Finish::Cancel;}
void Session::emit(uint32_t id,bool cancel){prepare_emit(id);commit_emit(id);finish_emit(cancel);}
void Session::cancel_before_emit(){need(!ledger_.pending,"pending tail requires explicit after-emit cancellation");if(ledger_.finish==Finish::Running)ledger_.finish=Finish::Cancel;}
void Session::invalidate()noexcept{ledger_.finish=Finish::Invalid;}
void Session::cancel_final()noexcept{ledger_.finish=Finish::Cancel;}
void Session::recipe_stop_final()noexcept{ledger_.finish=Finish::RecipeStop;}
void Session::advance_pending(TargetAdapter&target){
 need(ledger_.finish==Finish::Running&&ledger_.pending,"terminal or absent pending token cannot be processed");auto id=*ledger_.pending;auto before=ledger_.cursor;
 try{auto p=target.step(id,before);need(p.binding.owner==binding_.owner&&p.binding.epoch==binding_.epoch&&p.binding.bundle==binding_.bundle,"target owner/epoch/bundle");need(p.before==before&&p.after==before+1,"target processed cursor");
  for(unsigned i=0;i<3;++i){auto t=p.taps[i];need(t.owner==binding_.owner&&t.epoch==binding_.epoch&&t.position==before&&t.layer==37+i&&t.hc==4&&t.hidden==5120,"target tap provenance/geometry");}
  ledger_.processed.push_back(id);++ledger_.processed_generated;++ledger_.cursor;ledger_.pending.reset();
 }catch(...){invalidate();target.invalidate_and_drain();throw;}
}
const char* finish_name(Finish f){switch(f){case Finish::Running:return "running";case Finish::Length:return "length";case Finish::Eos:return "eos";case Finish::Cancel:return "cancel";case Finish::RecipeStop:return "recipe_stop";default:return "invalid";}}
DraftTransaction::DraftTransaction(DraftState&s):state_(s),saved_(s){state_ok(s);}
DraftTransaction::~DraftTransaction()noexcept{if(!closed_)std::swap(state_,saved_);}
void DraftTransaction::restore(){need(!closed_,"closed draft transaction");DraftState copy=saved_;std::swap(state_,copy);}
void DraftTransaction::commit(const DraftState&processed){need(!closed_,"closed draft transaction");state_ok(processed);need(processed.owner==saved_.owner&&processed.epoch==saved_.epoch&&processed.cursor>=saved_.cursor,"draft commit provenance/cursor");DraftState copy=processed;std::swap(state_,copy);closed_=true;}
RequestActor::RequestActor(ActorTarget&t,ActorDraft&d,RequestBinding b,uint64_t seed):target_(t),draft_(d),binding_(std::move(b)),rng_(seed){need(binding_.owner&&binding_.epoch&&!binding_.bundle.empty(),"actor request binding");}
ActorResult RequestActor::run(const std::vector<uint32_t>&prompt,uint64_t maximum,uint64_t width,const strata_ext::deepseek41::SamplingOptions&options,const std::function<ActorStop()>&stop,const std::function<void(const strata_ext::deepseek41::SampledToken&)>&emit){
 using namespace strata_ext::deepseek41;need(!used_,"actor request cannot be reused");used_=true;need(!prompt.empty()&&width&&emit,"actor prompt/width/emitter");ActorResult result;std::optional<Session> session;
 ActorStop reason=ActorStop::Continue;
 auto stopped=[&]{auto next=stop?stop():ActorStop::Continue;if(next==ActorStop::Cancel||reason!=ActorStop::Cancel&&next==ActorStop::RecipeStop)reason=next;return reason!=ActorStop::Continue;};ContinueWork work=[&]{return !stopped();};
 auto finish_stop=[&]{if(reason==ActorStop::RecipeStop)session->recipe_stop_final();else session->cancel_final();};
 if(!maximum){result.ledger.finish=Finish::Length;result.known_target_cursor=target_.known_cursor();result.draft_cursor=draft_.cursor();result.context_valid=result.known_target_cursor==result.draft_cursor&&result.known_target_cursor<=prompt.size();result.completion_known=target_.completion_known()&&draft_.completion_known();return result;}
 target_.set_control(work);
 try{
  need(target_.known_cursor()==draft_.cursor()&&target_.known_cursor()<=prompt.size(),"actor prepared common prefix");if(stopped())throw DraftCancelled{};target_.prefill(prompt);need(target_.known_cursor()==prompt.size()&&draft_.cursor()==prompt.size(),"prompt successful common cursor");auto history=prompt;auto vocabulary=target_.logits().size();need(vocabulary>1&&vocabulary<=129280,"actor target logits vocabulary");session.emplace(binding_,prompt.size(),maximum,uint32_t(vocabulary));
  auto common=[&]{need(target_.known_cursor()==session->ledger().cursor&&draft_.cursor()==session->ledger().cursor,"successful common processed cursor");};
  auto emit_one=[&](const SampledToken&token){if(stopped())throw DraftCancelled{};session->prepare_emit(token.id);
   if(history.size()==history.capacity()){history.push_back(token.id);history.pop_back();}
   emit(token);session->commit_emit(token.id);history.push_back(token.id);
#ifdef STRATA_T38_SESSION_TRACE
   {FixtureTraceEvent e{FixtureTraceKind::Emit};e.id=token.id;e.ledger=&session->ledger();trace_.publish(e);}
#endif
   auto halt=stopped();session->finish_emit(halt);if(halt&&reason==ActorStop::RecipeStop)session->recipe_stop_final();if(session->ledger().finish==Finish::Running){session->advance_pending(target_);common();
#ifdef STRATA_T38_SESSION_TRACE
   {FixtureTraceEvent e{FixtureTraceKind::Processed};e.id=token.id;e.ledger=&session->ledger();trace_.publish(e);}
#endif
   }};
  while(session->ledger().finish==Finish::Running){
   common();if(stopped()){finish_stop();break;}auto proposal=draft_.propose(width,options,history,rng_,work);if(stopped())throw DraftCancelled{};
   if(proposal.seed_only){need(proposal.ids.empty()&&proposal.q.empty()&&proposal.raw_confidence.empty(),"seed-only proposal shape");auto p=effective_distribution(target_.logits(),history,options);emit_one(sample_distribution(p,rng_.uniform(RngSpace::Target)));continue;}
   need(!proposal.ids.empty()&&proposal.ids.size()<=width&&proposal.q.size()==proposal.ids.size()&&proposal.raw_confidence.size()==proposal.ids.size(),"draft proposal fields");for(size_t i=0;i<proposal.ids.size();++i){validate_distribution(proposal.q[i]);need(proposal.q[i].size()==vocabulary&&proposal.ids[i]<vocabulary&&proposal.q[i][proposal.ids[i]]>0,"draft proposal original ID/support");}
#ifdef STRATA_T38_SESSION_TRACE
   for(size_t i=0;i<proposal.ids.size();++i){FixtureTraceEvent e{FixtureTraceKind::Proposal};e.index=i;e.id=proposal.ids[i];e.q=&proposal.q[i];trace_.publish(e);}
#endif
   bool all=true;
   for(size_t i=0;i<proposal.ids.size();++i){if(stopped())throw DraftCancelled{};auto target=effective_distribution(target_.logits(),history,options);auto p=target.probabilities();auto decision=verify_lazy(p,proposal.q[i],proposal.ids[i],rng_.uniform(RngSpace::Accept),[&]{return rng_.uniform(RngSpace::Residual);});
#ifdef STRATA_T38_SESSION_TRACE
    {FixtureTraceEvent e{FixtureTraceKind::Verify};e.index=i;e.id=decision.id;e.accepted=decision.accepted;e.acceptance=decision.acceptance;e.p=&p;e.q=&proposal.q[i];trace_.publish(e);}
#endif
    emit_one(describe_distribution(target,decision.id));if(!decision.accepted){all=false;break;}if(session->ledger().finish!=Finish::Running)break;}
   if(all&&session->ledger().finish==Finish::Running){if(stopped())throw DraftCancelled{};auto p=effective_distribution(target_.logits(),history,options);
#ifdef STRATA_T38_SESSION_TRACE
    {FixtureTraceEvent e{FixtureTraceKind::Bonus};try{auto probabilities=p.probabilities();e.p=&probabilities;trace_.publish(e);}catch(...){e.p=nullptr;e.incomplete=true;trace_.publish(e);}}
#endif
    emit_one(sample_distribution(p,rng_.uniform(RngSpace::Bonus)));}
  }
  if(stopped())finish_stop();
  if(session->ledger().finish==Finish::Cancel||session->ledger().finish==Finish::RecipeStop){target_.invalidate_and_drain();draft_.invalidate_and_drain();}else{target_.drain();draft_.drain();common();result.context_valid=true;}
 }catch(const DraftCancelled&e){if(session)finish_stop();else{result.ledger.prompt=target_.known_cursor();result.ledger.cursor=target_.known_cursor();result.ledger.finish=reason==ActorStop::RecipeStop?Finish::RecipeStop:Finish::Cancel;}result.error=e.what();target_.invalidate_and_drain();draft_.invalidate_and_drain();}
 catch(const std::exception&e){if(session)session->invalidate();else{result.ledger.prompt=target_.known_cursor();result.ledger.cursor=target_.known_cursor();result.ledger.finish=Finish::Invalid;}result.error=e.what();target_.invalidate_and_drain();draft_.invalidate_and_drain();}
 catch(...){if(session)session->invalidate();else{result.ledger.prompt=target_.known_cursor();result.ledger.cursor=target_.known_cursor();result.ledger.finish=Finish::Invalid;}result.error="unknown actor failure";target_.invalidate_and_drain();draft_.invalidate_and_drain();}
 target_.set_control({});if(session)result.ledger=session->ledger();result.known_target_cursor=target_.known_cursor();result.draft_cursor=draft_.cursor();result.completion_known=target_.completion_known()&&draft_.completion_known();
#ifdef STRATA_T38_SESSION_TRACE
 {FixtureTraceEvent e{FixtureTraceKind::Terminal};e.ledger=&result.ledger;trace_.publish(e);}
#endif
 return result;
}

}
