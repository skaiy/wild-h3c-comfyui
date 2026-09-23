"""Fake subprocess objects for testing run_h3 without spawning processes."""


class FakeStderr:
    """Byte-at-a-time readable stream, like an unbuffered stderr pipe."""

    def __init__(self, data: bytes):
        self._buf = bytearray(data)

    def read(self, n=-1):
        if not self._buf:
            return b""
        if n is None or n < 0:
            n = len(self._buf)
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out


class FakeProc:
    """Minimal stand-in for subprocess.Popen.

    poll() reports finished once terminate() or kill() was called, matching
    how a well-behaved child reacts to SIGTERM. wait() never blocks.
    """

    def __init__(self, stderr: bytes = b"", rc: int = 0):
        self.stderr = FakeStderr(stderr)
        self.rc = rc
        self.terminated = False
        self.killed = False
        self.wait_calls = []

    def poll(self):
        return self.rc if (self.terminated or self.killed) else None

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        return self.rc

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class StubbornProc(FakeProc):
    """Ignores SIGTERM: poll() stays None and wait(timeout) times out
    until kill() is called."""

    def poll(self):
        return self.rc if self.killed else None

    def wait(self, timeout=None):
        import subprocess

        self.wait_calls.append(timeout)
        if not self.killed:
            raise subprocess.TimeoutExpired(cmd="h3", timeout=timeout)
        return self.rc
