"""Projeksiyon-bake: FLUX motif PNG'sini mesh'in UV TEXTURE'una 3B projeksiyonla
pişir (decal gibi üstte değil, dokunun içine). Sonuç: motif kalitesinde gerçek
doku — dışa aktarımda kalıcı, kumaşa gömülü. InTeX/SD1.5 region-retexture'ın
yerine (renk-sadık, boşluksuz).

Frontend'in decal için hesapladığı poz (merkez C, normal N, ölçek s) ile birebir
aynı projeksiyon kullanılır → ekranda gördüğün decal = pişen doku (WYSIWYG).
"""
from __future__ import annotations

import numpy as np


def _rot_z_to(n: np.ndarray) -> np.ndarray:
    """Z=(0,0,1)'i n'e döndüren matris (drei setFromUnitVectors(Z,n) ile aynı).
    Sütunlar = decal yerel eksenleri (T,B,N) dünya uzayında."""
    z = np.array([0.0, 0.0, 1.0])
    n = n / (np.linalg.norm(n) + 1e-12)
    d = float(np.dot(z, n))
    if d > 0.999999:
        return np.eye(3)
    if d < -0.999999:
        # 180°, X ekseni etrafında
        return np.array([[1, 0, 0], [0, -1, 0], [0, 0, -1.0]])
    v = np.cross(z, n)
    s = np.linalg.norm(v)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * ((1 - d) / (s * s))


def _decode_channel(data_url: str, tex_size: int):
    """PBR kanal dataURL'i (UV-uzayı grayscale PNG) → (value[S,S] 0..1, mask[S,S] bool).
    Kanal canvas'ı useRegionMask konvansiyonu satır0=v0; bake albedo texture'ı
    satır0=(1-v) kullanır → hizalamak için dikey çevrilir. Gri değer=kanal değeri,
    alpha>0=boyalı texel."""
    import base64
    import io

    import numpy as np
    from PIL import Image

    _, _, b64 = (data_url or "").partition(",")
    raw = base64.b64decode(b64)
    img = Image.open(io.BytesIO(raw)).convert("RGBA")
    img = img.resize((tex_size, tex_size), Image.BILINEAR).transpose(Image.FLIP_TOP_BOTTOM)
    arr = np.asarray(img, dtype=np.float32) / 255.0
    return arr[..., 0], (arr[..., 3] > 0.02)


def _pack_metallic_roughness(channels: dict, tex_size: int):
    """{roughness?, metallic?} dataURL'lerini glTF metallicRoughnessTexture'a paketle:
    R=255 (1), G=roughness, B=metallic. Boyanmayan texel varsayılanı roughness=1 (tam
    mat), metallic=0. Hiç kanal yoksa None (albedo-only davranış korunur)."""
    import numpy as np
    from PIL import Image

    rgh = (channels or {}).get("roughness")
    mtl = (channels or {}).get("metallic")
    if not rgh and not mtl:
        return None
    rough = np.full((tex_size, tex_size), 1.0, dtype=np.float32)   # varsayılan tam mat
    metal = np.zeros((tex_size, tex_size), dtype=np.float32)       # varsayılan metalik yok
    if rgh:
        v, mk = _decode_channel(rgh, tex_size)
        rough[mk] = v[mk]
    if mtl:
        v, mk = _decode_channel(mtl, tex_size)
        metal[mk] = v[mk]
    mr = np.stack([np.ones_like(rough), rough, metal], axis=-1) * 255.0
    return Image.fromarray(np.clip(mr, 0, 255).astype(np.uint8))


