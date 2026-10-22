// tools/vision/strata_vision.cpp - the image half of Strata's multimodal path.
//
// Turns an image into the embeddings the text model reads in place of its <|image_pad|> tokens, with llama.cpp's
// mtmd library and the model's mmproj file (vision encoder + projector).  The engine does the rest: it places the
// rows at the image's pad tokens and gives them their 2-D M-RoPE positions (see --serve GENI in generate.cpp).
//
//   strata-vision --mmproj <mmproj.gguf> --model <text model .gguf, first split> [--gpu] [--threads N]
//                 [--max-tokens N] [--min-tokens N] [--flash-attn on|off|auto]
// Flash attention defaults to auto, and to off on the CPU when ggml is built with AVX-512 (see main).
//
// Resident: prints "READY <n_embd>", then per stdin line
//   ENC <image path> <output path>   ->  "OK <n_tokens> <nx> <ny> <ms>"  or  "ERR <message>"
//   QUIT
// The output file is  int32 {0x31455653 'SVE1', n_tokens, nx, ny, n_embd}  then float32 [n_tokens][n_embd],
// row i at grid position (x = i % nx, y = i / nx).  The text model is opened vocab-only (no weights).
#include "ggml-cpu.h"
#include "gguf.h"
#include "llama.h"
#include "mtmd.h"
#include "mtmd-helper.h"
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

#include <algorithm>
#if !defined(_WIN32)
#include <fcntl.h>
#include <unistd.h>
#endif
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace {

void quiet_log(ggml_log_level level, const char* text, void*) {
    if (level >= GGML_LOG_LEVEL_WARN) std::fputs(text, stderr);
}

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

struct graph_proof {
    size_t gpu = 0, cpu = 0;
};

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

// "ENC <image> <out>": paths may contain spaces, so the image path ends at the last " " before the output path;
// the server always writes paths without spaces, but a user calling the tool by hand might not
bool parse_enc(const std::string& line, std::string& img, std::string& out) {
    if (line.rfind("ENC ", 0) != 0) return false;
    const std::string rest = line.substr(4);
    const size_t sp = rest.rfind(' ');
    if (sp == std::string::npos || sp == 0) return false;
    img = rest.substr(0, sp);
    out = rest.substr(sp + 1);
    return !img.empty() && !out.empty();
}

}  // namespace

int main(int argc, char** argv) {
    std::string mmproj, model;
    bool gpu = false, require_hip = false, list_devices = false, trace_graph = false;
    int threads = 0, max_tokens = 0, min_tokens = 0;
    llama_flash_attn_type fa = LLAMA_FLASH_ATTN_TYPE_AUTO;
    bool fa_given = false;
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        auto next = [&]() -> std::string {
            if (i + 1 >= argc) { std::fprintf(stderr, "%s needs a value\n", a.c_str()); std::exit(2); }
            return argv[++i];
        };
        if (a == "--mmproj") mmproj = next();
        else if (a == "--model") model = next();
        else if (a == "--gpu") gpu = true;
        else if (a == "--require-hip") require_hip = true;
        else if (a == "--list-devices") list_devices = true;
        else if (a == "--trace-graph") trace_graph = true;
        else if (a == "--threads") threads = std::atoi(next().c_str());
        else if (a == "--max-tokens") max_tokens = std::atoi(next().c_str());
        else if (a == "--min-tokens") min_tokens = std::atoi(next().c_str());   // mtmd image_min_tokens (#767)
        else if (a == "--flash-attn") {   // FA keeps K and V in FP16; off = the attention in FP32
            const std::string v = next();
            fa = v == "on" ? LLAMA_FLASH_ATTN_TYPE_ENABLED : v == "off" ? LLAMA_FLASH_ATTN_TYPE_DISABLED
                                                                        : LLAMA_FLASH_ATTN_TYPE_AUTO;
            fa_given = true;
        }
        else { std::fprintf(stderr, "unknown argument %s\n", a.c_str()); return 2; }
    }
    if (require_hip && !gpu && !list_devices) {
        std::fprintf(stderr, "--require-hip needs --gpu\n");
        return 2;
    }
#ifndef STRATA_VISION_HIP
    if (require_hip) {
        std::fprintf(stderr, "strata-vision: --require-hip needs a STRATA_VISION_HIP=ON build\n");
        return 2;
    }
