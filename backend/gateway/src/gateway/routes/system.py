"""GET /system/stats — host CPU/RAM/disk + GPU (nvidia-smi). Metrik paneli için.

Ek bağımlılık YOK: /proc, os.statvfs ve nvidia-smi subprocess kullanır.
Frontend metrik paneli ~2 sn'de bir poll eder.
"""
from __future__ import annotations

import os
import re
import subprocess
import time

from common.engines.registry import default_gpu
from fastapi import APIRouter

from gateway.auth import require_token

router = APIRouter(prefix="/system", dependencies=[require_token()])

# Disk okuma/yazma HIZI için iki poll arası delta gerekir → son okuma modülde tutulur.
# Not: ağ/9p mount'ları /proc/diskstats'a yansımaz; bu sayaç yerel blok
# bloklarının (sd*/nvme*) toplamı = model yükleme/genel disk aktivitesini yakalar.
_DISK_RE = re.compile(r"^(sd[a-z]+|vd[a-z]+|nvme\d+n\d+|xvd[a-z]+)$")
_last_io: dict[str, float] = {"t": 0.0, "r": 0.0, "w": 0.0, "init": 0.0}


def _cpu() -> dict:
    """1-dakika yük ortalaması / çekirdek → kabaca % meşguliyet."""
    try:
        load1 = os.getloadavg()[0]
        cores = os.cpu_count() or 1
        return {"percent": round(min(load1 / cores * 100, 100), 1), "load1": round(load1, 2), "cores": cores}
    except OSError:
        return {"percent": 0.0, "load1": 0.0, "cores": os.cpu_count() or 1}


def _ram() -> dict:
    """/proc/meminfo (kB) → MemAvailable gerçekçi boş bellek."""
    info: dict[str, int] = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                key, _, rest = line.partition(":")
                info[key] = int(rest.strip().split()[0])  # kB
    except (OSError, ValueError):
        return {"used_gb": 0.0, "total_gb": 0.0, "percent": 0.0}
    total = info.get("MemTotal", 0)
    avail = info.get("MemAvailable", info.get("MemFree", 0))
    used = max(total - avail, 0)
    return {
        "used_gb": round(used / 1024 / 1024, 1),
        "total_gb": round(total / 1024 / 1024, 1),
        "percent": round(used / total * 100, 1) if total else 0.0,
    }


def _disk() -> dict:
    """Disk okuma/yazma HIZI (MB/s) — /proc/diskstats delta'sından.

    sektör = 512 bayt. İlk çağrıda hız 0 (referans yok). Frontend ~2sn'de bir poll
    eder; delta o aralıkta birikmiş bayttan hesaplanır.
    """
    r_sec = w_sec = 0
    try:
        with open("/proc/diskstats") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 10 or not _DISK_RE.match(parts[2]):
                    continue
                r_sec += int(parts[5])   # tamamlanan okuma sektörü
                w_sec += int(parts[9])   # tamamlanan yazma sektörü
    except (OSError, ValueError):
        return {"read_mbs": 0.0, "write_mbs": 0.0}

    now = time.monotonic()
    last = _last_io
    read_mbs = write_mbs = 0.0
    if last["init"] and now > last["t"]:
        dt = now - last["t"]
        read_mbs = max((r_sec - last["r"]) * 512 / 1e6 / dt, 0.0)
        write_mbs = max((w_sec - last["w"]) * 512 / 1e6 / dt, 0.0)
    last.update({"t": now, "r": r_sec, "w": w_sec, "init": 1.0})
    return {"read_mbs": round(read_mbs, 1), "write_mbs": round(write_mbs, 1)}


def _gpus() -> list[dict]:
    """nvidia-smi → her GPU için util %, VRAM kullanılan/toplam, sıcaklık."""
    try:
        out = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=index,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    gpus: list[dict] = []
    for line in out.stdout.strip().splitlines():
        try:
            idx, util, used, total, temp = (x.strip() for x in line.split(","))
            gpus.append({
                "index": int(idx),
                "util": float(util),
                "vram_used_gb": round(float(used) / 1024, 1),
                "vram_total_gb": round(float(total) / 1024, 1),
                "temp": float(temp),
            })
        except ValueError:
            continue
    return gpus


@router.get("/stats")
def system_stats() -> dict:
    """Host kaynak kullanımı — metrik paneli poll eder."""
    # default_gpu: arayüz motorların çalıştığı kartı (DEFAULT_GPU) işaretlesin diye.
    return {"cpu": _cpu(), "ram": _ram(), "disk": _disk(), "gpus": _gpus(),
            "default_gpu": default_gpu()}
