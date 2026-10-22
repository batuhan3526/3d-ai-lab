"""engine_id → sağlayıcı fonksiyonu.

Sağlayıcı modülleri şu imzaları sağlar (gerekeni):
- text_to_3d(prompt, params, key, tick, *, variant) -> (bytes, "glb"|"obj"|…)
- image_to_3d(image_path, params, key, tick, *, variant) -> (bytes, fmt)
- text_to_image(prompt, params, key, *, seed, tick, variant) -> bytes (PNG/JPEG/WebP)
`tick(pct)` 0-100 ilerleme bildirir (None olabilir). `variant` aynı sağlayıcıda model seçer.
"""
from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path

from cloud_worker.http import CloudError

# engine_id: (modül, variant)
_3D: dict[str, tuple[str, str]] = {
    "cloud-tripo-text": ("tripo", ""),
    "cloud-tripo-image": ("tripo", ""),
    "cloud-meshy-text": ("meshy", ""),
    "cloud-meshy-image": ("meshy", ""),
    "cloud-rodin-text": ("rodin", ""),
    "cloud-rodin-image": ("rodin", ""),
    "cloud-falhunyuan-text": ("fal", "hunyuan3d"),
    "cloud-falhunyuan-image": ("fal", "hunyuan3d"),
    "cloud-faltrellis-image": ("fal", "trellis"),
    "cloud-stability-image": ("stability", "sf3d"),
    "cloud-replicate-image": ("replicate", "trellis"),
}
_IMG: dict[str, tuple[str, str]] = {
    "cloud-openai-image": ("openai_img", ""),
    "cloud-google-nanobanana": ("google_img", "nanobanana"),
    "cloud-google-nanobananapro": ("google_img", "nanobananapro"),
    "cloud-bfl-flux": ("bfl", ""),
    "cloud-ideogram-image": ("ideogram", ""),
    "cloud-recraft-image": ("recraft", ""),
    "cloud-stability-sdimage": ("stability", "image"),
    "cloud-falflux-image": ("fal", "flux"),
    "cloud-replicate-flux": ("replicate", "flux"),
}


def _mod(name: str):
    return importlib.import_module(f"cloud_worker.providers.{name}")


def engine_ids() -> set[str]:
    return set(_3D) | set(_IMG)


def text_to_3d(engine_id: str, prompt: str, params: dict, key: str,
               tick: Callable[[float | None], None] | None = None) -> tuple[bytes, str]:
    if engine_id not in _3D:
        raise CloudError(f"Bilinmeyen bulut 3D motoru: {engine_id}")
    mod, variant = _3D[engine_id]
    return _mod(mod).text_to_3d(prompt, params, key, tick, variant=variant)


def image_to_3d(engine_id: str, image: Path, params: dict, key: str,
                tick: Callable[[float | None], None] | None = None) -> tuple[bytes, str]:
    if engine_id not in _3D:
        raise CloudError(f"Bilinmeyen bulut 3D motoru: {engine_id}")
    mod, variant = _3D[engine_id]
    return _mod(mod).image_to_3d(image, params, key, tick, variant=variant)


def text_to_image(engine_id: str, prompt: str, params: dict, key: str, *, seed: int = 42,
                  tick: Callable[[float | None], None] | None = None) -> bytes:
    if engine_id not in _IMG:
        raise CloudError(f"Bilinmeyen bulut görsel motoru: {engine_id}")
    mod, variant = _IMG[engine_id]
    return _mod(mod).text_to_image(prompt, params, key, seed=seed, tick=tick, variant=variant)
