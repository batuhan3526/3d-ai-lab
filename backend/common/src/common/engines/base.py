"""Motor arayüzü (protokol). Adapter'lar (ör. trellis_text) bunu uygular.

generate() worker ortamında (GPU) çağrılır; common bu protokolü import-zamanında
ağır bağımlılık (torch/trellis) çekmeden tanımlar.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from common.engines.params import GenParams


class Engine(Protocol):
    def load(self) -> None: ...
    def unload(self) -> None: ...
    def is_loaded(self) -> bool: ...
    def mem_report(self) -> dict: ...
    def generate(self, prompt_en: str, garment_type: str, params: GenParams,
                 out_path: Path) -> Path: ...
