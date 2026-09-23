"""pytest bootstrap (not part of the plugin; excluded via .comfyignore).

The repo root is the ComfyUI plugin package: its __init__.py uses relative
imports. pytest sees the rootdir's __init__.py, treats the rootdir as a
Package collector, and tries to import that __init__.py as a top-level module
named "__init__" — which fails on the relative import. Pre-seeding
sys.modules["__init__"] with an inert stub makes pytest reuse it instead
(importlib import mode returns already-loaded modules as-is). The real plugin
package is imported properly by tests/conftest.py when needed.
"""

import sys
import types

sys.modules.setdefault("__init__", types.ModuleType("__init__"))
