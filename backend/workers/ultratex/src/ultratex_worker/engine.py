"""UltraTex dokulama adaptörü (yiboz2001/UltraTex, MIT kod; SIGGRAPH Asia 2026).

Mevcut bir 3D modeli referans görsele göre yeniden dokular: 6 sabit kameradan dünya
normalleri + tek referans görsel → FLUX.2-klein 9B + UltraTex LoRA → 6 görünümlü albedo →
UV dokusuna geri işleme (gbuffer.bake). Geometri değişmez.

Bellek: 9B DiT (~18 GB) ile Qwen3-8B metin kodlayıcı (~16 GB) bir 24 GB karta sığmaz →
kodlayıcı ikinci GPU'da (yoksa CPU'da) çalışır, çıktısı DiT'in GPU'suna taşınır.
Lisans: kod MIT; FLUX.2-klein ağırlıkları BFL lisansı (HF erişimi gerekir), Qwen3-8B
Apache-2.0, FLUX.2 VAE Comfy-Org kopyası.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ENGINE_DIR = Path(os.getenv("ULTRATEX_DIR", Path(__file__).resolve().parents[5] / "engines" / "UltraTex"))


class _EncoderOn:
    """Metin kodlayıcıyı başka cihazda çalıştırıp çıktıyı hedef cihaza taşır."""

    def __init__(self, enc, out_device) -> None:
        self._enc = enc
        self._out = out_device

    def __call__(self, txt):
        return self._enc(txt).to(self._out)

    def requires_grad_(self, *a, **k):
        self._enc.requires_grad_(*a, **k)
        return self

    def eval(self):
        self._enc.eval()
        return self

    def __getattr__(self, name):
        return getattr(self._enc, name)


class _CachedEncoder:
    """Önceden hesaplanmış metin koşulu. UltraTex girdilerimizde prompt hep boş ("")."""

    def __init__(self, ctx) -> None:
        self._ctx = ctx

    def __call__(self, txt):
        if any(t for t in txt):
            raise ValueError("UltraTex worker yalnız boş prompt ile çalışır")
        return self._ctx.expand(len(txt), *self._ctx.shape[1:])

    def requires_grad_(self, *a, **k):
        return self

    def eval(self):
        return self


def _split_blocks(dit, dev, share: float = 0.5) -> int:
    """Sondaki single blokları `dev`e taşı (toplam parametrenin ~share kadarı).

    Girdiler bloğun kartına taşınır; çıktı yalnız son taşınan bloktan sonra asıl karta
    döner (blok başına gidip gelme yok). Dönüş: taşınan blok sayısı."""
    import torch
    blocks = list(dit.single_blocks)
    total = sum(p.numel() for p in dit.parameters())
    moved, size = [], 0
    for b in reversed(blocks):
        if size >= share * total:
            break
        moved.insert(0, b)
        size += sum(p.numel() for p in b.parameters())
    home = next(dit.parameters()).device

    def to(x, d):
        if torch.is_tensor(x):
            return x.to(d, non_blocking=True)
        if isinstance(x, (tuple, list)):
            return type(x)(to(v, d) for v in x)
        return x

    for i, b in enumerate(moved):
        b.to(dev)
        orig, last = b.forward_kv_extract, i == len(moved) - 1

        def fwd(*a, _orig=orig, _last=last, **k):
            with torch.cuda.device(dev):           # triton çekirdekleri geçerli kartta çalışır
                out = _orig(*to(a, dev), **{n: to(v, dev) for n, v in k.items()})
            return to(out, home) if _last else out

        b.forward_kv_extract = fwd
    torch.cuda.empty_cache()
    return len(moved)


def _patch_inference_loader() -> None:
    """Modeller yüklenince: metin koşulunu bir kez hesapla, Qwen3-8B'yi bırak, ikinci kart
    boşalınca DiT'in yarısını oraya taşı (9B DiT + 2048 token'lık görünümler tek 24 GB'a sığmaz)."""
    import gc

    import inference_flux2 as inf
    import torch
    if getattr(inf, "_split_patched", False):
        return
    orig = inf.load_inference_models

    def load(args, accelerator, checkpoint_file, trainer):
        model, ae, enc = orig(args, accelerator, checkpoint_file, trainer)
        with torch.no_grad():
            ctx = enc([""]).to(torch.bfloat16)
        inner = getattr(enc, "_enc", enc)
        del enc, inner
        gc.collect()
        torch.cuda.empty_cache()
        if torch.cuda.device_count() > 1:
            _split_blocks(model.get_base_model(), torch.device("cuda:1"))
        return model, ae, _CachedEncoder(ctx)

    inf.load_inference_models = load
    inf._split_patched = True


