"""InTeX doku yeniden-boyama motoru (mesh + prompt → yeniden-dokulu mesh).

InTeX main.py'yi subprocess olarak çağırır (temiz importlanabilir pipeline değil).
Model her çağrıda yüklenir (v1 — yavaş ~birkaç dk; ileride pipeline import'una
geçilebilir). UV'siz girdiler (Hunyuan-shape, TripoSR vertex-color) otomatik olarak
decimate + xatlas UV-unwrap'ten geçirilir (_ensure_uv) — her motor çıktısı retexture'lanabilir.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from common.config import engines_dir

# Override the InTeX checkout root with INTEX_DIR (portability).
_INTEX_DIR = os.environ.get(
    "INTEX_DIR", str(engines_dir() / "InTeX")
)

# UV-unwrap fallback'inde xatlas süresi patlamasın diye decimation hedefi.
_MAX_FACES_FOR_UNWRAP = 200_000


def _ensure_uv(mesh_path: str, work_dir: Path) -> str:
    """InTeX UV'li mesh ister. UV'siz girdiler (Hunyuan-shape, TripoSR vertex-color)
    için: gerekirse decimate + xatlas ile UV-unwrap edip geçici GLB döndür.
    UV'li mesh'e DOKUNMA (bölge modunda mevcut doku/maske eşleşmesi korunmalı)."""
    import numpy as np
    import trimesh

    m = trimesh.load(mesh_path, force="mesh")
    uv = getattr(m.visual, "uv", None)
    if uv is not None and len(uv) == len(m.vertices):
        return mesh_path

    vertices, faces = m.vertices, m.faces
    if len(faces) > _MAX_FACES_FOR_UNWRAP:
        import fast_simplification
        vertices, faces = fast_simplification.simplify(
            np.asarray(vertices, dtype=np.float32),
            np.asarray(faces, dtype=np.int64),
            target_count=_MAX_FACES_FOR_UNWRAP)

    import xatlas
    vmapping, indices, uvs = xatlas.parametrize(vertices, faces)
    out = trimesh.Trimesh(vertices=vertices[vmapping], faces=indices, process=False)
    # InTeX mesh.py load_trimesh, material'den baseColorTexture OKUMAYI bekler;
    # dokusuz materyalde texture[..., :3] scalar-index hatası verir → nötr gri doku göm.
    from PIL import Image
    base_tex = Image.new("RGB", (512, 512), (180, 180, 180))
    out.visual = trimesh.visual.TextureVisuals(
        uv=uvs, material=trimesh.visual.material.PBRMaterial(baseColorTexture=base_tex))
    tmp = work_dir / "uv_unwrapped_input.glb"
    out.export(tmp)
    return str(tmp)


class IntexEditEngine:
    def is_loaded(self) -> bool:
        return False  # subprocess; kalıcı model tutmaz

    def load(self) -> None:
        pass

    def unload(self) -> None:
        pass

    def mem_report(self) -> dict:
        try:
            import torch
            if torch.cuda.is_available():
                return {"loaded": False,
                        "reserved_mb": int(torch.cuda.memory_reserved() / 1024 / 1024),
                        "allocated_mb": int(torch.cuda.memory_allocated() / 1024 / 1024)}
        except Exception:  # noqa: BLE001
            pass
        return {"loaded": False, "reserved_mb": 0, "allocated_mb": 0}

    @staticmethod
    def _fabric_color_name(rgb) -> str:
        """Median RGB'yi SD-1.5'in anlayacağı kaba renk adına çevir."""
        import colorsys
        r, g, b = [x / 255.0 for x in rgb]
        mx, mn = max(r, g, b), min(r, g, b)
        v, s = mx, 0.0 if mx == 0 else (mx - mn) / mx
        if s < 0.12:
            if v > 0.85: return "white"
            if v > 0.55: return "light gray"
            if v > 0.25: return "gray"
            return "black"
        h = colorsys.rgb_to_hsv(r, g, b)[0] * 360
        for name, lo, hi in (("red", 345, 361), ("red", 0, 15), ("orange", 15, 45),
                             ("yellow", 45, 70), ("green", 70, 170), ("cyan", 170, 200),
                             ("blue", 200, 255), ("purple", 255, 290), ("pink", 290, 345)):
            if lo <= h < hi:
                return name
        return "gray"

    @classmethod
    def _prepare_region_mask(cls, mask_path: str, mesh_path: str,
                             work_dir: Path) -> tuple[str, str | None]:
        """Maske içi kıl-çatlakları kapat — ama MUHAFAZAKÂR (maks 2px büyüme):
        - closing (k=9) çatlağı bulur, ancak eklenen texel boyaya ≤2px ise alınır;
        - chart kapsama haritası dışındaki (gutter) texel'ler boyaya ≤2px ise
          alınır (kenar fringe'i — gutter 3B'de hiçbir yere maplenmez).
        Önceki 6px'lik serbest gutter genişletmesi BAŞKA chart'ların kenarına
        yapışan gutter texel'lerini de boyuyordu → bilinear örnekleme o
        chart'ların 3B konumuna renk sızdırdı ('lekeler geri geldi'
        raporu). 2px + boya-komşuluğu şartı bunu keser.
        Ayrıca bölge çevresindeki kumaş renginin adını döndürür (prompt'a
        'plain <renk> fabric background' eklemek için)."""
        import cv2
        import numpy as np
        m = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
        if m is None:
            return mask_path, None
        S = m.shape[0]
        mb = (m > 127).astype(np.uint8)
        orig = int(mb.sum())
        k3 = np.ones((3, 3), np.uint8)
        near_paint = cv2.dilate(mb, k3, iterations=2)
        k = max(3, int(round(S * 0.008)) | 1)
        closed = cv2.morphologyEx(
            mb, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        add = (closed > 0) & (mb == 0) & (near_paint > 0)
        bg_name = None
        try:
            import trimesh
            mesh = trimesh.load(mesh_path, force="mesh")
            uv = getattr(mesh.visual, "uv", None)
            if uv is not None and len(uv):
                polys = np.clip(np.asarray(uv)[mesh.faces] * S, 0, S - 1).astype(np.int32)
                cov = np.zeros((S, S), np.uint8)
                cv2.fillPoly(cov, polys, 1)
                # BAŞKA bir chart'ın dibindeki gutter texel'ine dokunma — bilinear
                # örnekleme o chart'ın 3B konumuna sızdırır (leke kaynağıydı)
                near_other = cv2.dilate(((cov > 0) & (mb == 0)).astype(np.uint8), k3, iterations=1)
                add |= (near_paint > 0) & (cov == 0) & (mb == 0) & (near_other == 0)
            tex = getattr(getattr(mesh.visual, "material", None), "baseColorTexture", None)
            if tex is not None:
                ts = np.asarray(tex.convert("RGB").resize((S, S)))
                ring = (cv2.dilate(mb, k3, iterations=4) > 0) & (near_paint == 0)
                if ring.sum() > 50:
                    bg_name = cls._fabric_color_name(np.median(ts[ring], axis=0))
        except Exception as e:  # noqa: BLE001
            print(f"[F5] kapsama/renk analizi atlandı: {e}", flush=True)
        mb = np.maximum(mb, add.astype(np.uint8))
        out = work_dir / "mask_prepared.png"
        cv2.imwrite(str(out), (mb > 0).astype(np.uint8) * 255)
        print(f"[F5] maske hazırlık: +{int((mb > 0).sum()) - orig} px (≤2px çatlak/fringe)"
              f" | kumaş rengi: {bg_name}", flush=True)
        return str(out), bg_name

    def retexture(self, mesh_path: str, prompt: str, out_path: Path,
                  mask_path: str | None = None) -> Path:
        """mask_path verilirse (F5 v2): mevcut dokuyu koru, SADECE maskeli UV bölgesini
        yeniden boya (InTeX region_mask). Yoksa (v1): tüm mesh'i yeniden dokula."""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        mesh_path = _ensure_uv(mesh_path, out_path.parent)
        if mask_path:
            # NOT: prompt'a "plain background" eki DENENDİ ve geri alındı —
            # SD kompozisyonu soluklaştırıyordu (eksiz bold sonuç tercih edildi).
            # Öğe/zemin ayrımı compose'da GrabCut+baskınlık ile; dağınıklık
            # üretimde negatif prompt'la engellenir. "single centered" eki
            # kompozisyonu tek öğeye toplar.
            mask_path, _bg = self._prepare_region_mask(mask_path, mesh_path, out_path.parent)
        env = dict(os.environ)
        env["CUDA_HOME"] = "/usr"
        cmd = [sys.executable, "main.py", "--config", "configs/base.yaml",
               f"mesh={mesh_path}", f"prompt={prompt}", f"save_path={out_path}"]
        if mask_path:
            # bölge modu: korunan dokunun kalitesini koru (Hunyuan çıktıları 2048)
            cmd.append(f"region_mask={mask_path}")
            cmd.append("texture_size=2048")
            # NOT: "single centered design" + agresif nega_prompt DENENDİ, işe
            # yaramadı (statik yoğunlaştı). Asıl suçlu bölgeye-zoom'du (geri
            # alındı); üretim eski-iyi 1b09da86 ile aynı koşullarda yapılır.
        proc = subprocess.run(cmd, cwd=_INTEX_DIR, env=env, capture_output=True,
                              text=True, timeout=1200)
        # Alt-süreç logu HER ZAMAN dosyaya yazılır — başarılı görünen ama içerik
        # olarak bozuk işlerde ([F5] satırları, çeviri, maske px) tek kanıt bu.
        log_path = out_path.parent / "intex_run.log"
        try:
            log_path.write_text(
                "CMD: " + " ".join(cmd) + "\n\n=== STDOUT ===\n" + (proc.stdout or "")
                + "\n=== STDERR ===\n" + (proc.stderr or ""))
        except OSError:
            pass
        if not out_path.exists():
            tail = (proc.stderr or proc.stdout or "")[-600:]
            raise RuntimeError(f"InTeX çıktı üretmedi (rc={proc.returncode}): {tail}")
        if mask_path:
            self._compose_region(mesh_path, out_path, mask_path)
        return out_path

    @staticmethod
    def _compose_region(src_mesh_path: str, out_path: Path, mask_path: str) -> None:
        """Maske DIŞINI kaynak dokunun orijinal pikselleriyle birebir geri yükle.
        InTeX yükleyicisi dokuyu gamma-kaymış okuyor (örn. 180 gri → 204 yazar) ve
        deblur/sr tüm dokuyu değiştiriyor — 'sadece bölgeyi boya' garantisi ancak
        InTeX dışında, dosya-pikseli seviyesinde kompoze ederek verilebilir.
        Kaynak (view) mesh ile çıktı aynı UV düzenini paylaşır; maske de aynı
        konvansiyonla boyandığı için üçü doğrudan görüntü uzayında birleşir."""
        import numpy as np
        import trimesh
        from PIL import Image

        src = trimesh.load(src_mesh_path, force="mesh")
        src_tex = getattr(getattr(src.visual, "material", None), "baseColorTexture", None)
        if src_tex is None:
            print("[F5] compose atlandı: kaynakta doku yok", flush=True)
            return
        out_mesh = trimesh.load(str(out_path), force="mesh")
        out_tex = getattr(getattr(out_mesh.visual, "material", None), "baseColorTexture", None)
        if out_tex is None:
            print("[F5] compose atlandı: çıktıda doku yok", flush=True)
            return
        import cv2
        size = out_tex.size
        out_a = np.asarray(out_tex.convert("RGB")).astype(np.float32)
        src_a = np.asarray(src_tex.convert("RGB").resize(size, Image.BILINEAR)).astype(np.float32)
        m = np.asarray(Image.open(mask_path).convert("L").resize(size, Image.NEAREST))
        inside = m > 127
        # MOTİF AYIKLAMA: bölge içinde yalnız belirgin öğe kalır, gerisi orijinal
        # kumaşa döner ("öğe harici işaretli alan orijinali korusun" kuralı).
        # Sabit renk eşiği YETMEZ: sis kahverengi/koyu da olabiliyor (öğeyi kırpıp
        # sisi tutuyordu) → GrabCut (renk modeli + graph-cut) öğeyi bütün olarak
        # ayırır; tohumlar orijinale-uzaklıktan gelir.
        diff = np.abs(out_a - src_a).max(axis=-1)
        sure_fg = inside & (diff >= 90.0)
        if int(sure_fg.sum()) >= 50:
            ys, xs = np.where(inside)
            y0, y1 = int(ys.min()), int(ys.max()) + 1
            x0, x1 = int(xs.min()), int(xs.max()) + 1
            img_c = out_a[y0:y1, x0:x1].astype(np.uint8)
            diff_c = diff[y0:y1, x0:x1]
            in_c = inside[y0:y1, x0:x1]
            fg_c = sure_fg[y0:y1, x0:x1]
            scale = 1200.0 / max(img_c.shape[:2])
            if scale < 1.0:  # bölge UV'ye dağınıksa bbox büyür — segmentasyonu küçült
                sz = (int(img_c.shape[1] * scale), int(img_c.shape[0] * scale))
                img_s = cv2.resize(img_c, sz, interpolation=cv2.INTER_AREA)
                diff_s = cv2.resize(diff_c, sz, interpolation=cv2.INTER_NEAREST)
                in_s = cv2.resize(in_c.astype(np.uint8), sz, interpolation=cv2.INTER_NEAREST) > 0
                fg_s = cv2.resize(fg_c.astype(np.uint8), sz, interpolation=cv2.INTER_NEAREST) > 0
            else:
                img_s, diff_s, in_s, fg_s = img_c, diff_c, in_c, fg_c
            gc = np.full(diff_s.shape, cv2.GC_BGD, np.uint8)
            gc[in_s & (diff_s < 40.0)] = cv2.GC_PR_BGD
            gc[in_s & (diff_s >= 40.0)] = cv2.GC_PR_FGD
            gc[fg_s] = cv2.GC_FGD
            bgd = np.zeros((1, 65), np.float64)
            fgd = np.zeros((1, 65), np.float64)
            cv2.grabCut(img_s, gc, None, bgd, fgd, 2, cv2.GC_INIT_WITH_MASK)
            motif_s = ((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD))
            if scale < 1.0:
                motif_s = cv2.resize(motif_s.astype(np.uint8),
                                     (img_c.shape[1], img_c.shape[0]),
                                     interpolation=cv2.INTER_NEAREST) > 0
            motif = np.zeros_like(inside)
            motif[y0:y1, x0:x1] = motif_s
            motif &= inside
        else:
            motif = inside & (diff >= 55.0)  # öğe yok denecek kadar soluksa eşik yeter
        lowq_p = out_path.parent / "region_lowq.png"
        if lowq_p.exists():
            lq = np.asarray(Image.open(lowq_p).convert("L").resize(size, Image.NEAREST)) > 127
            motif &= ~lq
        k3 = np.ones((3, 3), np.uint8)
        # (1) İnce köprüleri kes — SD'nin dağınık çevre süslemesi öğeye yapışmasın
        motif_u = cv2.morphologyEx(motif.astype(np.uint8), cv2.MORPH_OPEN, k3)
        # (2) BASKINLIK FİLTRESİ: öğe = en büyük bütünleşik parça (+ onun en az
        # %30'u kadar olan parçalar — çok parçalı tasarımlar için). SD'nin gül
        # çevresine serptiği yüksek-kontrast statik kırıntılar, renkten bağımsız
        # olarak küçük kaldıkları için elenir; "işaretli ama öğe olmayan alan
        # orijinal kıyafet kalır" garantisinin kalbi budur.
        n_c, lab, stats, _ = cv2.connectedComponentsWithStats(motif_u)
        if n_c > 1:
            areas = stats[1:, 4]
            largest = int(areas.max())
            thresh = max(int(largest * 0.30), 64)
            kept, dropped = 0, 0
            for i in range(1, n_c):
                if stats[i, 4] < thresh:
                    motif_u[lab == i] = 0
                    dropped += 1
                else:
                    kept += 1
            print(f"[F5] baskınlık filtresi: en büyük {largest}px; {kept} parça "
                  f"tutuldu, {dropped} kırıntı (<{thresh}px) orijinale döndü", flush=True)
        motif = motif_u.astype(bool)
        # (3) Öğe İÇİ delikleri doldur: öğenin açık tonlu iç detayları kumaşa
        # dönmesin. Delik = bölge-içi boyasız bileşen, bölge sınırına değmiyor.
        inv = (inside & ~motif).astype(np.uint8)
        n_i, lab_i, st_i, _ = cv2.connectedComponentsWithStats(inv)
        H, W = inv.shape
        inside_total = int(inside.sum())
        for i in range(1, n_i):
            x, y, w, h, area = st_i[i]
            if area > inside_total * 0.5:
                continue  # bölgenin ana boş gövdesi, delik değil
            x0, y0 = max(0, x - 1), max(0, y - 1)
            x1, y1 = min(W, x + w + 1), min(H, y + h + 1)
            comp = (lab_i[y0:y1, x0:x1] == i).astype(np.uint8)
            grown = cv2.dilate(comp, k3)
            ring = grown & (~inside[y0:y1, x0:x1]).astype(np.uint8)
            touches_motif = (grown & motif[y0:y1, x0:x1].astype(np.uint8)).any()
            if not ring.any() and touches_motif:
                motif[y0:y1, x0:x1] |= comp.astype(bool)
        # (4) Yumuşat + kenar geçişi
        motif_u = cv2.morphologyEx(motif.astype(np.uint8), cv2.MORPH_CLOSE,
                                   np.ones((5, 5), np.uint8))
        alpha = cv2.GaussianBlur(motif_u.astype(np.float32), (5, 5), 0)[..., None].clip(0, 1)
        composed = src_a * (1 - alpha) + out_a * alpha
        out_mesh.visual.material.baseColorTexture = Image.fromarray(
            composed.round().astype(np.uint8))
        out_mesh.export(str(out_path))
        print(f"[F5] region compose (engine): motif {int(motif_u.sum())} px tutuldu, "
              f"bölge içi {int(inside.sum()) - int(motif_u.sum())} px + maske dışı "
              "orijinale döndürüldü", flush=True)
