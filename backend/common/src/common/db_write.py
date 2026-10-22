"""Paylaşılan DB-yazma yardımcısı — worker'lar için tek doğruluk kaynağı.

9 worker daha önce kendi ham `sqlite3.connect` + `UPDATE projects` kopyasını
tutuyordu (WAL/busy_timeout YOK) → aynı SQLite dosyasına eşzamanlı yazımda
"database is locked" ve WAL-bozulma riski. Bu yardımcı WAL + busy_timeout ile
güvenli tek yol sağlar. İmza SABİT — worker'lar `set_mesh_path`'i buradan alır.
"""
from __future__ import annotations

import sqlite3

from common.paths import to_stored_mesh_path


def _sqlite_file(database_url: str) -> str:
    """`sqlite:///path` → `path`; diğer URL'ler olduğu gibi döner."""
    prefix = "sqlite:///"
    if database_url.startswith(prefix):
        return database_url[len(prefix):]
    return database_url


def set_mesh_path(database_url: str, project_id: str, mesh_path: str) -> None:
    """`projects.mesh_path`'i güvenli (WAL + busy_timeout) yaz.

    Yalnız SQLite hedeflenir (proje varsayılanı). busy_timeout, eşzamanlı yazan
    9 worker'ın 5 sn boyunca kilidi beklemesini sağlar; WAL okuyucuları
    yazıcıyı bloklamaz.
    """
    # İmza SABİT kalır; yolu içeride PROJECTS_DIR'e göreli biçime çeviririz
    # (taşınabilir DB). PROJECTS_DIR dışıysa mutlak POSIX olarak saklanır.
    stored = to_stored_mesh_path(mesh_path)
    db = _sqlite_file(database_url)
    conn = sqlite3.connect(db, timeout=5.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            "UPDATE projects SET mesh_path=? WHERE id=?", (stored, project_id)
        )
        conn.commit()
    finally:
        conn.close()


def set_thumbnail_path(database_url: str, project_id: str, thumbnail_path: str) -> None:
    """`projects.thumbnail_path`'i güvenli (WAL + busy_timeout) yaz (F2 sew3d önizlemesi).

    Gateway'in PUT /projects/{id}/thumbnail deseniyle aynı: mutlak yol str'i saklanır;
    GET /projects/{id}/thumbnail dosyayı sözleşme konumundan (`<id>/thumbnail.png`) okur.
    """
    db = _sqlite_file(database_url)
    conn = sqlite3.connect(db, timeout=5.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            "UPDATE projects SET thumbnail_path=? WHERE id=?", (str(thumbnail_path), project_id)
        )
        conn.commit()
    finally:
        conn.close()


def merge_customizations(database_url: str, project_id: str, patch: dict) -> None:
    """`projects.customizations` JSON'una üst-düzey anahtarları birleştir (WAL + busy_timeout).

    Worker'ların yalnız kendi anahtarlarını (ör. "mannequin", "measurements") yazması
    için; diğer alanlar (renk, decal'lar…) korunur. Oku-birleştir-yaz tek işlemde."""
    import json

    db = _sqlite_file(database_url)
    conn = sqlite3.connect(db, timeout=5.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT customizations FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            conn.rollback()
            return
        cur = row[0]
        data = json.loads(cur) if isinstance(cur, str) and cur else (cur or {})
        data.update(patch)
        conn.execute("UPDATE projects SET customizations=? WHERE id=?",
                     (json.dumps(data, ensure_ascii=False), project_id))
        conn.commit()
    finally:
        conn.close()
