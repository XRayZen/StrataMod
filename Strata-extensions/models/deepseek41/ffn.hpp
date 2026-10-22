#pragma once
#include "artifact.hpp"
#include "device_ops.hpp"
#include "../../native/stats/measurement.hpp"
#include <functional>
#include <map>
namespace strata_ext::deepseek41 {
struct Matrix {
 SourceTensor original;
 uint64_t source_absolute_offset=0;
 uint32_t type=0,rows=0,k=0;
 std::vector<uint8_t> packed;
};
using MatrixProvider=std::function<Matrix(const std::string&,uint32_t)>;
struct Stage { std::vector<uint8_t> bytes;uint64_t rows=0,columns=0;std::string dtype; };
struct AtomicRequest {
 std::string role;uint32_t expert=0,type=0,rows=0,k=0,batch=0;
 SourceTensor source;uint64_t source_absolute_offset=0,packed=0,input=0,output=0,owned_device=0;
};
struct FfnStats {
 uint64_t matrix_owned_peak=0,actual_scratch_peak=0,host_matrix_scope_peak=0,trace_payload_bytes=0;
 bool cleanup_unknown=false;
 std::vector<AtomicRequest> requests;
};
struct FfnTrace { std::map<std::string,Stage> stages;FfnStats stats; };
// Synchronous host-vector qualification interface. All numerical primitives are
// HIP; the caller supplies already bound raw matrices. This convenience API is
// not the later engine's asynchronous owner/lease/stream integration.
FfnTrace run_ffn(const std::vector<float>&,uint32_t batch,const std::vector<uint8_t>& image_bias,
                 const MatrixProvider&,const measurement::Identity&,const std::string& device_identity);
// Controlled qualification inputs use the same HIP kernels as run_ffn;
// no learned-weight/full-source qualification is implied.
FfnTrace run_boundaries(const std::vector<float>& casts,const std::vector<float>& qdq,
 const std::vector<float>& logits,const std::vector<float>& bias,const std::vector<float>& bias_vl,
 const std::vector<uint8_t>& masks,const std::vector<float>& gate,const std::vector<float>& up,const std::vector<float>& routes);
}
