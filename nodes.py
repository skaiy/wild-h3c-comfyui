"""ComfyUI V3 nodes wrapping the h3 (MiniMax-H3 C/Metal) CLI."""

import os
import wave

import torch

from comfy_api.latest import ComfyExtension, io

from .h3_runner import (
    PRESETS,
    build_command,
    load_config,
    preflight,
    requested_frames,
    resolve_path,
    run_h3,
    unique_path,
)

# ------------------------------------------------------------------ helpers


def _save_image_tensor(tensor, path):
    """ComfyUI IMAGE (B,H,W,C float 0..1) -> PNG file."""
    from PIL import Image

    arr = tensor[0].clamp(0, 1).mul(255).round().to(torch.uint8).cpu().numpy()
    Image.fromarray(arr).save(path, format="PNG")
    return path


def _save_audio_wav(audio, path):
    """ComfyUI AUDIO ({waveform: (B,C,T), sample_rate}) -> 16-bit PCM WAV."""
    waveform = audio["waveform"][0]  # (C, T)
    sample_rate = int(audio["sample_rate"])
    pcm = waveform.clamp(-1, 1).mul(32767).round().to(torch.int16).cpu().numpy()
    with wave.open(path, "wb") as f:
        f.setnchannels(pcm.shape[0])
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(pcm.T.tobytes())
    return path, waveform.shape[-1] / sample_rate


def _run(binary_path, model_dir, prompt, width, height, seconds, steps, preset, seed,
         token_reduction, ssd_streaming, first_frame=None, last_frame=None,
         ref_images=None, ref_image_size="match", ref_audio=None):
    import folder_paths

    from comfy.utils import ProgressBar

    binary = resolve_path(binary_path, "h3_binary")
    mdir = resolve_path(model_dir, "model_dir")

    if not os.path.isfile(binary):
        raise ValueError(
            f"[H3] h3 binary not found: {binary}\n"
            "Build it from source first (git clone https://github.com/antirez/h3.c && make -j8). "
            "See README.md."
        )
    if not os.path.isdir(mdir):
        raise ValueError(
            f"[H3] model directory not found: {mdir}\n"
            "Download the MiniMax-H3 checkpoints from Hugging Face first. See README.md."
        )

    temp_dir = folder_paths.get_temp_directory()
    first_path = _save_image_tensor(first_frame, unique_path(temp_dir, "h3_first", ".png")) if first_frame is not None else None
    last_path = _save_image_tensor(last_frame, unique_path(temp_dir, "h3_last", ".png")) if last_frame is not None else None
    ref_paths = []
    if ref_images is not None:
        n = ref_images.shape[0]
        for i in range(min(n, 9)):
            ref_paths.append(_save_image_tensor(ref_images[i:i + 1], unique_path(temp_dir, f"h3_ref{i}", ".png")))
    ref_audio_path, ref_audio_seconds = None, None
    if ref_audio is not None:
        ref_audio_path, ref_audio_seconds = _save_audio_wav(
            ref_audio, unique_path(temp_dir, "h3_refaudio", ".wav"))

    has_refs = bool(ref_paths) or ref_audio_path is not None
    preflight(prompt, width, height, seconds, steps, seed,
              has_refs, ref_audio_seconds, len(ref_paths))

    layers, reuse = PRESETS[preset]
    output_path = unique_path(temp_dir, "h3", ".mp4")
    cmd = build_command(
        binary, mdir, prompt, width, height, seconds, steps, layers, reuse, seed,
        output_path, token_reduction=token_reduction, ssd_streaming=ssd_streaming,
        first_frame=first_path, last_frame=last_path,
        ref_images=ref_paths, ref_image_size=ref_image_size, ref_audio=ref_audio_path,
    )
    print(f"[wild-h3c] running: {' '.join(cmd)}")

    frames = requested_frames(seconds)
    pbar = ProgressBar(max(frames, steps))
    run_h3(cmd, output_path, pbar=pbar)

    # Lazy import: InputImpl only exists inside the ComfyUI runtime.
    from comfy_api.latest import InputImpl, io, ui

    video = InputImpl.VideoFromFile(output_path)
    filename = output_path.replace("\\", "/").rpartition("/")[2]
    return io.NodeOutput(video, ui=ui.PreviewVideo([ui.SavedResult(filename, "", io.FolderType.temp)]))


# ------------------------------------------------------------------ schema


