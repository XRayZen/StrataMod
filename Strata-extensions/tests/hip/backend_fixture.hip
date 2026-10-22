#include "runtime.hpp"
#include <windows.h>
#include <dxgi1_4.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>

using strata_ext::hip_check;
using strata_ext::blas_check;

namespace {
std::string quote(const std::string& value) {
    std::ostringstream out;
    out << '"';
    for (unsigned char c : value) {
        if (c == '"' || c == '\\') out << '\\' << c;
        else if (c < 32) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << unsigned(c);
        else out << c;
    }
    return out.str() + '"';
}
std::string hex(const char* data, std::size_t size) {
    std::ostringstream out;
    for (std::size_t i = 0; i < size; ++i)
        out << std::hex << std::setw(2) << std::setfill('0') << unsigned(static_cast<unsigned char>(data[i]));
    return out.str();
}
std::string pci(int device) {
    char text[64]{};
    hip_check(hipDeviceGetPCIBusId(text, sizeof(text), device), "PCI identity");
    return text;
}
std::string identity(int device) {
    hipDeviceProp_t p{};
    hip_check(hipGetDeviceProperties(&p, device), "device properties");
    hipUUID uuid{};
    const auto uuid_status = hipDeviceGetUuid(&uuid, device);
    char luid[8]{};
    unsigned mask = 0;
    const auto luid_status = hipDeviceGetLuid(luid, &mask, device);
    (void)hipGetLastError();
    std::ostringstream out;
    out << "{\"ordinal\":" << device << ",\"name\":" << quote(p.name)
        << ",\"pci\":" << quote(pci(device)) << ",\"architecture\":" << quote(p.gcnArchName)
        << ",\"uuid_status\":" << int(uuid_status) << ",\"uuid\":"
        << (uuid_status == hipSuccess ? quote(hex(uuid.bytes, sizeof(uuid.bytes))) : "null")
        << ",\"luid_status\":" << int(luid_status) << ",\"luid\":"
        << (luid_status == hipSuccess ? quote(hex(luid, sizeof(luid))) : "null") << '}';
    return out.str();
}
std::string observed_count(bool valid, std::uint64_t value) {
    return valid ? std::to_string(value) : "null";
}
std::string segment_fields(const char* prefix, HRESULT status, const DXGI_QUERY_VIDEO_MEMORY_INFO& info) {
    const std::string key(prefix);
    std::ostringstream out;
    out << quote(key + "_hresult") << ':' << static_cast<long>(status)
        << ',' << quote(key + "_budget") << ':' << observed_count(SUCCEEDED(status), info.Budget)
        << ',' << quote(key + "_usage") << ':' << observed_count(SUCCEEDED(status), info.CurrentUsage)
        << ',' << quote(key + "_available_for_reservation") << ':'
        << observed_count(SUCCEEDED(status), info.AvailableForReservation);
    return out.str();
}
std::string budget(int device) {
    std::size_t free = 0, total = 0;
    const auto memory_status = hipMemGetInfo(&free, &total);
    char luid_bytes[8]{};
    unsigned mask = 0;
    const auto luid_status = hipDeviceGetLuid(luid_bytes, &mask, device);
    HRESULT status = E_FAIL;
    HRESULT local_status = E_FAIL, shared_status = E_FAIL;
    DXGI_QUERY_VIDEO_MEMORY_INFO local{}, shared{};
    if (luid_status == hipSuccess) {
        LUID luid{};
        std::memcpy(&luid, luid_bytes, sizeof(luid));
        IDXGIFactory4* factory = nullptr;
        status = CreateDXGIFactory1(__uuidof(IDXGIFactory4), reinterpret_cast<void**>(&factory));
        if (SUCCEEDED(status)) {
            IDXGIAdapter3* adapter = nullptr;
            status = factory->EnumAdapterByLuid(luid, __uuidof(IDXGIAdapter3), reinterpret_cast<void**>(&adapter));
            if (SUCCEEDED(status)) {
                local_status = adapter->QueryVideoMemoryInfo(0, DXGI_MEMORY_SEGMENT_GROUP_LOCAL, &local);
                shared_status = adapter->QueryVideoMemoryInfo(0, DXGI_MEMORY_SEGMENT_GROUP_NON_LOCAL, &shared);
                adapter->Release();
            }
            factory->Release();
        }
    }
    (void)hipGetLastError();
    std::ostringstream out;
    out << "{\"hip_status\":" << int(memory_status) << ",\"hip_free\":" << observed_count(memory_status == hipSuccess, free)
        << ",\"hip_total\":" << observed_count(memory_status == hipSuccess, total)
        << ",\"dxgi_binding_hresult\":" << static_cast<long>(status)
        << ',' << segment_fields("local", local_status, local)
        << ',' << segment_fields("shared", shared_status, shared) << '}';
    return out.str();
}
__global__ void vector_kernel(float* data, int count) {
    const int index = int(blockIdx.x * blockDim.x + threadIdx.x);
    if (index < count) data[index] = data[index] * 3.0f + 5.0f;
}
struct Measurement { float milliseconds = 0; double blas_error = 0; };

Measurement operations(bool inject_failure) {
    constexpr int count = 4096, n = 16;
    strata_ext::HipResources r;
    try {
        hip_check(hipStreamCreate(&r.stream), "stream create");
        hip_check(hipMalloc(reinterpret_cast<void**>(&r.vector), count * sizeof(float)), "vector allocate");
        if (inject_failure) throw std::runtime_error("injected-after-allocation");
        hip_check(hipHostMalloc(reinterpret_cast<void**>(&r.pinned), count * sizeof(float)), "pinned allocate");
        hip_check(hipEventCreate(&r.start), "start event create");
        hip_check(hipEventCreate(&r.end), "end event create");
        for (auto pointer : {&r.a, &r.b, &r.c})
            hip_check(hipMalloc(reinterpret_cast<void**>(pointer), n * n * sizeof(float)), "matrix allocate");
        blas_check(hipblasCreate(&r.blas), "BLAS create");
        blas_check(hipblasSetStream(r.blas, r.stream), "BLAS stream");
        for (int i = 0; i < count; ++i) r.pinned[i] = float(i);
        std::array<float, n * n> a{}, b{}, c{};
        for (int column = 0; column < n; ++column)
            for (int row = 0; row < n; ++row) {
                a[row + column * n] = float((row + 2 * column) % 7 - 3);
                b[row + column * n] = float((3 * row + column) % 5 - 2);
            }
        hip_check(hipEventRecord(r.start, r.stream), "start record");
        hip_check(hipMemcpyAsync(r.vector, r.pinned, count * sizeof(float), hipMemcpyHostToDevice, r.stream), "vector H2D");
        hipLaunchKernelGGL(vector_kernel, dim3(16), dim3(256), 0, r.stream, r.vector, count);
        hip_check(hipGetLastError(), "vector launch");
        hip_check(hipMemcpyAsync(r.pinned, r.vector, count * sizeof(float), hipMemcpyDeviceToHost, r.stream), "vector D2H");
        hip_check(hipMemcpyAsync(r.a, a.data(), sizeof(a), hipMemcpyHostToDevice, r.stream), "A H2D");
        hip_check(hipMemcpyAsync(r.b, b.data(), sizeof(b), hipMemcpyHostToDevice, r.stream), "B H2D");
        const float alpha = 1, beta = 0;
        blas_check(hipblasSgemm(r.blas, HIPBLAS_OP_N, HIPBLAS_OP_N, n, n, n,
                              &alpha, r.a, n, r.b, n, &beta, r.c, n), "SGEMM");
        hip_check(hipMemcpyAsync(c.data(), r.c, sizeof(c), hipMemcpyDeviceToHost, r.stream), "C D2H");
        hip_check(hipEventRecord(r.end, r.stream), "end record");
        hip_check(hipEventSynchronize(r.end), "end synchronize");
        Measurement m;
        hip_check(hipEventElapsedTime(&m.milliseconds, r.start, r.end), "same-device event timing");
        if (!std::isfinite(m.milliseconds) || m.milliseconds < 0) throw std::runtime_error("invalid timing");
        for (int i = 0; i < count; ++i)
            if (r.pinned[i] != float(i * 3 + 5)) throw std::runtime_error("vector numerical mismatch");
        for (int col = 0; col < n; ++col)
            for (int row = 0; row < n; ++row) {
                double expected = 0;
                for (int k = 0; k < n; ++k) expected += double(a[row + k * n]) * double(b[k + col * n]);
                if (!std::isfinite(c[row + col * n])) throw std::runtime_error("nonfinite BLAS result");
                m.blas_error = std::max(m.blas_error, std::abs(double(c[row + col * n]) - expected));
            }
        if (m.blas_error > 1e-5) throw std::runtime_error("BLAS numerical mismatch");
        if (!r.close().empty()) throw std::runtime_error("resource cleanup failed");
        return m;
    } catch (...) {
        const auto errors = r.close();
        if (!errors.empty()) throw std::runtime_error("cleanup failed after operation error");
        throw;
    }
}
std::string loaded_modules() {
    std::ostringstream out;
    out << '{';
    bool first = true;
    for (const char* name : {"amdhip64_7.dll", "hipblas.dll", "rocblas.dll", "rocm_kpack.dll", "libhipblaslt.dll"}) {
        char path[32768]{};
        const auto module = GetModuleHandleA(name);
        if (module && GetModuleFileNameA(module, path, sizeof(path))) {
            if (!first) out << ',';
            out << quote(name) << ':' << quote(path);
            first = false;
        }
    }
    return out.str() + '}';
}
}  // namespace

