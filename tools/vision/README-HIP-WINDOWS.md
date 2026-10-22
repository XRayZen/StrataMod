# Windows HIP image candidate

This is the opt-in R9700 candidate from [R9700-02](../../Docs/Inprogress/R9700-02-rocm-vision.md).
It is an independent image process. The text engine and its ROCm package are unchanged.
Use the reviewed StrataMod candidate runtime for GPU operations. Do not start the server directly.

## Build and isolation

The starting patch is `strata-windows-hip-vision.patch`, SHA256
`1f132caac7a1194ccd1fda69f3a634046876f49b78b3dc5a4ed86fa817161b34`.
llama.cpp is a clean separate checkout at `3cf03257f219afbe7334045ff7c6a06ac68c627d`.
The first image SDK is ROCm 10.1.0, with core/devel/libraries/device-gfx1201 all at that version.
The SDK's original bin/lib/.kpack layout is kept, with `strata-vision-hip.exe` beside its DLLs.
No SDK DLL is copied into the text engine. Switching the image SDK requires a separate environment/build/result.

`hip_windows.py build` configures and builds an empty HIP-only directory and refuses to overwrite an encoder.
The build uses SDK clang/clang++, Ninja, and MSVC 19.43 or newer with the Windows SDK.
`configure_command()` sets `GPU_TARGETS=gfx1201` as required by the fixed ggml Windows HIP build.
MSVC and Windows SDK files for this task were downloaded from Microsoft's manifest/NuGet and expanded inside
`.vision-toolchain`; no global install or PATH change was made. `.vision-tmp/build-env.ps1` supplies process-local paths.
Exact acquisition URLs, package versions and hashes are in `.vision-tmp/sdk-install.json`,
`.vision-toolchain/acquisition.json`, `*-acquisition.json`, and `.vision-toolchain/other-backends-acquisition.json`.

The CPU reference encoder uses the same source and fixed llama revision, without GPU backends.
The CPU/HIP build receipt is `.vision-tmp/hip-cpu-build-receipt.json`; it records encoder/source/cache hashes
and the SDK DLL/kpack closure. PE imports are in `.vision-tmp/hip-pe-imports.txt`.
The original four-backend receipt is `.vision-tmp/all-backend-build-receipt.json`.
Later Python-only fixes are bound separately by `.vision-tmp/vision-repair-binding.json`; the original build receipt
is preserved. All four current incremental builds returned exit 0 with no work, and all binary/SDK closure hashes matched.
Build success does not establish device enumeration, image encoding, numerical parity, or answering quality.
CPU/HIP/CUDA/SYCL all compiled and linked on Windows. CUDA used a fixed `sm_86` target for compilation only;
SYCL used generic SPIR-V with optional oneDNN/Level Zero API support disabled. No GPU program was executed.

## Candidate behavior

- `vision.backend=hip` requires `vision.gpu=true` and passes `--require-hip`.
- `windows_hip_env()` removes old GPU filters, tuning and SDK paths, then uses this SDK's own `hip_device` ordinal.
  This includes case-insensitive removal of the parent's `GPU_DEVICE_ORDINAL`; the parent environment is unchanged.
  Probe and record the private SDK's enumeration; do not reuse a text-engine ordinal without matching its PCI identity.
- TEMP/TMP and the COMGR cache use a private writable directory. The encoder's scratch directory is removed on shutdown.
- Windows HIP image arguments retain a reserve of at least 2560 MiB, including an existing `--vision` flag.
  Explicit reserves at or above the floor are preserved. Missing, duplicate, malformed or smaller explicit values fail.
  Warmup runs before text cache allocation, so the encoder's allocated memory is already excluded from free VRAM;
  the 2560 MiB floor is the engine's existing margin, not another encoder reservation.
