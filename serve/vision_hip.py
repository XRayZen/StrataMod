"""Compatibility alias for serve.stratamod.amd_vision.environment."""
import sys
from serve.stratamod.amd_vision import environment as _implementation
sys.modules[__name__] = _implementation
