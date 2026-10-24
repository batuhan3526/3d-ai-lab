"""UltraTex G-buffer hazırlığı ve dokuyu mesh'e geri işleme (bake).

UltraTex, nesneyi G-buffer TexVerse'in 6 sabit kamerasından görür (Blender, Z-yukarı;
1.67 birim uzaklık; odak = genişliğin 1.5625 katı): 0 ön (−Y), 1 sol (−X), 2 arka (+Y),
3 sağ (+X), 4 üst (+Z), 5 alt (−Z). Koşul = dünya normalleri, kodlama ((nX, nY, −nZ)+1)/2;
konum = glTF eksenlerinde (x, y_yukarı, z)/2 + 0.5. Karo düzeni 2×3: üst sıra 0,1,3; alt
sıra 2,4,5. Değerler yayımlanan örnek veriden (pose/*.npy, intrinsics.npy) doğrulandı.

Akış: mesh → normalize (en büyük boyut NORM_EXTENT) → 6 görünüm render (nvdiffrast) →
UltraTex girdileri → 6 görünümlü albedo → UV dokusuna geri izdüşüm (görünürlük + normal
ağırlıklı ortalama; görülmeyen dokular eski dokudan ya da en yakın görülen renkten).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

# G-buffer TexVerse kanonik kameraları (kamera→dünya, Blender kamerası −Z'ye bakar, +Y yukarı)
CAMS = np.array([
    [[1, 0, 0, 0], [0, 0, -1, -1.67], [0, 1, 0, 0]],
    [[0, 0, -1, -1.67], [-1, 0, 0, 0], [0, 1, 0, 0]],
    [[-1, 0, 0, 0], [0, 0, 1, 1.67], [0, 1, 0, 0]],
    [[0, 0, 1, 1.67], [1, 0, 0, 0], [0, 1, 0, 0]],
    [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 1.67]],
    [[-1, 0, 0, 0], [0, 1, 0, 0], [0, 0, -1, -1.67]],
], dtype=np.float64)
FOCAL = 6400.0 / 4096.0          # odak / görüntü genişliği
TILE = ((0, 1, 3), (2, 4, 5))    # karo düzeni (satır, sütun) → görünüm
NORM_EXTENT = 0.93               # örnek verideki nesnelerin en büyük boyutu
NEAR, FAR = 0.1, 10.0


def gltf_to_blender(v: np.ndarray) -> np.ndarray:
    return np.stack([v[:, 0], -v[:, 2], v[:, 1]], axis=1)


def normalize(vb: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    lo, hi = vb.min(axis=0), vb.max(axis=0)
    c = (lo + hi) / 2
    s = NORM_EXTENT / float((hi - lo).max())
    return (vb - c) * s, c, s


def _mats(view: int) -> tuple[np.ndarray, np.ndarray]:
    c2w = np.eye(4)
    c2w[:3] = CAMS[view]
    w2c = np.linalg.inv(c2w)
    f = 2 * FOCAL
    proj = np.array([[f, 0, 0, 0], [0, f, 0, 0],
                     [0, 0, -(FAR + NEAR) / (FAR - NEAR), -2 * FAR * NEAR / (FAR - NEAR)],
                     [0, 0, -1, 0]])
    return w2c, proj


def render_views(vb: np.ndarray, faces: np.ndarray, normals: np.ndarray, res: int, device: str = "cuda"):
    """Her görünüm için: alfa, kameraya dönük dünya normali, konum, kamera derinliği (H×W, satır 0 = üst)."""
    import nvdiffrast.torch as dr
    import torch
    glctx = dr.RasterizeCudaContext(device=device)
    tri = torch.as_tensor(faces, dtype=torch.int32, device=device)
    P = torch.as_tensor(np.c_[vb, np.ones(len(vb))], dtype=torch.float32, device=device)
    attrs = torch.as_tensor(np.c_[vb, normals], dtype=torch.float32, device=device)[None]
    out = []
    for i in range(6):
        w2c, proj = _mats(i)
        cam = P @ torch.as_tensor(w2c.T, dtype=torch.float32, device=device)
        clip = cam @ torch.as_tensor(proj.T, dtype=torch.float32, device=device)
        rast, _ = dr.rasterize(glctx, clip[None], tri, resolution=[res, res])
        a, _ = dr.interpolate(attrs, rast, tri)
        zc, _ = dr.interpolate(cam[None, :, 2:3].contiguous(), rast, tri)
        mask = (rast[0, ..., 3] > 0).cpu().numpy()[::-1]
        a = a[0].cpu().numpy()[::-1]
        pos, nrm = a[..., :3], a[..., 3:]
        nrm /= np.maximum(np.linalg.norm(nrm, axis=-1, keepdims=True), 1e-9)
        campos = CAMS[i][:, 3]
        flip = np.sum(nrm * (campos - pos), axis=-1) < 0      # açık yüzey: kameraya dönük taraf
        nrm[flip] *= -1
        depth = -zc[0, ..., 0].cpu().numpy()[::-1]
        out.append({"mask": mask, "pos": pos, "nrm": nrm, "depth": depth})
    return out


def write_inputs(out_dir: Path, views: list[dict], ref_rgba, res: int) -> Path:
    """UltraTex'in veri düzeninde girdi klasörü + eval json."""
    import json

    from PIL import Image
    out_dir = Path(out_dir)
    obj = out_dir / "obj_2048"
    for sub in ("albedo", "bump_normal_world", "position"):
        (obj / sub).mkdir(parents=True, exist_ok=True)
    for i, v in enumerate(views):
        a = (v["mask"] * 255).astype(np.uint8)
        n = v["nrm"] * np.array([1, 1, -1])
        nimg = np.clip((n + 1) / 2 * 255, 0, 255).astype(np.uint8)
        g = np.stack([v["pos"][..., 0], v["pos"][..., 2], -v["pos"][..., 1]], axis=-1)
        pimg = np.clip((g / 2 + 0.5) * 255, 0, 255).astype(np.uint8)
        white = np.full_like(nimg, 255)
        for sub, rgb in (("albedo", white), ("bump_normal_world", nimg), ("position", pimg)):
            Image.fromarray(np.dstack([rgb, a])).save(obj / sub / f"{i:03d}.webp", lossless=True)
    ref = ref_rgba.convert("RGBA")
    for r in range(3):
        d = obj / f"render_ref_{r}"
        d.mkdir(exist_ok=True)
        for k in range(4):
            ref.save(d / f"{k:03d}.webp", lossless=True)
    js = out_dir / "eval.json"
    js.write_text(json.dumps([{"prompt": "", "image_dir": str(obj), "id": "obj_2048", "id_only": "obj"}]))
    return js


