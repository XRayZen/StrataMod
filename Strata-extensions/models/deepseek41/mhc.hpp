#pragma once
#include "artifact.hpp"
#include "device_ops.hpp"
#include <map>
#include "../../native/stats/measurement.hpp"
namespace strata_ext::deepseek41 {
struct MhcStage { std::vector<float> values;uint64_t rows=0,columns=0; };
struct MhcWeights { SourceTensor original_fn;std::vector<uint8_t> fn;std::vector<float> base,scale,norm; };
struct MhcRequest { SourceTensor source;uint64_t batch=0,packed=0,input=0,output=0; };
struct MhcTrace { std::vector<MhcRequest> requests; std::map<std::string,MhcStage> stages;uint64_t scratch_peak=0,primitive_peak=0;bool cleanup_unknown=false; };
// Synchronous qualification API. Injected outputs isolate staggered boundaries;
// these are not substitutes for T20's real attention/FFN execution.
MhcTrace run_staggered(const std::vector<float>& residual,uint32_t batch,const MhcWeights& attn,const MhcWeights& ffn,const std::vector<std::vector<float>>& injected,const measurement::Identity&,const std::string& device);
MhcTrace run_controlled_mixes(const std::vector<float>& mixes,uint32_t batch);
}
