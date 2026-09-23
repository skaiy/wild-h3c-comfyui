"""Cancel semantics: ComfyUI interrupt terminates the h3 child process."""

import subprocess

import pytest
from fakes import FakeProc, StubbornProc


def test_interrupt_terminates_child(runner, fake_comfy, monkeypatch):
    fake_comfy.processing_interrupted = lambda: True  # user hit cancel
    proc = FakeProc(stderr=b"\rdenoise 1/4\r", rc=-15)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: proc)

    with pytest.raises(fake_comfy.InterruptProcessingException):
        runner.run_h3(["/fake/h3"], "/tmp/out.mp4")

    assert proc.terminated
    assert not proc.killed  # cooperative child: no SIGKILL needed


def test_kill_escalates_after_terminate_timeout(runner):
    proc = StubbornProc(rc=-9)

    runner._kill(proc)

    assert proc.terminated
    assert proc.killed
    assert proc.wait_calls == [5, 5]  # terminate wait, then kill wait


def test_kill_noop_when_process_already_dead(runner):
    proc = FakeProc(rc=0)
    proc.terminated = True  # poll() now reports finished

    runner._kill(proc)

    assert not proc.killed
    assert proc.wait_calls == []


def test_failed_run_also_kills_child(runner, fake_comfy, monkeypatch):
    # Any exception path (here: reader/stream works but we force an error by
    # interrupting mid-stream) must still reap the child.
    calls = {"n": 0}

    def interrupted():
        calls["n"] += 1
        return calls["n"] > 3  # let a few progress bytes through first

    fake_comfy.processing_interrupted = interrupted
    proc = FakeProc(stderr=b"\rdenoise 1/4\rdenoise 2/4\r", rc=-15)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: proc)

    with pytest.raises(fake_comfy.InterruptProcessingException):
        runner.run_h3(["/fake/h3"], "/tmp/out.mp4")

    assert proc.terminated
