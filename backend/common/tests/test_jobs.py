import json

import fakeredis


def _store():
    from common.jobs import JobStore
    return JobStore(fakeredis.FakeStrictRedis(decode_responses=True))


def test_create_and_get():
    s = _store()
    s.create("j1", {"kind": "text", "project_id": "p1"})
    job = s.get("j1")
    assert job["state"] == "SUBMITTED"
    assert job["project_id"] == "p1"


def test_set_state_and_progress():
    s = _store()
    s.create("j1", {})
    s.set_state("j1", "STARTED")
    s.set_progress("j1", stage="shape", percent=40)
    job = s.get("j1")
    assert job["state"] == "PROGRESS"
    assert job["stage"] == "shape"
    assert job["percent"] == "40"


def test_progress_is_published():
    s = _store()
    s.create("j1", {})
    pub = s.redis.pubsub()
    pub.subscribe("job:j1")
    pub.get_message(timeout=1)
    s.set_progress("j1", stage="paint", percent=70)
    msg = pub.get_message(timeout=1)
    payload = json.loads(msg["data"])
    assert payload["stage"] == "paint"
    assert payload["percent"] == 70


def test_succeed_and_fail():
    s = _store()
    s.create("j1", {})
    s.succeed("j1", {"project_id": "p1"})
    assert s.get("j1")["state"] == "SUCCESS"
    s.create("j2", {})
    s.fail("j2", "boom")
    j2 = s.get("j2")
    assert j2["state"] == "FAILURE"
    assert j2["error"] == "boom"
