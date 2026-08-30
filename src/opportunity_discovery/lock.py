"""Run lock preventing overlapping mutations (Windows- and POSIX-safe)."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_WINDOWS_STILL_ACTIVE = 0x103
_WINDOWS_ERROR_INVALID_PARAMETER = 87


def _load_kernel32() -> Any:
    """Load kernel32 with safe, event-free probe entry points configured.

    Isolated so tests can substitute a fake implementation on POSIX platforms.
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


class RunLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd: int | None = None

    @staticmethod
    def _is_stale(content: str) -> bool:
        # A malformed or non-positive pid can never name a live owner, so such
        # locks are stale. Uncertainty about liveness is treated as NOT stale:
        # uncertainty must never let a fresh lock be stolen. Age-based takeover
        # in acquire() remains the fallback for genuinely abandoned locks.
        try:
            pid = int(content.strip())
        except ValueError:
            return True
        if pid <= 0:
            return True
        return not RunLock._pid_is_alive(pid)

    @staticmethod
    def _pid_is_alive(pid: int) -> bool:
        if os.name == "nt":
            return RunLock._windows_pid_is_alive(pid)
        return RunLock._posix_pid_is_alive(pid)

    @staticmethod
    def _posix_pid_is_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return True
        return True

    @staticmethod
    def _windows_pid_is_alive(pid: int) -> bool:
        """Probe Windows liveness without os.kill, which sends console control events."""
        import ctypes
        from ctypes import wintypes

        kernel32 = _load_kernel32()
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            last_error = ctypes.get_last_error()  # type: ignore[attr-defined]
            return RunLock._windows_probe_alive(False, last_error, None)
        try:
            exit_code = wintypes.DWORD(0)
            queried = bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)))
            return RunLock._windows_probe_alive(True, 0, exit_code.value if queried else None)
        finally:
            kernel32.CloseHandle(handle)

    @staticmethod
    def _windows_probe_alive(opened: bool, last_error: int, exit_code: int | None) -> bool:
        """Map a Windows probe outcome to liveness; unknown outcomes assume alive."""
        if not opened:
            return last_error != _WINDOWS_ERROR_INVALID_PARAMETER
        if exit_code is None:
            return True
        return exit_code == _WINDOWS_STILL_ACTIVE

    def acquire(self, *, steal_stale_after_seconds: float = 6 * 3600) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            import time

            age = time.time() - self.path.stat().st_mtime
            try:
                content = self.path.read_text(encoding="utf-8")
            except OSError:
                return False
            if age > steal_stale_after_seconds or self._is_stale(content):
                with contextlib.suppress(OSError):
                    self.path.unlink()
                return self.acquire(steal_stale_after_seconds=steal_stale_after_seconds)
            return False
        else:
            self._fd = fd
            os.write(fd, str(os.getpid()).encode("ascii"))
            return True

    def release(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None
            with contextlib.suppress(OSError):
                self.path.unlink()

    def __enter__(self) -> RunLock:
        if not self.acquire():
            raise BlockingIOError(f"another run appears active: {self.path}")
        return self

    def __exit__(self, *exc_info) -> None:  # type: ignore[no-untyped-def]
        self.release()