def split_tile(tile, res: int) -> list[np.ndarray]:
    a = np.asarray(tile.convert("RGB"), dtype=np.float32) / 255.0
    h, w = a.shape[0] // 2, a.shape[1] // 3
    imgs = [None] * 6
    for r, row in enumerate(TILE):
        for c, view in enumerate(row):
            imgs[view] = a[r * h:(r + 1) * h, c * w:(c + 1) * w]
    return imgs


def bake(vb: np.ndarray, faces: np.ndarray, normals: np.ndarray, uv: np.ndarray, views: list[dict],
         imgs: list[np.ndarray], tex_res: int = 2048, fallback=None, device: str = "cuda") -> np.ndarray:
    """6 görünümlü albedo'yu UV dokusuna geri işle. Dönüş: (tex_res, tex_res, 3) uint8, satır 0 = üst."""
    import nvdiffrast.torch as dr
    import torch
    from scipy import ndimage
    glctx = dr.RasterizeCudaContext(device=device)
    tri = torch.as_tensor(faces, dtype=torch.int32, device=device)
    uvc = torch.as_tensor(np.c_[uv * 2 - 1, np.zeros(len(uv)), np.ones(len(uv))], dtype=torch.float32, device=device)
    rast, _ = dr.rasterize(glctx, uvc[None], tri, resolution=[tex_res, tex_res])
    attrs = torch.as_tensor(np.c_[vb, normals], dtype=torch.float32, device=device)[None]
    a, _ = dr.interpolate(attrs, rast, tri)
    cover = (rast[0, ..., 3] > 0).cpu().numpy()[::-1]
    a = a[0].cpu().numpy()[::-1]
    pos, nrm = a[..., :3][cover], a[..., 3:][cover]
    nrm /= np.maximum(np.linalg.norm(nrm, axis=-1, keepdims=True), 1e-9)
    acc = np.zeros((len(pos), 3))
    wsum = np.zeros(len(pos))
    for i in range(6):
        w2c, proj = _mats(i)
        cam = np.c_[pos, np.ones(len(pos))] @ w2c.T
        clip = cam @ proj.T
        ndc = clip[:, :2] / clip[:, 3:4]
        res = views[i]["depth"].shape[0]
        px = (ndc[:, 0] + 1) / 2 * res
        py = (1 - ndc[:, 1]) / 2 * res
        ix = np.clip(px.astype(int), 0, res - 1)
        iy = np.clip(py.astype(int), 0, res - 1)
        d = -cam[:, 2]
        vis = views[i]["mask"][iy, ix] & (np.abs(views[i]["depth"][iy, ix] - d) < 0.01)
        campos = CAMS[i][:, 3]
        dirv = campos - pos
        dirv /= np.linalg.norm(dirv, axis=1, keepdims=True)
        cos = np.abs(np.sum(nrm * dirv, axis=1))        # açık yüzey: iki yüz de görünür
        w = vis * cos ** 4
        img = imgs[i]
        sx = np.clip((px / res * img.shape[1]).astype(int), 0, img.shape[1] - 1)
        sy = np.clip((py / res * img.shape[0]).astype(int), 0, img.shape[0] - 1)
        acc += w[:, None] * img[sy, sx]
        wsum += w
    tex = np.zeros((tex_res, tex_res, 3))
    seen = np.zeros((tex_res, tex_res), bool)
    col = acc / np.maximum(wsum, 1e-9)[:, None]
    tex[cover] = col
    seen[cover] = wsum > 1e-6
    if fallback is not None:                                # görülmeyen: eski dokudan
        fb = np.asarray(fallback.convert("RGB").resize((tex_res, tex_res)), dtype=np.float32) / 255.0
        hole = cover & ~seen
        tex[hole] = fb[hole]
        seen |= hole
    idx = ndimage.distance_transform_edt(~seen, return_distances=False, return_indices=True)
    tex = tex[idx[0], idx[1]]                               # boşlukları/kenar taşmasını en yakın renkle doldur
    return np.clip(tex * 255, 0, 255).astype(np.uint8)
