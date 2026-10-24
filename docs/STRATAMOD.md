# StrataMod maintenance branch

This fork starts from official Strata v0.1.45, commit
`477ac13cbe8e582c20484871ce459d20d82df09d`. `StrataMod` is the integration
branch. Small contributions to upstream should start from the current upstream
`main`, with only the required changes and their dependencies.

The integration candidate includes official **v0.2.4**, peeled commit
`96ca4383c7b05a8a3e6064c65d9e9977d4b3bb59` (Qwen engine **0.1.48**).
Official v0.2.4 is integrated; machine-specific deployment and validation status is recorded separately.

## Changes kept here

- An opt-in Windows HIP image encoder, its environment isolation, device and
  loaded-module diagnostics, and CPU/CUDA/HIP/SYCL build compatibility.
- Windows AMD telemetry for the WebUI Monitor (GPU load, VRAM and temperature
  from DXGI, PDH and ADL); power and the PCIe link stay unavailable there.
- Python image-process ownership, cleanup and input validation. Multiple images
  and image history use the existing ordered SVE records and mRoPE path; the
  temporary HIP-only one-image rejection is removed.
- Optional lifecycle callbacks for the local calibration/ownership adapter.
- Windows token defaults retain child birth/record queries for the same user,
  SYSTEM and Administrators; owner-only file and directory ACLs stay unchanged.
- The Windows `local_runtime` adapter and its CPU tests. Its experiment memory
  policy and finite diagnostic output/retry settings do not become normal
  Strata settings. The official setup entry remains available.

Qwen Code's model image capability setting belongs to the separate client
configuration. It is not part of this Strata fork.

## Module boundaries

| Responsibility | Location and remaining server connection |
| --- | --- |
| Image request accounting | `serve/stratamod/amd_vision/request.py` owns ordered occurrences, cancellation checks, source caching and SVE validation. `server.HipImageRequest` keeps its three-argument interface and binds the existing loader and cancellation exception. |
| Encoder and SDK | `serve/stratamod/amd_vision/environment.py` isolates the HIP environment. AMD-only policy helpers live beside it in `encoder.py`; `server.Vision` retains shared process/cache/lifecycle. |
| Build and native diagnostics | `tools/vision/amd_vision/cli.py` and `diagnostics.{h,cpp}` own HIP build/config and device/graph/loaded-DLL reporting. Common ENC/SVE/mRoPE stays in `strata_vision.cpp`; the existing CMake target is retained. |
| Local operation and calibration | `local_runtime` retains installation authority, ownership and recovery; the optional engine/calibration callbacks remain in the upstream-facing files. |
| Clients and validation | Synthetic fixtures and `tools/vision` validation helpers remain separate from the server. Qwen Code is a separate project. |

This extraction does not move `Service` request/history handling, the native
generation protocol, or HTTP routes. Those upstream contact points remain; a
future upstream update still needs a review of lifecycle and image ordering.

The feature is called **amdVision**; its directories/imports use `amd_vision`.
The old `serve.vision_hip`, `serve.vision_request` and
`tools.vision.hip_windows` imports remain aliases, including their patchable
module globals. The existing build/probe/config script and public server class
signatures remain available. Shared `Vision` stays in the upstream-facing file:
moving its common code wholesale would also create delete/edit conflicts and
more manual porting work during upstream updates.

## Opt-in Windows HIP image encoder

The official setup enables pictures by default and chooses CPU or GPU according
to VRAM, while retaining the explicit picture-mode choice and GPU-to-CPU fallback.
The separate [amdVision build → probe → config guide](amd_vision.md) is an opt-in
private SDK and strict diagnostic path. Its flags do not replace the official
reader defaults. SDKs, models and native binaries remain external dependencies.
The helper now supplies the official HIP architecture setting and copies the
official `strata-vision-hip` output name.

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
not Git HEAD alone. Python-only changes use the strict source-only revision.
Changed native compilation inputs or executables instead need a reviewed finite
native revision: exact parent/full proof, changed build inputs and versioned
outputs, dependency provenance and permitted configuration changes are bound
separately. Unchanged large assets inherit their original full hashes only while
their metadata still matches. Explicit full verification remains available;
historical receipts are never rewritten, and preparation does not activate a
profile. This local authority mechanism is not a general-purpose installer.

The release candidate expands the finite source inventory to the official
`strata_control` and `strata_cli` modules and native reader build inputs. Existing
receipts cannot authorize those changed sources or a newly built executable;
reviewed native revision preparation and normal activation remain separate work.

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

## v0.2.3 integration validation

The release merge retains encoder ownership until exit is proved, preserves the
private HIP token cap, and aborts tool-image requests when reader cleanup is
pending. Official reader token defaults and elastic startup remain available.
Synthetic CPU regression tests cover those boundaries and image ordering.

A local Windows R9700 installation answered a short prompt, one request with
four images, and a follow-up using that image history with engine 0.1.48. That
installation includes an unpublished plain launcher and RAM selection changes;
it is not a GPU validation of this published tree or its receipt-based adapter.
Image detail accuracy, full-context input and long-running stability were not
measured. Product CUDA/HIP/SYCL rebuilds and GPU execution of this published
candidate have not been performed.

## v0.2.4 integration

This merge includes the official separate DeepSeek family, DSML handling and
engine-selection support. It does not install a DeepSeek model or engine into
the existing local Qwen installation. The Qwen engine bundle stays 0.1.48.
Mod image preparation events and cleanup checks remain beside the official
DeepSeek shared-prefix selection; Qwen requests keep their existing behavior.

Validation of this published tree uses synthetic CPU tests. Product backend
rebuilds and DeepSeek hardware execution are not performed. The local plain
installation has unpublished adapter changes, so its separate GPU verification
is not a GPU certification of this public receipt-based adapter.
