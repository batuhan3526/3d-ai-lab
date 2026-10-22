"""Her bulut motoru, docs/CLOUD_API_REFERENCE.md'deki sözleşmeyi taklit eden sahte bir
HTTP sunucusuna karşı uçtan uca koşar (ağ YOK): doğru adres, kimlik başlığı, zorunlu
alanlar, iş sorgulama ve sonuç indirme. Gerçek anahtarla canlı doğrulama YAPILMADI."""
from __future__ import annotations

import base64
import io
import json
import pathlib
import sys

import httpx
import pytest
from PIL import Image

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cloud_worker import http  # noqa: E402
from cloud_worker.providers import catalog  # noqa: E402

KEY = "sk-live-TEST"
GLB = b"glTF" + b"\x02\x00\x00\x00" + b"\x00" * 64
_buf = io.BytesIO()
Image.new("RGB", (8, 8), "white").save(_buf, "PNG")
PNG = _buf.getvalue()
B64 = base64.b64encode(PNG).decode()


class Fake:
    """Kural listesi: (method, url önek) → handler(req) -> Response. İstekleri kaydeder."""

    def __init__(self):
        self.rules: list[tuple[str, str, object]] = []
        self.calls: list[httpx.Request] = []
        self.state: dict = {}

    def on(self, method: str, prefix: str, fn):
        self.rules.append((method, prefix, fn))
        return self

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        for m, pre, fn in self.rules:
            if req.method == m and str(req.url).startswith(pre):
                return fn(req)
        return httpx.Response(404, json={"error": f"eşleşme yok {req.method} {req.url}"})


@pytest.fixture
def fake(monkeypatch):
    f = Fake()
    http.set_transport(httpx.MockTransport(f))
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    yield f
    http.set_transport(None)


def _j(req) -> dict:
    return json.loads(req.content or b"{}")


def _img(tmp_path) -> pathlib.Path:
    p = tmp_path / "in.png"
    p.write_bytes(PNG)
    return p


P3 = {"detail": "medium", "texture": True, "seed": 0}
PI = {"detail": "medium"}


# --- 3D ---------------------------------------------------------------------------
def _tripo(f: Fake, kind: str):
    def create(req):
        assert req.headers["authorization"] == f"Bearer {KEY}"
        b = _j(req)
        assert b["model"] and b["texture"] is True
        assert ("prompt" in b) if kind == "text" else (b["input"] == "file_tok")
        return httpx.Response(200, json={"code": 0, "data": {"task_id": "t1"}})
    seq = iter(["queued", "running", "success"])

    def task(req):
        st = next(seq)
        out = {"model_url": "https://cdn.tripo/m.glb"} if st == "success" else {}
        return httpx.Response(200, json={"code": 0, "data": {"status": st, "progress": 50, "output": out}})
    f.on("POST", "https://openapi.tripo3d.com/v3/files",
         lambda r: httpx.Response(200, json={"code": 0, "data": {"file_token": "file_tok"}}))
    f.on("POST", "https://openapi.tripo3d.com/v3/generation/", create)
    f.on("GET", "https://openapi.tripo3d.com/v3/tasks/t1", task)
    f.on("GET", "https://cdn.tripo/m.glb", lambda r: httpx.Response(200, content=GLB))


def _meshy(f: Fake, kind: str):
    created = []

    def create(req):
        assert req.headers["authorization"] == f"Bearer {KEY}"
        b = _j(req)
        assert b.get("target_formats") == ["glb"] or b.get("mode") == "refine"
        if kind == "image":
            assert b["image_url"].startswith("data:image/png;base64,")
        created.append(b.get("mode", "image"))
        return httpx.Response(200, json={"result": f"m{len(created)}"})

    def get(req):
        return httpx.Response(200, json={"status": "SUCCEEDED", "progress": 100,
                                         "model_urls": {"glb": "https://assets.meshy/m.glb"}})
    f.on("POST", "https://api.meshy.ai/openapi/", create)
    f.on("GET", "https://api.meshy.ai/openapi/", get)
    f.on("GET", "https://assets.meshy/m.glb", lambda r: httpx.Response(200, content=GLB))
    f.state["meshy"] = created