- The installed profile uses 300 tokens per image. Multiple images, including retained history and duplicate
  occurrences, follow the existing sequential encoder/SVE/native path in prompt order. Existing source bytes <=20 MiB, edges <=4096, pixels <=4,000,000,
  and HTTP body <=32 MiB. JPEG/PNG/WebP are decoded and checked before child I/O; EXIF normalization is retained.
  The configured token cap (up to 1024) and READY-reported embedding width remain authoritative;
  no new aggregate image-count/source-byte/feature-byte/preparation-time cap is imposed.
  The current multi-image change has CPU verification; real four-image QwenCode validation is pending.
- The C++ preprocessor's actual token count must fit the cap before encoding. SVE1 must be rectangular, have the
  expected embedding width and exact length, and contain finite float32 values. Invalid output is removed.
- The first server encode deadline is 60 seconds; later deadlines are twice the largest observed encode duration
  plus 10 seconds. Cancellation and timeouts kill/wait the owned image child. If exit cannot be proved, the
  original Popen and scratch files remain owned, capability reports `cleanup_pending`, and start/unload/shutdown
  report an error until exit is confirmed. No second child or successful directory deletion is allowed meanwhile.
- Health, status, models and props use actual sidecar liveness for HIP capability. An enabled config is separate
  from an available image process. Legacy CPU/CUDA behavior is retained.

`check_models()` checks first-shard status, dimensions, Qwen3.8 qwen4exp/qwen3vl_merger family and image markers.
The candidate runtime manifest owns exact native-pack/model/revision/tokenizer/mmproj/exe/SDK binding;
matching width or family alone is insufficient authorization to substitute an asset.
The helper also requires its `--model` path to match the text config's one `--native` first-shard path.
The read-only asset observation is `.vision-tmp/model-vision-binding.json`: projection 2560, image markers
248053/248054/248056, and the fixed 907543008-byte projector SHA256 from plan v6.

## Device and image validation handoff

All GPU/API/probe/start/stop operations belong to the runtime worker under the shared operation and runtime locks.
Required offline/build checks and the independent implementation review precede those operations.

`hip_windows.py probe --rocm-root <private SDK>` lists that SDK's unfiltered devices without loading a model.
Before starting the child, it requires the SDK inside StrataMod, resolves TEMP/cache containment, creates both
private directories and verifies write/flush/delete. External, corrupt and unwritable locations fail before launch.
The next filtered encode uses the matched R9700 identity and passes `--gpu --require-hip --max-tokens 300`.
The CPU reference uses the same model/projector/image/cap without `--gpu`.
`--require-hip` rejects a missing ROCm device and explicit-device initialization failure. It also requires completed
ROCm compute nodes in warmup and each encode. The existing mtmd scheduler callback counts completed expensive
compute nodes by their buffer device; CPU helper operations remain visible separately. No fixed llama source is patched.
`--trace-graph` requests the same graph summaries for the CPU reference.
stderr records runtime version, mask, logical device, PCI/architecture/name, actual loaded HIP/BLAS/comgr/kpack
module paths, and graph counts. Loaded SDK modules outside the encoder directory fail closed.
Runtime evidence must hash those actual module paths against the pinned build closure. HIP kernel command tracing
can be enabled for one diagnostic run with the documented `AMD_LOG_LEVEL`/`AMD_LOG_MASK` process environment.
Graph placement and a backend name must not be presented as a hardware profiler trace.

The next gates remain CPU A/A and CPU/HIP shape/grid/token/finite/L2/cosine parity, known OCR/shape/color/position
answers, OpenAI/Anthropic/Responses image paths, WebUI attachment, oversized/corrupt/timeout/cancel/OOM recovery,
text-image-text cache separation, long context, memory budgets, and normal rollback. See the child contract for exact criteria.

## Offline evidence

