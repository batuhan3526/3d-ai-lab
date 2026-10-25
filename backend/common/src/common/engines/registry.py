"""Bildirimsel model kataloğu. Gateway listeler/doğrular, worker motoru çözer."""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field


# --- Tek-GPU tasarım sözleşmesi: görünür GPU kümesi tek yerden türetilir --------
# Doğruluk kaynağı: DEFAULT_GPU (kod varsayılanı 0 → tek-GPU cloner kutudan çalışır)
# ve opsiyonel VISIBLE_GPUS override ("0,1"). Değerler önce Settings'ten (.env okur),
# Settings kurulamıyorsa (ör. app_token yok) doğrudan ortam değişkeninden gelir.
def _detected_gpu_count() -> int:
    """Görünür GPU sayısı: torch varsa ondan, yoksa CUDA_VISIBLE_DEVICES'tan.
    Hiçbiri yoksa 0 (GPU'suz/headless ortam). CUDA İŞİ ÇALIŞTIRMAZ — sadece sayar."""
    try:
        import torch  # type: ignore

        n = int(torch.cuda.device_count())
        if n > 0:
            return n
    except Exception:  # noqa: BLE001 — torch yok/başarısız → env'e düş
        pass
    cvd = os.getenv("CUDA_VISIBLE_DEVICES")
    if cvd is not None and cvd.strip() != "":
        return len([x for x in cvd.split(",") if x.strip() != ""])
    return 0


def _gpu_config() -> tuple[str, int]:
    """(visible_gpus_str, default_gpu). Önce Settings (.env), aksi halde ortam."""
    try:
        from common.config import get_settings

        s = get_settings()
        return s.visible_gpus, int(s.default_gpu)
    except Exception:  # noqa: BLE001 — Settings kurulamıyorsa (app_token yok vb.) env
        return os.getenv("VISIBLE_GPUS", ""), int(os.getenv("DEFAULT_GPU", "0") or "0")


def default_gpu() -> int:
    """Varsayılan GPU index'i (DEFAULT_GPU). Cloner varsayılanı 0."""
    return _gpu_config()[1]


def visible_gpu_set() -> set[int]:
    """İzin verilen GPU index kümesi. VISIBLE_GPUS açıkça verilmişse onu kullan;
    boşsa cihaz sayısından otomatik türet; hiç saptanamazsa en az DEFAULT_GPU.
    Tek-GPU host'ta bu {0}'a çöker; validatörler/katalog hep bunu tüketir."""
    raw, dgpu = _gpu_config()
    raw = (raw or "").strip()
    if raw:
        return {int(x) for x in raw.split(",") if x.strip() != ""}
    n = _detected_gpu_count()
    if n > 0:
        return set(range(n)) | {dgpu}
    return {dgpu}


@dataclass(frozen=True)
class EngineSpec:
    id: str
    label: str
    kind: str  # "text" | "image" | "edit"
    quality_presets: list[str]
    vram_estimate_mb: int
    license: str
    # modelin ne yaptığı (1 cümle, TR) — katalog kartında gösterilir
    description: str = ""
    # ne yapabildiği: "text-to-3d" | "image-to-3d" | "multi-image-to-3d"
    capabilities: list[str] = field(default_factory=list)
    # worker'da adapter'ı bulmak için "modül:sınıf" yolu
    adapter: str = ""
    params: list[dict] = field(default_factory=list)
    presets: dict = field(default_factory=dict)
    # Görünür GPU kümesinden türetilir (tek doğruluk kaynağı). Tek-GPU host'ta [0];
    # spec'e özel GPU çakması YOK (VISIBLE_GPUS/DEFAULT_GPU tek yerden yönetir).
    gpus: list[int] = field(default_factory=lambda: sorted(visible_gpu_set()))
    precisions: list[str] = field(default_factory=lambda: ["bf16"])
    device_modes: list[str] = field(default_factory=lambda: ["single"])
    # "" = normal; "kalite" | "hız" = katalog/üretimde "Önerilen" rozetiyle öne çıkar.
    # Teknik olmayan kullanıcı için: 1 kaliteli + 1 hızlı model yeterli.
    recommended: str = ""
    # False = kodu/ağırlığı henüz yok VEYA lisans/gated erişim yayınlanamaz durumda;
    # frontend "yakında/kilitli" gösterir, gateway üretim/refine route'unda 422 reddeder.
    available: bool = True
    # Lisans TİCARİ kullanıma izin veriyor mu? NC/araştırma/koşullu-gated motorlar False.
    # Yalnız bilgilendirme + UI uyarısı; otomatik "Önerilen" rozeti verilmemesini garanti eder.
    commercial_use: bool = True
    # Bulut API motorları: gereken anahtarın env adı (ör. "TRIPO_API_KEY"). Anahtar
    # ayarlı değilse motor kilitli (spec_available False). Boş = yerel motor.
    requires_key: str = ""
    # Bulut motorları için yaklaşık çağrı ücreti (bilgi amaçlı, UI'da gösterilir).
    price_note: str = ""


