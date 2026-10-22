"""Project API şemaları (Pydantic v2)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


def _default_customizations() -> dict[str, Any]:
    return {"color": "#cccccc", "decals": []}


# --- Tek-GPU sözleşmesi: default + validasyon tek doğruluk kaynağından -----------
def _default_gpu() -> int:
    """İstek gpu vermezse kullanılacak varsayılan (settings.default_gpu / DEFAULT_GPU)."""
    from common.engines.registry import default_gpu
    return default_gpu()


def _validate_gpu(v: int) -> int:
    """gpu görünür GPU kümesinde mi? Tek-GPU host'ta küme {0}'a çöker (hardcode YOK)."""
    from common.engines.registry import visible_gpu_set
    allowed = visible_gpu_set()
    if v not in allowed:
        raise ValueError(f"gpu {sorted(allowed)} içinde olmalı")
    return v


class ProjectCreate(BaseModel):
    name: str = "İsimsiz Tasarım"
    garment_type: str
    template_id: str
    customizations: dict[str, Any] = Field(default_factory=_default_customizations)


class ProjectUpdate(BaseModel):
    name: str | None = None
    customizations: dict[str, Any] | None = None


class ProjectOut(BaseModel):
    id: str
    user_id: str
    name: str
    garment_type: str
    template_id: str
    customizations: dict[str, Any]
    thumbnail_path: str | None
    mesh_path: str | None = None
    engine_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


GARMENT_TYPES = {"model", "tshirt", "shirt", "pants", "skirt", "hat", "boots"}


class GenerateTextIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=500)
    garment_type: str
    engine_id: str = "trellis-text"
    # Üretimden sonra mankene giydir: {"mannequin_id"?, "body"?: {gender, height_cm, chest_cm,
    # waist_cm, hip_cm}} — verilmezse giydirme yok.
    dress: dict | None = None
    gpu: int = Field(default_factory=_default_gpu)
    quality: str = "balanced"
    prompt_enhance: bool = True
    advanced: dict[str, Any] | None = None
    precision: str | None = None
    device_mode: str | None = None

    @field_validator("garment_type")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in GARMENT_TYPES:
            raise ValueError(f"Bilinmeyen tür: {v}")
        return v

    @field_validator("engine_id")
    @classmethod
    def _known_engine(cls, v: str) -> str:
        from common.engines.registry import get_spec, spec_available
        try:
            spec = get_spec(v)
        except KeyError:
            raise ValueError(f"Bilinmeyen motor: {v}") from None
        if spec.available and not spec_available(spec):
            raise ValueError(f"{spec.label} için API anahtarı ayarlı değil ({spec.requires_key})")
        if not spec.available:
            raise ValueError(f"{spec.label} şu an kullanılamıyor "
                             "(lisans/gated erişim veya henüz yayınlanmadı)")
        # Bu uç metin→3D üretimi; hareket/animasyon motorları (text-to-motion) buraya
        # gelmemeli (aksi halde text_to_3d.generate kayıtsız worker'da asılı kalır).
        if "text-to-3d" not in spec.capabilities:
            raise ValueError(f"{spec.label} metin→3D üretmez")
        return v

    @field_validator("gpu")
    @classmethod
    def _valid_gpu(cls, v: int) -> int:
        return _validate_gpu(v)

    @field_validator("quality")
    @classmethod
    def _valid_quality(cls, v: str) -> str:
        from common.engines.params import QUALITY_PRESETS
        if v not in QUALITY_PRESETS:
            raise ValueError(f"Bilinmeyen kalite: {v}")
        return v

    @model_validator(mode="after")
    def _validate_advanced_for_engine(self):
        from common.engines.registry import resolve_engine_params
        if self.advanced is not None:
            try:
                resolve_engine_params(self.engine_id, self.quality, self.advanced)
            except ValueError as e:
                raise ValueError(str(e)) from None
        return self


class GenerateOut(BaseModel):
    job_id: str
    project_id: str
    # Üretimle birlikte "mankene giydir" istendiyse: üretim bitince kendiliğinden başlayan
    # giydirme işinin kimliği (ayrı izlenir; sonuç projeye otomatik uygulanır).
    dress_job_id: str | None = None


class JobOut(BaseModel):
    state: str
    stage: str | None = None
    percent: int | None = None
    project_id: str | None = None
    error: str | None = None
    decal_path: str | None = None  # motif işi sonucunda üretilen şeffaf PNG (göreli)


class JobListItem(BaseModel):
    """İş kuyruğu paneli satırı."""
    job_id: str
    state: str
    kind: str | None = None
    stage: str | None = None
    percent: int | None = None
    project_id: str | None = None


class ReleaseModeIn(BaseModel):
    mode: str = "cache"

    @field_validator("mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        if v not in ("cache", "model"):
            raise ValueError("mode 'cache' veya 'model' olmalı")
        return v


class RetextureIn(BaseModel):
    source_project_id: str
    prompt: str = Field(min_length=1, max_length=500)
    gpu: int = Field(default_factory=_default_gpu)
    prompt_enhance: bool = True

    @field_validator("gpu")
    @classmethod
    def _gpu(cls, v: int) -> int:
        return _validate_gpu(v)


class TileIn(BaseModel):
    """Motifi tüm yüzeye desen olarak döşe → YENİ proje (dışa aktarılabilir doku)."""
    source_project_id: str
    motif_rel: str = Field(min_length=1)   # kaynak projedeki decal PNG göreli yolu (decals/x.png)
    repeat: int = Field(default=3, ge=1, le=10)
    bg_color: str = "#ffffff"
    gpu: int = Field(default_factory=_default_gpu)

    @field_validator("gpu")
    @classmethod
    def _gpu(cls, v: int) -> int:
        return _validate_gpu(v)


class StyleSource(BaseModel):
    """Stil transferi kaynağı: yüklenen görselden normalize kutu kırpma (+opsiyonel AI)."""
    image_name: str
    crop: list[float] = Field(min_length=4, max_length=4)  # [x0,y0,x1,y1] normalize
    ai: bool = False


class MotifIn(BaseModel):
    """İşaretli bölgeye motif: mevcut projeye decal PNG üretir (yeni proje YOK).
    prompt YA DA style verilmeli (style = stil transferi kaynağı)."""
    project_id: str
    prompt: str = Field(default="", max_length=500)
    style: StyleSource | None = None
    # Motif motoru: yerel "flux-motif" ya da bulut görsel motoru (cloud-*, capabilities motif).
    engine_id: str = "flux-motif"
    gpu: int = Field(default_factory=_default_gpu)
    prompt_enhance: bool = True

    @field_validator("gpu")
    @classmethod
    def _gpu(cls, v: int) -> int:
        return _validate_gpu(v)

    @model_validator(mode="after")
    def _need_source(self):
        if not self.prompt.strip() and self.style is None:
            raise ValueError("prompt veya style gerekli")
        return self


class PbrChannels(BaseModel):
    """PBR kanal fırçası çıktısı (BATCH-F). UV-uzayı grayscale PNG dataURL'leri:
    her boyalı texel'in gri değeri = kanalın 0-1 değeri (slider), şeffaflık = boyalı
    maske. YOKSA bake bugünkü davranışı (yalnız albedo). Worker glTF paketleme:
    metallicRoughnessTexture R=1, G=roughness, B=metallic."""
    roughness: str | None = None
    metallic: str | None = None


class MotifBakeIn(BaseModel):
    """İşaretli bölgeye motif DOKU olarak: FLUX motif üret + UV texture'a 3B
    projeksiyonla pişir → YENİ proje (decal değil, dokuya gömülü). Poz frontend'in
    decal poz hesabıyla aynı (merkez/normal/ölçek). prompt YA DA style.
    channels: opsiyonel PBR roughness/metallic kanalları (yoksa bugünkü davranış)."""
    source_project_id: str
    prompt: str = Field(default="", max_length=500)
    style: StyleSource | None = None
    center: list[float] = Field(min_length=3, max_length=3)
    normal: list[float] = Field(min_length=3, max_length=3)
    scale: float = Field(gt=0, le=10)
    channels: PbrChannels | None = None
    # Motif motoru: yerel "flux-motif" ya da bulut görsel motoru (cloud-*, capabilities motif).
    engine_id: str = "flux-motif"
    gpu: int = Field(default_factory=_default_gpu)
    prompt_enhance: bool = True

    @field_validator("gpu")
    @classmethod
    def _gpu(cls, v: int) -> int:
        return _validate_gpu(v)

    @model_validator(mode="after")
    def _need_source(self):
        if not self.prompt.strip() and self.style is None:
            raise ValueError("prompt veya style gerekli")
        return self


class ReleaseIn(BaseModel):
    family: str = "trellis"
    gpu: int = Field(default_factory=_default_gpu)
    mode: str = "cache"

    @field_validator("family")
    @classmethod
    def _family(cls, v: str) -> str:
        from common.engines.registry import engine_family, list_specs
        families = {engine_family(s["id"]) for s in list_specs()}
        if v not in families:
            raise ValueError(f"family {sorted(families)} içinde olmalı")
        return v

    @field_validator("gpu")
    @classmethod
    def _gpu(cls, v: int) -> int:
        return _validate_gpu(v)

    @field_validator("mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        if v not in ("cache", "model"):
            raise ValueError("mode 'cache' veya 'model' olmalı")
        return v


class BatchIn(BaseModel):
    """N varyasyon üret: aynı istekten farklı seed'lerle paralel iş grubu.
    kind='motif' → prompt şart; kind='style' → style şart. (v1: 3D yok.)"""
    kind: str
    project_id: str
    count: int = Field(ge=1, le=20)
    prompt: str = Field(default="", max_length=500)
    style: StyleSource | None = None
    # Motif motoru: yerel "flux-motif" ya da bulut görsel motoru (cloud-*, capabilities motif).
    engine_id: str = "flux-motif"
    gpu: int = Field(default_factory=_default_gpu)
    prompt_enhance: bool = True
    seed_base: int | None = None  # verilirse seed_base+i; yoksa rastgele

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in ("motif", "style"):
            raise ValueError("kind 'motif' veya 'style' olmalı")
        return v

    @field_validator("gpu")
    @classmethod
    def _gpu(cls, v: int) -> int:
        return _validate_gpu(v)

    @model_validator(mode="after")
    def _need_source(self):
        if self.kind == "motif" and not self.prompt.strip():
            raise ValueError("motif için prompt gerekli")
        if self.kind == "style" and self.style is None:
            raise ValueError("style için style kaynağı gerekli")
        return self


class BatchJobOut(BaseModel):
    job_id: str
    variation_id: str
    seed: int


class BatchOut(BaseModel):
    group_id: str
    jobs: list[BatchJobOut]


class VariationOut(BaseModel):
    id: str
    group_id: str
    project_id: str
    kind: str
    seed: int
    prompt: str | None
    job_id: str | None
    status: str
    result_path: str | None
    thumbnail_path: str | None
    size_bytes: int | None
    favorite: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class StorageGroupOut(BaseModel):
    group_id: str
    kind: str
    prompt: str | None
    count: int
    bytes: int
    created_at: datetime
    variations: list[VariationOut]


class StorageOut(BaseModel):
    total_bytes: int
    count: int
    groups: list[StorageGroupOut]


class VersionIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    auto: bool = False
    customizations: dict[str, Any]


class VersionOut(BaseModel):
    id: str
    project_id: str
    name: str
    auto: bool
    customizations: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}