`.vision-tmp/reserve-red.txt` captures the reserve regression before the fix. `.vision-tmp/limits-red.txt`,
`cleanup-red.txt`, `unbounded-readline-red.txt` and `family-red.txt` capture added failures before their fixes.
`.vision-tmp/offline-vision-final.txt` is the combined 102-test successful run, including the supplied 12 tests
plus the family regression, candidate safety, existing vision/env/busy/elastic, timeout/cancel, WebUI and status suites.
These tests use fixtures or the mock engine. They are not R9700 image execution or quality evidence.
After that run, the native-model binding fixture passed, and an explicit-token-type fixture exposed a known
HIP config validation gap (0/float/string/None coercion). Its RED is `.vision-tmp/token-cap-red.txt`.
The Main's repair thaw fixed it: HIP caps must now be non-boolean integers from 1 to 1024, with omission defaulting to 300.
The same repair added seven probe TEMP fixtures with a mocked child launch. `.vision-tmp/repair-red.txt` and
`repair-green.txt` hold that TDD cycle; `.vision-tmp/offline-vision-repair-final.txt` preserves the **111/111** aggregate.
The earlier 102-test and 14-helper-test results are retained as history and are not added together.
No actual GPU probe, image encode or ACL integration result is implied by the mocked probe fixtures.

The independent code review repair is bound by `.vision-tmp/vision-vcr-binding.json`, preserving both earlier receipts.
It fixes unconfirmed HIP termination, initial tool-image cancellation, and config-relative library/tokenizer paths.
`.vision-tmp/vcr-red.txt` and `vcr-pending-error-red.txt` preserve RED results; `vcr-green.txt` records the focused
GREEN run. That aggregate is **120 unique tests / 120 PASS**, `.vision-tmp/offline-vision-vcr-final.txt`;
its exact command is `.vision-tmp/offline-vision-vcr-command.txt`. C++/CMake/SDK/binaries did not change in this
repair; their hashes were checked against the original successful four-backend build receipt, without relabeling
old builds as new compilation. Source/helper/tests are frozen for fresh review and runtime manifest binding.

The VCR-01 service follow-up fixes repeated unload when the text engine has already stopped: a retained HIP child
still requires confirmed cleanup, so `/unload` (including wait) and `/v1/unload` keep returning 503 JSON while pending.
`ensure_loaded` preserves the specialized pending error, including an elastic encoder or an already loaded text
engine; `/load` and `/v1/load` return 503 JSON without starting a second child or restarting text. Once the same
Popen confirms exit, unload/load may succeed. The candidate official stop's existing guarded HTTP rejects that
non-200 unload before process termination; this repair does not change the official management layer.
`.vision-tmp/vcr-service-red.txt` (four methods, six failures/two errors) and `vcr-service-green.txt` preserve TDD.
The current aggregate is **141 unique tests / 141 PASS**, `.vision-tmp/offline-vision-service-final.txt`, including
the existing `SharingTheGpu` regression suite. Its exact command is `.vision-tmp/offline-vision-service-command.txt`.
`.vision-tmp/vision-vcr-service-binding.json` binds this Python-only repair and unchanged SDK/binaries to the original
receipts. HTTP pending tests call the handler with mock I/O; they do not contact the running runtime or a real GPU.

The VSR-01 specification follow-up adds only `GPU_DEVICE_ORDINAL` to that existing removal set. Uppercase and mixed
case fixtures verify parent preservation, selected HIP mask retention and no inherited ordinal/visibility masks in
the probe's mocked child environment. `.vision-tmp/vsr01-red.txt` (two methods, four failures) and `vsr01-green.txt`
preserve TDD. The prior 141-test result remains historical; the latest aggregate is **143 unique tests / 143 PASS**
(34.650 seconds, exit 0). Its log and unchanged build binding are
recorded in `.vision-tmp/offline-vision-vsr01-final.txt` and `.vision-tmp/vision-vsr01-binding.json`.
This proves environment construction only; this Windows machine's actual ordinal-filter behavior is unmeasured.

## Exact first-device handoff (not executed)

These are commands for the runtime worker **after fresh independent review**, inside its already acquired
operation/runtime locks and checked owner, idle/queue, memory and rollback gates. They acquire no locks by
themselves. No image probe/encode/API command below has run. CPU A/A also uses the runtime measurement window.
Run in a dedicated process; all environment changes below are process-local. Keep the text engine stopped for
the first standalone image gate, and record startup/warmup separately from the initial 60-second encode budget.
Stop on the plan's memory/commit thresholds. An SDK/driver failure returns to Main before another SDK arm.

