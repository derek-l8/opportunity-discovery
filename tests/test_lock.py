
import pytest

from opportunity_discovery.lock import RunLock


def test_acquire_release(tmp_path):
    lock = RunLock(tmp_path / "run.lock")
    assert lock.acquire()
    assert not (RunLock(tmp_path / "run.lock").acquire())
    lock.release()
    assert RunLock(tmp_path / "run.lock").acquire()


def test_context_manager_blocks_second_holder(tmp_path):
    with RunLock(tmp_path / "l.lock"), pytest.raises(BlockingIOError), RunLock(tmp_path / "l.lock"):
        pass


def test_stale_lock_taken_over(tmp_path):
    path = tmp_path / "stale.lock"
    path.write_text("999999999")  # pid that does not exist
    import time

    time.sleep(0.01)
    lock = RunLock(path)
    assert lock.acquire(), "dead-pid lock should be stealable"
    lock.release()
