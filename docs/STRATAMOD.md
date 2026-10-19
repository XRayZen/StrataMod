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
