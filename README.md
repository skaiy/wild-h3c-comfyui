# Wild H3C — MiniMax H3 for Apple Silicon

Run **MiniMax H3** video generation **locally on your Mac**, powered by the
[h3.c](https://github.com/antirez/h3.c) Metal engine — the native C/Metal port
of MiniMax H3 for Apple Silicon by Salvatore Sanfilippo (antirez, author of
Redis).

> **[中文版 README](README.zh-CN.md)**

<!-- TODO: add a screenshot or short screen recording of the nodes in action -->
<!-- ![Wild H3C nodes in ComfyUI](docs/screenshot.png) -->

## Why this plugin

- **The only practical way to run MiniMax H3 on a Mac.** ComfyUI's built-in
  local H3 support targets NVIDIA CUDA; on Apple Silicon the PyTorch path is
  unusably slow (an hour+ per clip). h3.c generates a short clip in seconds to
  minutes on Apple Silicon via Metal.
- **Zero API cost.** The official MiniMax API nodes bill per second of video.
  Local generation has a marginal cost of zero — iterate on prompts, seeds and
  references as much as you like.
- **Private and offline.** Your footage and references never leave the
  machine.

This plugin is a thin, audited bridge: it shells out to the `h3` CLI binary
you build yourself, streams its progress into ComfyUI's progress bar, and
returns a standard ComfyUI `VIDEO` output.

## Requirements

- macOS on **Apple Silicon** (the h3.c engine runs on Metal)
- ComfyUI ≥ 0.18 (V3 node schema; verified on 0.37.0)
- `ffmpeg` and `ffprobe` on your `PATH` (e.g. `brew install ffmpeg`)
- The `h3` binary, built from source (see below)
- The MiniMax-H3 checkpoints, ~268 GB on disk (see below)

No Python dependencies beyond what ComfyUI already ships.

## Installation

### Via ComfyUI Manager (once published to the Registry)

Search for **Wild H3C** in ComfyUI Manager and install.

### Manual

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/skaiy/wild-h3c-comfyui.git
```

Then restart ComfyUI.

## Step 1 — Build the h3.c engine

The plugin does not ship the engine binary; you build it from the upstream
source (MIT licensed):

```bash
git clone https://github.com/antirez/h3.c.git
cd h3.c
make -j8
```

This produces the `./h3` executable. Keep the whole `h3.c` directory — the
binary locates `h3_shaders.metal` relative to its own location at runtime.

## Step 2 — Get the model

The plugin does not ship or download the model. There are two paths,
depending on whether you already have the MiniMax-H3 weights on disk.

### Path A — You already have the weights

For example from an earlier h3.c setup. Just point the plugin at the existing
directory — either `model_dir` in `config.json` or the per-node override
(see Step 3). The directory layout h3 expects:

```
MiniMax-H3/
├── model_index.json
├── FL2VA/      # required: text-to-video + first/last-frame anchoring
│   ├── tokenizer/  text_encoder/  processor/
│   ├── transformer/  video_vae/  audio_vae/
│   └── model_index.json
└── Ref2VA/     # only needed for the Reference to Video node
    └── (same subfolders)
```

Each checkpoint is ~134 GB on disk; **FL2VA alone is enough** if you only use
the Text to Video node.

To verify a directory before configuring the plugin, run h3's header-only
inventory check (seconds, no weights loaded):

```bash
cd <path-to>/h3.c
./h3 --info -d <path-to>/MiniMax-H3
```

If it prints the checkpoint inventory (Qwen3-VL encoder, FL2VA DiT, video VAE,
audio VAE, …) without errors, the directory is good to use.

### Path B — Download the weights

The checkpoints live on Hugging Face:
[MiniMaxAI/MiniMax-H3](https://huggingface.co/MiniMaxAI/MiniMax-H3)
(~268 GB total; grab FL2VA only if you don't need reference conditioning):

```bash
# everything:
huggingface-cli download MiniMaxAI/MiniMax-H3 --local-dir <path-to>/MiniMax-H3

# FL2VA only (~134 GB):
huggingface-cli download MiniMaxAI/MiniMax-H3 --include "FL2VA/*" "model_index.json" \
    --local-dir <path-to>/MiniMax-H3
```

If Hugging Face is unreachable from your network, the weights are also
mirrored on ModelScope (`MiniMax/MiniMax-H3`), and `huggingface-cli` works
with mirrors via `HF_ENDPOINT` (e.g. `HF_ENDPOINT=https://hf-mirror.com`).
Some h3.c checkouts also ship a resumable helper, `download-h3.sh`
(`./download-h3.sh <file-list> <target-dir> [jobs]`, curl + hf-mirror with
retries), which does the same job.

Either way, verify the result with `./h3 --info -d <dir>` as in Path A.

> ### ⚠️ Model license — read before downloading
>
> The MiniMax-H3 weights are **not** open source. They are governed by the
> **MiniMax H3 Community License Agreement**, which — as of this writing —
> restricts deployment in certain regions (reportedly the US, EU, UK and
> South Korea) and requires a **paid commercial license** for commercial use
> of generated content (Comfy is the official reseller).
>
> This plugin's code is MIT, but the model license is entirely separate.
> **You are responsible for confirming that your location and your use case
> comply with the MiniMax H3 Community License before downloading or using
> the weights.**

## Step 3 — Configure paths

The plugin needs to know where the `h3` binary and the model directory live.
Two ways:

**Option A — `config.json`** (recommended): edit `config.json` in the plugin
folder (the repo also ships `config.example.json` with a filled-in example):

```json
{
  "h3_binary": "<path-to>/h3.c/h3",
  "model_dir": "<path-to>/h3.c/MiniMax-H3"
}
```

- `h3_binary` — path to the `h3` executable you built in Step 1.
- `model_dir` — path to the MiniMax-H3 directory from Step 2 (the folder that
  contains `FL2VA/` etc., not the `FL2VA` folder itself).

JSON has no comments, so the field documentation lives here; keep both files
valid JSON.

**Option B — per-node override**: every node has advanced inputs
`binary_path` / `model_dir`. Leave them empty to use `config.json`; fill them
in to override per workflow.

Both support `~` expansion. If neither is set, the node fails fast with a
clear error telling you what to configure.

## Nodes

### Wild H3 Text to Video

Text-to-video (FL2VA), with optional first/last-frame anchoring.

| Input | Type | Notes |
|---|---|---|
| `prompt` | STRING (multiline) | Raw H3 prompt |
| `width` / `height` | INT | Multiples of 32, area ≤ 768×1344; default 864×480 |
| `seconds` | FLOAT | 0.25–15.0 at 24 fps; h3 aligns frames to 5+17n chunks |
| `steps` | INT | Denoising passes; default 20 |
| `preset` | COMBO | `precise` (50 layers/reuse 1), `balanced` (45/2), `fast` (40/3) |
| `seed` | INT | Full 64-bit range, supports randomize |
| `token_reduction` | BOOL (advanced) | Pair video tokens in middle DiT blocks — aggressive speedup |
| `ssd_streaming` | BOOL (advanced) | Stream BF16 DiT weights from SSD |
| `binary_path` / `model_dir` | STRING (advanced) | Per-node config overrides |
| `first_frame` | IMAGE (optional) | FL2VA first-frame conditioning |
| `last_frame` | IMAGE (optional) | FL2VA last-frame conditioning |

Output: **VIDEO** — plug straight into the built-in **Save Video** /
**Preview Video** nodes.

### Wild H3 Reference to Video (Ref2VA)

Reference-conditioned generation.

| Input | Type | Notes |
|---|---|---|
| *(all common inputs above)* | | |
| `ref_images` | IMAGE (optional, batch) | Up to 9 ordered reference images; cite them in the prompt as `<Picture 1>`, `<Picture 2>`, … |
| `ref_audio` | AUDIO (optional) | One 2–15 s audio reference, cited as `<Audio 1>`; requires at least one reference image |
| `ref_image_size` | COMBO (advanced) | `match` or `max` |

Reference inputs are mutually exclusive with first/last-frame anchoring (use
the Text to Video node for that).

## Example

1. Add **Wild H3 Text to Video**.
2. Prompt: `A drone shot gliding over a misty pine forest at dawn, cinematic.`
3. 864×480, 4 seconds, 20 steps, preset `balanced`.
4. Connect `video` → **Save Video**. Queue.

First runs pay a one-time model-load cost (tens of seconds with no progress
updates — this is normal). On an M5 Max, a default 20-step clip lands in well
under a minute; `fast` preset + fewer steps is near-instant for iteration.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `h3 binary not found` | Build h3.c (`make -j8`) and point `config.json` at the `h3` executable |
| `model directory not found` | Download the checkpoints and set `model_dir` to the folder containing them |
| `ffmpeg`/`ffprobe` errors from h3 | `brew install ffmpeg` so both are on `PATH` |
| Long stall with no progress bar | Model loading (37 GiB checkpoint) prints no progress lines; wait it out |
| Node fails on an old workflow | Node IDs were renamed to `WildH3*` at release; re-add the node |

Behavior notes:

- **Progress**: h3 prints `\r<phase> done/total` to stderr; the plugin feeds
  it into ComfyUI's progress bar.
- **Cancel**: interrupting in ComfyUI terminates the h3 child process
  (terminate → 5 s → kill).
- **Concurrency**: h3 calls are serialized with a global lock — one process
  already saturates the GPU.
- **Errors**: preflight failures list the exact rule violated; non-zero h3
  exit codes surface the raw stderr tail.

## How this relates to the official MiniMax API nodes

Complementary, not competing. Use Wild H3C as your **local iteration layer** —
prompt, composition and reference experiments are free and instant on your
Mac. When a shot is locked, you can optionally hand the final prompt to the
official MiniMax API nodes (built into ComfyUI) for H3 Max, Context-IR or the
hosted 2K Regenerate pass. The official nodes also remain the only way to use
features that are not in the open checkpoints.

## Support the project

Wild H3C is free and open source (MIT). If it saves you API bills or studio
time, you can support development:

- **GitHub Sponsors**: <!-- TODO: enable GitHub Sponsors, then link --> `https://github.com/sponsors/skaiy` *(placeholder — coming soon)*
- **爱发电 (Afdian)**: <!-- TODO: create Afdian page, then link --> *(placeholder — coming soon)*

## Acknowledgements

- [antirez/h3.c](https://github.com/antirez/h3.c) — Salvatore Sanfilippo's
  native C/Metal port that makes all of this possible (MIT).
- [MiniMax-AI/MiniMax-H3](https://huggingface.co/MiniMaxAI/MiniMax-H3) — the
  model and its checkpoints (MiniMax H3 Community License).

"Wild H3C" is an independent community project and is not affiliated with or
endorsed by MiniMax. "MiniMax" and "H3" are referenced here only to describe
compatibility.

## Development

The test suite lives in `tests/` (excluded from the Registry package via
`.comfyignore`). Run it with ComfyUI's own Python — no extra dependencies
beyond `pytest`:

```bash
# one-time:
/path/to/ComfyUI/.venv/bin/python -m pip install pytest

# from the repo root:
/path/to/ComfyUI/.venv/bin/python -m pytest
```

- Unit tests (preflight rules, command building, config resolution, progress
  parsing, cancel semantics) are pure stdlib + pytest and finish in seconds.
- Schema/loading tests import the plugin against a real ComfyUI checkout.
  They default to a hard-coded local path; point `COMFYUI_ROOT` at your
  ComfyUI root to override (tests skip cleanly if none is found):

  ```bash
  COMFYUI_ROOT=/path/to/ComfyUI /path/to/ComfyUI/.venv/bin/python -m pytest
  ```

- `tests/manual_e2e.py` is a manual smoke test that runs one real minimal
  generation (512×512, 0.25 s, 4 steps) through the Text to Video node. It is
  not collected by pytest and requires a working h3 binary + model; see the
  header comment in the file.

## Publishing (for the maintainer)

1. Register at [registry.comfy.org](https://registry.comfy.org) and create a
   Publisher — the PublisherId is permanent, choose carefully.
2. Put the PublisherId into `pyproject.toml` → `[tool.comfy] PublisherId`
   (replace `YOUR_PUBLISHER_ID`).
3. Generate a Registry Publishing API Key on the publisher page and add it to
   this repo as the `REGISTRY_ACCESS_TOKEN` secret (Settings → Secrets and
   variables → Actions).
4. Set the repository variable `REGISTRY_PUBLISH_ENABLED` to `true` (same
   settings page, Variables tab) — this arms the publish workflow.
5. Bump `version` in `pyproject.toml` and push — the GitHub Action publishes
   automatically on any `pyproject.toml` change. First release can also be
   done locally with `comfy node publish`.

## License

Plugin code: [MIT](LICENSE). The h3.c engine is MIT (its own repository).
MiniMax-H3 model weights are governed by the MiniMax H3 Community License —
see the warning above.