# TRELLIS (text + image) parametre şeması — GenParams alanlarıyla birebir
_TRELLIS_PARAMS = [
    {"key": "sparse_steps", "label": "Sparse adım", "type": "int", "default": 25, "min": 1, "max": 100,
     "desc": "Kaba yapı (sparse) difüzyon adımı. Yüksek = daha iyi şekil ama yavaş."},
    {"key": "slat_steps", "label": "SLAT adım", "type": "int", "default": 25, "min": 1, "max": 100,
     "desc": "Detay (SLAT) difüzyon adımı. Yüksek = daha çok detay ama yavaş."},
    {"key": "sparse_cfg", "label": "Sparse CFG", "type": "float", "default": 7.5, "min": 0.0, "max": 30.0, "step": 0.1,
     "desc": "Kaba yapının prompt'a bağlılığı. Yüksek = daha sadık, aşırısı bozar."},
    {"key": "slat_cfg", "label": "SLAT CFG", "type": "float", "default": 7.5, "min": 0.0, "max": 30.0, "step": 0.1,
     "desc": "Detay aşamasının prompt'a bağlılığı."},
    {"key": "texture_size", "label": "Doku boyutu", "type": "select", "default": 1024, "options": [256, 512, 1024, 2048],
     "desc": "Doku (texture) çözünürlüğü px. Yüksek = daha keskin doku, daha büyük dosya."},
    {"key": "simplify", "label": "Sadeleştirme", "type": "float", "default": 0.95, "min": 0.0, "max": 0.98, "step": 0.01,
     "desc": "Mesh sadeleştirme oranı. Yüksek = daha az poligon (hafif), aşırısı detay kaybı."},
    {"key": "seed", "label": "Seed (boş=rastgele)", "type": "int", "default": None, "min": 0, "max": 2147483647,
     "desc": "Rastgelelik tohumu. Aynı seed = tekrarlanabilir sonuç; boş = her seferinde farklı."},
    {"key": "num_samples", "label": "Örnek sayısı", "type": "int", "default": 1, "min": 1, "max": 4,
     "desc": "Tek seferde üretilecek aday sayısı. Yüksek = daha çok seçenek, daha yavaş."},
]
_TRELLIS_PRESETS = {
    "fast": {"sparse_steps": 12, "slat_steps": 12, "sparse_cfg": 7.5, "slat_cfg": 7.5, "texture_size": 512, "simplify": 0.95, "num_samples": 1},
    "balanced": {"sparse_steps": 25, "slat_steps": 25, "sparse_cfg": 7.5, "slat_cfg": 7.5, "texture_size": 1024, "simplify": 0.95, "num_samples": 1},
    "quality": {"sparse_steps": 40, "slat_steps": 40, "sparse_cfg": 7.5, "slat_cfg": 7.5, "texture_size": 2048, "simplify": 0.90, "num_samples": 1},
}
_HUNYUAN_PARAMS = [
    {"key": "num_inference_steps", "label": "Adım", "type": "int", "default": 35, "min": 10, "max": 100,
     "desc": "Difüzyon adım sayısı. Yüksek = daha iyi kalite ama yavaş."},
    {"key": "guidance_scale", "label": "CFG", "type": "float", "default": 7.5, "min": 0.0, "max": 30.0, "step": 0.1,
     "desc": "Girdiye bağlılık. Yüksek = daha sadık, aşırısı bozar."},
    {"key": "octree_resolution", "label": "Çözünürlük", "type": "select", "default": 384, "options": [256, 384, 512],
     "desc": "Geometri çözünürlüğü. Yüksek = daha çok detay, daha yavaş."},
    {"key": "seed", "label": "Seed (boş=rastgele)", "type": "int", "default": None, "min": 0, "max": 2147483647,
     "desc": "Rastgelelik tohumu. Aynı seed = tekrarlanabilir sonuç."},
]
_HUNYUAN_PRESETS = {
    "fast": {"num_inference_steps": 25, "guidance_scale": 7.5, "octree_resolution": 256},
    "balanced": {"num_inference_steps": 35, "guidance_scale": 7.5, "octree_resolution": 384},
    "quality": {"num_inference_steps": 50, "guidance_scale": 7.5, "octree_resolution": 512},
}
_HUNYUAN_TEX_PARAMS = [
    {"key": "num_inference_steps", "label": "Adım", "type": "int", "default": 35, "min": 10, "max": 100,
     "desc": "Difüzyon adım sayısı. Yüksek = daha iyi kalite ama yavaş."},
    {"key": "guidance_scale", "label": "CFG", "type": "float", "default": 7.5, "min": 0.0, "max": 30.0, "step": 0.1,
     "desc": "Girdiye bağlılık. Yüksek = daha sadık, aşırısı bozar."},
    {"key": "octree_resolution", "label": "Çözünürlük", "type": "select", "default": 384, "options": [256, 384, 512],
     "desc": "Geometri çözünürlüğü. Yüksek = daha çok detay, daha yavaş."},
    {"key": "seed", "label": "Seed (boş=rastgele)", "type": "int", "default": None, "min": 0, "max": 2147483647,
     "desc": "Rastgelelik tohumu. Aynı seed = tekrarlanabilir sonuç."},
]
_HUNYUAN_TEX_PRESETS = {
    "fast": {"num_inference_steps": 25, "guidance_scale": 7.5, "octree_resolution": 256},
    "balanced": {"num_inference_steps": 35, "guidance_scale": 7.5, "octree_resolution": 384},
    "quality": {"num_inference_steps": 50, "guidance_scale": 7.5, "octree_resolution": 512},
}
_TRIPOSR_PARAMS = [
    {"key": "mc_resolution", "label": "Mesh çözünürlük", "type": "select", "default": 256, "options": [128, 256, 320, 512],
     "desc": "Marching-cubes mesh çözünürlüğü. Yüksek = daha pürüzsüz, daha ağır."},
    {"key": "foreground_ratio", "label": "Ön-plan oranı", "type": "float", "default": 0.85, "min": 0.5, "max": 1.0, "step": 0.05,
     "desc": "Nesnenin kare içindeki kaplama oranı."},
]
_SF3D_PARAMS = [
    {"key": "texture_resolution", "label": "Doku çözünürlük", "type": "select", "default": 1024, "options": [512, 1024, 2048],
     "desc": "Doku çözünürlüğü px. Yüksek = daha keskin doku."},
    {"key": "remesh_option", "label": "Yeniden-mesh", "type": "select", "default": "none", "options": ["none", "triangle", "quad"],
     "desc": "Yeniden topoloji: none/triangle/quad."},
    {"key": "target_vertex_count", "label": "Hedef vertex (-1=kapalı)", "type": "int", "default": -1, "min": -1, "max": 100000,
     "desc": "Hedef vertex sayısı (-1 = kapalı)."},
    {"key": "foreground_ratio", "label": "Ön-plan oranı", "type": "float", "default": 0.85, "min": 0.5, "max": 1.0, "step": 0.05,
     "desc": "Nesnenin kare içindeki kaplama oranı."},
]
_SF3D_PRESETS = {
    "fast": {"texture_resolution": 512, "remesh_option": "none", "target_vertex_count": -1, "foreground_ratio": 0.85},
    "balanced": {"texture_resolution": 1024, "remesh_option": "none", "target_vertex_count": -1, "foreground_ratio": 0.85},
    "quality": {"texture_resolution": 2048, "remesh_option": "none", "target_vertex_count": -1, "foreground_ratio": 0.85},
}
_HI3DGEN_PARAMS = [
    {"key": "ss_steps", "label": "Yapı adım", "type": "int", "default": 50, "min": 10, "max": 100,
     "desc": "Yapı (structure) aşaması adım sayısı."},
    {"key": "ss_cfg", "label": "Yapı CFG", "type": "float", "default": 3.0, "min": 0.0, "max": 15.0, "step": 0.1,
     "desc": "Yapı (structure) aşaması CFG."},
    {"key": "slat_steps", "label": "SLAT adım", "type": "int", "default": 6, "min": 1, "max": 50,
     "desc": "Detay (SLAT) aşaması adım sayısı."},
    {"key": "slat_cfg", "label": "SLAT CFG", "type": "float", "default": 3.0, "min": 0.0, "max": 15.0, "step": 0.1,
     "desc": "Detay (SLAT) aşaması CFG."},
    {"key": "seed", "label": "Seed (boş=rastgele)", "type": "int", "default": None, "min": 0, "max": 2147483647,
     "desc": "Rastgelelik tohumu. Aynı seed = tekrarlanabilir sonuç."},
]
_HI3DGEN_PRESETS = {
    "fast": {"ss_steps": 25, "ss_cfg": 3.0, "slat_steps": 6, "slat_cfg": 3.0},
    "balanced": {"ss_steps": 50, "ss_cfg": 3.0, "slat_steps": 6, "slat_cfg": 3.0},
    "quality": {"ss_steps": 50, "ss_cfg": 3.0, "slat_steps": 12, "slat_cfg": 3.0},
}
_PARTCRAFTER_PARAMS = [
    {"key": "num_parts", "label": "Parça sayısı", "type": "int", "default": 4, "min": 1, "max": 16,
     "desc": "Modelin böleceği parça sayısı."},
    {"key": "num_tokens", "label": "Parça başına token", "type": "select", "default": 1024, "options": [512, 1024, 2048],
     "desc": "Parça başına temsil token'ı. Yüksek = daha çok detay."},
    {"key": "num_inference_steps", "label": "Adım", "type": "int", "default": 50, "min": 10, "max": 100,
     "desc": "Difüzyon adım sayısı. Yüksek = daha iyi kalite ama yavaş."},
    {"key": "guidance_scale", "label": "CFG", "type": "float", "default": 7.0, "min": 0.0, "max": 20.0, "step": 0.1,
     "desc": "Girdiye bağlılık. Yüksek = daha sadık, aşırısı bozar."},
    {"key": "seed", "label": "Seed (boş=rastgele)", "type": "int", "default": None, "min": 0, "max": 2147483647,
     "desc": "Rastgelelik tohumu. Aynı seed = tekrarlanabilir sonuç."},
]
_PARTCRAFTER_PRESETS = {
    "fast": {"num_parts": 3, "num_tokens": 512, "num_inference_steps": 30, "guidance_scale": 7.0},
    "balanced": {"num_parts": 4, "num_tokens": 1024, "num_inference_steps": 50, "guidance_scale": 7.0},
    "quality": {"num_parts": 6, "num_tokens": 1024, "num_inference_steps": 50, "guidance_scale": 7.0},
}
_SAM3D_PARAMS = [
    {"key": "seed", "label": "Seed (boş=42)", "type": "int", "default": 42, "min": 0, "max": 2147483647,
     "desc": "Rastgelelik tohumu. Aynı seed = tekrarlanabilir sonuç."},
]
_SAM3D_PRESETS = {"fast": {"seed": 42}, "balanced": {"seed": 42}, "quality": {"seed": 42}}
_TRELLIS2_PARAMS = [
    {"key": "pipeline_type", "label": "Çözünürlük", "type": "select", "default": "1024_cascade",
     "options": ["512", "1024_cascade", "1536_cascade"],
     "desc": "Voxel çözünürlüğü. 1536 daha detaylı ama yavaş ve çok VRAM ister."},
    {"key": "texture_size", "label": "Doku boyutu", "type": "select", "default": 2048, "options": [1024, 2048, 4096],
     "desc": "PBR doku çözünürlüğü px."},
    {"key": "decimation_target", "label": "Hedef üçgen", "type": "int", "default": 300000, "min": 20000, "max": 2000000,
     "desc": "Dışa aktarılan mesh'in yaklaşık üçgen sayısı."},
    {"key": "remesh", "label": "Yeniden-mesh", "type": "bool", "default": False,
     "desc": "Açık: düzgün topoloji, ama kol/boyun ağzı gibi açık kenarları kapatabilir."},
    {"key": "seed", "label": "Seed (boş=42)", "type": "int", "default": None, "min": 0, "max": 2147483647,
     "desc": "Aynı seed + aynı görsel = aynı sonuç."},
]
_TRELLIS2_PRESETS = {
    "fast": {"pipeline_type": "512", "texture_size": 1024, "decimation_target": 150000},
    "balanced": {"pipeline_type": "1024_cascade", "texture_size": 2048, "decimation_target": 300000},
    "quality": {"pipeline_type": "1536_cascade", "texture_size": 4096, "decimation_target": 600000},
}
_PIXAL3D_PARAMS = [
    {"key": "resolution", "label": "Çözünürlük", "type": "select", "default": 1024, "options": [1024, 1536],
     "desc": "Voxel çözünürlüğü. 1536 daha detaylı, daha yavaş ve çok VRAM ister."},
    {"key": "low_vram", "label": "Düşük VRAM", "type": "bool", "default": True,
     "desc": "Modelleri aşama aşama GPU'ya alır (~12 GB). Kapalı: daha hızlı, ~18 GB+."},
    {"key": "fov", "label": "Kamera açısı (rad, -1=otomatik)", "type": "float", "default": -1.0, "min": -1.0, "max": 1.5, "step": 0.05,
     "desc": "Görüntünün görüş açısı. -1: MoGe-2 tahmin eder; bozulma görürsen 0.2 dene."},
    {"key": "seed", "label": "Seed (boş=42)", "type": "int", "default": None, "min": 0, "max": 2147483647,
     "desc": "Aynı seed + aynı görsel = aynı sonuç."},
]
_PIXAL3D_PRESETS = {
    "fast": {"resolution": 1024, "low_vram": True},
    "balanced": {"resolution": 1024, "low_vram": True},
    "quality": {"resolution": 1536, "low_vram": True},
}
_ULTRATEX_PARAMS = [
    {"key": "resolution", "label": "Görünüm çözünürlüğü", "type": "select", "default": 1024, "options": [1024, 2048],
     "desc": "6 görünümün her birinin çözünürlüğü. 2048 = modelin eğitildiği 2K, çok VRAM ister."},
    {"key": "steps", "label": "Adım", "type": "int", "default": 25, "min": 4, "max": 50,
     "desc": "Difüzyon adımı. Yüksek = daha temiz doku, daha yavaş."},
    {"key": "guidance", "label": "Rehberlik", "type": "float", "default": 4.0, "min": 1.0, "max": 10.0, "step": 0.5,
     "desc": "Referans görsele bağlılık."},
    {"key": "texture_size", "label": "Doku boyutu", "type": "select", "default": 2048, "options": [1024, 2048, 4096],
     "desc": "Modele işlenen UV dokusunun çözünürlüğü."},
    {"key": "seed", "label": "Seed (boş=42)", "type": "int", "default": None, "min": 0, "max": 2147483647,
     "desc": "Aynı seed + aynı girdi = aynı sonuç."},
]
_ULTRATEX_PRESETS = {
    "fast": {"resolution": 1024, "steps": 12, "texture_size": 1024},
    "balanced": {"resolution": 1024, "steps": 25, "texture_size": 2048},
    "quality": {"resolution": 2048, "steps": 25, "texture_size": 4096},
}
# Hi3D v1.0: mevcut mesh + referans görsel → yüksek çözünürlüklü geometri (yalnız şekil).
_HI3D_PARAMS = [
    {"key": "resolution", "label": "Çözünürlük", "type": "select", "default": 1024, "options": [512, 1024, 1536],
     "desc": "Seyrek ızgara: 512 = tek geçiş, 1024 = iki, 1536 = üç geçiş (en ince detay, en yavaş)."},
    {"key": "steps", "label": "Adım", "type": "int", "default": 25, "min": 4, "max": 50,
     "desc": "Geçiş başına akış adımı. Yüksek = daha temiz yüzey, daha yavaş."},
    {"key": "faces", "label": "Yüz sayısı", "type": "select", "default": 200000, "options": [100000, 200000, 500000],
     "desc": "Sonuç bu sayıya sadeleştirilir; yüksek = daha çok detay, daha ağır dosya."},
    {"key": "keep_openings", "label": "Açıklıkları koru", "type": "bool", "default": True,
     "desc": "Kıyafette yaka/kol/etek ucu açık kalır (giydirme için şart); kapalı nesnelerde kapatın."},
    {"key": "retexture", "label": "Sonra dokula (UltraTex)", "type": "bool", "default": True,
     "desc": "Hi3D yalnız şekil üretir; açıkken inceltilmiş model referans görselle yeniden dokulanır."},
    {"key": "seed", "label": "Seed (boş=0)", "type": "int", "default": None, "min": 0, "max": 2147483647,
     "desc": "Aynı seed + aynı girdi ≈ aynı sonuç (GPU çekirdekleri bit-bit belirlenimli değil)."},
]
_HI3D_PRESETS = {
    "fast": {"resolution": 512, "steps": 15},
    "balanced": {"resolution": 1024, "steps": 25},
    "quality": {"resolution": 1536, "steps": 25, "faces": 500000},
}
_TRIPOSR_PRESETS = {
    "fast": {"mc_resolution": 128, "foreground_ratio": 0.85},
    "balanced": {"mc_resolution": 256, "foreground_ratio": 0.85},
    "quality": {"mc_resolution": 512, "foreground_ratio": 0.85},
}
# World Tracing: foto->3D. mode=poisson (hızlı, dokusuz, open3d) | trellis2 (dokulu, ağır).
_WT_PARAMS = [
    {"key": "mode", "label": "Mesh modu", "type": "select", "default": "poisson",
     "options": ["poisson", "trellis2"],
     "desc": "poisson=hızlı dokusuz yüzey, trellis2=dokulu (ağır, TRELLIS.2-4B gerekir)."},
    {"key": "poisson_depth", "label": "Poisson derinlik", "type": "int", "default": 8, "min": 6, "max": 10,
     "desc": "Poisson yüzey çözünürlüğü. Yüksek = daha çok detay, daha ağır."},
    {"key": "texture_size", "label": "Doku boyutu", "type": "select", "default": 2048, "options": [1024, 2048, 4096],
     "desc": "trellis2 modunda doku çözünürlüğü px."},
    {"key": "seed", "label": "Seed (boş=42)", "type": "int", "default": 42, "min": 0, "max": 2147483647,
     "desc": "Rastgelelik tohumu. Aynı seed = tekrarlanabilir sonuç."},
]
_WT_PRESETS = {
    "fast": {"mode": "poisson", "poisson_depth": 7},
    "balanced": {"mode": "poisson", "poisson_depth": 8},
    "quality": {"mode": "trellis2", "texture_size": 2048},
}
# MeshFlow refine: mevcut mesh -> temiz topoloji (VAE encode/decode, DINOv3'süz).
_MF_PARAMS = [
    {"key": "sample_posterior", "label": "Posterior örnekle", "type": "bool", "default": True,
     "desc": "Açık = latent z'yi posterior'dan örnekle (daha çeşitli); kapalı = mod (deterministik)."},
    {"key": "dynamic_latent", "label": "Dinamik latent", "type": "bool", "default": True,
     "desc": "Açık = sadece geçerli vertex latent'lerini çöz (padding'i atla)."},
]
_MF_PRESETS = {"fast": {"sample_posterior": False, "dynamic_latent": True},
               "balanced": {"sample_posterior": True, "dynamic_latent": True},
               "quality": {"sample_posterior": True, "dynamic_latent": True}}
