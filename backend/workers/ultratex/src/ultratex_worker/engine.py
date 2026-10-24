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
        self._ready = True

    def unload(self) -> None:
        import torch
        torch.cuda.empty_cache()

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
        old_tex = None
        if uv is None or len(uv) != len(verts):
            import xatlas
            vmap, faces, uv = xatlas.parametrize(verts, faces)
            verts = verts[vmap]
        else:
            mat = getattr(m.visual, "material", None)
            old_tex = getattr(mat, "baseColorTexture", None) if mat is not None else None
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
                    seed=int(params.get("seed") or 42), num_workers=0,
                    save_raw_result=True, save_composite=False, overwrite=True))
            finally:
                os.chdir(cwd)
            result = next(Path(td, "out").rglob("*_result.*"))
            tile = Image.open(result)
            imgs = G.split_tile(tile, res)
            tex = G.bake(vb, faces, nb, np.asarray(uv), views, imgs,
                         tex_res=int(params.get("texture_size", 2048)), fallback=old_tex)
        out = trimesh.Trimesh(verts, faces, process=False)
        out.visual = trimesh.visual.TextureVisuals(
            uv=uv, material=trimesh.visual.material.PBRMaterial(
                baseColorTexture=Image.fromarray(tex), doubleSided=True,
                metallicFactor=0.0, roughnessFactor=0.8))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out.export(str(out_path))
        return out_path
