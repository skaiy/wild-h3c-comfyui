"""Subprocess runner for the h3 (MiniMax-H3 C/Metal) CLI.

Wraps `./h3 -d MODEL_DIR -p PROMPT ... -o OUT.mp4`:
  * builds the command line from node parameters,
  * reads stderr one character at a time (progress is flushed with \\r,
    so line iteration would deadlock),
  * feeds parsed progress into comfy.utils.ProgressBar,
  * kills the child process when ComfyUI interrupts execution.
"""

import json
import math
import os
import queue
import re
import subprocess
import threading
import time
import uuid
from collections import deque

# h3 prints progress to stderr as:  \r<phase>  <done>/<total>
PROGRESS_RE = re.compile(
    r"(denoise(?: enqueue)?|video VAE load|FFmpeg|Qwen|video VAE|audio VAE|H3 DiT|load"
    r"|tokenizer|text encoder)\s+(\d+)\s*/\s*(\d+)"
)
WROTE_RE = re.compile(r"h3: wrote (.+)")

# One h3 process saturates the GPU; never let two nodes run concurrently.
_h3_lock = threading.Lock()

# No built-in machine paths: the plugin never guesses where h3.c or the model
# live. Both must be set in config.json or in the node's advanced inputs.
_DEFAULTS = {
    "h3_binary": "",
    "model_dir": "",
}

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
_config_cache = None


def load_config():
    """Plugin config.json merged over empty defaults; user edits take precedence."""
    global _config_cache
    if _config_cache is None:
        cfg = dict(_DEFAULTS)
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update({k: v for k, v in json.load(f).items() if isinstance(v, str)})
        except FileNotFoundError:
            pass
        except Exception as exc:
            print(f"[wild-h3c] failed to read config.json, using defaults: {exc}")
        _config_cache = cfg
    return _config_cache


def resolve_path(value, key):
    """Empty widget value falls back to config.json; '~' is expanded either way.

    Raises a ValueError with setup instructions when nothing is configured,
    instead of failing deep inside a subprocess call.
    """
    raw = ""
    if value and value.strip():
        raw = value.strip()
    else:
        raw = (load_config().get(key) or "").strip()
    if not raw:
        raise ValueError(
            f"[H3] '{key}' is not configured.\n"
            "Set it in the node's advanced inputs, or edit config.json in this "
            "plugin folder, e.g.:\n"
            '  {"h3_binary": "~/h3.c/h3", "model_dir": "~/h3.c/MiniMax-H3"}\n'
            "See README.md for how to build the h3 binary and download the model."
        )
    return os.path.abspath(os.path.expanduser(raw))


# ---------------------------------------------------------------- preflight

PRESETS = {
    #          layers, reuse
    "precise": (50, 1),
    "balanced": (45, 2),
    "fast": (40, 3),
}

MAX_PIXELS = 768 * 1344


def requested_frames(seconds):
    """Match h3's C llround(seconds * 24)."""
    return math.floor(seconds * 24 + 0.5)


def preflight(prompt, width, height, seconds, steps, seed, has_refs, ref_audio_seconds, n_ref_images):
    errors = []
    if not prompt or not prompt.strip():
        errors.append("prompt is empty")
    if width < 32 or height < 32 or width % 32 or height % 32:
        errors.append(f"width/height must be multiples of 32 (got {width}x{height})")
    if width * height > MAX_PIXELS:
        errors.append(f"width*height must be <= 768*1344 (got {width}x{height})")
    if not math.isfinite(seconds) or seconds <= 0:
        errors.append(f"seconds must be positive (got {seconds})")
    else:
        frames = requested_frames(seconds)
        if not 6 <= frames <= 362:
            errors.append(
                f"seconds={seconds} requests {frames} frames; h3 trains on 6..362 frame chunks "
                f"(~0.25s..15.1s at 24fps)"
            )
    if not 2 <= steps <= 1000:
        errors.append(f"steps must be 2..1000 (got {steps})")
    if not 0 <= seed < 2**64:
        errors.append(f"seed must be an unsigned 64-bit integer (got {seed})")
    if has_refs:
        if n_ref_images > 9:
            errors.append(f"Ref2VA supports at most 9 reference images (got {n_ref_images})")
        if ref_audio_seconds is not None:
            if n_ref_images == 0:
                errors.append("reference audio requires at least one reference image")
            if not 2.0 <= ref_audio_seconds <= 15.0:
                errors.append(f"reference audio must be 2..15 seconds (got {ref_audio_seconds:.2f}s)")
    if errors:
        raise ValueError("[H3] preflight failed:\n - " + "\n - ".join(errors))