def _rodin(f: Fake, kind: str):
    def submit(req):
        assert req.headers["authorization"] == f"Bearer {KEY}"
        assert req.headers["content-type"].startswith("multipart/form-data")
        body = req.content.decode("latin-1")
        assert 'name="tier"' in body and "Gen-2.5-" in body
        assert ('name="images"' in body) if kind == "image" else ('name="prompt"' in body)
        return httpx.Response(201, json={"uuid": "U", "jobs": {"uuids": ["a"], "subscription_key": "SK"}, "error": None})
    seq = iter(["Waiting", "Generating", "Done"])
    f.on("POST", "https://api.hyper3d.com/api/v2/rodin", submit)
    f.on("POST", "https://api.hyper3d.com/api/v2/status",
         lambda r: (_j(r)["subscription_key"] == "SK") and httpx.Response(200, json={"jobs": [{"uuid": "a", "status": next(seq)}]}))
    f.on("POST", "https://api.hyper3d.com/api/v2/download",
         lambda r: httpx.Response(200, json={"list": [{"name": "preview.webp", "url": "https://x/p"},
                                                      {"name": "base.glb", "url": "https://dl.rodin/b.glb"}]}))
    f.on("GET", "https://dl.rodin/b.glb", lambda r: httpx.Response(200, content=GLB))


def _fal(f: Fake, model: str, result: dict, check=None):
    def submit(req):
        assert req.headers["authorization"] == f"Key {KEY}"
        if check:
            check(_j(req))
        return httpx.Response(200, json={"request_id": "R", "status_url": "https://queue.fal.run/x/requests/R/status",
                                         "response_url": "https://queue.fal.run/x/requests/R"})
    seq = iter(["IN_QUEUE", "IN_PROGRESS", "COMPLETED"])
    f.on("POST", "https://rest.fal.ai/storage/upload/initiate",
         lambda r: httpx.Response(200, json={"upload_url": "https://gcs/up", "file_url": "https://v3b.fal.media/in.png"}))
    f.on("PUT", "https://gcs/up", lambda r: ("authorization" not in r.headers) and httpx.Response(200))
    f.on("POST", f"https://queue.fal.run/{model}", submit)
    f.on("GET", "https://queue.fal.run/x/requests/R/status", lambda r: httpx.Response(200, json={"status": next(seq)}))
    f.on("GET", "https://queue.fal.run/x/requests/R", lambda r: httpx.Response(200, json=result))
    f.on("GET", "https://v3b.fal.media/out", lambda r: httpx.Response(200, content=GLB if "glb" in str(r.url) else PNG))


def _stability3d(f: Fake):
    def sf3d(req):
        assert req.headers["authorization"] == f"Bearer {KEY}"
        assert 'name="image"' in req.content.decode("latin-1")
        return httpx.Response(200, content=GLB, headers={"content-type": "model/gltf-binary"})
    f.on("POST", "https://api.stability.ai/v2beta/3d/stable-fast-3d", sf3d)


def _replicate3d(f: Fake):
    def create(req):
        b = _j(req)
        assert req.headers["authorization"] == f"Bearer {KEY}" and req.headers["prefer"].startswith("wait")
        assert b["version"].startswith("firtoz/trellis:") and b["input"]["generate_model"] is True
        assert b["input"]["images"][0].startswith("data:image/jpeg;base64,")
        return httpx.Response(201, json={"id": "P", "status": "processing", "urls": {"get": "https://api.replicate.com/v1/predictions/P"}})
    f.on("POST", "https://api.replicate.com/v1/predictions", create)
    f.on("GET", "https://api.replicate.com/v1/predictions/P",
         lambda r: httpx.Response(200, json={"status": "succeeded", "output": {"model_file": "https://replicate.delivery/m.glb"}}))
    f.on("GET", "https://replicate.delivery/m.glb",
         lambda r: ("authorization" in r.headers) and httpx.Response(200, content=GLB))


