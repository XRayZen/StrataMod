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
