import inspect


def test_generate_motif_task_accepts_seed():
    from flux_motif_worker.worker import generate_motif
    # Celery task; sarılı fonksiyonun imzası __wrapped__ veya run üzerinden
    fn = getattr(generate_motif, "run", generate_motif)
    params = inspect.signature(fn).parameters
    assert "seed" in params


def test_make_motif_forwards_seed_to_engine(monkeypatch):
    import flux_motif_worker.worker as w
    captured = {}

    class FakeEngine:
        def generate(self, text, out, *, seed=42, **kw):
            captured["text"] = text; captured["seed"] = seed; captured["out"] = out

        def motif_from_style(self, img, crop, out, *, ai=False, prompt="", seed=42, **kw):
            captured["seed"] = seed

    monkeypatch.setattr(w, "_get", lambda: FakeEngine())
    w._make_motif("/tmp/x.png", text="rose", style=None, seed=777)
    assert captured["seed"] == 777
