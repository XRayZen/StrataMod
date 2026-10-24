// AMD device, graph placement and already-loaded SDK module diagnostics.
#include "diagnostics.h"
#ifdef STRATA_VISION_HIP
#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif
#include <hip/hip_runtime_api.h>
#endif

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

namespace amd_vision {
ggml_backend_dev_t require_hip_device(bool selected) {
    for (size_t i = 0; i < ggml_backend_dev_count(); ++i) {
        const auto dev = ggml_backend_dev_get(i);
        const auto type = ggml_backend_dev_type(dev);
        const auto reg = ggml_backend_dev_backend_reg(dev);
        if (std::strcmp(ggml_backend_reg_name(reg), "ROCm") == 0 &&
            (type == GGML_BACKEND_DEVICE_TYPE_GPU || type == GGML_BACKEND_DEVICE_TYPE_IGPU)) {
            ggml_backend_dev_props props{};
            ggml_backend_dev_get_props(dev, &props);
            std::fprintf(stderr, "strata-vision: %s HIP device %s (%s), PCI %s\n",
                         selected ? "required" : "available", ggml_backend_dev_name(dev), ggml_backend_dev_description(dev),
                         props.device_id ? props.device_id : "unavailable");
            return dev;
        }
    }
    return nullptr;
}

bool hip_diagnostics() {
#ifdef STRATA_VISION_HIP
    int version = 0;
    if (hipRuntimeGetVersion(&version) != hipSuccess) return false;
    std::fprintf(stderr, "strata-vision: HIP runtime version %d\n", version);
    int count = 0;
    if (hipGetDeviceCount(&count) != hipSuccess || count <= 0) return false;
    // Query every visible SDK device without changing the current device. In an
    // unfiltered probe the default device need not be the requested R9700.
    for (int device = 0; device < count; ++device) {
        hipDeviceProp_t props{};
        char pci[64] = {};
        if (hipGetDeviceProperties(&props, device) != hipSuccess ||
            hipDeviceGetPCIBusId(pci, sizeof pci, device) != hipSuccess ||
            !pci[0] || !props.gcnArchName[0] || !props.name[0]) return false;
        std::fprintf(stderr, "strata-vision: HIP identity logical=%d PCI=%s arch=%s name=%s mask=%s\n",
                     device, pci, props.gcnArchName, props.name,
                     std::getenv("HIP_VISIBLE_DEVICES") ? std::getenv("HIP_VISIBLE_DEVICES") : "unfiltered");
    }
#ifdef _WIN32
    // &hipRuntimeGetVersion can point to the EXE's import thunk on Windows.
    // Observe the already-loaded runtime module; never load a substitute here.
    HMODULE module = GetModuleHandleW(L"amdhip64_7.dll");
    wchar_t path[32768] = {};
    const DWORD length = module ? GetModuleFileNameW(module, path, 32768) : 0;
    if (length > 0 && length < 32768) {
        const int n = WideCharToMultiByte(CP_UTF8, 0, path, -1, nullptr, 0, nullptr, nullptr);
        if (n > 0) {
            std::vector<char> utf8(n);
            if (WideCharToMultiByte(CP_UTF8, 0, path, -1, utf8.data(), n, nullptr, nullptr) != n) return false;
            std::fprintf(stderr, "strata-vision: HIP runtime DLL %s\n", utf8.data());
            return true;
        }
    }
#endif
#ifdef _WIN32
    return false;
#else
    return true;
#endif
#else
    return true;
#endif
}

// The scheduler calls again after the requested node has completed. Its buffer's
// device records actual graph placement; this is separate from backend enumeration.
bool graph_eval(ggml_tensor* t, bool ask, void* user) {
    const bool compute = t->op == GGML_OP_MUL_MAT || t->op == GGML_OP_MUL_MAT_ID ||
                         t->op == GGML_OP_FLASH_ATTN_EXT;
    if (ask) return compute;
    if (!compute) return true;
    auto* proof = static_cast<graph_proof*>(user);
    ggml_backend_buffer_t buffer = t->buffer ? t->buffer : t->view_src ? t->view_src->buffer : nullptr;
    auto dev = buffer ? ggml_backend_buft_get_device(ggml_backend_buffer_get_type(buffer)) : nullptr;
    const bool hip = dev && std::strcmp(ggml_backend_reg_name(ggml_backend_dev_backend_reg(dev)), "ROCm") == 0;
    if (hip) ++proof->gpu; else ++proof->cpu;
    return true;
}

void report_graph(const char* phase, const graph_proof& proof) {
    std::fprintf(stderr, "strata-vision: GRAPH phase=%s completed_hip_compute=%zu completed_cpu_compute=%zu\n",
                 phase, proof.gpu, proof.cpu);
}

bool report_hip_modules() {
#if defined(STRATA_VISION_HIP) && defined(_WIN32)
    wchar_t exe_path[32768] = {};
    if (!GetModuleFileNameW(nullptr, exe_path, 32768)) return false;
    std::wstring folder(exe_path);
    folder.resize(folder.find_last_of(L"\\/") + 1);
    for (const wchar_t* name : {L"amdhip64_7.dll", L"hipblas.dll", L"rocblas.dll", L"libhipblaslt.dll",
                                L"amd_comgr.dll", L"rocm_kpack.dll"}) {
        HMODULE module = GetModuleHandleW(name);
        if (!module) continue;  // BLASLt/comgr/kpack may be loaded on demand; record what is actually loaded.
        wchar_t path[32768] = {};
        if (!GetModuleFileNameW(module, path, 32768)) return false;
        const int n = WideCharToMultiByte(CP_UTF8, 0, path, -1, nullptr, 0, nullptr, nullptr);
        if (n <= 0) return false;
        std::vector<char> utf8(n);
        WideCharToMultiByte(CP_UTF8, 0, path, -1, utf8.data(), n, nullptr, nullptr);
        std::fprintf(stderr, "strata-vision: LOADED_DLL %s\n", utf8.data());
        std::wstring actual(path);
        actual.resize(actual.find_last_of(L"\\/") + 1);
        if (_wcsicmp(folder.c_str(), actual.c_str()) != 0) {
            std::fprintf(stderr, "strata-vision: SDK module escaped the private encoder directory\n");
            return false;
        }
    }
#endif
    return true;
}

}  // namespace amd_vision
