"""Run lock preventing overlapping mutations (Windows- and POSIX-safe)."""
from __future__ import annotations

import contextlib
import os
from pathlib import Path


class RunLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd: int | None = None

    @staticmethod
    def _is_stale(content: str) -> bool:
        # If the pid recorded is not alive we may take over. On Windows os.kill
        # raises for missing pids; treat any probe failure as stale-safe only
        # when the lockfile is older than 6 hours.
        try:
            pid = int(content.strip() or "-1")
        except ValueError:
            return True
        try:
            os.kill(pid, 0)
            return False
        except ProcessLookupError:
            return True
        except PermissionError:
            return False  # exists but owned by someone else -> not stale
        except OSError:
            return False

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