```powershell
Set-Location -LiteralPath C:/Develop/AI/StrataMod
$env:TEMP = 'C:/Develop/AI/StrataMod/.vision-tmp'
$env:TMP = $env:TEMP
$python = 'C:/Develop/AI/StrataMod/.vision-venv-10.1/Scripts/python.exe'
$sdk = 'C:/Develop/AI/StrataMod/.vision-venv-10.1/Lib/site-packages/_rocm_sdk_devel'
& $python -X utf8 tools/vision/hip_windows.py probe --rocm-root $sdk
```

The probe runs exactly `$sdk/bin/strata-vision-hip.exe --list-devices --require-hip`, using `windows_hip_env`, then removing
`HIP_VISIBLE_DEVICES` for unfiltered enumeration. Its PATH is SDK bin, SDK lib/llvm/bin, System32, Windows;
HIP_PATH/ROCM_PATH point to this SDK; TEMP/TMP are SDK/tmp and AMD_COMGR_CACHE_DIR is SDK/tmp/comgr.
Expect exit 0 and a ROCm device list. Match **PCI identity + gfx1201** to R9700 and record the observed SDK ordinal;
do not infer an ordinal from the old text runtime. The following script requires that observed ordinal in
`$env:VISION_HIP_ORDINAL` before the HIP arm, and passes it through the same sanitized environment.

The fixed CPU executable is `.vision-build/cpu-reference-2/bin/strata-vision.exe` (SHA256
`aa3c2660832bf66940f3fed760c90f2aa3d498b6241a6d4e7d388861376113a4`); the HIP executable is SDK/bin/
`strata-vision-hip.exe` (SHA256 `911498856bed4a8b4d6af287748ba9e1bad1d340c2d490508e389ac4d9419af3`).
Both use the model/projector below, cap 300, four threads, FA off and the same normalized image. The projector
is 907543008 bytes, SHA256 `b1a82259702816a5330d7bd7607cd9676b11780e79ff7348c21103ff3ce49bd0`.
The current runtime manifest must bind these assets and the SDK closure before execution.

```powershell
$encodeOne = @'
import os, shutil, sys, time
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from serve.server import Vision, VisionCleanupPending
from serve.vision_hip import windows_hip_env
root = Path('C:/Develop/AI/StrataMod')
sdk = root / '.vision-venv-10.1/Lib/site-packages/_rocm_sdk_devel'
arm = sys.argv[1]
assert arm in ('cpu-aa1', 'cpu-aa2', 'hip')
image = root / '.vision-tmp/vision-small.png'
if arm == 'cpu-aa1':
    im = Image.new('RGB', (512, 320), 'white')
    d = ImageDraw.Draw(im)
    d.text((20, 10), 'R9700 123 ABC', fill='black',
           font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 40))
    d.rectangle((35, 85, 155, 205), fill='red')
    d.ellipse((345, 85, 465, 205), fill='blue')
    d.polygon([(210, 300), (300, 300), (255, 225)], fill='green')
    im.save(image)
cfg = dict(exe=str(root / '.vision-build/cpu-reference-2/bin/strata-vision.exe'),
           model='C:/Develop/AI/Strata-data/huihui-ud-iq4_xs/Qwen3.8-Flash-Next-UD-IQ4_XS-00001-of-00003.gguf',
           mmproj='C:/Develop/AI/Strata-data/vision-sidecars/ista/mmproj-Qwen3.8-Flash-Next-BF16.gguf',
           gpu=False, max_tokens=300, threads=4)
# CPU build has no GPU backend; its CRT search uses the pinned SDK bin, with no old SDK path.
env = windows_hip_env(dict(rocm_root=str(sdk), exe=str(sdk/'bin/strata-vision-hip.exe'),
                          hip_device=0, temp_dir=str(root/'.vision-tmp')), dict(os.environ))
if arm == 'hip':
    cfg.update(backend='hip', gpu=True, rocm_root=str(sdk),
               exe=str(sdk/'bin/strata-vision-hip.exe'),
               hip_device=int(os.environ['VISION_HIP_ORDINAL']), temp_dir=str(root/'.vision-tmp'))
    env = windows_hip_env(cfg, dict(os.environ))
with (root/f'.vision-tmp/{arm}.stderr.log').open('w', encoding='utf-8') as log:
    v = Vision(cfg, log=log, env=env, lazy=True)
    v.spawn[0].extend(['--trace-graph', '--flash-attn', 'off'])
    try:
        v._start()
        t0 = time.monotonic()
        path, tokens = v.encode(str(image))
        shutil.copyfile(path, root/f'.vision-tmp/{arm}.sve')
        print(arm, 'tokens', tokens, 'encode_seconds', time.monotonic()-t0)
    finally:
        # Raises on unconfirmed HIP exit; do not delete scratch or spawn another child on that error.
        v.shutdown()
'@
$encodeOne | & $python -X utf8 - cpu-aa1
# Check exit code, logs and memory/recovery before each following invocation.
$encodeOne | & $python -X utf8 - cpu-aa2
# Set VISION_HIP_ORDINAL to the exact observed/matched ordinal, then:
$encodeOne | & $python -X utf8 - hip
```

