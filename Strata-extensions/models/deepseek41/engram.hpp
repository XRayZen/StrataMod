#pragma once
#include <cstdint>
#include <filesystem>
#include <vector>

namespace strata_ext::deepseek41::engram {
struct Config {
    std::vector<uint32_t> token_map;
    std::vector<uint64_t> multipliers,primes,offsets;
    uint32_t pad=0,compressed_size=0;
    void validate() const;
};
// Caller first binds the actual strict T03 prefix SHA. This uses the existing
// generic GGUF parser; it grants no original-file or tokenizer authority.
Config inspect_metadata(const std::filesystem::path&);
// Per-sequence state. Caller retains immutable Config, synchronizes this instance under
// its existing coordinator, and connects its request/epoch owner at T20.
// Only three prior compressed IDs are needed; no normal context size limit.
class History {
    const Config& config_;
    std::vector<int64_t> recent_;
    uint64_t position_=0;
public:
    explicit History(const Config&);
    uint64_t position() const{return position_;}
#ifdef STRATA_DEEPSEEK_T36_FIXTURE_CAPTURE
    // Synchronous fixture read only: values are oldest to newest, at most three.
    // Caller serializes History and must not retain values or reenter/mutate it.
    template<class Visitor>
    void fixture_visit_history(Visitor&& visitor) const {
        visitor(position_, static_cast<const int64_t*>(recent_.data()),
                static_cast<uint64_t>(recent_.size()));
    }
#endif
    void reset(){position_=0;recent_.clear();}
    // [token][layer1,layer14][ngram2,3,4][8heads], global table row IDs.
    // False mask is a DEAD boundary; even masked IDs must be valid raw IDs.
    std::vector<uint64_t> append(uint64_t start,const std::vector<uint32_t>& raw,const std::vector<uint8_t>& mask);
};
void validate_indices(uint64_t bank_rows,const std::vector<uint32_t>& indices);
// Caller owns all device buffers and their stream lifetime. No allocation,
// upload/readback or synchronization is hidden here. error is a device int,
// initialized to zero by the caller; invalid indices set it without reading OOB.
void gather_device(const uint8_t* bank,uint64_t bank_rows,const uint32_t* indices,
                   uint64_t requests,float* decoded,uint16_t* bf16,int* error,void* stream);
}
