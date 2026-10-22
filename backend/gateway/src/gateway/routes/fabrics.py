"""GET /fabrics — kumaş hazır ayarları listesi (fizik + görünüm).

Tek kaynak `common.fabrics` (FABRICS). Frontend kumaş seçicisi bu listeyi okur:
`name_tr`/`name_en` + `desc_tr` gösterilir, `pbr` three.js MeshPhysicalMaterial'e
uygulanır, seçilen `id` drape (`POST /projects/{id}/drape` → `fabric_id`) ve 3D
dikiş (`POST /patterns/{id}/sew3d` → `fabric_id`) isteklerine geçer. `blender`
alanı bilgi amaçlıdır (simülasyon ayarları worker'da aynı kaynaktan okunur).
"""
from __future__ import annotations

from common.fabrics import DEFAULT_FABRIC_ID, list_fabrics
from fastapi import APIRouter

from gateway.auth import require_token

router = APIRouter(prefix="/fabrics", dependencies=[require_token()])


@router.get("")
def get_fabrics() -> dict:
    """{"default": "denim", "fabrics": [{id, name_tr, name_en, desc_tr, blender, pbr}, ...]}"""
    return {"default": DEFAULT_FABRIC_ID, "fabrics": list_fabrics()}
