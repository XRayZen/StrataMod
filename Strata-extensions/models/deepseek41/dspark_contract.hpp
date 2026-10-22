#pragma once
#include <cstdint>
#include <string>
#include <vector>

namespace strata_ext::dspark {
// Original tensor geometry is retained; a fixture is a subspan, not a new tensor.
struct SourceSpan {
    std::string name, revision, lfs;
    uint32_t type;
    std::vector<uint64_t> dims;
    uint64_t tensor_offset, tensor_bytes, file_bytes, offset, bytes;
};
struct Request {
    uint64_t owner, epoch, position, width;
    std::vector<uint32_t> original_ids;
};
struct Tap {
    uint32_t target_layer, capture_layer, hc, hidden;
    uint64_t owner, epoch, position;
};
void validate(const SourceSpan&);
void validate(const Request&);
void validate(const Request&, const std::vector<Tap>&);
uint32_t widen_f16(uint16_t code);
std::vector<uint16_t> hc_mean(const std::vector<float>&);
float confidence_dot(const std::vector<float>& hidden, const std::vector<float>& markov,
                     const std::vector<float>& weights);
double accept(const std::vector<double>& p, const std::vector<double>& q, uint32_t id);
std::vector<double> residual(const std::vector<double>& p, const std::vector<double>& q);
// Verification and proposal scheduling are separate. Future confidence is absent
// from this interface, so it cannot change the verified prefix.
std::vector<uint32_t> verified_prefix(const std::vector<uint32_t>& proposals,
                                    const std::vector<bool>& accepted, uint32_t replacement,
                                    uint32_t bonus, bool cancelled);
}
