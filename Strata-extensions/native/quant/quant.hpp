#pragma once
#include <cstddef>
#include <cstdint>
#include <vector>
namespace strata_ext::quant {
// T09 host-vector wrappers own short-lived allocations and synchronous transfers.
// Packed device arithmetic lives in quant.hip. Engine I/O/stream lifetime is
// deliberately not qualified by these fixture convenience interfaces.
// Checked non-owning launch boundary. The owner serializes lease mutation and
// retains allocations/stream until its completion event (and output D2H) drains.
// A lease is invalidated BEFORE allocation/stream reuse; no ownership registry.
struct ProjectionLease { uint64_t generation=1; bool active=true; };
struct PackedDeviceView { const uint8_t* data; uint32_t type; std::size_t rows,k,bytes; int device; };
class DeviceProjection {
public:
    DeviceProjection() = default;
private:
    PackedDeviceView packed_{};const float* input_=nullptr;float* output_=nullptr;
    std::size_t input_bytes_=0,output_bytes_=0,output_stride_=0;void* stream_=nullptr;
    const ProjectionLease* lease_=nullptr;uint64_t generation_=0;int device_=-1;
    friend DeviceProjection checked_projection(PackedDeviceView,const float*,std::size_t,float*,std::size_t,void*,const ProjectionLease&);
    friend DeviceProjection checked_projection_strided(PackedDeviceView,const float*,std::size_t,float*,std::size_t,std::size_t,void*,const ProjectionLease&);
    friend void project_into(const DeviceProjection&,std::size_t);
};
// Pointer/stream APIs are observed once per owner allocation/stream generation.
DeviceProjection checked_projection(PackedDeviceView,const float* input,std::size_t input_bytes,
                                     float* output,std::size_t output_bytes,void* stream,
                                     const ProjectionLease& lease);
// Output row tiling preserves FULL K and the canonical reduction. output_stride
// is the caller's batch-major destination row width; legacy API uses v.rows.
DeviceProjection checked_projection_strided(PackedDeviceView,const float* input,std::size_t input_bytes,
 float* output,std::size_t output_bytes,std::size_t output_stride,void* stream,const ProjectionLease&);
// Raw decode into an owner-provided device buffer, with native format semantics.
void decode_into(PackedDeviceView,float* output,std::size_t output_bytes,void* stream,const ProjectionLease&);
// No allocation/copy/free/synchronization. Caller records last-use on same stream.
void project_into(const DeviceProjection&,std::size_t batch);
std::size_t packed_bytes(uint32_t type, std::size_t count);
void validate_projection_shape(uint32_t type, std::size_t rows, std::size_t k, std::size_t batch);
std::vector<float> decode(const std::vector<uint8_t>& raw, uint32_t type, std::size_t count);
std::vector<float> project(const std::vector<uint8_t>& raw, uint32_t type,
                          std::size_t rows, std::size_t k, std::size_t batch,
                          const std::vector<float>& inputs);
}
