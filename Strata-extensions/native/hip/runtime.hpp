#pragma once
#include <hip/hip_runtime.h>
#include <hipblas/hipblas.h>
#include <stdexcept>
#include <string>
#include <vector>

namespace strata_ext {
inline void hip_check(hipError_t code, const char* operation) {
    if (code != hipSuccess) throw std::runtime_error(std::string(operation) + ": " + hipGetErrorString(code));
}
inline void blas_check(hipblasStatus_t code, const char* operation) {
    if (code != HIPBLAS_STATUS_SUCCESS)
        throw std::runtime_error(std::string(operation) + ": hipBLAS status " + std::to_string(code));
}
// Resources belong only to the selected device and this fixture's stream.
// Close explicitly to inspect failures; never reset a device or another context.
struct HipResources {
    hipStream_t stream = nullptr;
    hipEvent_t start = nullptr, end = nullptr;
    hipblasHandle_t blas = nullptr;
    float *vector = nullptr, *a = nullptr, *b = nullptr, *c = nullptr, *pinned = nullptr;
    HipResources() = default;
    HipResources(const HipResources&) = delete;
    HipResources& operator=(const HipResources&) = delete;
    std::vector<std::string> close() noexcept {
        std::vector<std::string> errors;
        auto note = [&](hipError_t code, const char* name) {
            if (code != hipSuccess) errors.emplace_back(std::string(name) + ": " + hipGetErrorString(code));
        };
        if (stream) note(hipStreamSynchronize(stream), "stream drain");
        for (auto pointer : {&vector, &a, &b, &c}) {
            if (*pointer) { note(hipFree(*pointer), "device free"); *pointer = nullptr; }
        }
        if (pinned) { note(hipHostFree(pinned), "pinned free"); pinned = nullptr; }
        if (start) { note(hipEventDestroy(start), "start event destroy"); start = nullptr; }
        if (end) { note(hipEventDestroy(end), "end event destroy"); end = nullptr; }
        if (blas) {
            if (hipblasDestroy(blas) != HIPBLAS_STATUS_SUCCESS) errors.emplace_back("BLAS destroy");
            blas = nullptr;
        }
        if (stream) { note(hipStreamDestroy(stream), "stream destroy"); stream = nullptr; }
        return errors;
    }
    ~HipResources() { close(); }
};
}  // namespace strata_ext