int main(int argc, char** argv) {
    try {
        if (argc == 2 && std::string(argv[1]) == "--budget-format-selftest") {
            DXGI_QUERY_VIDEO_MEMORY_INFO values{};
            values.Budget = 1234; values.CurrentUsage = 234; values.AvailableForReservation = 1000;
            std::cout << "{\"local_ok_shared_failed\":{"
                      << segment_fields("local", S_OK, values) << ',' << segment_fields("shared", E_FAIL, values)
                      << "},\"local_failed_shared_ok\":{" << segment_fields("local", E_FAIL, values)
                      << ',' << segment_fields("shared", S_OK, values) << "}}\n";
            return 0;
        }
        if (argc == 2 && std::string(argv[1]) == "--identity") {
            std::cout << "{\"compiled_sha256\":\"" << STRATA_EXT_SOURCE_ID << "\"}\n";
            return 0;
        }
        hip_check(hipInit(0), "HIP initialize");
        int count = 0;
        hip_check(hipGetDeviceCount(&count), "device count");
        if (argc == 2 && std::string(argv[1]) == "--inventory") {
            std::cout << "{\"compiled_sha256\":\"" << STRATA_EXT_SOURCE_ID << "\",\"devices\":[";
            for (int i = 0; i < count; ++i) {
                if (i) std::cout << ',';
                std::cout << identity(i);
            }
            std::cout << "],\"loaded_modules\":" << loaded_modules() << "}\n";
            return 0;
        }
        if (argc != 3 || std::string(argv[1]) != "--probe") throw std::runtime_error("expected --probe PCI or --inventory");
        int selected = -1;
        for (int i = 0; i < count; ++i) if (pci(i) == argv[2]) {
            if (selected != -1) throw std::runtime_error("ambiguous PCI identity");
            selected = i;
        }
        if (selected < 0) throw std::runtime_error("selected PCI identity absent");
        hip_check(hipSetDevice(selected), "select exact PCI device");
        const auto before = budget(selected);
        std::size_t free = 0, total = 0;
        hip_check(hipMemGetInfo(&free, &total), "memory observation");
        // A fixture-only bound on explicitly requested allocations, not a model policy.
        if (free < 1024 * 1024) throw std::runtime_error("insufficient memory for small fixture");
        const auto first = operations(false);
        const auto invalid = hipSetDevice(count);
        if (invalid != hipErrorInvalidDevice) throw std::runtime_error("invalid ordinal was not rejected");
        (void)hipGetLastError();
        hip_check(hipSetDevice(selected), "restore selected device after negative");
        bool injected = false;
        try { operations(true); }
        catch (const std::runtime_error& e) { injected = std::string(e.what()) == "injected-after-allocation"; }
        if (!injected) throw std::runtime_error("injected failure/cleanup contract failed");
        const auto next = operations(false);
        std::cout << "{\"status\":\"passed\",\"compiled_sha256\":\"" << STRATA_EXT_SOURCE_ID
                  << "\",\"device\":" << identity(selected) << ",\"budget_before\":" << before
                  << ",\"budget_after\":" << budget(selected)
                  << ",\"explicit_device_bytes\":19456,\"explicit_pinned_bytes\":16384"
                  << ",\"blas_context_internal_bytes\":\"not separately measured\""
                  << ",\"event_milliseconds\":" << first.milliseconds
                  << ",\"blas_max_abs_error\":" << first.blas_error
                  << ",\"next_operation_max_abs_error\":" << next.blas_error
                  << ",\"invalid_device_rejected\":true,\"injected_cleanup_next_operation\":true"
                  << ",\"loaded_modules\":" << loaded_modules() << "}\n";
        return 0;
    } catch (const std::exception& e) {
        std::cout << "{\"status\":\"not_established\",\"error\":" << quote(e.what())
                  << ",\"loaded_modules\":" << loaded_modules() << "}\n";
        return 2;
    }
}
