#pragma once
#include <cstdint>
#include <string>
#include <vector>
namespace strata_ext::dspark::t38 {
struct Tensor {std::string name;uint32_t type=0;std::vector<uint64_t> dims;uint64_t offset=0,bytes=0,row_bytes=0;};
struct Asset {uint64_t data_start=0,file_bytes=0;std::vector<Tensor> tensors;};
struct Span {Tensor tensor;uint64_t matrix=0,row=0,count=0,offset=0,bytes=0;};
constexpr uint64_t artifact_bytes=7965746848ull;
// Fixed T37 metadata schema, not proof of full payload identity. Caller retains T37 receipt.
Asset inspect_prefix(const std::vector<uint8_t>&,uint64_t file_bytes);
Span required_span(const Asset&,const std::string&,uint64_t matrix,uint64_t first,uint64_t count);
std::vector<uint8_t> read_span(const std::string& path,const Span&,uint64_t byte_credit);

struct ProjectionWave {uint64_t first=0;uint32_t rows=0;uint64_t input_bytes=0,output_bytes=0;};
std::vector<ProjectionWave> projection_wave_offsets(uint64_t batch,uint64_t k,uint64_t output_stride,
 uint64_t output_rows,uint64_t input_bytes,uint64_t output_bytes,const std::vector<uint32_t>& waves);
}