#endif
    if (!list_devices && (mmproj.empty() || model.empty())) {
        std::fprintf(stderr, "usage: strata-vision --mmproj <mmproj.gguf> --model <model.gguf> [--gpu] [--threads N] "
                             "[--max-tokens N] [--min-tokens N] [--flash-attn on|off|auto] [--require-hip]\n"
                             "       strata-vision --list-devices [--require-hip]\n");
        return 2;
    }
    // On the CPU the GPU stays unseen: a CUDA build otherwise opens a context there (measured: 0.4-0.7 GB of VRAM,
    // 150-260 expert slots less for the engine beside it).  Before anything reaches the CUDA runtime.
    if (!gpu && !list_devices) {
#ifdef _WIN32
        _putenv_s("CUDA_VISIBLE_DEVICES", "-1");
#ifdef STRATA_VISION_HIP
        _putenv_s("HIP_VISIBLE_DEVICES", "-1");
#endif
#else
        setenv("CUDA_VISIBLE_DEVICES", "-1", 1);
#ifdef STRATA_VISION_HIP
        setenv("HIP_VISIBLE_DEVICES", "-1", 1);
#endif
#endif
    }
    llama_log_set(quiet_log, nullptr);
    mtmd_helper_log_set(quiet_log, nullptr);
    llama_backend_init();
    ggml_backend_dev_t hip_device = require_hip ? require_hip_device(!list_devices) : nullptr;
    if (require_hip && !hip_device) {
        std::printf("ERR no usable ROCm GPU; HIP was required, CPU fallback is disabled\n");
        std::fflush(stdout);
        llama_backend_free();
        return 1;
    }
    if ((require_hip || list_devices) && !hip_diagnostics()) {
        std::printf("ERR cannot verify the HIP runtime and selected device\n");
        std::fflush(stdout);
        llama_backend_free();
        return 1;
    }
    if (require_hip && !report_hip_modules()) {
        std::printf("ERR mixed HIP SDK module paths\n");
        std::fflush(stdout);
        llama_backend_free();
        return 1;
    }
    if (list_devices) {
        for (size_t i = 0; i < ggml_backend_dev_count(); ++i) {
            const auto dev = ggml_backend_dev_get(i);
            ggml_backend_dev_props props{};
            ggml_backend_dev_get_props(dev, &props);
            std::printf("DEVICE %s %s %s PCI=%s\n", ggml_backend_reg_name(ggml_backend_dev_backend_reg(dev)),
                        ggml_backend_dev_name(dev), ggml_backend_dev_description(dev),
                        props.device_id ? props.device_id : "unavailable");
        }
        llama_backend_free();
        return 0;
    }

    const auto load_t0 = std::chrono::steady_clock::now();
#if !defined(_WIN32) && !defined(__APPLE__)   // macOS has no posix_fadvise
    // ask the OS for the projector file up front (128 KiB steps) so the loader's sequential reads find it cached;
    // STRATA_READ_AHEAD=0 turns it off, as in the engine
    if (const char* ra = std::getenv("STRATA_READ_AHEAD"); ra == nullptr || std::atoi(ra) != 0) {
        const int fd = open(mmproj.c_str(), O_RDONLY);
        if (fd >= 0) {
            const off_t n = lseek(fd, 0, SEEK_END);
            for (off_t at = 0; at < n; at += (off_t) (128 << 10))
                (void) posix_fadvise(fd, at, std::min<off_t>((off_t) (128 << 10), n - at), POSIX_FADV_WILLNEED);
            close(fd);
        }
    }