def _common_inputs():
    return [
        io.String.Input("prompt", multiline=True, default="",
                        tooltip="Raw H3 prompt. Reference media are cited as <Picture N>/<Audio N>."),
        io.Int.Input("width", default=864, min=32, max=1344, step=32,
                     tooltip="Output width. Multiple of 32, width*height <= 768*1344."),
        io.Int.Input("height", default=480, min=32, max=1344, step=32,
                     tooltip="Output height. Multiple of 32."),
        io.Float.Input("seconds", default=2.0, min=0.25, max=15.0, step=0.25,
                       tooltip="Duration at 24 fps; h3 aligns frames up to 5+17n chunks."),
        io.Int.Input("steps", default=20, min=2, max=1000, tooltip="Denoising passes."),
        io.Combo.Input("preset", options=list(PRESETS.keys()), default="balanced",
                       tooltip="Speed/quality: precise=50 layers/reuse 1, balanced=45/2, fast=40/3."),
        io.Int.Input("seed", default=42, min=0, max=0xFFFFFFFFFFFFFFFF,
                     control_after_generate=True),
        io.Boolean.Input("token_reduction", default=False, advanced=True,
                         tooltip="Pair video tokens in middle DiT blocks (aggressive speedup)."),
        io.Boolean.Input("ssd_streaming", default=False, advanced=True,
                         tooltip="Stream BF16 DiT weights from SSD (VRAM for speed)."),
        io.String.Input("binary_path", default="", advanced=True,
                        tooltip="Override h3 binary path. Empty = config.json."),
        io.String.Input("model_dir", default="", advanced=True,
                        tooltip="Override MiniMax-H3 model directory. Empty = config.json."),
    ]


def _cfg_display():
    cfg = load_config()
    binary = cfg.get("h3_binary") or "(not configured)"
    mdir = cfg.get("model_dir") or "(not configured)"
    return f"binary: {binary}\nmodel: {mdir}"


class H3TextToVideo(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="WildH3TextToVideo",
            display_name="Wild H3 Text to Video",
            category="Wild H3",
            description=(
                "Text-to-video with MiniMax H3 via the local h3.c C/Metal binary.\n"
                + _cfg_display()
            ),
            inputs=_common_inputs() + [
                io.Image.Input("first_frame", optional=True,
                               tooltip="FL2VA first-frame conditioning. Mutually exclusive with reference inputs."),
                io.Image.Input("last_frame", optional=True,
                               tooltip="FL2VA last-frame conditioning."),
            ],
            outputs=[io.Video.Output(display_name="video")],
        )

    @classmethod
    def execute(cls, prompt, width, height, seconds, steps, preset, seed,
                token_reduction, ssd_streaming, binary_path, model_dir,
                first_frame=None, last_frame=None) -> io.NodeOutput:
        return _run(binary_path, model_dir, prompt, width, height, seconds, steps,
                    preset, seed, token_reduction, ssd_streaming,
                    first_frame=first_frame, last_frame=last_frame)


class H3RefToVideo(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="WildH3RefToVideo",
            display_name="Wild H3 Reference to Video (Ref2VA)",
            category="Wild H3",
            description=(
                "MiniMax H3 Ref2VA generation via the local h3.c binary. "
                "Reference images are cited in the prompt as <Picture 1>, <Picture 2>, ...; "
                "audio as <Audio 1>. References cannot be combined with first/last-frame anchors "
                "(use Wild H3 Text to Video for that).\n"
                + _cfg_display()
            ),
            inputs=_common_inputs() + [
                io.Image.Input("ref_images", optional=True,
                               tooltip="Up to 9 ordered reference images (batch). Cited as <Picture N>."),
                io.Audio.Input("ref_audio", optional=True,
                               tooltip="One 2..15s audio reference. Requires at least one reference image."),
                io.Combo.Input("ref_image_size", options=["match", "max"], default="match", advanced=True,
                               tooltip="Reference image sizing."),
            ],
            outputs=[io.Video.Output(display_name="video")],
        )

    @classmethod
    def execute(cls, prompt, width, height, seconds, steps, preset, seed,
                token_reduction, ssd_streaming, binary_path, model_dir,
                ref_images=None, ref_audio=None, ref_image_size="match") -> io.NodeOutput:
        return _run(binary_path, model_dir, prompt, width, height, seconds, steps,
                    preset, seed, token_reduction, ssd_streaming,
                    ref_images=ref_images, ref_audio=ref_audio, ref_image_size=ref_image_size)


class H3Extension(ComfyExtension):
    async def get_node_list(self):
        return [H3TextToVideo, H3RefToVideo]


async def comfy_entrypoint() -> H3Extension:
    return H3Extension()