# MeshFlow guided: mesh + referans-görsel -> temiz topoloji (DiT flow + DINOv3 gated).
_MFG_PARAMS = [
    {"key": "steps", "label": "Örnekleme adımı", "type": "int", "default": 28, "min": 8, "max": 60,
     "desc": "Flow-matching adım sayısı. Yüksek = daha kaliteli, daha yavaş."},
    {"key": "guidance_scale", "label": "CFG", "type": "float", "default": 2.5, "min": 0.0, "max": 10.0, "step": 0.1,
     "desc": "Referans-görsele bağlılık. Yüksek = daha sadık."},
    {"key": "seed", "label": "Seed (boş=42)", "type": "int", "default": 42, "min": 0, "max": 2147483647,
     "desc": "Rastgelelik tohumu."},
]
_MFG_PRESETS = {"fast": {"steps": 16, "guidance_scale": 2.5},
                "balanced": {"steps": 28, "guidance_scale": 2.5},
                "quality": {"steps": 40, "guidance_scale": 3.0}}
# VideoMDM: metin -> SMPL hareket dizisi (animasyon hattının hareket ayağı).
_VIDEOMDM_PARAMS = [
    {"key": "motion_length", "label": "Süre (sn)", "type": "float", "default": 6.0, "min": 2.0, "max": 12.0, "step": 0.5,
     "desc": "Üretilecek hareketin saniye cinsinden süresi."},
    {"key": "guidance_scale", "label": "CFG", "type": "float", "default": 2.5, "min": 0.0, "max": 10.0, "step": 0.1,
     "desc": "Metne bağlılık. Yüksek = daha sadık."},
    {"key": "seed", "label": "Seed (boş=10)", "type": "int", "default": 10, "min": 0, "max": 2147483647,
     "desc": "Rastgelelik tohumu."},
]
_VIDEOMDM_PRESETS = {"fast": {"motion_length": 4.0}, "balanced": {"motion_length": 6.0},
                     "quality": {"motion_length": 8.0}}


