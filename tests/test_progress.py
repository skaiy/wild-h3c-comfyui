"""run_h3 progress parsing and failure handling, with a fake subprocess.

h3 prints progress to stderr as `\\r<phase>  <done>/<total>`; run_h3 reads it
one byte at a time and feeds comfy.utils.ProgressBar.update_absolute.
"""

import subprocess

import pytest
from fakes import FakeProc


class RecordingPbar:
    def __init__(self):
        self.calls = []

    def update_absolute(self, done, total):
        self.calls.append((done, total))


def patch_popen(monkeypatch, proc):
    """Route subprocess.Popen to a factory returning the fake proc."""
    captured = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return proc

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    return captured


PROGRESS_STREAM = (
    b"\rtokenizer 0/1"
    b"\rtokenizer 1/1"
    b"\ntext encoder 12/50"
    b"\rtext encoder 50/50"
    b"\rdenoise 1/4"
    b"\rdenoise 2/4"
    b"\rdenoise 3/4"
    b"\rdenoise 4/4"
    b"\rh3: wrote /tmp/out.mp4\n"
)


def test_progress_stream_feeds_progress_bar(runner, fake_comfy, monkeypatch):
    proc = FakeProc(stderr=PROGRESS_STREAM, rc=0)
    patch_popen(monkeypatch, proc)
    pbar = RecordingPbar()

    out = runner.run_h3(["/fake/h3", "-d", "/m"], "/tmp/out.mp4", pbar=pbar)

    assert out == "/tmp/out.mp4"
    assert pbar.calls == [
        (0, 1), (1, 1),          # tokenizer
        (12, 50), (50, 50),      # text encoder
        (1, 4), (2, 4), (3, 4), (4, 4),  # denoise
    ]


def test_progress_goes_to_log_without_pbar(runner, fake_comfy, monkeypatch):
    proc = FakeProc(stderr=PROGRESS_STREAM, rc=0)
    patch_popen(monkeypatch, proc)
    lines = []

    runner.run_h3(["/fake/h3"], "/tmp/out.mp4", pbar=None, log=lines.append)

    assert "[H3] denoise 4/4" in lines
    assert "[H3] tokenizer 0/1" in lines


def test_runs_from_binary_directory(runner, fake_comfy, monkeypatch):
    # h3 locates h3_shaders.metal relative to cwd.
    proc = FakeProc(stderr=b"h3: wrote /tmp/out.mp4\n", rc=0)
    captured = patch_popen(monkeypatch, proc)

    runner.run_h3(["/opt/h3.c/h3", "-d", "/m"], "/tmp/out.mp4")

    assert captured["kwargs"]["cwd"] == "/opt/h3.c"


def test_nonzero_exit_raises_with_stderr_tail(runner, fake_comfy, monkeypatch):
    proc = FakeProc(stderr=b"loading...\n\rboom: tensor mismatch\n", rc=1)
    patch_popen(monkeypatch, proc)

    with pytest.raises(RuntimeError) as exc_info:
        runner.run_h3(["/fake/h3"], "/tmp/out.mp4")

    msg = str(exc_info.value)
    assert "exited with code 1" in msg
    assert "runtime error" in msg
    assert "boom: tensor mismatch" in msg


def test_exit_code_2_is_argument_error(runner, fake_comfy, monkeypatch):
    proc = FakeProc(stderr=b"unknown flag\n", rc=2)
    patch_popen(monkeypatch, proc)

    with pytest.raises(RuntimeError, match="argument error"):
        runner.run_h3(["/fake/h3"], "/tmp/out.mp4")


def test_zero_exit_without_output_file_raises(runner, fake_comfy, monkeypatch, tmp_path):
    proc = FakeProc(stderr=b"\rdenoise 4/4\r", rc=0)  # no "h3: wrote" line
    patch_popen(monkeypatch, proc)
    missing = str(tmp_path / "never-created.mp4")

    with pytest.raises(RuntimeError, match="exited 0"):
        runner.run_h3(["/fake/h3"], missing)


def test_zero_exit_with_existing_file_passes(runner, fake_comfy, monkeypatch, tmp_path):
    # Defensive path: h3 forgot to print "h3: wrote" but the file is there.
    out = tmp_path / "out.mp4"
    out.write_bytes(b"\x00")
    proc = FakeProc(stderr=b"\rdenoise 4/4\r", rc=0)
    patch_popen(monkeypatch, proc)

    assert runner.run_h3(["/fake/h3"], str(out)) == str(out)


def test_all_progress_phases_are_recognized(runner, fake_comfy, monkeypatch):
    stream = b"".join(
        f"\r{phase} 1/2".encode()
        for phase in (
            "load", "tokenizer", "text encoder", "Qwen", "H3 DiT",
            "video VAE load", "video VAE", "audio VAE", "denoise",
            "denoise enqueue", "FFmpeg",
        )
    ) + b"\rh3: wrote /tmp/out.mp4\n"
    proc = FakeProc(stderr=stream, rc=0)
    patch_popen(monkeypatch, proc)
    pbar = RecordingPbar()

    runner.run_h3(["/fake/h3"], "/tmp/out.mp4", pbar=pbar)

    assert len(pbar.calls) == 11
    assert all(call == (1, 2) for call in pbar.calls)
