"""Shared fixtures and helpers for the wild-h3c test suite.

Unit tests load h3_runner.py as a standalone module (pure stdlib — no ComfyUI
needed). Schema tests need a real ComfyUI checkout for comfy_api; point the
COMFYUI_ROOT environment variable at it, otherwise the default below is used.
"""

import importlib.util
import os
import sys
import types

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# importlib import mode does not put the test dir on sys.path; do it here so
# test modules can `from fakes import ...`.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
DEFAULT_COMFYUI_ROOT = (
    "/Users/skaiy/Desktop/03.skaiy项目/00.AI项目/01.AIGCComfyUI/ComfyUI"
)


def load_runner():
    """Import h3_runner.py standalone (no package context, no ComfyUI).

    Each call returns a fresh module object, so tests can monkeypatch module
    state (_CONFIG_PATH, _config_cache) without leaking into other tests.
    """
    spec = importlib.util.spec_from_file_location(
        "wild_h3c_h3_runner_under_test", os.path.join(REPO_ROOT, "h3_runner.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_plugin_package():
    """Import the plugin as package `wild_h3c`, mimicking ComfyUI's loader.

    Requires a ComfyUI checkout on sys.path (comfy_api, comfy, folder_paths).
    """
    root = os.environ.get("COMFYUI_ROOT", DEFAULT_COMFYUI_ROOT)
    if not os.path.isfile(os.path.join(root, "comfy", "model_management.py")):
        pytest.skip(f"ComfyUI checkout not found at {root} (set COMFYUI_ROOT)")
    if root not in sys.path:
        sys.path.insert(0, root)
    init = os.path.join(REPO_ROOT, "__init__.py")
    spec = importlib.util.spec_from_file_location(
        "wild_h3c", init, submodule_search_locations=[REPO_ROOT]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["wild_h3c"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def runner():
    """A fresh h3_runner module for each test."""
    return load_runner()


@pytest.fixture()
def plugin():
    """The plugin package loaded against a real ComfyUI checkout."""
    return load_plugin_package()


@pytest.fixture()
def fake_comfy(monkeypatch):
    """Stub `comfy.model_management` so run_h3() can be unit-tested.

    Returns the fake model_management module; tests can override
    processing_interrupted to simulate a ComfyUI cancel.
    """
    mm = types.ModuleType("comfy.model_management")

    class InterruptProcessingException(Exception):
        pass

    mm.InterruptProcessingException = InterruptProcessingException
    mm.processing_interrupted = lambda: False

    comfy = types.ModuleType("comfy")
    comfy.model_management = mm
    monkeypatch.setitem(sys.modules, "comfy", comfy)
    monkeypatch.setitem(sys.modules, "comfy.model_management", mm)
    return mm
