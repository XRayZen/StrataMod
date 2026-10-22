#pragma once
#include "artifact.hpp"
#include "device_ops.hpp"
#include "../../native/stats/measurement.hpp"
#include <map>
#include <array>
namespace strata_ext::deepseek41 {
struct KvStage { std::vector<uint8_t> bytes;std::string dtype;uint64_t rows=0,columns=0; };
struct KvTrace { std::map<std::string,KvStage> stages;uint64_t scratch_peak=0,primitive_peak=0;bool cleanup_unknown=false; };
struct KvWeight { SourceTensor original;std::vector<uint8_t> packed; };
using KvWeights=std::map<std::string,KvWeight>;
using KvFloats=std::map<std::string,std::vector<float>>;
// Synchronous host-wrapper qualification, not a resident device cache API.
KvTrace kv_project(const std::vector<float>& input,uint32_t batch,const KvWeights&,const measurement::Identity&,const std::string& device);
KvTrace kv_temporal(const KvTrace& actual_projection8,uint64_t length,uint32_t phase,const KvWeights&);
KvTrace kv_append_replay(const KvTrace& actual_projection8,uint64_t length,uint32_t phase,const KvWeights&);
KvTrace kv_control(const std::string& kind,const KvFloats& input,const std::vector<int64_t>& positions);
struct KvWindowView { enum class Kind { PrefillChunk,DecodeRing };Kind kind;uint64_t first_position=0,rows=0;std::vector<int32_t> indices; };
// Caller supplies identity/epoch. This metadata owns no global authority.
// Borrowed views expire at the next mutation. Publication occurs only after
// synchronous scalar/quantization work finishes; T18/T20 add device leases.
class KvSequence {
 uint64_t epoch_=0,position_=0;bool active_=false;
 std::array<uint64_t,4> rows_{};std::array<bool,3> pending_{};
 int writer_=-1;uint64_t published_=0;
public:
 void reset(uint64_t epoch);
 KvWindowView prefill(uint64_t count,uint64_t epoch);
 KvWindowView append(uint64_t position,uint64_t epoch);
 void publish(int writer,uint64_t rows,uint64_t epoch);
 uint64_t read(int layer,uint64_t epoch) const;
 void cancel(uint64_t epoch);
 void reuse_exact_prefix(uint64_t epoch);
 uint64_t position()const{return position_;}uint64_t epoch()const{return epoch_;}
 uint64_t rows(int source)const;bool pending(int source)const;
};
}
