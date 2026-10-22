#pragma once
#include <cstdint>
#include <optional>
#include <random>
#include <utility>
#include <vector>
namespace strata_ext::deepseek41 {
// Host adaptation of fixed-base q36_engine host sampling: requested Core logits
// are already host F32. No model CPU fallback and no implicit 64-candidate cap.
struct SamplingOptions {
 double temperature=1,top_p=1,min_p=0,repetition_penalty=1,frequency_penalty=0,presence_penalty=0;
 int64_t top_k=0;std::optional<int64_t> penalty_last_n;
 bool logprobs=false;uint32_t top_logprobs=0;
 std::vector<std::pair<uint32_t,double>> logit_bias;
};
struct SampledToken { uint32_t id=0;float logprob=0;std::vector<std::pair<uint32_t,float>> alternatives; };
class EffectiveDistribution {
 std::vector<double> adjusted_logits_,raw_weights_;
 std::vector<uint32_t> order_;
 std::size_t keep_=0;
 double total_=0,maximum_=0,diagnostic_logsum_=0;
 bool greedy_=false,prepared_=false,logprobs_=false;
 uint32_t top_logprobs_=0;
 EffectiveDistribution()=default;
 void validate_prepared() const;
 SampledToken describe_prepared(uint32_t actual_id) const;
 friend EffectiveDistribution effective_distribution(const std::vector<float>&,const std::vector<uint32_t>&,const SamplingOptions&);
 friend SampledToken sample_distribution(const EffectiveDistribution&,double);
 friend SampledToken describe_distribution(const EffectiveDistribution&,uint32_t);
public:
 EffectiveDistribution(const EffectiveDistribution&)=default;
 EffectiveDistribution& operator=(const EffectiveDistribution&);
 EffectiveDistribution(EffectiveDistribution&&) noexcept;
 EffectiveDistribution& operator=(EffectiveDistribution&&) noexcept;
 friend void swap(EffectiveDistribution&,EffectiveDistribution&) noexcept;
 uint32_t vocabulary() const;
 std::vector<double> probabilities() const;
};
// Sole sampler transform. Dense probabilities are exported only on explicit request.
EffectiveDistribution effective_distribution(const std::vector<float>&,const std::vector<uint32_t>&,const SamplingOptions&);
SampledToken sample_distribution(const EffectiveDistribution&,double uniform);
// Existing target diagnostics for an already selected original ID; no transform/RNG.
SampledToken describe_distribution(const EffectiveDistribution&,uint32_t actual_id);
// uniform is explicitly [0,1); separated from RNG for independent CDF vectors.
SampledToken sample_logits(const std::vector<float>&,const std::vector<uint32_t>&history,const SamplingOptions&,double uniform);
class RequestSampler {
 std::mt19937_64 random_;
public:
 explicit RequestSampler(uint64_t seed):random_(seed){}
 double next_uniform();
 SampledToken sample(const std::vector<float>&v,const std::vector<uint32_t>&h,const SamplingOptions&o);
};
}
