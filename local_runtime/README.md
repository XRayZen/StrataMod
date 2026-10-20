# Optional local Windows adapter

This directory preserves the StrataMod experiment and normal-entry adapter,
including its ownership and failed-start cleanup tests. It uses the sibling
`Strata` Python environment and `Strata-data` model/configuration authority.
Cloning the source does not create those installations or authorize a GPU run.

For a general installation, use the official [setup instructions](../docs/AI_SETUP.md).
For an existing validated local installation, `StrataMod.cmd` opens its normal
entry, `StrataMod.cmd status` reads its state, and Ctrl+C in the owning terminal
requests shutdown. Check current state before changing a running installation.
Do not apply experiment-only limits to ordinary use.

`Install-StrataMod.cmd --check` checks the local command installation;
`Install-StrataMod.cmd` installs its fixed shim after its existing ownership,
collision and lock checks. It has no arbitrary output-target option.
The script derives the source root and current user's shim directory instead
of embedding a developer's absolute path.

Private `normal`, `profiles`, `runs`, `records` and `calibration-runs` data are
excluded from Git. A validated source-only receipt revision is required after
changing bound source. Historical experiment manifests retain their strict
baseline commit; new manifests bind baseline, exact commit/tree and raw source
inside their separately approved authorization.

CPU fixtures use test-owned process/path/transport stubs. Model, image, SDK and
real-GPU results remain separate. See [maintenance notes](../docs/STRATAMOD.md).

The optional `release_revision` reader binds the official 0.1.45.3 signed
Windows HIP bundle in a private versioned `runtimes` directory. It preserves the
saved normal profile values and supports the official GPU reader with its CPU
fallback; status reports the actual image backend. Historical private HIP
diagnostic receipts keep their original strict SDK/argument contract.
New bundle and Python dependencies receive full hashes. Unchanged model hashes
are inherited only after matching the saved no-reparse size/mtime proof.

The finite `release_trial` entry is separate from normal selection. Its approved
five arms change only two performance flags and a common trial-only prompt
cache of zero. Quantitative requests use the fixed 128-token fixture and a
120-second disconnect watchdog. Normal requests retain their existing output,
thinking and retry defaults. Performance adoption remains a separate decision.

The optional `normal_performance_revision` adapter records an explicitly
approved saved adoption of `STRATA_HIP_WMMA=1` and `STRATA_PF_FUSED=1`. Its
version 2 receipts bind a clean release-descended commit and the exact runtime
source inventory, while preserving every other saved profile value. The
ordinary engine defaults stay unchanged. Installation paths, parent proof and
selected receipt belong in ignored private data, not published source. Legacy
receipts keep their validators; moving an existing private installation to a
new source version requires a matching receipt before ordinary launch.