CASES_3D = {
    "cloud-tripo-text": lambda f: _tripo(f, "text"),
    "cloud-tripo-image": lambda f: _tripo(f, "image"),
    "cloud-meshy-text": lambda f: _meshy(f, "text"),
    "cloud-meshy-image": lambda f: _meshy(f, "image"),
    "cloud-rodin-text": lambda f: _rodin(f, "text"),
    "cloud-rodin-image": lambda f: _rodin(f, "image"),
    "cloud-falhunyuan-text": lambda f: _fal(f, "fal-ai/hunyuan-3d/v3.1/rapid/text-to-3d",
                                            {"model_urls": {"glb": {"url": "https://v3b.fal.media/out.glb"}},
                                             "model_obj": {"url": "https://v3b.fal.media/out.obj"}},
                                            lambda b: len(b["prompt"]) <= 200),
    "cloud-falhunyuan-image": lambda f: _fal(f, "fal-ai/hunyuan-3d/v3.1/pro/image-to-3d",
                                             {"model_glb": {"url": "https://v3b.fal.media/out.glb", "content_type": "model/gltf-binary"}},
                                             lambda b: b["input_image_url"].startswith("https://v3b.fal.media/")),
    "cloud-faltrellis-image": lambda f: _fal(f, "fal-ai/trellis-2", {"model_glb": {"url": "https://v3b.fal.media/out.glb"}},
                                             lambda b: b["image_url"] and b["resolution"] == 1024),
    "cloud-stability-image": _stability3d,
    "cloud-replicate-image": _replicate3d,
}


@pytest.mark.parametrize("engine_id", sorted(CASES_3D))
def test_3d_engine_against_fake_api(engine_id, fake, tmp_path):
    CASES_3D[engine_id](fake)
    ticks = []
    if engine_id.endswith("-text"):
        data, fmt = catalog.text_to_3d(engine_id, "red hoodie", P3, KEY, ticks.append)
    else:
        data, fmt = catalog.image_to_3d(engine_id, _img(tmp_path), P3, KEY, ticks.append)
    assert data[:4] == b"glTF" and fmt == "glb"
    if engine_id == "cloud-meshy-text":
        assert fake.state["meshy"] == ["preview", "refine"]


# --- Görsel ------------------------------------------------------------------------
def _openai(f):
    def gen(req):
        b = _j(req)
        assert req.headers["authorization"] == f"Bearer {KEY}"
        assert b["model"].startswith("gpt-image") and b["background"] == "transparent" and b["output_format"] == "png"
        return httpx.Response(200, json={"data": [{"b64_json": B64}]})
    f.on("POST", "https://api.openai.com/v1/images/generations", gen)


