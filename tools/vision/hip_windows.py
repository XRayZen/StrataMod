"""Compatibility entry for the existing amdVision build/probe/config CLI."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.vision.amd_vision import cli as _implementation

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