#endif
    llama_model_params mp = llama_model_default_params();
    mp.vocab_only = true;
    llama_model* text = llama_model_load_from_file(model.c_str(), mp);
    if (!text) { std::printf("ERR cannot open the text model %s\n", model.c_str()); std::fflush(stdout); return 1; }

    mtmd_context_params cp = mtmd_context_params_default();
    graph_proof proof;
    if (require_hip || trace_graph) {
        cp.cb_eval = graph_eval;
        cp.cb_eval_user_data = &proof;
    }
    cp.use_gpu = gpu;
    if (require_hip) cp.device = hip_device;  // mtmd fails on this device instead of choosing the CPU
    cp.print_timings = false;
    cp.warmup = false;
    // On the CPU "auto" turns flash attention on.  ggml's fast (tiled) CPU kernel for it needs the head size, 72 in this
    // encoder, to be a multiple of the vector width: 8 floats with AVX2 (the release builds), 16 with AVX-512 (a build
    // from source on a CPU that has it), where ggml falls back to a kernel that is several times slower and accumulates
    // in FP16.  A 1024x1024 picture on a Ryzen 7 7700X, 8 threads: AVX2 8-10 s with it, 14-15 s without; AVX-512 44 s
    // with it (26% off the FP32 attention's output), 13 s without.
    if (!gpu && !fa_given && ggml_cpu_has_avx512()) fa = LLAMA_FLASH_ATTN_TYPE_DISABLED;
    cp.flash_attn_type = fa;
    // on the CPU without --threads: one per core (mtmd's own default is 4 threads)
    if (threads <= 0 && !gpu) threads = std::max(1u, std::thread::hardware_concurrency() / 2);
    if (threads > 0) cp.n_threads = threads;
    if (max_tokens > 0) cp.image_max_tokens = max_tokens;
    if (min_tokens > 0) cp.image_min_tokens = min_tokens;
    mtmd_context* ctx = mtmd_init_from_file(mmproj.c_str(), text, cp);
    if (!ctx || !mtmd_support_vision(ctx)) {
        std::printf("ERR cannot load the vision encoder %s\n", mmproj.c_str());
        std::fflush(stdout);
        return 1;
    }
    std::fprintf(stderr, "strata-vision: model files loaded in %.1f s\n",
                 std::chrono::duration<double>(std::chrono::steady_clock::now() - load_t0).count());
    // a vocab-only model reports no hparams, so the width comes from the projector: its output is the model's input
    int n_embd = 0;
    {
        gguf_init_params gp{true, nullptr};
        gguf_context* gg = gguf_init_from_file(mmproj.c_str(), gp);
        const int64_t k = gg ? gguf_find_key(gg, "clip.vision.projection_dim") : -1;
        if (k >= 0) n_embd = (int) gguf_get_val_u32(gg, k);
        if (gg) gguf_free(gg);
    }
    if (n_embd <= 0) { std::printf("ERR the vision encoder has no projection_dim\n"); std::fflush(stdout); return 1; }
    // Warm up at the LARGEST picture before READY: the encoder's GPU work buffers are allocated now, not at the first
    // real picture.  The server starts this process before the engine, so the engine sizes its expert cache from
    // what is really left; allocating ~1 GB later, on a GPU the engine has filled, made Windows page GPU memory and
    // the engine crawl to a standstill.  (A square image well above any cap; mtmd scales it to the token limit.)
    // On the CPU there is no VRAM to reserve, and the warm-up would only delay the engine's start by one encode
    // (~6 s at 1,024 tokens).
    if (!gpu) std::fprintf(stderr, "strata-vision: on the CPU, %d threads, no warm-up\n", threads);
    else {
        const auto warm_t0 = std::chrono::steady_clock::now();
        const uint32_t side = 2048;
        std::vector<unsigned char> rgb((size_t) side * side * 3, 128);
        mtmd_bitmap* bm = mtmd_bitmap_init(side, side, rgb.data());
        mtmd_input_chunks* chunks = mtmd_input_chunks_init();
        const std::string marker = mtmd_default_marker();
        mtmd_input_text txt{marker.c_str(), marker.size(), false, true};
        const mtmd_bitmap* bms[1] = {bm};
        int warm_tokens = 0;
        if (bm && mtmd_tokenize(ctx, chunks, &txt, bms, 1) == 0) {
            for (size_t c = 0; c < mtmd_input_chunks_size(chunks); ++c) {
                const mtmd_input_chunk* ch = mtmd_input_chunks_get(chunks, c);
                if (mtmd_input_chunk_get_type(ch) == MTMD_INPUT_CHUNK_TYPE_IMAGE &&
                    (!require_hip || max_tokens <= 0 || mtmd_input_chunk_get_n_tokens(ch) <= (size_t) max_tokens) &&
                    mtmd_encode_chunk(ctx, ch) == 0)
                    warm_tokens = (int) mtmd_input_chunk_get_n_tokens(ch);
            }
        }
        std::fprintf(stderr, "strata-vision: warmed up at %d image tokens in %.1f s\n", warm_tokens,
                     std::chrono::duration<double>(std::chrono::steady_clock::now() - warm_t0).count());
        mtmd_input_chunks_free(chunks);
        if (bm) mtmd_bitmap_free(bm);
        if (require_hip || trace_graph) report_graph("warmup", proof);
        if (require_hip && (proof.gpu == 0 || !report_hip_modules())) warm_tokens = 0;
        if (require_hip && warm_tokens <= 0) {
            std::printf("ERR required HIP image warm-up failed\n");
            std::fflush(stdout);
            mtmd_free(ctx);
            llama_model_free(text);
            llama_backend_free();
            return 1;
        }
    }
    std::printf("READY %d\n", n_embd);
    std::fflush(stdout);

    std::string line;
    while (std::getline(std::cin, line)) {
        while (!line.empty() && (line.back() == '\r' || line.back() == '\n')) line.pop_back();
        if (line == "QUIT") break;
        std::string img, out;
        if (!parse_enc(line, img, out)) { std::printf("ERR expected: ENC <image> <output>\n"); std::fflush(stdout); continue; }
        const auto t0 = std::chrono::steady_clock::now();
        proof = {};
        mtmd_helper_bitmap_wrapper bw = mtmd_helper_bitmap_init_from_file(ctx, img.c_str(), false,
                                                                            mtmd_helper_init_opt_default());
        if (!bw.bitmap) { std::printf("ERR cannot read the image %s\n", img.c_str()); std::fflush(stdout); continue; }
        mtmd_input_chunks* chunks = mtmd_input_chunks_init();
        const std::string prompt = mtmd_default_marker();
        mtmd_input_text txt{prompt.c_str(), prompt.size(), false, true};
        const mtmd_bitmap* bm[1] = {bw.bitmap};
        std::string err;
        const mtmd_input_chunk* ichunk = nullptr;
        if (mtmd_tokenize(ctx, chunks, &txt, bm, 1) != 0) err = "the image could not be preprocessed";
        for (size_t c = 0; err.empty() && c < mtmd_input_chunks_size(chunks); ++c) {
            const mtmd_input_chunk* ch = mtmd_input_chunks_get(chunks, c);
            if (mtmd_input_chunk_get_type(ch) == MTMD_INPUT_CHUNK_TYPE_IMAGE) ichunk = ch;
        }
        if (err.empty() && !ichunk) err = "no image chunk";
        if (err.empty() && (mtmd_input_chunk_get_n_tokens(ichunk) <= 0 ||
            ((require_hip || trace_graph) && max_tokens > 0 &&
             mtmd_input_chunk_get_n_tokens(ichunk) > (size_t) max_tokens)))
            err = "image exceeds the configured token cap after preprocessing";
        if (err.empty() && mtmd_encode_chunk(ctx, ichunk) != 0) err = "the vision encoder failed";
        if (require_hip || trace_graph) report_graph("encode", proof);
        if (err.empty() && require_hip && proof.gpu == 0) err = "no completed HIP graph compute";
        if (err.empty() && require_hip && !report_hip_modules()) err = "mixed HIP SDK module paths";
        if (err.empty()) {
            const mtmd_image_tokens* it = mtmd_input_chunk_get_tokens_image(ichunk);
            const int n = (int) mtmd_input_chunk_get_n_tokens(ichunk);
            // the grid from the decoder positions (nx/ny getters are deprecated): x and y of the last token
            const mtmd_decoder_pos last = mtmd_image_tokens_get_decoder_pos(it, 0, (size_t) n - 1);
            const int nx = (int) last.x + 1, ny = (int) last.y + 1;
            if (nx * ny != n) err = "the image grid is not rectangular (" + std::to_string(n) + " tokens)";
            const float* embd = mtmd_get_output_embd(ctx);
            for (size_t i = 0; err.empty() && i < (size_t) n * n_embd; ++i)
                if (!std::isfinite(embd[i])) err = "non-finite image embedding";
            FILE* f = err.empty() ? std::fopen(out.c_str(), "wb") : nullptr;
            if (err.empty() && !f) err = "cannot write " + out;
            if (f) {
                const int32_t hdr[5] = {0x31455653, n, nx, ny, n_embd};
                const bool ok = std::fwrite(hdr, sizeof hdr, 1, f) == 1 &&
                                std::fwrite(embd, sizeof(float) * (size_t) n_embd, (size_t) n, f) == (size_t) n;
                std::fclose(f);
                if (!ok) err = "short write to " + out;
                const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
                if (ok) std::printf("OK %d %d %d %.0f\n", n, nx, ny, ms);
            }
        }
        if (!err.empty()) {
            std::remove(out.c_str());
            std::printf("ERR %s\n", err.c_str());
        }
        std::fflush(stdout);
        mtmd_input_chunks_free(chunks);
        mtmd_bitmap_free(bw.bitmap);
        if (bw.video_ctx) mtmd_helper_video_free(bw.video_ctx);
    }
    mtmd_free(ctx);
    llama_model_free(text);
    llama_backend_free();
    return 0;
}
