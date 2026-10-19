# StrataMod maintenance branch

This fork starts from official Strata v0.1.45, commit
`477ac13cbe8e582c20484871ce459d20d82df09d`. `StrataMod` is the integration
branch. Small contributions to upstream should start from the current upstream
`main`, with only the required changes and their dependencies.

## Changes kept here

- An opt-in Windows HIP image encoder, its environment isolation, device and
  loaded-module diagnostics, and CPU/CUDA/HIP/SYCL build compatibility.
- Python image-process ownership, cleanup and input validation. Multiple images
  and image history use the existing ordered SVE records and mRoPE path; the
  temporary HIP-only one-image rejection is removed.
- Optional lifecycle callbacks for the local calibration/ownership adapter.
- The Windows `local_runtime` adapter and its CPU tests. Its experiment memory
  policy and finite diagnostic output/retry settings do not become normal
  Strata settings. The official setup entry remains available.

Qwen Code's model image capability setting belongs to the separate client
configuration. It is not part of this Strata fork.

## Module boundaries

| Responsibility | Location and remaining server connection |
| --- | --- |
| Image request accounting | `serve/vision_request.py` owns ordered occurrences, cancellation checks, source caching and SVE validation. `server.HipImageRequest` keeps its three-argument interface and binds the existing loader and cancellation exception. |
| Encoder and SDK | `serve/vision_hip.py` isolates the HIP environment; `tools/vision` owns the native adapter and build helper. `server.Vision` still owns the encoder process and cleanup. |
| Local operation and calibration | `local_runtime` retains installation authority, ownership and recovery; the optional engine/calibration callbacks remain in the upstream-facing files. |
| Clients and validation | Synthetic fixtures and `tools/vision` validation helpers remain separate from the server. Qwen Code is a separate project. |

This extraction does not move `Service` request/history handling, the native
generation protocol, or HTTP routes. Those upstream contact points remain; a
future upstream update still needs a review of lifecycle and image ordering.

## Opt-in Windows HIP image encoder

The standard setup currently leaves HIP image support off on Windows. Use
[`hip_windows.py`](../tools/vision/hip_windows.py) explicitly; this does not
change the text engine or make the local ownership adapter a general installer.

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

## Local installation and evidence

The optional local adapter expects the sibling `Strata` and `Strata-data`
directories and a separately validated private installation. It is not a new
general-purpose model installer. See [the adapter notes](../local_runtime/README.md).
The official installation instructions remain [AI_SETUP.md](AI_SETUP.md).

Models, projectors, SDKs, DLLs, virtual environments, image inputs, generated SVE,
profiles, receipts and logs are not included. Their individual licenses and
local validation requirements still apply. No private image or diagnostic dump
is needed to run the synthetic CPU fixtures.

The development installation previously read four images through Qwen Code and
answered a follow-up using the same image history. Main subjects and scenes
matched existing text annotations for all four images in both turns. This was
an image-unviewed text comparison; detail accuracy and full wire hashes were
not established. That hardware result does not certify every later commit.

## Source and Git identity

Historical experiment authorizations remain tied to their original commit.
New experiment manifests record the official baseline, exact commit and Git
tree, and must retain separately approved manifest hashes, raw source hashes
and the existing artifact authority. Merely generating a manifest grants no
execution approval. An unapproved commit, changed tree/source, missing Git
identity or unrelated history is rejected.

The normal installation receipt checks raw source and private configuration,
not Git HEAD alone. A source change requires an explicit source-only receipt
revision and validation; existing full asset verification may be inherited
where its established checks permit it. Do not rewrite historical receipts.

## Upstream overlap and validation

Windows HIP enablement overlaps existing upstream
[PR #1287](https://github.com/Niko1221/Strata/pull/1287) and
[PR #2704](https://github.com/Niko1221/Strata/pull/2704). Review those first;
do not present their shared base changes as a new independent contribution.
The private historical patch archive is not redistributed here.

Keep the repository MIT notice. Dependency, SDK and model licenses remain
separate. Before a contribution, test the extracted exact revision and build
every affected backend as required by [AGENTS.md](../AGENTS.md). State which
builds, GPU operations and failure paths were actually tested. Local CPU
fixtures and adapter compilation are not a new image-generation measurement.