def _patch_text_encoder() -> None:
    import torch
    import train_flux2
    if getattr(train_flux2, "_split_patched", False):
        return
    orig_loader = train_flux2.load_text_encoder

    def get_models(model_name, device):
        dit = train_flux2.load_flow_model(model_name, device="cpu")
        ae = train_flux2.load_ae(model_name, device=device)
        other = "cuda:1" if torch.cuda.device_count() > 1 else "cpu"
        enc = orig_loader(model_name, device=other)
        return dit, ae, _EncoderOn(enc, device)

    train_flux2.get_models = get_models
    train_flux2._split_patched = True


def _free_gpus() -> None:
    """Çıkarım bitince modeller düşer ama önbellek ayırıcısı belleği tutar; worker boşta iki
    kartta da ~22 GB bırakıyordu (ikinci kart başka işlere de lazım)."""
    import gc

    import torch
    gc.collect()
    for i in range(torch.cuda.device_count()):
        with torch.cuda.device(i):
            torch.cuda.empty_cache()


class UltraTexEngine:
    def __init__(self) -> None:
        self._ready = False

    def is_loaded(self) -> bool:
        return self._ready

    def load(self) -> None:
        if self._ready:
            return
        if str(ENGINE_DIR) not in sys.path:
            sys.path.insert(0, str(ENGINE_DIR))
        base = ENGINE_DIR / "checkpoints" / "base" / "flux2"
        os.environ.setdefault("AE_MODEL_PATH", str(base / "ae.safetensors"))
        os.environ.setdefault("KLEIN_9B_BASE_MODEL_PATH", str(base / "flux-2-klein-base-9b.safetensors"))
        os.environ.setdefault("QWEN3_8B_PATH", str(base / "qwen3-8b"))
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        _patch_text_encoder()
        _patch_inference_loader()
        self._ready = True

    def unload(self) -> None:
        _free_gpus()

    def mem_report(self) -> dict:
        try:
            import torch
            if torch.cuda.is_available():
                return {"loaded": self._ready,
                        "reserved_mb": int(torch.cuda.memory_reserved() / 1024 / 1024),
                        "allocated_mb": int(torch.cuda.memory_allocated() / 1024 / 1024)}
        except Exception:  # noqa: BLE001
            pass
        return {"loaded": self._ready, "reserved_mb": 0, "allocated_mb": 0}

    def retexture(self, mesh_path: str, ref_path: str, params: dict, out_path: Path) -> Path:
        """mesh_path'i ref_path görseline göre yeniden dokula → out_path (GLB)."""
        self.load()
        import numpy as np
        import trimesh
        from PIL import Image

        from ultratex_worker import gbuffer as G
        res = int(params.get("resolution", 1024))
        m = trimesh.load(mesh_path, force="mesh")
        verts, faces = np.asarray(m.vertices, float), np.asarray(m.faces)
        uv = getattr(m.visual, "uv", None)
        if uv is None or len(uv) != len(verts):
            import xatlas
            vmap, faces, uv = xatlas.parametrize(verts, faces)
            verts = verts[vmap]
        normals = trimesh.Trimesh(verts, faces, process=False).vertex_normals
        vb, _, _ = G.normalize(G.gltf_to_blender(verts))
        nb = G.gltf_to_blender(np.asarray(normals))
        views = G.render_views(vb, faces, nb, res)
        with tempfile.TemporaryDirectory(prefix="ultratex_") as td:
            js = G.write_inputs(Path(td), views, Image.open(ref_path), res)
            import inference_flux2 as inf
            cwd = os.getcwd()
            os.chdir(ENGINE_DIR)                  # upstream göreli yolları (checkpoints/...) okur
            try:
                inf.main(inf.InferenceArgs(
                    eval_data_json=str(js), project_dir=str(Path(td) / "out"), resolution=res,
                    inference_num_steps=int(params.get("steps", 25)),
                    guidance=float(params.get("guidance", 4.0)),
                    seed=int(params.get("seed") or 42), num_workers=0, max_samples=1,
                    save_raw_result=True, save_composite=False, overwrite=True))
            finally:
                os.chdir(cwd)
                _free_gpus()                      # 9B DiT + VAE iki kartta ~22'şer GB tutmasın
            result = next(Path(td, "out").rglob("*_result.*"))
            tile = Image.open(result)
            imgs = G.split_tile(tile, res)
            tex = G.bake(vb, faces, nb, np.asarray(uv), views, imgs,
                         tex_res=int(params.get("texture_size", 2048)))
        # görülmeyen dokular en yakın görülen renkten dolar; eski doku (çoğu zaman farklı ton)
        # kumaşta koyu benek bırakıyordu
        out = trimesh.Trimesh(verts, faces, process=False)
        out.visual = trimesh.visual.TextureVisuals(
            uv=uv, material=trimesh.visual.material.PBRMaterial(
                baseColorTexture=Image.fromarray(tex), doubleSided=True,
                metallicFactor=0.0, roughnessFactor=0.8))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out.export(str(out_path))
        return out_path