def bake_motif_into_texture(mesh_path: str, motif_path: str, out_path: str,
                            center, normal, scale: float,
                            tex_size: int = 2048,
                            base_color=(228, 228, 230),
                            channels: dict | None = None) -> str:
    """mesh + motif PNG + decal pozu → motif texture'a pişmiş yeni mesh.glb.
    channels (opsiyonel BATCH-F): {roughness?, metallic?} UV dataURL'leri →
    metallicRoughnessTexture. Yoksa yalnız albedo (bugünkü davranış aynen korunur)."""
    import trimesh
    from PIL import Image

    m = trimesh.load(mesh_path, force="mesh")
    V = np.asarray(m.vertices, dtype=np.float64)
    F = np.asarray(m.faces, dtype=np.int64)
    uv_attr = getattr(m.visual, "uv", None)
    if uv_attr is None or len(uv_attr) != len(V):
        raise RuntimeError("mesh'te UV yok — bake edilemez")
    UV = np.asarray(uv_attr, dtype=np.float64)

    # taban texture: mevcut gerçek texture varsa onu büyüt, yoksa düz renk
    existing = getattr(getattr(m.visual, "material", None), "baseColorTexture", None)
    if existing is not None and min(existing.size) >= 64:
        base = existing.convert("RGB").resize((tex_size, tex_size), Image.BILINEAR)
        tex = np.asarray(base, dtype=np.float32).copy()
    else:
        tex = np.empty((tex_size, tex_size, 3), dtype=np.float32)
        tex[:] = np.array(base_color, dtype=np.float32)

    motif = np.asarray(Image.open(motif_path).convert("RGBA"), dtype=np.float32) / 255.0
    mh, mw = motif.shape[:2]

    C = np.asarray(center, dtype=np.float64)
    N = np.asarray(normal, dtype=np.float64)
    N = N / (np.linalg.norm(N) + 1e-12)
    R = _rot_z_to(N)
    T, B = R[:, 0], R[:, 1]
    half = scale / 2.0

    fn = np.asarray(m.face_normals, dtype=np.float64)
    S = tex_size

    # sadece decal kutusuna yakın + projektöre bakan üçgenler
    tri_v = V[F]                                   # (nf,3,3)
    near = (np.linalg.norm(tri_v - C, axis=2) <= (half * 1.8)).any(axis=1)
    facing = (fn @ N) > 0.15
    cand = np.where(near & facing)[0]

    painted = 0
    for fi in cand:
        idx = F[fi]
        p3 = V[idx]                                # (3,3) dünya
        uvf = UV[idx]
        tx = uvf[:, 0] * S
        ty = (1.0 - uvf[:, 1]) * S                 # texture satır 0 = üst
        minx = max(int(np.floor(tx.min())), 0); maxx = min(int(np.ceil(tx.max())), S - 1)
        miny = max(int(np.floor(ty.min())), 0); maxy = min(int(np.ceil(ty.max())), S - 1)
        if maxx < minx or maxy < miny:
            continue
        xs = np.arange(minx, maxx + 1) + 0.5
        ys = np.arange(miny, maxy + 1) + 0.5
        gx, gy = np.meshgrid(xs, ys)               # (h,w)
        # barisentrik (texel uzayında)
        x1, y1 = tx[0], ty[0]; x2, y2 = tx[1], ty[1]; x3, y3 = tx[2], ty[2]
        det = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
        if abs(det) < 1e-9:
            continue
        w0 = ((y2 - y3) * (gx - x3) + (x3 - x2) * (gy - y3)) / det
        w1 = ((y3 - y1) * (gx - x3) + (x1 - x3) * (gy - y3)) / det
        w2 = 1.0 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue
        # 3B pozisyon
        P = (w0[..., None] * p3[0] + w1[..., None] * p3[1] + w2[..., None] * p3[2])  # (h,w,3)
        d = P - C
        lx = d @ T; ly = d @ B; lz = d @ N
        box = inside & (np.abs(lx) <= half) & (np.abs(ly) <= half) & (np.abs(lz) <= half)
        if not box.any():
            continue
        mu = (lx / half + 1) / 2
        mv = (ly / half + 1) / 2
        mxs = np.clip((mu * (mw - 1)).astype(np.int32), 0, mw - 1)
        mys = np.clip(((1 - mv) * (mh - 1)).astype(np.int32), 0, mh - 1)
        sampled = motif[mys, mxs]                  # (h,w,4)
        al = sampled[..., 3] * box
        paint = al > 0.02
        if not paint.any():
            continue
        py, px = np.where(paint)
        a = al[py, px][:, None]
        rgb = sampled[py, px, :3] * 255.0
        gyi = (miny + py); gxi = (minx + px)
        tex[gyi, gxi] = (1 - a) * tex[gyi, gxi] + a * rgb
        painted += int(paint.sum())

    new_tex = Image.fromarray(np.clip(tex, 0, 255).astype(np.uint8))
    mat = trimesh.visual.material.PBRMaterial(baseColorTexture=new_tex)
    # BATCH-F: PBR kanalları verildiyse metallicRoughnessTexture paketle (yoksa albedo-only).
    mr_tex = _pack_metallic_roughness(channels, tex_size) if channels else None
    if mr_tex is not None:
        mat.metallicRoughnessTexture = mr_tex
        mat.roughnessFactor = 1.0   # texture değerleri doğrudan kullanılsın
        mat.metallicFactor = 1.0
    m.visual = trimesh.visual.TextureVisuals(uv=UV, material=mat)
    m.export(out_path)
    return f"painted={painted} texels, faces={len(cand)}, pbr={mr_tex is not None}"
