import errno
import os
import time

import pytest

from opportunity_discovery import lock as lock_module
from opportunity_discovery.lock import RunLock

NONEXISTENT_PID = "999999999"
WINDOWS_ERROR_ACCESS_DENIED = 5
WINDOWS_ERROR_INVALID_PARAMETER = 87
WINDOWS_STILL_ACTIVE = 259


class FakeKernel32:
    def __init__(self, *, handle, exit_code=None, query_succeeds=True):
        self.handle = handle
        self.exit_code = exit_code
        self.query_succeeds = query_succeeds
        self.open_calls = []
        self.closed_handles = []

    def OpenProcess(self, access, inherit, pid):
        self.open_calls.append((access, inherit, pid))
        return self.handle

    def GetExitCodeProcess(self, handle, pointer):
        if self.exit_code is not None:
            pointer._obj.value = self.exit_code
        return self.query_succeeds

    def CloseHandle(self, handle):
        self.closed_handles.append(handle)
        return 1


def test_acquire_release(tmp_path):
    lock = RunLock(tmp_path / "run.lock")
    assert lock.acquire()
    assert not (RunLock(tmp_path / "run.lock").acquire())
    lock.release()
    assert RunLock(tmp_path / "run.lock").acquire()


def test_context_manager_blocks_second_holder(tmp_path):
    with RunLock(tmp_path / "l.lock"), pytest.raises(BlockingIOError), RunLock(tmp_path / "l.lock"):
        pass


def test_current_process_pid_is_active():
    assert RunLock._pid_is_alive(os.getpid()) is True


def test_nonexistent_pid_recognized_as_stale():
    assert RunLock._is_stale(NONEXISTENT_PID) is True


def test_malformed_and_nonpositive_pids_are_stale():
    for content in ("", "not-a-pid", "12.5", "0", "-7"):
        assert RunLock._is_stale(content) is True, content


def test_fresh_lock_of_live_process_cannot_be_stolen(tmp_path):
    path = tmp_path / "fresh.lock"
    path.write_text(str(os.getpid()), encoding="ascii")
    assert RunLock(path).acquire() is False
    assert path.exists(), "fresh live-owner lock must not be removed"


def test_stale_lock_taken_over(tmp_path):
    path = tmp_path / "stale.lock"
    path.write_text(NONEXISTENT_PID)  # pid that does not exist
    time.sleep(0.01)
    lock = RunLock(path)
    assert lock.acquire(), "dead-pid lock should be stealable"
    lock.release()


def test_posix_permission_error_means_not_stale(monkeypatch):
    def fake_kill(pid, sig):
        raise PermissionError(errno.EPERM, "probe denied")

    monkeypatch.setattr(lock_module.os, "kill", fake_kill)
    assert RunLock._is_stale("12345") is False


def test_posix_unknown_oserror_means_not_stale(monkeypatch):
    def fake_kill(pid, sig):
        raise OSError(errno.EIO, "probe failed")

    monkeypatch.setattr(lock_module.os, "kill", fake_kill)
    assert RunLock._is_stale("12345") is False


def test_windows_no_such_process_confirmed_dead():
    alive = RunLock._windows_probe_alive(False, WINDOWS_ERROR_INVALID_PARAMETER, None)
    assert alive is False


def test_windows_access_denied_assumed_alive():
    alive = RunLock._windows_probe_alive(False, WINDOWS_ERROR_ACCESS_DENIED, None)
    assert alive is True


def test_windows_unknown_error_assumed_alive():
    assert RunLock._windows_probe_alive(False, 4242, None) is True


def test_windows_exit_code_distinguishes_live_and_exited():
    assert RunLock._windows_probe_alive(True, 0, WINDOWS_STILL_ACTIVE) is True
    assert RunLock._windows_probe_alive(True, 0, 0) is False


def test_windows_query_failure_assumed_alive():
    assert RunLock._windows_probe_alive(True, 0, None) is True


def test_dispatch_uses_windows_helper_without_os_kill(monkeypatch):
    probed = []

    def fake_windows(pid):
        probed.append(pid)
        return False

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(RunLock, "_windows_pid_is_alive", staticmethod(fake_windows))
    kill_calls = []
    monkeypatch.setattr(lock_module.os, "kill", lambda pid, sig: kill_calls.append(pid))
    assert RunLock._is_stale("424242") is True
    assert probed == [424242]
    assert kill_calls == []


def test_dispatch_uses_posix_helper_on_posix(monkeypatch):
    probed = []

    def fake_posix(pid):
        probed.append(pid)
        return True

    monkeypatch.setattr(RunLock, "_posix_pid_is_alive", staticmethod(fake_posix))
    assert RunLock._is_stale("77") is False
    assert probed == [77]


def test_windows_helper_always_closes_handle(monkeypatch):
    fake = FakeKernel32(handle=1234, exit_code=WINDOWS_STILL_ACTIVE)
    monkeypatch.setattr(lock_module, "_load_kernel32", lambda: fake)
    assert RunLock._windows_pid_is_alive(555) is True
    assert fake.open_calls == [(0x1000, False, 555)]
    assert fake.closed_handles == [1234]


def test_windows_helper_closes_handle_when_query_fails(monkeypatch):
    fake = FakeKernel32(handle=99, query_succeeds=False)
    monkeypatch.setattr(lock_module, "_load_kernel32", lambda: fake)
    assert RunLock._windows_pid_is_alive(555) is True
    assert fake.closed_handles == [99]
