#pragma once
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace strata_ext::artifact {
// These descriptors are not runtime ownership/activation authorities.
// Caller binds revision/LFS/layout provenance and strict T03 prefix SHA first.
struct TensorSpan {
    uint32_t shard_index = 0;
    uint32_t type_id = 0;
    std::string name;
    std::vector<uint64_t> dims_ggml;
    uint64_t row_bytes = 0, absolute_offset = 0, bytes = 0;
};
struct PrefixIndex {
    uint64_t split_no = 0, split_count = 0, split_total = 0;
    std::vector<TensorSpan> tensors;
};
// Reuses the base parser on actual PREFIX bytes only. It never calls
// tensor_data() or treats the prefix mmap as the original tensor payload.
PrefixIndex inspect_prefix(const std::filesystem::path&, uint64_t logical_source_bytes);
std::vector<TensorSpan> merge_prefixes(const std::vector<PrefixIndex>&);

// Physical bytes are a bounded view at an original SOURCE absolute offset.
// A whole source view would use base0; extracted fixtures retain their base.
struct FixtureView {
    std::filesystem::path path;
    uint64_t source_absolute_offset = 0, bytes = 0;
    std::vector<uint8_t> read_exact(uint64_t logical_offset, uint64_t count) const;
};
// Qualified fixed T03 native layouts only. IDs67/117 are not aliases for43.
std::vector<float> decode_blocks(uint32_t type_id, const std::vector<uint8_t>&);
}
