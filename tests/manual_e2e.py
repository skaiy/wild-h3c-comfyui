#!/usr/bin/env python3
"""Manual end-to-end smoke test — NOT collected by pytest, NOT for CI.

Runs one real minimal generation (512x512, 0.25s = 6 frames, 4 steps, fast
preset) through H3TextToVideo.execute and checks the VIDEO output.

Prerequisites on this machine:
  * the h3 binary, built from h3.c (e.g. ~/h3.c/h3)
  * the MiniMax-H3 checkpoints (~268 GB; FL2VA suffices for this test)
  * config.json in the plugin folder filled in, or edit H3_BINARY/MODEL_DIR
    below / set the env vars
  * run with ComfyUI's venv python, e.g.:

    COMFYUI_ROOT=/path/to/ComfyUI \
      /path/to/ComfyUI/.venv/bin/python3.12 tests/manual_e2e.py

Measured on an M5 Max: ~32 s wall clock for these settings.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # for conftest

from conftest import load_plugin_package  # noqa: E402


def main():
    plugin = load_plugin_package()
    nodes = plugin.nodes

    result = nodes.H3TextToVideo.execute(
        prompt="A red cube rotating slowly on a white background, studio light.",
        width=512,
        height=512,
        seconds=0.25,          # 6 frames, the h3 minimum
        steps=4,
        preset="fast",
        seed=1,
        token_reduction=False,
        ssd_streaming=False,
        binary_path=os.environ.get("H3_BINARY", ""),
        model_dir=os.environ.get("H3_MODEL_DIR", ""),
    )

    from comfy_api.latest import InputImpl

    videos = result.result if isinstance(result.result, (list, tuple)) else [result.result]
    video = videos[0]
    assert isinstance(video, InputImpl.VideoFromFile), (
        f"expected VideoFromFile, got {type(video)!r}")

    # VideoFromFile stores the internal file reference; resolve it to a path.
    impl = getattr(video, "_VideoFromFile__impl", video)
    path = getattr(impl, "path", None) or getattr(impl, "file", None)
    if path is None:
        # Fall back: dig through whatever attribute holds the filename.
        for attr in vars(impl).values() if hasattr(impl, "__dict__") else []:
            if isinstance(attr, str) and attr.endswith(".mp4"):
                path = attr
                break
    assert path, f"could not extract file path from {video!r}"
    assert os.path.isfile(path), f"output file missing: {path}"
    assert os.path.getsize(path) > 0, f"output file is empty: {path}"

    print(f"OK: {path} ({os.path.getsize(path)} bytes)")


if __name__ == "__main__":
    main()
