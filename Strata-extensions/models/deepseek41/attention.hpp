#pragma once
#include "kv.hpp"
#include "device_ops.hpp"
namespace strata_ext::deepseek41 {
// Explicit synchronous host fixture views. SourceTensor retains original file
// coordinates; these wrappers confer neither full-source nor resident status.
struct AttentionArray {std::vector<float> values;uint64_t rows=0,columns=0;};
bool index_candidate_pruning(int key_writer);
struct AttentionIndexView {
 int writer=0;uint64_t epoch=0,ratio=0,positions=0;
 std::vector<float> decoded; // positions x 128, activation FP4 QDQ values
 void validate(int consumer,uint64_t expected_epoch)const;
};
struct AttentionCandidates {
 int writer=20;uint64_t epoch=0,queries=0,positions=0;
 std::vector<uint8_t> mask;std::vector<int64_t> visible;
 void validate(uint64_t expected_epoch)const;
};
KvTrace attention_primitive(const std::string&kind,const KvFloats&,
 const std::map<std::string,std::vector<int64_t>>&integer_inputs,
 uint64_t rows,uint64_t columns);
KvTrace attention_projection(const std::vector<float>&input,uint32_t batch,
 const KvWeights&,const measurement::Identity&,const std::string&device);
KvTrace attention_long(const KvFloats&,const std::vector<int64_t>&visible);
KvTrace attention_short(const std::vector<float>&input8,uint64_t length,
 uint32_t phase,const KvWeights&,const KvWeights&compression_weights,
 const measurement::Identity&,const std::string&device);
}
