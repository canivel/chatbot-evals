"""Root conftest - ensure local packages take precedence over stdlib."""

import sys
from pathlib import Path

project_root = str(Path(__file__).parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Also add the SDK directory so `chatbot_evals` package is importable
sdk_root = str(Path(__file__).parent / "sdk")
if sdk_root not in sys.path:
    sys.path.insert(0, sdk_root)
