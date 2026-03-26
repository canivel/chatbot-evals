"""Root conftest - ensure local packages take precedence over stdlib."""

import sys
from pathlib import Path

# Insert project root at the beginning of sys.path so our 'platform' package
# takes precedence over the stdlib 'platform' module.
project_root = str(Path(__file__).parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)
