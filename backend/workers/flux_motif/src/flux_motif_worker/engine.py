"""FLUX.1-dev 2D-motif motoru: prompt -> düz beyaz zeminde tek motif (FLUX,
4-bit) -> BiRefNet ile matte -> şeffaf RGBA PNG. Decal olarak yerleştirilir.

InTeX/SD1.5 bölge-retexture'ın renk-sadakatsizlik + boşluk/kesik sorunlarının
yerine: decal motifin GERÇEK piksellerini gösterir (1:1 renk, dikiş/leke yok).

DEFAULT_GPU üzerinde (worker CUDA_VISIBLE_DEVICES ile tek karta sabitlenir).
12B transformer 4-bit (bitsandbytes) + cpu-offload ile 24GB karta sığar.
Modeller lazy yüklenir ve resident kalır (tekrar üretim hızlı); release() ile boşaltılır.
"""
from __future__ import annotations

import os
from pathlib import Path

from common.config import engines_dir

CKPT = "black-forest-labs/FLUX.1-dev"
_NEG = "shadow, gradient background, multiple objects, blurry, low quality, watermark, text, frame"

# Real-ESRGAN x4 ağırlığı (BSD-3, xinntao/Real-ESRGAN). spandrel bunu mimarisiz
# yükler. Yol .env ile override edilebilir; yoksa/spandrel yoksa EsrganMissing.
ESRGAN_WEIGHT = os.getenv(
    "ESRGAN_WEIGHT", str(engines_dir() / "models/esrgan/RealESRGAN_x4plus.pth")
)


class EsrganMissing(RuntimeError):
    """spandrel kurulu değil ya da ESRGAN ağırlığı diskte yok → doku upscale yapılamaz.

    Worker bunu yakalayıp job'ı FAILURE('esrgan-missing') yapar (kullanıcıya net
    'model indir' mesajı). raise/kesinti değil, best-effort düşüş."""


def _wrap_prompt(prompt: str) -> str:
    """Motifi tek-nesne + düz zemin kalıbına sok. "sticker style" KULLANMA — die-cut
    beyaz kenar bırakıyor (decal/bake'de kumaşta sırıtıyor). Temiz illustration."""
    return (
        f"{prompt}, single centered subject, isolated on a plain solid white "
        f"background, flat vector illustration, bold clean shapes, vivid accurate "
        f"colors, high detail, crisp edges, no drop shadow, no text, no white outline, no border"
    )


