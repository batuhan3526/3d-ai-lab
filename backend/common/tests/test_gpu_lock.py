"""GPU lock tests (in-memory stub)."""
import threading
import time

import pytest


def test_acquire_and_release():
    """Lock acquired in 'with' block, released after exit."""
    from common.gpu_lock import gpu_lock

    with gpu_lock(0):
        pass  # critical section
    # If we reach here without timeout, lock was released


def test_blocks_when_held():
    """A second acquire on the same GPU blocks until first releases."""
    from common.gpu_lock import gpu_lock

    order = []

    def worker_a():
        with gpu_lock(0, timeout=5):
            order.append("a-in")
            time.sleep(0.2)
            order.append("a-out")

    def worker_b():
        time.sleep(0.05)  # ensure a starts first
        with gpu_lock(0, timeout=5):
            order.append("b-in")

    ta = threading.Thread(target=worker_a)
    tb = threading.Thread(target=worker_b)
    ta.start()
    tb.start()
    ta.join()
    tb.join()

    assert order == ["a-in", "a-out", "b-in"]


def test_different_gpus_independent():
    """Different GPU IDs use independent locks."""
    from common.gpu_lock import gpu_lock

    with gpu_lock(0, timeout=1):
        with gpu_lock(1, timeout=1):
            pass  # both held simultaneously


def test_timeout_raises():
    """Acquire times out and raises if lock held too long."""
    from common.gpu_lock import GpuLockTimeout, gpu_lock

    holder = threading.Event()
    release = threading.Event()

    def hold_forever():
        with gpu_lock(0, timeout=5):
            holder.set()
            release.wait()

    t = threading.Thread(target=hold_forever)
    t.start()
    holder.wait()  # wait until lock is acquired

    with pytest.raises(GpuLockTimeout):
        with gpu_lock(0, timeout=0.1):
            pass

    release.set()
    t.join()