Expect READY width 2560, <=300 actual image tokens, one SVE1 output per arm, and successful owned-child exit.
The HIP stderr must prove selected ROCm device/PCI/gfx1201, actual SDK DLL/BLAS/kpack paths, and completed HIP
compute >0 in **both warmup and encode**. Compare loaded paths/hashes to the pinned receipt. CPU helper nodes
are separately reported; whole encoder CPU fallback fails. Preserve actual kernel trace evidence in the runtime
diagnostic window as required by v6, in addition to these graph summaries.

Compare the three outputs without another encode:

```powershell
@'
import struct
from pathlib import Path
import numpy as np
root = Path('C:/Develop/AI/StrataMod/.vision-tmp')
def read(arm):
    b = (root/f'{arm}.sve').read_bytes()
    h = struct.unpack('<5i', b[:20])
    magic,n,nx,ny,d = h
    assert magic == 0x31455653 and 0 < n <= 300 and nx > 0 and ny > 0 and nx*ny == n and d == 2560
    assert len(b) == 20+n*d*4
    a = np.frombuffer(b, dtype='<f4', offset=20).astype(np.float64)
    assert np.isfinite(a).all()
    return h,a
h,a = read('cpu-aa1')
for arm in ('cpu-aa2','hip'):
    hh,b = read(arm)
    assert hh == h
    norm = np.linalg.norm(a)
    assert norm > 0 and np.linalg.norm(b) > 0
    rel = np.linalg.norm(a-b)/norm
    cos = np.dot(a,b)/(norm*np.linalg.norm(b))
    print(arm, 'shape', hh, 'L2relative', rel, 'cosine', cos)
    assert rel <= 0.02 and cos >= 0.999
'@ | & $python -X utf8 -
```

Preserve CPU A/A metrics as the numerical baseline; use any stricter existing parity criterion in preference to
the ceiling above. The image's known answer is `R9700 123 ABC`, red square left, blue circle right, green triangle
bottom. Embedding parity alone does not prove answering quality. After standalone gates, the runtime worker binds
the image config through its existing candidate manifest, then checks OpenAI data URL, Anthropic base64, Responses
image and WebUI attachment with that answer. Next verify corrupt/overlarge/timeout/cancel/OOM recovery and
text-image-text cache separation before long context or 512→1024-token gates. On any unconfirmed kill/wait, retain
the owned Popen and scratch path, report cleanup_pending/error, and stop subsequent starts until the same handle
confirms exit. Real failure recovery, memory budget and rollback remain pending until measured.

No commit, push or PR is authorized. Required real-environment checks keep the child Inprogress.