class FluxMotifEngine:
    def __init__(self) -> None:
        self._pipe = None
        self._img2img = None
        self._birefnet = None
        self._esrgan = None

    # --- model yükleme (lazy) ---
    def _load_flux(self):
        if self._pipe is not None:
            return self._pipe
        import torch
        from diffusers import BitsAndBytesConfig as DBnb
        from diffusers import FluxPipeline, FluxTransformer2DModel
        from transformers import BitsAndBytesConfig as TBnb
        from transformers import T5EncoderModel

        t5 = T5EncoderModel.from_pretrained(
            CKPT, subfolder="text_encoder_2",
            quantization_config=TBnb(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16),
            torch_dtype=torch.bfloat16,
        )
        tr = FluxTransformer2DModel.from_pretrained(
            CKPT, subfolder="transformer",
            quantization_config=DBnb(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16),
            torch_dtype=torch.bfloat16,
        )
        pipe = FluxPipeline.from_pretrained(
            CKPT, transformer=tr, text_encoder_2=t5, torch_dtype=torch.bfloat16,
        )
        pipe.enable_model_cpu_offload()
        self._pipe = pipe
        return pipe

    def _load_birefnet(self):
        if self._birefnet is not None:
            return self._birefnet
        from transformers import AutoModelForImageSegmentation
        net = AutoModelForImageSegmentation.from_pretrained(
            "ZhengPeng7/BiRefNet", trust_remote_code=True
        ).to("cuda").eval()
        self._birefnet = net
        return net

    # --- üretim ---
    def generate(self, prompt: str, out_path: str, *, seed: int = 42,
                 steps: int = 30, guidance: float = 3.5, size: int = 1024) -> str:
        """prompt -> şeffaf RGBA PNG out_path. Çıktı yolunu döndürür."""
        import torch

        pipe = self._load_flux()
        img = pipe(
            _wrap_prompt(prompt),
            height=size, width=size,
            guidance_scale=guidance, num_inference_steps=steps,
            generator=torch.Generator("cpu").manual_seed(seed),
        ).images[0]
        cutout = self._matte(img)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        cutout.save(out_path)
        return out_path

    def _load_img2img(self):
        """FLUX img2img — base pipeline'ın bileşenlerini PAYLAŞIR (ekstra VRAM/indirme
        yok). from_pipe offload ayarını da taşır."""
        if self._img2img is not None:
            return self._img2img
        from diffusers import FluxImg2ImgPipeline
        base = self._load_flux()
        self._img2img = FluxImg2ImgPipeline.from_pipe(base)
        return self._img2img

    def motif_from_style(self, style_image_path: str, crop, out_path: str, *,
                         ai: bool = False, prompt: str = "", seed: int = 42,
                         steps: int = 30, guidance: float = 3.5) -> str:
        """Stil görselinden kırpılan bölgeyi motif PNG'sine çevir. crop = normalize
        [x0,y0,x1,y1]. ai=True ise FLUX img2img ile temizle/uyarla."""
        from PIL import Image
        img = Image.open(style_image_path).convert("RGB")
        W, H = img.size
        x0, y0, x1, y1 = crop
        box = (max(0, int(x0 * W)), max(0, int(y0 * H)),
               min(W, int(x1 * W)), min(H, int(y1 * H)))
        if box[2] - box[0] < 4 or box[3] - box[1] < 4:
            raise RuntimeError("kırpma alanı çok küçük")
        region = img.crop(box)
        if ai:
            import torch
            pipe = self._load_img2img()
            init = region.resize((1024, 1024), Image.BILINEAR)
            wrapped = (
                f"{prompt or 'decorative ornament in the same style'}, single centered "
                f"subject, isolated on a plain solid white background, flat vector "
                f"illustration, bold clean shapes, vivid accurate colors, crisp edges, "
                f"no drop shadow, no text, no border"
            )
            region = pipe(
                prompt=wrapped, image=init, strength=0.6,
                guidance_scale=guidance, num_inference_steps=steps,
                generator=torch.Generator("cpu").manual_seed(seed),
            ).images[0]
        cutout = self._matte(region)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        cutout.save(out_path)
        return out_path

    def matte_file(self, image_path: str, out_path: str) -> str:
        """Bir foto dosyasının arka planını BiRefNet ile kaldır → şeffaf RGBA PNG
        out_path'e yaz. FLUX modeli yüklenmez (yalnız BiRefNet); ön-kırpma task'ı
        (image.matte) bunu kullanır. Çıktı yolunu döndürür."""
        from PIL import Image
        img = Image.open(image_path).convert("RGB")
        cutout = self._matte(img)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        cutout.save(out_path)
        return out_path

    # --- Real-ESRGAN doku upscale (spandrel) ---
    def _load_esrgan(self):
        """ESRGAN ağırlığını spandrel ile CUDA'ya yükle (lazy, resident kalır).
        spandrel yoksa ya da ağırlık dosyası diskte değilse EsrganMissing fırlat."""
        if self._esrgan is not None:
            return self._esrgan
        try:
            from spandrel import ModelLoader
        except Exception as e:  # noqa: BLE001 — paket yok → net domain hatası
            raise EsrganMissing("spandrel-missing") from e
        if not os.path.exists(ESRGAN_WEIGHT):
            raise EsrganMissing(f"weight-missing: {ESRGAN_WEIGHT}")
        model = ModelLoader().load_from_file(ESRGAN_WEIGHT)
        model = model.to("cuda").eval()
        self._esrgan = model
        return model

    def upscale_image(self, img, *, scale: int = 2, tile: int = 1024):
        """PIL görselini Real-ESRGAN ile netleştir → hedef `scale` katına ölçekli PIL.

        ESRGAN ağırlığı native x4'tür; çıktı hedef scale'e (2/3/4) LANCZOS ile
        ayarlanır. Kenarı `tile`px'i aşan görsellerde bindirmeli döşeli çıkarım
        (VRAM sınırı). Model/ağırlık yoksa EsrganMissing (worker yakalar)."""
        model = self._load_esrgan()  # EsrganMissing önce burada; torch'a değinmeden
        import numpy as np
        import torch

        rgb = img.convert("RGB")
        arr = np.asarray(rgb, dtype=np.float32) / 255.0
        t = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).to("cuda")
        with torch.no_grad():
            if max(rgb.size) > tile:
                out_t = self._tiled_infer(model, t, tile)
            else:
                out_t = model(t)
        out = out_t.clamp(0, 1).squeeze(0).permute(1, 2, 0).cpu().numpy()
        from PIL import Image
        up = Image.fromarray((out * 255.0 + 0.5).astype("uint8"), mode="RGB")
        target = (rgb.width * int(scale), rgb.height * int(scale))
        if up.size != target:
            up = up.resize(target, Image.LANCZOS)
        return up

    def _tiled_infer(self, model, t, tile: int):
        """VRAM'i sınırlamak için bindirmeli döşeli ESRGAN çıkarımı. Her giriş
        döşemesine `pad`px bağlam eklenir, çıktı ölçekli olarak kırpılıp yerleştirilir."""
        import torch
        s = int(getattr(model, "scale", 4))
        _, _, H, W = t.shape
        pad = 32
        out = torch.zeros((1, 3, H * s, W * s), device=t.device, dtype=t.dtype)
        for y in range(0, H, tile):
            for x in range(0, W, tile):
                y0, x0 = max(0, y - pad), max(0, x - pad)
                y1, x1 = min(H, y + tile + pad), min(W, x + tile + pad)
                up = model(t[:, :, y0:y1, x0:x1])
                top, left = (y - y0) * s, (x - x0) * s
                h, w = min(tile, H - y) * s, min(tile, W - x) * s
                out[:, :, y * s:y * s + h, x * s:x * s + w] = up[:, :, top:top + h, left:left + w]
        return out

    def _matte(self, img):
        import torch
        from torchvision import transforms
        net = self._load_birefnet()
        tf = transforms.Compose([
            transforms.Resize((1024, 1024)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])
        x = tf(img.convert("RGB")).unsqueeze(0).to("cuda").to(torch.float32)
        with torch.no_grad():
            pred = net(x)[-1].sigmoid().cpu()[0].squeeze()
        mask = transforms.ToPILImage()(pred).resize(img.size)
        out = img.convert("RGBA")
        out.putalpha(mask)
        return out

    # --- durum/serbest bırakma (intex ile parite) ---
    def mem_report(self) -> dict:
        try:
            import torch
            return {
                "loaded": self._pipe is not None,
                "reserved_mb": int(torch.cuda.memory_reserved() / 1e6),
                "allocated_mb": int(torch.cuda.memory_allocated() / 1e6),
            }
        except Exception:  # noqa: BLE001
            return {"loaded": False, "reserved_mb": 0, "allocated_mb": 0}

    def release(self) -> None:
        self._pipe = None
        self._img2img = None
        self._birefnet = None
        self._esrgan = None
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass
