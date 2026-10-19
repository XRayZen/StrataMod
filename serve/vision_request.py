"""Compatibility alias for serve.stratamod.amd_vision.request."""
import sys
from serve.stratamod.amd_vision import request as _implementation
sys.modules[__name__] = _implementation
