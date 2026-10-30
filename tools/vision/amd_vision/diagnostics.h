// Internal amdVision diagnostics; no new DLL or exported plugin ABI.
#pragma once
#include "ggml-backend.h"
#include <cstddef>

namespace amd_vision {
struct graph_proof {
    size_t gpu = 0, cpu = 0;
};
ggml_backend_dev_t require_hip_device(bool selected);
bool hip_diagnostics();
bool graph_eval(ggml_tensor* tensor, bool ask, void* user);
void report_graph(const char* phase, const graph_proof& proof);
bool report_hip_modules();
}  // namespace amd_vision
