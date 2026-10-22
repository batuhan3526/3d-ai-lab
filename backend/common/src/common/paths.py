"""Mesh yolu depolama/çözümleme yardımcıları — taşınabilir DB için tek doğruluk.

Sorun: mutlak yol tutan bir DB (`/srv/studio/data/projects/<...>`), başka bir
makineye ya da farklı bir mount noktasına taşınınca kırılır.

Çözüm: yazma tarafı yolları PROJECTS_DIR'e GÖRELİ saklar (`default/<id>/mesh.glb`);
okuma tarafı `resolve_mesh_path` ile geçerli PROJECTS_DIR altına çözer. Eski MUTLAK
değerler (migre edilmemiş satırlar) geriye-uyum için aynen kullanılır.

Not: PROJECTS_DIR bir sürücü-harfli yol da olabilir (ör.
`D:/studio/data/projects`); bu, PurePosixPath açısından "mutlak" görünmez ama
prefix (relative_to) işlemleri saf-string olarak doğru çalışır. Bu yüzden mutlaklık
kararını `is_absolute()` değil, açık bir "sürücü harfi / kök `/`" testiyle veririz.
"""
from __future__ import annotations

import re
from pathlib import Path

from common.config import get_settings

# `C:/...`, `D:\...` gibi sürücü-kökü öneki.
_WIN_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")


def _looks_absolute(stored: str) -> bool:
    """Depolanan değer MUTLAK bir yol mu? (relative-to-PROJECTS_DIR değil)

    - POSIX kökü (`/srv/...`) → mutlak.
    - Sürücü harfi (`D:/...`, `D:\\...`) → mutlak.
    - Aksi halde (ör. `default/<id>/mesh.glb`) → PROJECTS_DIR'e göreli.
    """
    s = stored.replace("\\", "/")
    return s.startswith("/") or bool(_WIN_DRIVE.match(stored))


def resolve_mesh_path(stored: str) -> Path:
    """Depolanan bir mesh yolunu diskteki mutlak yola çöz.

    - Değer mutlaksa (eski satırlar) aynen döner (geriye-uyum).
    - Göreliyse geçerli PROJECTS_DIR altına eklenir.
    """
    s = str(stored)
    if _looks_absolute(s):
        return Path(s.replace("\\", "/"))
    return Path(get_settings().projects_dir) / s.replace("\\", "/")


def to_stored_mesh_path(p: str | Path) -> str:
    """Bir mesh yolunu DB'ye yazılacak biçime çevir.

    - PROJECTS_DIR altındaysa POSIX GÖRELİ str döner (`default/<id>/mesh.glb`).
    - Değilse mutlak POSIX str döner (taşınabilir yapamayız; aynen sakla).
    """
    projects_dir = Path(str(get_settings().projects_dir).replace("\\", "/"))
    path = Path(str(p).replace("\\", "/"))
    try:
        return path.relative_to(projects_dir).as_posix()
    except ValueError:
        return path.as_posix()
