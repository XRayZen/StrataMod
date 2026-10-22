#include "sampling.hpp"
#include <algorithm>
#include <cmath>
#include <numeric>
#include <stdexcept>
#include <unordered_set>
namespace strata_ext::deepseek41 {
namespace {void need(bool x,const char*s){if(!x)throw std::invalid_argument(s);}bool finite(double x){return std::isfinite(x);}}
void swap(EffectiveDistribution&a,EffectiveDistribution&b) noexcept {
 using std::swap;a.adjusted_logits_.swap(b.adjusted_logits_);a.raw_weights_.swap(b.raw_weights_);a.order_.swap(b.order_);
 swap(a.keep_,b.keep_);swap(a.total_,b.total_);swap(a.maximum_,b.maximum_);swap(a.diagnostic_logsum_,b.diagnostic_logsum_);
 swap(a.greedy_,b.greedy_);swap(a.prepared_,b.prepared_);swap(a.logprobs_,b.logprobs_);swap(a.top_logprobs_,b.top_logprobs_);
}
EffectiveDistribution::EffectiveDistribution(EffectiveDistribution&&other) noexcept:EffectiveDistribution(){swap(*this,other);}
EffectiveDistribution& EffectiveDistribution::operator=(EffectiveDistribution&&other) noexcept {if(this!=&other){EffectiveDistribution complete(std::move(other));swap(*this,complete);}return *this;}
EffectiveDistribution& EffectiveDistribution::operator=(const EffectiveDistribution&other){if(this!=&other){EffectiveDistribution complete(other);swap(*this,complete);}return *this;}
void EffectiveDistribution::validate_prepared() const {
 need(prepared_&&!adjusted_logits_.empty()&&adjusted_logits_.size()<=UINT32_MAX&&!order_.empty()&&order_.size()<=adjusted_logits_.size()&&keep_&&keep_<=order_.size()&&finite(total_)&&total_>0,"invalid or moved-from prepared distribution");
 need(greedy_?(keep_==1&&raw_weights_.empty()&&total_==1):(keep_<=raw_weights_.size()&&raw_weights_.size()<=order_.size()),"invalid prepared support shape");
}
uint32_t EffectiveDistribution::vocabulary() const {validate_prepared();return uint32_t(adjusted_logits_.size());}
std::vector<double> EffectiveDistribution::probabilities() const {
 validate_prepared();std::vector<double> result(adjusted_logits_.size(),0.);
 if(greedy_)result[order_[0]]=1.;else for(size_t i=0;i<keep_;++i)result[order_[i]]=raw_weights_[i]/total_;
 return result;
}
EffectiveDistribution effective_distribution(const std::vector<float>&input,const std::vector<uint32_t>&history,const SamplingOptions&o){
 need(!input.empty()&&input.size()<=UINT32_MAX,"empty/oversized vocabulary");
 EffectiveDistribution d;
 need(finite(o.temperature)&&o.temperature>=0&&o.temperature<=2,"temperature outside [0,2]");
 need(finite(o.top_p)&&o.top_p>0&&o.top_p<=1&&finite(o.min_p)&&o.min_p>=0&&o.min_p<=1&&o.top_k>=0,"candidate options");
 need(finite(o.repetition_penalty)&&o.repetition_penalty>0,"repetition penalty");
 need(finite(o.frequency_penalty)&&std::abs(o.frequency_penalty)<=2&&finite(o.presence_penalty)&&std::abs(o.presence_penalty)<=2,"official penalty range");
 need(o.top_logprobs<=20&&(o.logprobs||!o.top_logprobs),"logprob options");
 d.adjusted_logits_.assign(input.begin(),input.end());auto&logits=d.adjusted_logits_;for(double x:logits)need(finite(x),"nonfinite model logits");
 for(auto id:history)need(id<input.size(),"history original ID outside vocabulary");
 std::vector<uint64_t> counts(input.size(),0);
 if(!o.penalty_last_n||*o.penalty_last_n!=0){size_t start=0;if(o.penalty_last_n&&*o.penalty_last_n>0&&uint64_t(*o.penalty_last_n)<history.size())start=history.size()-size_t(*o.penalty_last_n);for(size_t i=start;i<history.size();++i)++counts[history[i]];}
 for(size_t id=0;id<counts.size();++id)if(counts[id]){auto&x=logits[id];x=x<0?x*o.repetition_penalty:x/o.repetition_penalty;x-=o.frequency_penalty*double(counts[id])+o.presence_penalty;}
 std::unordered_set<uint32_t> biases;for(auto [id,bias]:o.logit_bias){need(id<input.size()&&finite(bias)&&biases.insert(id).second,"invalid/duplicate logit bias");logits[id]+=bias;}
 for(double x:logits)need(finite(x),"nonfinite adjusted logits");
 d.order_.resize(input.size());auto&order=d.order_;std::iota(order.begin(),order.end(),0);
 std::sort(order.begin(),order.end(),[&](uint32_t a,uint32_t b){return logits[a]>logits[b]||(logits[a]==logits[b]&&a<b);});

 // Diagnostic LP stays before temperature/truncation; F32 LP validation is request-only.
 double maximum=logits[order[0]],sum=0;for(double x:logits)sum+=std::exp(x-maximum);
 d.maximum_=maximum;d.diagnostic_logsum_=std::log(sum);d.logprobs_=o.logprobs;d.top_logprobs_=o.top_logprobs;
 if(o.temperature==0){d.greedy_=true;d.keep_=1;d.total_=1.;}else{
  if(o.top_k>0&&uint64_t(o.top_k)<order.size())order.resize(size_t(o.top_k));
  auto&weights=d.raw_weights_;weights.reserve(order.size());double total=0;
  for(auto id:order){double w=std::exp((logits[id]-maximum)/o.temperature);if(w<o.min_p)break;weights.push_back(w);total+=w;}
  need(!weights.empty()&&finite(total)&&total>0,"empty probability support");
  size_t keep=weights.size();if(o.top_p<1){double c=0;for(size_t i=0;i<weights.size();++i){c+=weights[i];if(c>=o.top_p*total){keep=i+1;total=c;break;}}}
  d.total_=total;d.keep_=keep;
}
 d.prepared_=true;return d;
}
SampledToken EffectiveDistribution::describe_prepared(uint32_t actual_id)const{
 const auto&logits=adjusted_logits_;SampledToken result;result.id=actual_id;
 auto lp=[&](uint32_t id){float value=float((logits[id]-maximum_)-diagnostic_logsum_);need(std::isfinite(value)&&value<=0,"logprob not finite F32");return value;};
 if(logprobs_){result.alternatives.reserve(std::min<size_t>(top_logprobs_,logits.size()));result.logprob=lp(result.id);std::vector<uint32_t> alternatives(logits.size());std::iota(alternatives.begin(),alternatives.end(),0);std::partial_sort(alternatives.begin(),alternatives.begin()+std::min<size_t>(top_logprobs_,alternatives.size()),alternatives.end(),[&](uint32_t a,uint32_t b){return logits[a]>logits[b]||(logits[a]==logits[b]&&a<b);});for(size_t i=0;i<std::min<size_t>(top_logprobs_,alternatives.size());++i)result.alternatives.emplace_back(alternatives[i],lp(alternatives[i]));}
 return result;
}
SampledToken describe_distribution(const EffectiveDistribution&d,uint32_t actual_id){
 d.validate_prepared();need(actual_id<d.adjusted_logits_.size(),"diagnostic original ID outside vocabulary");return d.describe_prepared(actual_id);
}
SampledToken sample_distribution(const EffectiveDistribution&d,double uniform){
 d.validate_prepared();need(finite(uniform)&&uniform>=0&&uniform<1,"uniform draw outside [0,1)");
 const auto&order=d.order_;uint32_t id;
 if(d.greedy_)id=order[0];else{double target=uniform*d.total_,c=0;id=order[d.keep_-1];for(size_t i=0;i<d.keep_;++i){c+=d.raw_weights_[i];if(target<c){id=order[i];break;}}}
 return d.describe_prepared(id);
}
SampledToken sample_logits(const std::vector<float>&input,const std::vector<uint32_t>&history,const SamplingOptions&o,double uniform){
 need(!input.empty()&&input.size()<=UINT32_MAX,"empty/oversized vocabulary");
 need(finite(uniform)&&uniform>=0&&uniform<1,"uniform draw outside [0,1)");
 return sample_distribution(effective_distribution(input,history,o),uniform);
}
double RequestSampler::next_uniform(){return double(random_()>>11)*0x1.0p-53;}
SampledToken RequestSampler::sample(const std::vector<float>&v,const std::vector<uint32_t>&h,const SamplingOptions&o){double draw=next_uniform();return sample_logits(v,h,o,draw);}
}
