import fakeredis
import pytest


def test_acquires_and_releases():
    from common.gpu_lock import gpu_lock
    r = fakeredis.FakeStrictRedis()
    with gpu_lock(0, client=r, blocking_timeout=1):
        assert r.get("gpu:0") is not None
    assert r.get("gpu:0") is None


def test_busy_raises():
    from common.gpu_lock import gpu_lock
    r = fakeredis.FakeStrictRedis()
    with gpu_lock(0, client=r, blocking_timeout=1):
        with pytest.raises(TimeoutError):
            with gpu_lock(0, client=r, blocking_timeout=1):
                pass