_REGISTRY: dict[str, EngineSpec] = {
    "trellis-text": EngineSpec(
        id="trellis-text",
        label="TRELLIS Metin→3D",
        kind="text",
        quality_presets=["fast", "balanced", "quality"],
        vram_estimate_mb=10000,
        license="MIT",
        description="Yazılı prompt'tan tek-nesne 3D mesh üretir; dokulu, ~24s. Genel amaçlı ana motor.",
        capabilities=["text-to-3d"],
        adapter="text_to_3d.engines.trellis_text:TrellisTextEngine",
        params=_TRELLIS_PARAMS,
        presets=_TRELLIS_PRESETS,
    ),
    "trellis-image": EngineSpec(
        id="trellis-image",
        label="TRELLIS Foto→3D",
        kind="image",
        quality_presets=["fast", "balanced", "quality"],
        vram_estimate_mb=12000,
        license="MIT",
        description="Bir veya birden çok fotoğraftan dokulu 3D mesh; UV'li, yeniden-dokulamaya uygun.",
        capabilities=["image-to-3d", "multi-image-to-3d"],
        adapter="text_to_3d.engines.trellis_image:TrellisImageEngine",
        params=_TRELLIS_PARAMS,
        presets=_TRELLIS_PRESETS,
        recommended="hız",
    ),
    "hunyuan-image": EngineSpec(
        id="hunyuan-image",
        label="Hunyuan3D-2.1 Foto→3D (shape, deneysel)",
        kind="image",
        quality_presets=["fast", "balanced", "quality"],
        vram_estimate_mb=8000,
        license="Tencent Hunyuan NON-COMMERCIAL",
        description="Tek fotoğraftan yüksek-kaliteli geometri (yalnız shape, dokusuz).",
        capabilities=["image-to-3d"],
        adapter="hunyuan_worker.engine:HunyuanImageEngine",
        params=_HUNYUAN_PARAMS,
        presets=_HUNYUAN_PRESETS,
        # Tencent Hunyuan Community License = ticari değil (Territory dışı + >1M MAU
        # ayrı lisans). NC motoruna "Önerilen" rozeti VERİLMEZ ve OSS dağıtımında
        # varsayılan kapalı (kullanıcı kendi kopyasında açar).
        commercial_use=False,
        available=True,  # 2026-10-19: yerel kopyada açık (NC/gated, ticari değil)
        # dual_gpu KALDIRILDI: özel pipeline'lar model-parallel split desteklemiyor +
        # gereksiz (her model tek GPU'ya sığar). Büyük texture aşaması için "sequential"
        # (shape yükle→üret→boşalt→texture yükle→üret) tek GPU'da 24GB'a sığar.
        device_modes=["single", "sequential"],
    ),
    "hunyuan-textured": EngineSpec(
        id="hunyuan-textured",
        label="Hunyuan3D-2.1 Foto→3D (PBR dokulu, deneysel)",
        kind="image",
        quality_presets=["fast", "balanced", "quality"],
        # shape (~8GB) + paint (multiview+super-res+DINO-giant+renderer) sequential
        # çalışır; tepe VRAM paint aşamasında ~22GB. Tek GPU'ya sığar.
        vram_estimate_mb=22000,
        license="Tencent Hunyuan NON-COMMERCIAL",
        description="Tek fotoğraftan PBR-dokulu 3D mesh (shape+boya, sıralı aşama). ~2-3 dk.",
        capabilities=["image-to-3d"],
        adapter="hunyuan_worker.engine_textured:HunyuanTexturedEngine",
        params=_HUNYUAN_TEX_PARAMS,
        presets=_HUNYUAN_TEX_PRESETS,
        # Tencent NC lisans + paint aşaması DINOv3-gated → OSS'te kapalı.
        commercial_use=False,
        available=True,  # 2026-10-19: yerel kopyada açık (NC/gated, ticari değil)
        # paint aşaması neredeyse tüm GPU'yu kullanır → shape ile aynı anda tutulmaz.
        device_modes=["sequential"],
    ),
    # Hunyuan3D-2 multi-view (mv): TRELLIS dışında GERÇEK çoklu-foto→3D motoru.
    # mv DiT (tencent/Hunyuan3D-2mv, gated değil) + dict view (front/back/left/right).
    # family "hunyuan" -> queue hunyuan-gpuN; task multi_image_to_3d.generate.
    "hunyuan-mv": EngineSpec(
        id="hunyuan-mv",
        label="Hunyuan3D-2 Çok-Görünüm (çoklu foto→3D)",
        kind="image",
        quality_presets=["fast", "balanced", "quality"],
        vram_estimate_mb=10000,
        license="Tencent Hunyuan NON-COMMERCIAL",
        description="Birden çok fotoğraftan (ön/arka/yan) tutarlı 3D geometri; tek-fotoğrafa göre daha doğru.",
        capabilities=["multi-image-to-3d"],
        adapter="hunyuan_worker.engine_mv:HunyuanMVEngine",
        params=_HUNYUAN_PARAMS,
        presets=_HUNYUAN_PRESETS,
        # Tencent NC lisans → "Önerilen" rozeti yok, OSS'te varsayılan kapalı.
        commercial_use=False,
        available=True,  # 2026-10-19: yerel kopyada açık (NC/gated, ticari değil)
        device_modes=["single"],
    ),
    "triposr": EngineSpec(
        id="triposr",
        label="TripoSR Foto→3D (hızlı, ~4s)",
        kind="image",
        quality_presets=["fast", "balanced", "quality"],
        vram_estimate_mb=6000,
        license="MIT",
        description="Tek fotoğraftan çok hızlı 3D mesh (~4s); hafif, UV yok.",
        capabilities=["image-to-3d"],
        adapter="triposr_worker.engine:TripoSRImageEngine",
        params=_TRIPOSR_PARAMS,
        presets=_TRIPOSR_PRESETS,
    ),
    "trellis2-image": EngineSpec(
        id="trellis2-image",
        label="TRELLIS.2 Foto→3D (açık yüzey, PBR)",
        kind="image",
        quality_presets=["fast", "balanced", "quality"],
        vram_estimate_mb=24000,
        license="MIT (DINOv3 kodlayıcısı: Meta lisansı, HF erişimi gerekir)",
        description="Tek fotoğraftan PBR dokulu mesh; açık yüzeyler (kıyafetin kol/boyun ağzı) korunur.",
        capabilities=["image-to-3d"],
        adapter="trellis2_worker.engine:Trellis2ImageEngine",
        params=_TRELLIS2_PARAMS,
        presets=_TRELLIS2_PRESETS,
    ),
    "pixal3d-image": EngineSpec(
        id="pixal3d-image",
        label="Pixal3D Foto→3D (piksel hizalı, PBR)",
        kind="image",
        quality_presets=["fast", "balanced", "quality"],
        vram_estimate_mb=12000,
        license="MIT (DINOv3 kodlayıcısı: Meta lisansı, HF erişimi gerekir)",
        description="Tek fotoğraftan görsele en sadık şekil + PBR doku (TRELLIS.2 omurgası).",
        capabilities=["image-to-3d"],
        adapter="pixal3d_worker.engine:Pixal3DImageEngine",
        params=_PIXAL3D_PARAMS,
        presets=_PIXAL3D_PRESETS,
    ),
    "ultratex-retexture": EngineSpec(
        id="ultratex-retexture",
        label="UltraTex Görselden Doku (2K, çok görünüm)",
        kind="edit",
        quality_presets=["fast", "balanced", "quality"],
        vram_estimate_mb=24000,
        license="MIT kod · FLUX.2-klein (BFL lisansı, HF erişimi) · Qwen3-8B Apache-2.0",
        description="Mevcut 3D modeli bir referans görsele göre yeniden dokular; şekil aynı kalır.",
        capabilities=["image-retexture"],
        adapter="ultratex_worker.engine:UltraTexEngine",
        params=_ULTRATEX_PARAMS,
        presets=_ULTRATEX_PRESETS,
        commercial_use=False,
    ),
    # Hi3D refine (kind=edit): family "hi3d" -> queue hi3d-gpuN; task mesh_refine.generate,
    # retexture açıksa iş ultratex-gpuN'e devredilir.
    "hi3d-refine": EngineSpec(
        id="hi3d-refine",
        label="Hi3D Geometri İncelt (1536³)",
        kind="edit",
        quality_presets=["fast", "balanced", "quality"],
        vram_estimate_mb=20000,
        license="Hi3D Open License 1.0 (ticari serbest, \"Powered by Hi3D 1.0\" ibaresi; 200k MAU üstü ayrı lisans)",
        description="Mevcut modelin şeklini referans görsele göre yüksek çözünürlükte yeniden üretir (yaka, dikiş, kırışık).",
        capabilities=["image-refine"],
        adapter="hi3d_worker.engine:Hi3DEngine",
        params=_HI3D_PARAMS,
        presets=_HI3D_PRESETS,
    ),
    "sf3d-image": EngineSpec(
        id="sf3d-image",
        label="Stable-Fast-3D Foto→3D (hızlı, PBR dokulu)",
        kind="image",
        quality_presets=["fast", "balanced", "quality"],
        vram_estimate_mb=7000,
        license="Stability AI Community (ticari koşullu)",
        description="Tek fotoğraftan hızlı PBR-dokulu mesh (~1s); UV'li.",
        capabilities=["image-to-3d"],
        adapter="sf3d_worker.engine:SF3DImageEngine",
        params=_SF3D_PARAMS,
        presets=_SF3D_PRESETS,
    ),
    "hi3dgen-image": EngineSpec(
        id="hi3dgen-image",
        label="Hi3DGen Foto→3D (yüksek geometri detayı)",
        kind="image",
        quality_presets=["fast", "balanced", "quality"],
        vram_estimate_mb=14000,
        license="MIT",
        description="Tek veya çok fotoğraftan yüksek geometri-detaylı mesh (normal-tahmin destekli).",
        capabilities=["image-to-3d", "multi-image-to-3d"],
        adapter="hi3dgen_worker.engine:Hi3DGenImageEngine",
        params=_HI3DGEN_PARAMS,
        presets=_HI3DGEN_PRESETS,
    ),
    "partcrafter-image": EngineSpec(
        id="partcrafter-image",
        label="PartCrafter Foto→3D (parça-bilinçli)",
        kind="image",
        quality_presets=["fast", "balanced", "quality"],
        vram_estimate_mb=12000,
        license="MIT",
        description="Tek fotoğraftan parça-bilinçli mesh; nesneyi ayrı parçalara böler.",
        capabilities=["image-to-3d"],
        adapter="partcrafter_worker.engine:PartCrafterImageEngine",
        params=_PARTCRAFTER_PARAMS,
        presets=_PARTCRAFTER_PRESETS,
        # PartCrafter kodu MIT ama varsayılan pipeline briaai/RMBG-1.4 (NON-COMMERCIAL)
        # çeker → efektif ticari kullanım kısıtlı. Motor çalışır, ticari değil.
        commercial_use=False,
    ),
    "sam3d-image": EngineSpec(
        id="sam3d-image",
        label="SAM 3D Objects Foto→3D (gerçek-foto, dokulu, deneysel)",
        kind="image",
        quality_presets=["fast", "balanced", "quality"],
        vram_estimate_mb=24000,
        license="SAM License (Meta)",
        description="Gerçek fotoğraftan dokulu 3D rekonstrüksiyon (Meta SAM 3D); doğal sahneler için.",
        capabilities=["image-to-3d"],
        adapter="sam3d_worker.engine:SAM3DObjectEngine",
        params=_SAM3D_PARAMS,
        presets=_SAM3D_PRESETS,
    ),
    # kind="edit" → üretim DEĞİL, mevcut mesh'i prompt'la yeniden-dokular (InTeX).
    # Frontend üretim dropdown'ında gösterilmez (kind=edit filtrelenir); status/release
    # için "intex" ailesi kapsanır.
    "intex-retexture": EngineSpec(
        id="intex-retexture",
        label="InTeX Yeniden-Dokula (prompt)",
        kind="edit",
        quality_presets=["balanced"],
        vram_estimate_mb=8000,
        license="InTeX + SD model (kendi lisansları)",
        description="Mevcut mesh'i prompt'la yeniden-dokular (üretim değil).",
        capabilities=["retexture"],
        adapter="intex_worker.engine:IntexEditEngine",
        params=[],
        presets={"fast": {}, "balanced": {}, "quality": {}},
    ),
    # İşaretli bölgeye TEMİZ motif: FLUX.1-dev 2D üretir + BiRefNet matte ->
    # şeffaf PNG decal. SD1.5 region-inpaint'in renk/boşluk sorunlarını çözer.
    # kind=edit (katalog dropdown'ında gösterilmez); family "flux" -> queue flux-gpuN.
    "flux-motif": EngineSpec(
        id="flux-motif",
        label="FLUX Motif (decal)",
        kind="edit",
        quality_presets=["balanced"],
        vram_estimate_mb=16000,
        license="FLUX.1-dev Non-Commercial (kişisel kullanım ücretsiz)",
        description="Prompt'tan 2D motif üretip işaretli bölgeye decal olarak koyar.",
        capabilities=["motif"],
        adapter="flux_motif_worker.engine:FluxMotifEngine",
        params=[],
        presets={"fast": {}, "balanced": {}, "quality": {}},
        # FLUX.1-dev Non-Commercial License + HF-gated. Üretilen çıktı ticari kullanılabilir
        # ama modelin kendisi ticari serviste çalıştırılamaz → commercial_use=False.
        commercial_use=False,
    ),
    # World Tracing: foto->3D, ön yüz piksel-hizalı + arka yüz üretimi (hiza/arka-yüz sorununu hedefler).
    # family "worldtracing" -> queue worldtracing-gpuN. Ağırlık gated (haoz19/*), worker gelince canlı.
    "worldtracing-image": EngineSpec(
        id="worldtracing-image",
        label="World Tracing Foto→3D (hiza + arka-yüz)",
        kind="image",
        quality_presets=["fast", "balanced", "quality"],
        vram_estimate_mb=12000,
        license="World Labs (araştırma)",
        description="Tek fotoğraftan 3D; ön yüzü piksel-hizalı tutar, görünmeyen arka yüzü üretir.",
        capabilities=["image-to-3d"],
        adapter="worldtracing_worker.engine:WorldTracingEngine",
        params=_WT_PARAMS,
        presets=_WT_PRESETS,
        # CC BY-NC-ND (ticari değil + türev yok) + ağırlık gated (haoz19/*).
        # "Önerilen" rozeti KALDIRILDI; OSS'te varsayılan kapalı.
        commercial_use=False,
        available=True,  # 2026-10-19: yerel kopyada açık (NC/gated, ticari değil)
    ),
    # MeshFlow refine (kind=edit): mevcut mesh'i temiz topolojiyle yeniden üretir; UV/fırça/retexture kalitesi.
    # family "meshflow" -> queue meshflow-gpuN; task mesh_refine.generate.
    "meshflow-refine": EngineSpec(
        id="meshflow-refine",
        label="MeshFlow Temizle (remesh)",
        kind="edit",
        quality_presets=["fast", "balanced", "quality"],
        vram_estimate_mb=10000,
        license="CC-BY-NC 4.0 (Meta)",
        description="Mevcut mesh'i temiz topolojiyle yeniden üretir (UV/boyama kalitesini artırır).",
        capabilities=["retexture"],
        adapter="meshflow_worker.engine_refine:MeshFlowRefineEngine",
        params=_MF_PARAMS,
        presets=_MF_PRESETS,
        # FAIR Noncommercial Research License + ağırlık (facebook/meshflow) Meta-gated
        # → OSS'te varsayılan kapalı, ticari değil.
        commercial_use=False,
        available=True,  # 2026-10-19: yerel kopyada açık (NC/gated, ticari değil)
    ),
    # MeshFlow guided (kind=edit): mesh + referans-görsel -> temiz topoloji (DiT flow, DINOv3 gated).
    "meshflow-guided": EngineSpec(
        id="meshflow-guided",
        label="MeshFlow Görsel-Rehberli Temizle",
        kind="edit",
        quality_presets=["fast", "balanced", "quality"],
        vram_estimate_mb=12000,
        license="CC-BY-NC 4.0 (Meta)",
        description="Mevcut mesh'i referans görsele göre temiz topolojiyle yeniden üretir.",
        capabilities=["retexture", "motif"],
        adapter="meshflow_worker.engine_guided:MeshFlowGuidedEngine",
        params=_MFG_PARAMS,
        presets=_MFG_PRESETS,
        # FAIR Noncommercial + facebook/meshflow gated + DINOv3 gated → OSS'te kapalı.
        commercial_use=False,
        available=True,  # 2026-10-19: yerel kopyada açık (NC/gated, ticari değil)
    ),
    # VideoMDM (kind=text): metin -> SMPL hareket dizisi (animasyon hattının hareket ayağı).
    # family "videomdm" -> queue videomdm-gpuN; task motion.generate / animate.generate.
    "videomdm-motion": EngineSpec(
        id="videomdm-motion",
        label="VideoMDM Metin→Hareket",
        kind="text",
        quality_presets=["fast", "balanced", "quality"],
        vram_estimate_mb=6000,
        license="MIT (MDM tabanlı)",
        description="Metinden 3D insan hareketi üretir; manken animasyonu/video için.",
        capabilities=["text-to-motion"],
        adapter="videomdm_worker.motion:MotionGenerator",
        params=_VIDEOMDM_PARAMS,
        presets=_VIDEOMDM_PRESETS,
        # Kod MIT ama zorunlu SMPL/SMPL-X (MPI non-commercial, gated) + AMASS/Fit3D
        # (NC) bağımlılıkları → efektif ticari değil ve gated. capabilities yalnız
        # "text-to-motion" olduğundan text→3D dropdown'ında GÖSTERİLMEZ; animasyon
        # /animate route'undan çalışır. gpus pini KALDIRILDI (görünür kümeden türer).
        commercial_use=False,
        available=True,  # 2026-10-19: yerel kopyada açık (NC/gated, ticari değil)
    ),
    # ClothSim drape (kind=edit): mevcut mesh'i manken üstüne fizik-tabanlı düşürür
    # (offline Blender headless cloth sim). CPU-only (gpus=[]) → tek-GPU sözleşmesi
    # ETKİLENMEZ; family "clothsim" -> queue clothsim-cpu; task clothsim.drape.
    # Blender GPL-3.0 ama ayrı binary olarak (subprocess) çağrılır; app kodu MIT kalır.
    "clothsim-drape": EngineSpec(
        id="clothsim-drape",
        label="Kumaş Simülasyonu (Blender drape)",
        kind="edit",
        quality_presets=["fast", "balanced", "quality"],
        vram_estimate_mb=0,
        license="GPL-3.0 (Blender binary) + MIT (app kodu)",
        description="Mevcut mesh'i manken üstüne fizik-tabanlı düşürür (offline Blender kumaş simülasyonu).",
        capabilities=["drape"],
        # Task-tabanlı routing (clothsim.drape); adapter sınıfı yok.
        adapter="",
        params=[
            {"key": "frames", "label": "Sim kare sayısı", "type": "int", "default": 40, "min": 2, "max": 240,
             "desc": "Kumaş simülasyonu kare sayısı. Yüksek = daha oturmuş drape, daha yavaş."},
        ],
        presets={"fast": {"frames": 20}, "balanced": {"frames": 40}, "quality": {"frames": 80}},
        # CPU-only: görünür GPU kümesinden GPU pini YOK. Blender headless CPU'da çalışır.
        gpus=[],
        # Blender ayrı bir binary (subprocess) olarak çağrılır → uygulamanın kendi
        # dağıtımı GPL kapsamına girmez; kurulum kullanıcıda (apt install blender).
        available=True,
        commercial_use=True,
    ),
    # Flex4DHuman: kod/ağırlık henüz yayınlanmadı -> placeholder (available=False, frontend "yakında").
    "flex4dhuman-4d": EngineSpec(
        id="flex4dhuman-4d",
        label="Flex4DHuman (yakında)",
        kind="image",
        quality_presets=["balanced"],
        vram_estimate_mb=24000,
        license="World Labs (araştırma)",
        description="Çok-görünüm video→4D Gaussian. Kod henüz yayınlanmadı (placeholder).",
        # Gerçek yetenek video→4D insan, "image-to-3d" DEĞİL (yanlış etiket motor bir gün
        # available olunca foto→3D validator'ından geçerdi). kind="image" kalıyor ki
        # dropdown'da "yakında" rozetiyle görünmeye devam etsin; routing caps'e bakar.
        capabilities=["video-to-4d"],
        adapter="",
        params=[],
        presets={"balanced": {}},
        # Kod/ağırlık yayınlanmadı (yalnız dataset, CC BY-NC-SA) → placeholder.
        available=False,
        commercial_use=False,
    ),
    # FaceAnything (ECCV'26, TUM): video/foto → 4D yüz rekonstrüksiyonu + yoğun takip.
    # family "faceanything" -> queue faceanything-gpuN; task face4d.generate.
    "faceanything-4d": EngineSpec(
        id="faceanything-4d",
        label="FaceAnything Yüz→4D",
        kind="image",
        quality_presets=["fast", "balanced", "quality"],
        vram_estimate_mb=18000,
        license="CC BY-NC 4.0 (ticari değil)",
        description="Video veya fotoğraftan 4D yüz rekonstrüksiyonu ve yoğun takip (manken kişiselleştirme).",
        capabilities=["face-4d"],
        adapter="faceanything_worker.engine:FaceAnythingEngine",
        params=[
            {"key": "process_res", "label": "İşleme çözünürlüğü", "type": "int", "default": 504,
             "min": 252, "max": 1008, "desc": "Model girdi çözünürlüğü. Yüksek = detay, yavaş + çok VRAM."},
            {"key": "max_frames", "label": "Azami kare", "type": "int", "default": 0, "min": 0, "max": 600,
             "desc": "0 = hepsi. Video girdide kare sayısını sınırlar."},
        ],
        presets={"fast": {"process_res": 378}, "balanced": {"process_res": 504},
                 "quality": {"process_res": 756}},
        # CC BY-NC 4.0 → ticari kullanım YASAK; dahili deney için available=True.
        commercial_use=False,
        available=True,
    ),
    # GaussianGPT (ECCV'26, TUM, MIT): otoregresif 3DGS sahne üretimi (koşulsuz/completion).
    # Sahne-seviyesi ckpt (3D-FRONT iç mekan); obje-seviyesi ckpt beklemede (2026-07-13).
    # family "gaussiangpt" -> queue gaussiangpt-gpuN; task scene.generate.
    "gaussiangpt-scene": EngineSpec(
        id="gaussiangpt-scene",
        label="GaussianGPT Sahne Üret",
        kind="text",
        quality_presets=["fast", "balanced", "quality"],
        vram_estimate_mb=12000,
        license="MIT",
        description="Otoregresif 3D Gaussian sahne üretimi (iç mekan chunk; arka plan/showroom adayı).",
        capabilities=["scene-generation"],
        adapter="gaussiangpt_worker.engine:GaussianGPTEngine",
        params=[
            {"key": "temperature", "label": "Sıcaklık", "type": "float", "default": 1.0,
             "min": 0.1, "max": 2.0, "step": 0.05, "desc": "Örnekleme çeşitliliği. Yüksek = çeşitli/riskli."},
            {"key": "num_samples", "label": "Örnek sayısı", "type": "int", "default": 1, "min": 1, "max": 8,
             "desc": "Kaç sahne chunk'ı üretilecek."},
        ],
        presets={"fast": {"num_samples": 1}, "balanced": {"num_samples": 2},
                 "quality": {"num_samples": 4}},
        commercial_use=True,
        available=True,
    ),
    # PixWorld (arXiv 2607.05373): 3D sahne üretimi+rekonstrüksiyonu piksel uzayında,
    # sahne başına ~0.6sn (4-adım damıtılmış, 480P), çıktı 3DGS. KOD/AĞIRLIK HENÜZ
    # YAYINLANMADI → placeholder (flex4dhuman deseni). Release izleyici:
    # (upstream ağırlıkları henüz yayınlanmadı). Çıkınca:
    # gaussiangpt worker deseni kopyalanır, available=True yapılır.
    "pixworld-scene": EngineSpec(
        id="pixworld-scene",
        label="PixWorld Sahne (yakında)",
        kind="image",
        quality_presets=["balanced"],
        vram_estimate_mb=16000,
        license="bilinmiyor (kod yayınlanmadı)",
        description="Foto/metinden ~0.6 saniyede 3DGS sahne. Kod henüz yayınlanmadı (placeholder).",
        capabilities=["scene-generation"],
        adapter="",
        params=[],
        presets={"balanced": {}},
        available=False,
        commercial_use=False,
    ),
    # ArtiFixer (SIGGRAPH'26, NVIDIA, Apache-2.0): 3DGS/COLMAP taramalarının az-görülen
    # bölgelerini 14B AR-video-difüzyonla düzeltir/tamamlar ("gerçek ürün tarama" hattı).
    # 3090 notu: bf16 ~28GB → worker CPU-offload'la koşturur (yavaş). vram_estimate
    # offload sonrası GPU'da kalan çalışma kümesini yansıtır.
    # family "artifixer" -> queue artifixer-gpuN; task scanfix.prepare / scanfix.generate.
    "artifixer-fix": EngineSpec(
        id="artifixer-fix",
        label="ArtiFixer Tarama Düzelt",
        kind="edit",
        quality_presets=["fast", "balanced", "quality"],
        vram_estimate_mb=22000,
        license="Apache-2.0",
        description="Çok-fotoğraf (COLMAP) taramasının eksik/bozuk bölgelerini üretken modelle düzeltir.",
        capabilities=["scan-fix"],
        adapter="artifixer_worker.engine:ArtiFixerEngine",
        params=[
            {"key": "num_inference_steps", "label": "Difüzyon adımı", "type": "int", "default": 4,
             "min": 1, "max": 16, "desc": "Denoise adım sayısı. 4 genelde yeter (damıtılmış model)."},
        ],
        presets={"fast": {"num_inference_steps": 2}, "balanced": {"num_inference_steps": 4},
                 "quality": {"num_inference_steps": 8}},
        commercial_use=True,
        available=True,
    ),
}