def _google(model):
    def setup(f):
        def gen(req):
            assert req.headers["x-goog-api-key"] == KEY
            b = _j(req)
            assert "IMAGE" in b["generationConfig"]["responseModalities"]
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [
                {"text": "işte"}, {"inlineData": {"mimeType": "image/png", "data": B64}}]}}]})
        f.on("POST", f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", gen)
    return setup


def _bfl(f):
    seq = iter(["Pending", "Generating", "Ready"])

    def sub(req):
        assert req.headers["x-key"] == KEY and _j(req)["output_format"] == "png"
        return httpx.Response(200, json={"id": "B", "polling_url": "https://api.bfl.ai/v1/get_result?id=B"})

    def res(req):
        st = next(seq)
        return httpx.Response(200, json={"status": st, "result": {"sample": "https://delivery.bfl.ai/s.png"} if st == "Ready" else None})
    f.on("POST", "https://api.bfl.ai/v1/flux-2-pro", sub)
    f.on("GET", "https://api.bfl.ai/v1/get_result", res)
    f.on("GET", "https://delivery.bfl.ai/s.png", lambda r: httpx.Response(200, content=PNG))


def _ideogram(f):
    def gen(req):
        assert req.headers["api-key"] == KEY and _j(req)["rendering_speed"] == "default"
        return httpx.Response(200, json={"data": [{"url": "https://ideogram.ai/api/images/x.png", "is_image_safe": True}]})
    f.on("POST", "https://api.ideogram.ai/v2/image/generate/ideogram-3-transparent", gen)
    f.on("GET", "https://ideogram.ai/api/images/x.png", lambda r: httpx.Response(200, content=PNG))


def _recraft(f):
    def gen(req):
        b = _j(req)
        assert req.headers["authorization"] == f"Bearer {KEY}" and b["image_format"] == "png"
        assert not b["model"].endswith("_vector")
        return httpx.Response(200, json={"data": [{"b64_json": B64}]})
    f.on("POST", "https://external.api.recraft.ai/v1/images/generations", gen)


def _stability_img(f):
    def gen(req):
        assert req.headers["authorization"] == f"Bearer {KEY}" and req.headers["accept"] == "image/*"
        assert 'name="prompt"' in req.content.decode("latin-1")
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
    f.on("POST", "https://api.stability.ai/v2beta/stable-image/generate/core", gen)


def _replicate_flux(f):
    def create(req):
        assert _j(req)["input"]["output_format"] == "png"
        return httpx.Response(201, json={"id": "F", "status": "succeeded", "output": "https://replicate.delivery/o.png"})
    f.on("POST", "https://api.replicate.com/v1/models/black-forest-labs/flux-1.1-pro/predictions", create)
    f.on("GET", "https://replicate.delivery/o.png", lambda r: httpx.Response(200, content=PNG))


CASES_IMG = {
    "cloud-openai-image": _openai,
    "cloud-google-nanobanana": _google("gemini-3.1-flash-image"),
    "cloud-google-nanobananapro": _google("gemini-3-pro-image"),
    "cloud-bfl-flux": _bfl,
    "cloud-ideogram-image": _ideogram,
    "cloud-recraft-image": _recraft,
    "cloud-stability-sdimage": _stability_img,
    "cloud-falflux-image": lambda f: _fal(f, "fal-ai/flux-2-pro", {"images": [{"url": "https://v3b.fal.media/out.png"}]},
                                          lambda b: b["output_format"] == "png"),
    "cloud-replicate-flux": _replicate_flux,
}


@pytest.mark.parametrize("engine_id", sorted(CASES_IMG))
def test_image_engine_against_fake_api(engine_id, fake):
    CASES_IMG[engine_id](fake)
    data = catalog.text_to_image(engine_id, "tribal dragon", PI, KEY, seed=7)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_cases_cover_every_cloud_engine():
    assert set(CASES_3D) | set(CASES_IMG) == catalog.engine_ids()


def test_provider_failure_is_reported(fake, tmp_path):
    fake.on("POST", "https://api.meshy.ai/openapi/", lambda r: httpx.Response(200, json={"result": "m"}))
    fake.on("GET", "https://api.meshy.ai/openapi/",
            lambda r: httpx.Response(200, json={"status": "FAILED", "task_error": {"message": "görsel uygunsuz"}}))
    with pytest.raises(http.CloudError, match="görsel uygunsuz"):
        catalog.image_to_3d("cloud-meshy-image", _img(tmp_path), P3, KEY)


def test_auth_error_hides_key(fake):
    http.register_secret(KEY)
    fake.on("POST", "https://api.openai.com/v1/images/generations",
            lambda r: httpx.Response(401, json={"error": {"message": f"Incorrect API key {KEY}"}}))
    with pytest.raises(http.CloudError) as e:
        catalog.text_to_image("cloud-openai-image", "x", PI, KEY)
    assert KEY not in str(e.value) and "geçersiz" in str(e.value)
