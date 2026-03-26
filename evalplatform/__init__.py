"""Chatbot-evals platform package.

This package shadows the stdlib ``platform`` module.  To keep third-party
libraries (e.g. ``attrs``, ``rich``, ``structlog``) working, we locate the
stdlib module by its file path and re-export its public API.
"""

from __future__ import annotations

import importlib.util as _ilu
import os as _os
import sys as _sys
import sysconfig as _sysconfig

# Locate the stdlib ``platform`` module on disk.  We cannot use
# ``importlib.import_module("platform")`` because it would recurse into
# this very package.
_stdlib_dir = _sysconfig.get_paths()["stdlib"]
_stdlib_platform_path = _os.path.join(_stdlib_dir, "platform.py")

_spec = _ilu.spec_from_file_location(
    "_stdlib_platform", _stdlib_platform_path
)
if _spec and _spec.loader:
    _stdlib_platform = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_stdlib_platform)

    # Re-export every public attribute from the stdlib module so that code
    # like ``import platform; platform.python_implementation()`` works.
    _self = _sys.modules[__name__]
    for _attr in dir(_stdlib_platform):
        if not _attr.startswith("_") and not hasattr(_self, _attr):
            setattr(_self, _attr, getattr(_stdlib_platform, _attr))

    del _self, _stdlib_platform, _attr

del _ilu, _os, _sysconfig, _stdlib_dir, _stdlib_platform_path, _spec