# --- Bulut API motorları (opsiyonel, ücretli) ----------------------------------------
# Hepsi "cloud-" önekli → aile "cloud" → tek CPU worker (kuyruk cloud-cpu). Anahtarı
# (requires_key) .env'de yoksa spec_available False → arayüzde kilitli. Fiyatlar
# yaklaşık (2026-10 web araştırması); güncel tarifeyi sağlayıcı sayfasından doğrula.
# Ortak 3D şeması: detail (sağlayıcı kendi kalite/poligon seçeneğine çevirir),
# texture (dokulu/dokusuz), seed (0 = rastgele).
_CLOUD3D_PARAMS = [
    {"key": "detail", "label": "Detay", "type": "select", "default": "medium",
     "options": ["low", "medium", "high"],
     "desc": "Sağlayıcının kalite/poligon seviyesi. Yüksek = daha detaylı, daha pahalı/yavaş."},
    {"key": "texture", "label": "Doku", "type": "bool", "default": True,
     "desc": "Kapalı = yalnız şekil (daha ucuz/hızlı)."},
    {"key": "seed", "label": "Seed", "type": "int", "default": 0, "min": 0, "max": 2_000_000_000,
     "desc": "0 = rastgele. Aynı seed + girdi ≈ aynı sonuç (sağlayıcı destekliyorsa)."},
]
_CLOUD3D_PRESETS = {"fast": {"detail": "low"}, "balanced": {"detail": "medium"},
                    "quality": {"detail": "high"}}
