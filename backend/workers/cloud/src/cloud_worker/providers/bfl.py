"""Black Forest Labs doğrudan FLUX API (docs.bfl.ai). `x-key` başlığı. Gönderim
`polling_url` döner — HER ZAMAN o sorgulanır. Sonuç result.sample (10 dk geçerli)."""
from __future__ import annotations

from cloud_worker.http import CloudError, client, download, json_of, poll

BASE = "https://api.bfl.ai/v1"
NAME = "Black Forest Labs"
_RUN = {"Pending", "Reasoning", "Generating"}


def text_to_image(prompt: str, params: dict, key: str, *, seed: int = 42, tick=None, variant: str = "") -> bytes:
    model = "flux-2-max" if params.get("detail") == "high" else "flux-2-pro"
    body = {"prompt": prompt, "width": 1024, "height": 1024, "seed": int(seed), "output_format": "png"}
    with client({"x-key": key}) as c:
        sub = json_of(c.post(f"{BASE}/{model}", json=body), NAME)
        purl = sub.get("polling_url")
        if not purl:
            raise CloudError(f"{NAME}: polling_url dönmedi")

        def failed(d: dict) -> str | None:
            st = d.get("status")
            return None if st in _RUN or st == "Ready" else f"durum={st}"

        res = poll(lambda: json_of(c.get(purl), NAME), lambda d: d.get("status") == "Ready", failed,
                   provider=NAME, interval=1.0, timeout=300,
                   on_tick=lambda d: tick and tick(50.0 if d.get("status") == "Generating" else 10.0))
    url = (res.get("result") or {}).get("sample")
    if not url:
        raise CloudError(f"{NAME}: result.sample yok")
    return download(url, NAME)
