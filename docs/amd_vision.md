# amdVision — opt-in Windows HIP images

Official v0.2.0-beta setup enables pictures by default and chooses its CPU or GPU
reader by VRAM, with an explicit mode choice and automatic GPU-to-CPU fallback.
This guide describes the separate private SDK diagnostic path. Use
[`hip_windows.py`](../tools/vision/hip_windows.py) explicitly for that opt-in path;
it does not replace the official picture defaults, change the text engine or
make the local ownership adapter a general installer.

Use an x64 Visual Studio developer shell (MSVC 19.43 or newer, CMake and Ninja).
Obtain an isolated **ROCm 10.1.0** SDK for your supported GPU from
[AMD's installation instructions](https://rocm.docs.amd.com/en/docs-10.1.0/install/rocm.html)
or [TheRock's release instructions](https://github.com/ROCm/TheRock/blob/main/RELEASES.md).
For its Python distribution, initialize it with `rocm-sdk init` and obtain the
root with `rocm-sdk path --root`. Put its private environment and SDK beneath
this repository root, in a path without spaces (the probe and encoder temporary
directory guards require this layout). Keep it separate from the working text
engine and its libraries; do not replace its DLLs or change the global PATH.
The following PowerShell commands run from this repository root, with
`$ImageSdk` set to that initialized SDK root and `python` from your build environment:

```powershell
git clone https://github.com/ggml-org/llama.cpp .vision-src/llama.cpp
git -C .vision-src/llama.cpp checkout --detach 3cf03257f219afbe7334045ff7c6a06ac68c627d
python tools/vision/hip_windows.py build --rocm-root $ImageSdk --llama-dir .vision-src/llama.cpp --build-dir .vision-build/hip-private --arch gfx1201
python tools/vision/hip_windows.py probe --rocm-root $ImageSdk
```

Use a fresh llama.cpp directory and build directory. The helper checks the
clean pinned checkout, stages the encoder beside this private SDK, and refuses
to overwrite an existing encoder. `gfx1201` is the tested Radeon AI PRO R9700
target, not a universal GPU setting. The probe lists the SDK's unfiltered device
ordinals without loading a model: select the actual target, not an assumed 0.

Set `$TextConfig` to an existing working HIP text configuration, `$NativeModel`
to its first `--native` GGUF, `$Projector` to the matching model-family mmproj,
`$DeviceOrdinal` to the probed ordinal and `$ImageConfig` to a new JSON path:

```powershell
python tools/vision/hip_windows.py config --rocm-root $ImageSdk --config $TextConfig --model $NativeModel --mmproj $Projector --out $ImageConfig --hip-device $DeviceOrdinal --max-tokens 300
python -m serve.server --engine strata --config $ImageConfig
```

The config helper preserves the text arguments and creates a separate image
configuration; it does not overwrite the original. Matching dimensions alone
do not establish model-family compatibility. Build/probe success does not prove
image recognition: validate the chosen models, device, loaded DLLs, image order
and history, and normal shutdown on the target machine. Models, SDKs and native
binaries are not bundled. The local alias requires its separately validated
installation authority; creating this JSON does not activate that authority.


## Implementation and update boundary

The `amdVision` feature uses canonical `amd_vision` directories under
`serve/stratamod` and `tools/vision`. The old Python imports and build CLI remain
compatible. `server.Vision` retains the shared encoder owner, cache and lifecycle;
AMD validation, capability and image checks delegate to feature helpers. The
shared stop helper retains every reader's original process until exit is proved,
including the official CPU fallback; pending cleanup blocks another spawn and
keeps the temporary files until retrying cleanup succeeds.
The common native encoder retains ENC/SVE/mRoPE and model handling. AMD device,
graph and loaded-module diagnostics have their own internal translation unit.

Moving native build inputs or selecting a new executable requires a reviewed
native revision, not a source-only receipt or rewriting historical full proofs.
Unchanged models and SDK files may inherit their pinned full proof and metadata;
changed inputs and versioned binaries must be fully hashed and validated.

The local native revision inherits the original model/SDK payload evidence;
it does not claim a new full model pass. Newly recorded SDK/toolchain import
libraries are finite build dependencies and are hashed separately. This is
different from rereading an entire SDK or model directory. Activation still
verifies the used critical DLLs and selected executable in full.

The common `Vision` owner, cache and HTTP/service lifecycle remain in
`serve/server.py`. Only AMD-specific validation/stop/capability helpers are
delegated. Moving shared upstream code out of that file is not required to use
the feature folders. CUDA/CPU behavior and the existing native protocol remain
shared; this layout does not introduce a backend plugin API.