_CLOUDIMG_PARAMS = [
    {"key": "detail", "label": "Kalite", "type": "select", "default": "medium",
     "options": ["low", "medium", "high"], "desc": "Sağlayıcının kalite seviyesi."},
]


def _cloud3d(eid: str, label: str, kind: str, key: str, price: str, desc: str,
             license_: str, commercial: bool = True) -> EngineSpec:
    return EngineSpec(
        id=eid, label=label, kind=kind, quality_presets=["fast", "balanced", "quality"],
        vram_estimate_mb=0, license=license_, description=desc,
        capabilities=["text-to-3d" if kind == "text" else "image-to-3d"],
        adapter="cloud_worker.worker", params=_CLOUD3D_PARAMS, presets=_CLOUD3D_PRESETS,
        gpus=[], precisions=["cloud"], requires_key=key, price_note=price,
        commercial_use=commercial)


def _cloudimg(eid: str, label: str, key: str, price: str, desc: str, license_: str) -> EngineSpec:
    return EngineSpec(
        id=eid, label=label, kind="edit", quality_presets=["fast", "balanced", "quality"],
        vram_estimate_mb=0, license=license_, description=desc, capabilities=["motif"],
        adapter="cloud_worker.worker", params=_CLOUDIMG_PARAMS,
        presets={"fast": {"detail": "low"}, "balanced": {"detail": "medium"},
                 "quality": {"detail": "high"}},
        gpus=[], precisions=["cloud"], requires_key=key, price_note=price)