def build_command(binary, model_dir, prompt, width, height, seconds, steps, layers, reuse,
                  seed, output_path, token_reduction=False, ssd_streaming=False,
                  first_frame=None, last_frame=None, ref_images=None, ref_image_size="match",
                  ref_audio=None):
    cmd = [
        binary, "--profile",
        "-d", model_dir,
        "-p", prompt,
        "--width", str(width),
        "--height", str(height),
        "--seconds", f"{seconds:g}",
        "--steps", str(steps),
        "--layers", str(layers),
        "--reuse", str(reuse),
        "--seed", str(seed),
        "-o", output_path,
    ]
    if first_frame:
        cmd += ["--first-frame", first_frame]
    if last_frame:
        cmd += ["--last-frame", last_frame]
    for img in ref_images or []:
        cmd += ["--ref-image", img]
    if ref_images:
        cmd += ["--ref-image-size", ref_image_size]
    if ref_audio:
        cmd += ["--ref-audio", ref_audio]
    if token_reduction:
        cmd.append("--token-reduction")
    if ssd_streaming:
        cmd.append("--ssd-streaming")
    return cmd


# ---------------------------------------------------------------- subprocess

def unique_path(directory, prefix, ext):
    os.makedirs(directory, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return os.path.join(directory, f"{prefix}_{stamp}_{uuid.uuid4().hex[:8]}{ext}")


def run_h3(cmd, output_path, pbar=None, log=print):
    """Run h3 to completion, streaming stderr progress into `pbar`.

    Raises model_management.InterruptProcessingException on ComfyUI cancel,
    RuntimeError on h3 failure (with the stderr tail attached).
    """
    from comfy import model_management

    with _h3_lock:
        # h3 locates h3_shaders.metal relative to cwd; -o and -d are absolute,
        # so running from the binary's directory writes nothing into h3.c.
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            bufsize=0,
            cwd=os.path.dirname(os.path.abspath(cmd[0])) or None,
        )
        chunks: queue.Queue = queue.Queue()

        def _reader():
            try:
                while True:
                    ch = proc.stderr.read(1)
                    if not ch:
                        break
                    chunks.put(ch)
            except Exception:
                pass
            finally:
                chunks.put(None)

        reader = threading.Thread(target=_reader, daemon=True)
        reader.start()

        buf = b""
        tail = deque(maxlen=40)
        saw_wrote = False
        eof = False
        try:
            while not eof:
                if model_management.processing_interrupted():
                    raise model_management.InterruptProcessingException()
                try:
                    item = chunks.get(timeout=0.25)
                except queue.Empty:
                    if proc.poll() is not None and not reader.is_alive():
                        eof = True
                    continue
                if item is None:
                    eof = True
                    continue
                buf += item
                if item in (b"\r", b"\n"):
                    segment = buf.decode("utf-8", errors="replace").strip()
                    buf = b""
                    if not segment:
                        continue
                    tail.append(segment)
                    if WROTE_RE.search(segment):
                        saw_wrote = True
                    m = PROGRESS_RE.search(segment)
                    if m and pbar is not None:
                        done, total = int(m.group(2)), max(int(m.group(3)), 1)
                        pbar.update_absolute(done, total)
                    elif m:
                        log(f"[H3] {m.group(1)} {m.group(2)}/{m.group(3)}")
            rc = proc.wait()
        except BaseException:
            _kill(proc)
            raise

    if rc != 0:
        stderr_tail = "\n".join(tail)
        kind = "argument error" if rc == 2 else "runtime error"
        raise RuntimeError(
            f"[H3] h3 exited with code {rc} ({kind}).\n"
            f"command: {' '.join(cmd[:1])} ...\n"
            f"stderr tail:\n{stderr_tail}"
        )
    if not saw_wrote and not os.path.isfile(output_path):
        raise RuntimeError(
            "[H3] h3 exited 0 but neither printed 'h3: wrote' nor produced the output file.\n"
            f"stderr tail:\n" + "\n".join(tail)
        )
    return output_path


def _kill(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