_TOS = "Sağlayıcı kullanım şartları (ücretli API)"
for _s in (
    # 3D — metinden
    _cloud3d("cloud-tripo-text", "Tripo3D Metin→3D", "text", "TRIPO_API_KEY", "~$0.05–0.20 / model",
             "Tripo3D bulut API'si: metinden dokulu 3D (GLB). En ucuz bulut 3D.", _TOS),
    _cloud3d("cloud-meshy-text", "Meshy Metin→3D", "text", "MESHY_API_KEY", "20–30 kredi (~$0.20–0.30)",
             "Meshy-6: metinden önizleme + dokulu (PBR) model.", _TOS),
    _cloud3d("cloud-rodin-text", "Hyper3D Rodin Metin→3D", "text", "RODIN_API_KEY", "~$0.40–1.50 / model",
             "Rodin Gen-2: en yüksek kalite bulut 3D (API için iş planı gerekebilir).", _TOS),
    _cloud3d("cloud-falhunyuan-text", "Hunyuan3D (fal.ai) Metin→3D", "text", "FAL_KEY", "~$0.225 / model",
             "Tencent Hunyuan3D v3.1 Rapid, fal.ai üzerinden.", _TOS),
    # 3D — görselden
    _cloud3d("cloud-tripo-image", "Tripo3D Foto→3D", "image", "TRIPO_API_KEY", "~$0.05–0.20 / model",
             "Tripo3D bulut API'si: görselden dokulu 3D (GLB).", _TOS),
    _cloud3d("cloud-meshy-image", "Meshy Foto→3D", "image", "MESHY_API_KEY", "20–30 kredi (~$0.20–0.30)",
             "Meshy-6: görselden dokulu (PBR) model.", _TOS),
    _cloud3d("cloud-rodin-image", "Hyper3D Rodin Foto→3D", "image", "RODIN_API_KEY", "~$0.40–1.50 / model",
             "Rodin Gen-2: görselden yüksek kalite 3D.", _TOS),
    _cloud3d("cloud-falhunyuan-image", "Hunyuan3D (fal.ai) Foto→3D", "image", "FAL_KEY", "~$0.375 (+PBR $0.15)",
             "Tencent Hunyuan3D v3 (Pro), fal.ai üzerinden.", _TOS),
    _cloud3d("cloud-faltrellis-image", "TRELLIS (fal.ai) Foto→3D", "image", "FAL_KEY", "~$0.02–0.05 / model",
             "Yerel TRELLIS'in bulut sürümü (GPU meşgulken yedek).", _TOS),
    _cloud3d("cloud-stability-image", "Stable Fast 3D (Stability) Foto→3D", "image", "STABILITY_API_KEY",
             "10 kredi (~$0.10)", "Stability AI Stable Fast 3D: saniyeler içinde GLB.", _TOS),
    _cloud3d("cloud-replicate-image", "TRELLIS (Replicate) Foto→3D", "image", "REPLICATE_API_TOKEN",
             "çalıştırma başına (~$0.05)", "Replicate üzerinde TRELLIS.", _TOS),
    # 3D — 2026-10-25 web taraması: fal.ai/Replicate'te yeni modeller + yeni sağlayıcılar
    _cloud3d("cloud-faltripo-text", "Tripo H3.1 (fal.ai) Metin→3D", "text", "FAL_KEY", "$0.10–0.30 (+$0.20 detaylı)",
             "Tripo'nun en yeni H3.1 modeli, fal.ai anahtarıyla.", _TOS),
    _cloud3d("cloud-faltripo-image", "Tripo H3.1 (fal.ai) Foto→3D", "image", "FAL_KEY", "$0.20–0.40 (+$0.20 detaylı)",
             "Tripo H3.1, fal.ai üzerinden: dokulu PBR GLB.", _TOS),
    _cloud3d("cloud-falmeshy-text", "Meshy 7.1 (fal.ai) Metin→3D", "text", "FAL_KEY", "$0.80–1.20 / model",
             "Meshy 7.1, fal.ai üzerinden (önizleme + dokulu).", _TOS),
    _cloud3d("cloud-falmeshy-image", "Meshy 7.1 (fal.ai) Foto→3D", "image", "FAL_KEY", "$0.80–1.20 / model",
             "Meshy 7.1, fal.ai üzerinden: dokulu (PBR) model.", _TOS),
    _cloud3d("cloud-falrodin-text", "Rodin Gen-2.5 (fal.ai) Metin→3D", "text", "FAL_KEY", "$0.40 / model",
             "Hyper3D Rodin Gen-2.5, iş planı gerekmeden fal.ai anahtarıyla.", _TOS),
    _cloud3d("cloud-falrodin-image", "Rodin Gen-2.5 (fal.ai) Foto→3D", "image", "FAL_KEY", "$0.40 / model",
             "Hyper3D Rodin Gen-2.5, fal.ai üzerinden: yüksek detay.", _TOS),
    _cloud3d("cloud-falhunyuanrapid-image", "Hunyuan3D Rapid (fal.ai) Foto→3D", "image", "FAL_KEY",
             "$0.225 (+PBR $0.15)", "Tencent Hunyuan3D v3.1 Rapid: Pro'dan ucuz ve hızlı.", _TOS),
    _cloud3d("cloud-falhitem3d-image", "Hitem3D v3 (fal.ai) Foto→3D", "image", "FAL_KEY", "$2.10–9.10 / model",
             "Hitem3D (Sparc3D/Ultra3D) v3.0: çok yüksek poligonlu, en pahalı bulut 3D.", _TOS),
    _cloud3d("cloud-falsam3d-image", "SAM 3D Objects (fal.ai) Foto→3D", "image", "FAL_KEY", "~$0.02 / birim",
             "Meta SAM 3D: gerçek fotoğraftaki nesneyi ayırıp 3D'ye çevirir.", _TOS),
    _cloud3d("cloud-falpixal3d-image", "Pixal3D (fal.ai) Foto→3D", "image", "FAL_KEY", "$0.30–0.42 / model",
             "Yerel Pixal3D'nin bulut sürümü (piksel hizalı).", _TOS),
    _cloud3d("cloud-replicatehunyuan-text", "Hunyuan3D 3.1 (Replicate) Metin→3D", "text", "REPLICATE_API_TOKEN",
             "$0.50 / model", "Tencent'in Replicate'teki resmi Hunyuan3D 3.1 modeli.", _TOS),
    _cloud3d("cloud-replicatehunyuan-image", "Hunyuan3D 3.1 (Replicate) Foto→3D", "image", "REPLICATE_API_TOKEN",
             "$0.50 / model", "Tencent'in Replicate'teki resmi Hunyuan3D 3.1 modeli.", _TOS),
    _cloud3d("cloud-replicatetrellis2-image", "TRELLIS.2 (Replicate) Foto→3D", "image", "REPLICATE_API_TOKEN",
             "~$0.90 / çalıştırma", "TRELLIS.2 topluluk modeli, Replicate (A100) üzerinde.", _TOS),
    _cloud3d("cloud-tencent-text", "Tencent HY 3D Pro Metin→3D", "text", "TENCENTCLOUD_API_KEY",
             "25–55 kredi ($0.50–1.10)", "Hunyuan 3D 3.1 Pro, Tencent Cloud'un resmi uluslararası API'si.", _TOS),
    _cloud3d("cloud-tencent-image", "Tencent HY 3D Pro Foto→3D", "image", "TENCENTCLOUD_API_KEY",
             "25–55 kredi ($0.50–1.10)", "Hunyuan 3D 3.1 Pro, resmi API (200 ücretsiz başlangıç kredisi).", _TOS),
    _cloud3d("cloud-hitem3d-image", "Hitem3D v3 Foto→3D", "image", "HITEM3D_API_KEY", "$0.90–2.90 / model",
             "Hitem3D'nin kendi API'si: fal.ai'den ucuz, aynı v3.0 modeli.", _TOS),
    _cloud3d("cloud-neural4d-text", "Neural4D Metin→3D", "text", "NEURAL4D_API_KEY", "~30 kredi / model",
             "DreamTech Neural4D 2.5 (Direct3D-S2). API için ücretli abonelik gerekir.", _TOS),
    _cloud3d("cloud-neural4d-image", "Neural4D Foto→3D", "image", "NEURAL4D_API_KEY", "~30 kredi / model",
             "DreamTech Neural4D 2.5: görselden dokulu model.", _TOS),
    _cloud3d("cloud-aistudio-text", "Hunyuan3D Pro (3D AI Studio) Metin→3D", "text", "THREEDAISTUDIO_API_KEY",
             "60–100 kredi", "3D AI Studio üzerinden Hunyuan 3D 3.1 Pro (dakikada 3 istek sınırı).", _TOS),
    _cloud3d("cloud-aistudio-image", "Hunyuan3D Pro (3D AI Studio) Foto→3D", "image", "THREEDAISTUDIO_API_KEY",
             "60–100 kredi", "3D AI Studio üzerinden Hunyuan 3D 3.1 Pro.", _TOS),
    _cloud3d("cloud-aistudiotrellis2-image", "TRELLIS.2 (3D AI Studio) Foto→3D", "image", "THREEDAISTUDIO_API_KEY",
             "15–55 kredi", "3D AI Studio üzerinden TRELLIS.2.", _TOS),
    _cloud3d("cloud-atlasseed3d-image", "Seed3D 2.0 (Atlas Cloud) Foto→3D", "image", "ATLASCLOUD_API_KEY",
             "$0.353 / model", "ByteDance Seed3D 2.0: tek görselden dokulu 3D (100k–1M yüz).", _TOS),
    _cloud3d("cloud-arkrodin-text", "Rodin Gen-2 (BytePlus) Metin→3D", "text", "ARK_API_KEY", "~$0.40 / model",
             "Hyper3D Rodin Gen-2, BytePlus ModelArk üzerinden (Türkiye destekli).", _TOS),
    _cloud3d("cloud-arkrodin-image", "Rodin Gen-2 (BytePlus) Foto→3D", "image", "ARK_API_KEY", "~$0.40 / model",
             "Hyper3D Rodin Gen-2, BytePlus ModelArk üzerinden.", _TOS),
    # Görsel (motif / desen) — kind=edit, capabilities motif (Tasarımcı'da motor seçici)
    _cloudimg("cloud-openai-image", "OpenAI GPT Image", "OPENAI_API_KEY", "$0.01–0.21 / görsel",
              "Prompt'a en iyi uyan model; şeffaf zemin destekler.", _TOS),
    # Imagen 4 Gemini API'de kapatıldı (2026-10) → Nano Banana ailesi.
    _cloudimg("cloud-google-nanobanana", "Google Nano Banana 2", "GOOGLE_API_KEY", "$0.045–0.15 / görsel",
              "Gemini 3.1 Flash Image (Nano Banana 2). GEMINI_API_KEY adı da kabul edilir.", _TOS),
    _cloudimg("cloud-google-nanobananapro", "Google Nano Banana Pro", "GOOGLE_API_KEY", "$0.134–0.24 / görsel",
              "Gemini 3 Pro Image: en yüksek kalite Google görsel modeli.", _TOS),
    _cloudimg("cloud-bfl-flux", "FLUX Pro (Black Forest Labs)", "BFL_API_KEY", "~$0.03–0.06 / görsel",
              "Yerel FLUX'un daha güçlü ticari bulut sürümü.", _TOS),
    _cloudimg("cloud-ideogram-image", "Ideogram 3", "IDEOGRAM_API_KEY", "$0.03–0.10 / görsel",
              "Yazılı tasarımlar (logo, slogan) için güçlü.", _TOS),
    _cloudimg("cloud-recraft-image", "Recraft V3", "RECRAFT_API_KEY", "~$0.04 / görsel",
              "İllüstrasyon/vektör tarzı; baskıya uygun temiz çizgiler.", _TOS),
    _cloudimg("cloud-stability-sdimage", "Stable Image (Stability)", "STABILITY_API_KEY", "3–8 kredi (~$0.03–0.08)",
              "Stability AI Stable Image Core/Ultra.", _TOS),
    _cloudimg("cloud-falflux-image", "FLUX Pro (fal.ai)", "FAL_KEY", "~$0.03–0.05 / görsel",
              "FLUX Pro, fal.ai üzerinden.", _TOS),
    _cloudimg("cloud-replicate-flux", "FLUX (Replicate)", "REPLICATE_API_TOKEN", "~$0.003–0.04 / görsel",
              "FLUX modelleri Replicate üzerinden.", _TOS),
):
    _REGISTRY[_s.id] = _s


def get_spec(engine_id: str) -> EngineSpec:
    return _REGISTRY[engine_id]


def key_is_set(env_name: str) -> bool:
    """Bulut anahtarı ayarlı mı (Settings alanı = env adının küçük harfi)."""
    if not env_name:
        return True
    from common.config import get_settings
    return bool(str(getattr(get_settings(), env_name.lower(), "") or "").strip())


def spec_available(spec: EngineSpec) -> bool:
    """Motor şu an kullanılabilir mi: kayıtta açık VE (bulutsa) anahtarı ayarlı."""
    return spec.available and key_is_set(spec.requires_key)


def list_specs() -> list[dict]:
    out = []
    for spec in _REGISTRY.values():
        d = asdict(spec)
        d.pop("adapter", None)  # iç detay, API'ye sızmaz
        d["cloud"] = bool(spec.requires_key)
        d["key_set"] = key_is_set(spec.requires_key)
        d["available"] = spec_available(spec)
        out.append(d)
    return out


def engine_family(engine_id: str) -> str:
    """engine_id -> aile (queue routing için): 'trellis-text' -> 'trellis'."""
    return engine_id.split("-")[0]


def queue_for(engine_id: str, gpu: int) -> str:
    """Celery kuyruğu: GPU'suz motorlar (gpus=[]; bulut, clothsim) '<aile>-cpu',
    diğerleri '<aile>-gpu<n>'."""
    fam = engine_family(engine_id)
    spec = _REGISTRY.get(engine_id)
    if spec is not None and not spec.gpus:
        return f"{fam}-cpu"
    return f"{fam}-gpu{gpu}"


def resolve_engine_params(engine_id: str, preset: str, advanced: dict | None) -> dict:
    """preset taban + advanced override → motorun şemasına göre doğrulanmış param dict."""
    spec = get_spec(engine_id)
    schema = {p["key"]: p for p in spec.params}
    if preset not in spec.presets:
        raise ValueError(f"Bilinmeyen preset: {preset}")
    values = {p["key"]: p.get("default") for p in spec.params}
    values.update(spec.presets[preset])
    if advanced:
        unknown = set(advanced) - set(schema)
        if unknown:
            raise ValueError(f"Bilinmeyen parametre: {sorted(unknown)}")
        for k, v in advanced.items():
            if v is not None:
                values[k] = v
    for key, val in values.items():
        if val is None:
            continue
        p = schema[key]
        t = p["type"]
        if t == "select":
            if val not in p["options"]:
                raise ValueError(f"{key} {p['options']} içinde olmalı")
        elif t in ("int", "float"):
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise ValueError(f"{key} sayı olmalı")
            if "min" in p and val < p["min"]:
                raise ValueError(f"{key} >= {p['min']} olmalı")
            if "max" in p and val > p["max"]:
                raise ValueError(f"{key} <= {p['max']} olmalı")
        elif t == "bool":
            if not isinstance(val, bool):
                raise ValueError(f"{key} bool olmalı")
    return values
