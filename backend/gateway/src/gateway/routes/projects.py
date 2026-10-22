"""Project CRUD + thumbnail — token korumalı (kullanıcı tasarımları)."""
from __future__ import annotations

import copy
import json
import logging
import re
import shutil
import threading
from pathlib import Path

import trimesh
from common.config import get_settings
from common.paths import resolve_mesh_path, to_stored_mesh_path
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from gateway.auth import require_token
from gateway.db import get_db
from gateway.models.orm import Project
from gateway.models.schemas import ProjectCreate, ProjectOut, ProjectUpdate

router = APIRouter(prefix="/projects", dependencies=[require_token()])
# Thumbnail GET token'sız: <img src> Authorization header gönderemez. Önizleme
# görseli hassas değil, UUID ile adreslenir ve uygulama zaten Tailscale arkasında;
# public template-assets servisiyle tutarlı. Yazma (PUT) korumalı kalır.
public_router = APIRouter(prefix="/projects")

# Dosya deposu düzeni ve mesh üretimi hâlâ `default` kullanıcısı altında toplanır
# (tek-ev / single-household). Proje SAHİPLİĞİ ise projects.user_id ile takip edilir:
# oturum kullanıcısı varsa onun id'si, makine token'ında (APP_TOKEN → user_id None)
# 'default'. Erişim tek-ev olduğundan paylaşımlıdır (aşağıdaki _get_or_404 sahibe göre
# filtrelemez); attribution galeri/liste owner_username için kullanılır.
_USER = "default"


def _owner(request: Request) -> str:
    """İstekteki oturum kullanıcısının id'si; makine token'ında (None) 'default'e düşer.

    verify_token, oturum token'ında `request.state.user_id`'yi ilgili kullanıcıya,
    APP_TOKEN'da None'a ayarlar. Yeni projelerin sahipliği buradan atanır."""
    return getattr(request.state, "user_id", None) or _USER


def _get_or_404(db: Session, project_id: str) -> Project:
    # Tek-ev: sahibe göre filtrelemeyiz (herkes aynı hane) → oturum kullanıcısının
    # oluşturduğu projeler de (user_id != 'default') açılabilir/düzenlenebilir.
    proj = db.get(Project, project_id)
    if proj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proje bulunamadı")
    return proj


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate, request: Request, db: Session = Depends(get_db)
) -> Project:
    proj = Project(
        user_id=_owner(request),
        name=payload.name,
        garment_type=payload.garment_type,
        template_id=payload.template_id,
        customizations=payload.customizations,
    )
    db.add(proj)
    db.commit()
    db.refresh(proj)
    return proj


def _username_map(db: Session) -> dict[str, str]:
    """user_id → username eşlemesi (owner_username çözümü için tek sorgu)."""
    rows = db.execute(text("SELECT id, username FROM users")).all()
    return {r.id: r.username for r in rows}


@router.get("")
def list_projects(db: Session = Depends(get_db)) -> list[dict]:
    """Tüm projeler (tek-ev: sahibe göre filtreleme YOK), her biri owner_username ile.

    response_model=ProjectOut owner_username taşımadığından (şema bu görevin kapsamı
    dışı) ProjectOut serileştirmesini elle owner_username ile zenginleştiririz."""
    stmt = select(Project).order_by(Project.updated_at.desc())
    projects = list(db.scalars(stmt))
    umap = _username_map(db)
    out: list[dict] = []
    for p in projects:
        d = ProjectOut.model_validate(p).model_dump(mode="json")
        d["owner_username"] = umap.get(p.user_id) or p.user_id
        out.append(d)
    return out


# NOT: `/gallery`, `/{project_id}` catch-all'ından ÖNCE tanımlanmalı; aksi halde
# Starlette onu project_id="gallery" olarak yakalar. Bu görevin dosya kapsamı
# main.py'yi (router include) İÇERMEDİĞİ için galeri, top-level `/gallery` yerine
# zaten include edilmiş projects router'ı altında (`GET /projects/gallery`) servis
# edilir — auth (require_token) miras alınır.
@router.get("/gallery")
def gallery(db: Session = Depends(get_db)) -> list[dict]:
    """Paylaşılan (shared=1) tasarımlar — sahibi kullanıcı adıyla.

    `shared` sütunu B1'in ALTER guard'ıyla eklendi ama ORM'e map'lenmedi; ham SQL
    kullanırız (users.py deseniyle tutarlı). Ayrı `shared_at` sütunu yok →
    `updated_at` ile temsil edilir. owner_username, projects.user_id → users.id
    LEFT JOIN'inden; eşleşme yoksa ham user_id'ye düşer.
    """
    rows = db.execute(text(
        "SELECT p.id AS id, p.name AS name, p.updated_at AS shared_at, "
        "p.user_id AS user_id, u.username AS username "
        "FROM projects p LEFT JOIN users u ON p.user_id = u.id "
        "WHERE p.shared = 1 ORDER BY p.updated_at DESC"
    )).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "thumb": f"/projects/{r.id}/thumbnail",
            "owner_username": r.username or r.user_id,
            "shared_at": str(r.shared_at) if r.shared_at is not None else None,
        }
        for r in rows
    ]


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)) -> Project:
    return _get_or_404(db, project_id)


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(project_id: str, payload: ProjectUpdate, db: Session = Depends(get_db)) -> Project:
    proj = _get_or_404(db, project_id)
    if payload.name is not None:
        proj.name = payload.name
    if payload.customizations is not None:
        proj.customizations = payload.customizations
    db.commit()
    db.refresh(proj)
    return proj


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: str, db: Session = Depends(get_db)) -> None:
    proj = _get_or_404(db, project_id)
    db.delete(proj)
    db.commit()


@router.post("/{project_id}/duplicate", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def duplicate_project(
    project_id: str, request: Request, db: Session = Depends(get_db)
) -> Project:
    """Projeyi çoğalt: customizations + mesh/decals dosyaları kopyalanır, yeni
    bağımsız proje. Decal URL'leri yeni id'ye yeniden yazılır. ('kopyada dene' akışı.)
    Kopyanın sahibi çoğaltmayı yapan oturum kullanıcısı (makine token'ında 'default')."""
    src = _get_or_404(db, project_id)
    new = Project(
        user_id=_owner(request), name=f"{src.name} (kopya)",
        garment_type=src.garment_type, template_id=src.template_id,
        customizations=copy.deepcopy(src.customizations or {}),
    )
    db.add(new); db.commit(); db.refresh(new)
    base = Path(get_settings().projects_dir) / _USER
    srcdir, dstdir = base / project_id, base / new.id
    dstdir.mkdir(parents=True, exist_ok=True)
    for fname in ("mesh.glb", "mesh_view.glb", "sew_report.json"):
        f = srcdir / fname
        if f.exists():
            shutil.copy2(f, dstdir / fname)
    if (srcdir / "decals").exists():
        shutil.copytree(srcdir / "decals", dstdir / "decals", dirs_exist_ok=True)
    if (dstdir / "mesh.glb").exists():
        new.mesh_path = to_stored_mesh_path(dstdir / "mesh.glb")
    # decal URL'lerini yeni projeye yönlendir
    new.customizations = json.loads(
        json.dumps(new.customizations).replace(f"/projects/{project_id}/", f"/projects/{new.id}/"))
    db.commit(); db.refresh(new)
    return new


@router.post("/{project_id}/share")
def toggle_share(project_id: str, db: Session = Depends(get_db)) -> dict:
    """Projeyi galeriye aç/kapat (`shared` bayrağını toggle'la).

    `shared` ORM'e map'li olmadığından ham SQL ile okunup yazılır. Sahiplik
    kontrolü `_get_or_404` üzerinden (bugün tek kullanıcı: user_id='default')."""
    _get_or_404(db, project_id)
    row = db.execute(
        text("SELECT shared FROM projects WHERE id = :i"), {"i": project_id}
    ).first()
    new_val = 0 if (row is not None and row.shared) else 1
    db.execute(
        text("UPDATE projects SET shared = :s WHERE id = :i"),
        {"s": new_val, "i": project_id},
    )
    db.commit()
    return {"id": project_id, "shared": bool(new_val)}


def _thumb_path(project_id: str) -> Path:
    return Path(get_settings().projects_dir) / _USER / project_id / "thumbnail.png"


def _mesh_path(project_id: str) -> Path:
    return Path(get_settings().projects_dir) / _USER / project_id / "mesh.glb"


def _stored_mesh_path(db: Session, project_id: str) -> Path:
    """DB'de kayıtlı mesh yolunu geçerli PROJECTS_DIR altına çöz.

    Kayıt yoksa (eski projeler / henüz üretilmemiş) sözleşme konumuna düşer
    (`PROJECTS_DIR/default/<id>/mesh.glb`). Böylece göreli-migre edilmiş,
    eski-mutlak ve NULL değerlerin hepsi doğru dosyaya çözülür.
    """
    proj = db.get(Project, project_id)
    if proj is not None and proj.mesh_path:
        return resolve_mesh_path(proj.mesh_path)
    return _mesh_path(project_id)


# Viewer kopyası üst sınırı. 300k çok yüksekti: r3f her pointermove'da mesh'i
# BVH'siz raycast ediyor (her ışın = tüm üçgenler) → fırça/orbit ~saniyelerce
# kastırıyordu (headless ölçümde 300k'da fırça darbesi ~20sn). 80k görüntüleme +
# 3B fırça için yeterli; tam çözünürlük mesh.glb (ör. ~1.4M üçgen) KANONİK kalır
# (retexture/export hep onu kullanır), bu yalnız viewer kopyasıdır.
_VIEW_MAX_FACES = 80_000

# F6/R2: kullanıcı görüntüleme çözünürlüğünü SERBEST seçebilir. faces artık
# üç sabit değere kilitli değil; 1_000..1_000_000 arası herhangi bir tam sayı
# kabul edilir (aralık dışı → 422). 20k/40k/80k yalnız arayüzdeki hızlı-seçim
# butonları için referans; doğrulama ARALIK üzerinden yapılır. Her farklı değer
# ayrı bir viewer kopyasına önbelleklenir (mesh_view_5000.glb vb.); faces yoksa
# eski davranış (mesh_view.glb) korunur.
_VIEW_FACE_MIN = 1_000
_VIEW_FACE_MAX = 1_000_000
_VIEW_FACE_QUICK = (20_000, 40_000, 80_000)


def _view_mesh_path(project_id: str, faces: int | None = None) -> Path:
    name = f"mesh_view_{faces}.glb" if faces else "mesh_view.glb"
    return Path(get_settings().projects_dir) / _USER / project_id / name


# Build durumu (in-process): "src" = orijinal yeterli (küçük+UV'li, view dosyası yok),
# "building" = arka planda üretiliyor. Disk'teki mesh_view.glb kalıcı önbellektir.
_VIEW_STATE: dict[str, str] = {}
_VIEW_LOCK = threading.Lock()

# View doku yeniden-bake parametreleri (T1). 1024² hedef; orijinal yüzey
# örnek sayısı mesh boyutuyla ölçeklenir (üst sınır ile).
_VIEW_BAKE_SIZE = 1024
_VIEW_BAKE_SAMPLES = 200_000


def _sample_texture_nn(tex, uv):
    """glTF UV konvansiyonuyla (origin sol-üst, v aşağı) en-yakın-komşu doku
    örneklemesi. tex: (H,W,3) uint8; uv: (N,2) float → (N,3) uint8 renk.
    UV [0,1] dışına taşarsa kenara clamp'lenir (baked decal dokular [0,1]'de)."""
    import numpy as np
    h, w = tex.shape[:2]
    u = np.clip(uv[:, 0], 0.0, 1.0)
    v = np.clip(uv[:, 1], 0.0, 1.0)
    col = np.clip(np.rint(u * (w - 1)).astype(np.int64), 0, w - 1)
    row = np.clip(np.rint(v * (h - 1)).astype(np.int64), 0, h - 1)
    return tex[row, col]


def _rebake_view_texture(orig_verts, orig_faces, orig_uv, orig_tex,
                         view_verts, view_uv, view_faces, size=_VIEW_BAKE_SIZE):
    """Yeniden-parametrize edilmiş (yeni UV) view mesh'i için, ORİJİNAL dokudan
    yeni bir baseColorTexture bake'ler.

    Neden gerekli: decimation + xatlas-reparametrize orijinal UV↔doku eşlemesini
    bozar; view mesh'in üçgenleri orijinal dokunun boş/gutter (beyaz) bölgelerini
    örneklemeye başlar → düşük/orta çözünürlükte beyaz kılcal çizgiler ve beyaz
    ince üçgenler. Çözüm: yeni UV düzeninin her texel'ini view yüzeyinde bir dünya
    noktasına çevir, o noktayı orijinal yüzeye eşle, orijinal dokudan rengi oku.

    Yaklaşım (performans için per-pixel python döngüsü YOK):
    1. Orijinal yüzeyi yoğun örnekle (dünya konumu + barycentric UV → önceden
       hesaplanmış renk); scipy cKDTree ile indeksle.
    2. View mesh'i UV-uzayında üçgen-başına bbox rasterize et → her texel'in view
       yüzey dünya konumu (numpy, üçgen içi vektörize barycentric).
    3. Rasterize edilen texeller için en-yakın orijinal örneğin rengini yaz.
    4. Boş texelleri en-yakın dolu texel rengiyle doldur (dilation) → mipmap
       küçültmesi gutter'lardan beyaz sızdırmasın.
    """
    import numpy as np
    import trimesh as _tm
    from PIL import Image
    from scipy import ndimage
    from scipy.spatial import cKDTree

    # 1) Orijinal yüzey örnekleri + her örneğin orijinal-doku rengi
    n = int(min(_VIEW_BAKE_SAMPLES, max(50_000, len(orig_faces) * 4)))
    orig_mesh = _tm.Trimesh(vertices=orig_verts, faces=orig_faces, process=False)
    pts, fidx = _tm.sample.sample_surface(orig_mesh, n)
    pts = np.asarray(pts, dtype=np.float64)
    tri = orig_verts[orig_faces[fidx]]                        # (n,3,3)
    bary = _tm.triangles.points_to_barycentric(tri, pts)      # (n,3)
    face_uv = orig_uv[orig_faces[fidx]]                       # (n,3,2)
    sample_uv = np.einsum("ij,ijk->ik", bary, face_uv)        # (n,2)
    sample_col = _sample_texture_nn(orig_tex, sample_uv)      # (n,3) uint8
    tree = cKDTree(pts)

    # 2) View mesh'i UV-uzayında rasterize et → texel başına dünya konumu
    w = h = int(size)
    world = np.zeros((h, w, 3), dtype=np.float64)
    filled = np.zeros((h, w), dtype=bool)
    px = view_uv[:, 0] * (w - 1)
    py = view_uv[:, 1] * (h - 1)
    for f in view_faces:
        i0, i1, i2 = int(f[0]), int(f[1]), int(f[2])
        u0, u1, u2 = px[i0], px[i1], px[i2]
        v0, v1, v2 = py[i0], py[i1], py[i2]
        minx = max(int(np.floor(min(u0, u1, u2))), 0)
        maxx = min(int(np.ceil(max(u0, u1, u2))), w - 1)
        miny = max(int(np.floor(min(v0, v1, v2))), 0)
        maxy = min(int(np.ceil(max(v0, v1, v2))), h - 1)
        if maxx < minx or maxy < miny:
            continue
        denom = (v1 - v2) * (u0 - u2) + (u2 - u1) * (v0 - v2)
        if abs(denom) < 1e-12:
            continue
        gx, gy = np.meshgrid(np.arange(minx, maxx + 1), np.arange(miny, maxy + 1))
        a = ((v1 - v2) * (gx - u2) + (u2 - u1) * (gy - v2)) / denom
        b = ((v2 - v0) * (gx - u2) + (u0 - u2) * (gy - v2)) / denom
        c = 1.0 - a - b
        inside = (a >= -1e-4) & (b >= -1e-4) & (c >= -1e-4)
        if not inside.any():
            continue
        aa, bb, cc = a[inside], b[inside], c[inside]
        w0, w1, w2 = view_verts[i0], view_verts[i1], view_verts[i2]
        pos = aa[:, None] * w0 + bb[:, None] * w1 + cc[:, None] * w2
        rr, cc2 = gy[inside], gx[inside]
        world[rr, cc2] = pos
        filled[rr, cc2] = True

    img = np.zeros((h, w, 3), dtype=np.uint8)
    if filled.any():
        # 3) Rasterize edilen texeller → en-yakın orijinal örnek rengi
        _d, idx = tree.query(world[filled], workers=-1)
        img[filled] = sample_col[idx]
        # 4) Boş texelleri en-yakın dolu texel'den doldur (gutter dilation)
        inds = ndimage.distance_transform_edt(
            ~filled, return_distances=False, return_indices=True)
        img = img[tuple(inds)]
    return Image.fromarray(img, "RGB")


def _ensure_view_mesh(project_id: str, faces: int | None = None) -> Path:
    """Viewer için hafif + UV'li kopya (mesh_view[_<faces>].glb) üret/önbellekle.

    mesh.glb (tam çözünürlük) KANONİK kalır: retexture, format dışa-aktarma vb.
    hep tam modeli kullanır. Bu kopya yalnız görüntüleme + 3D fırça içindir
    (fırça UV ister; Hunyuan-shape/TripoSR çıktıları UV'siz gelir).
    Küçük ve UV'li mesh'te kopya üretilmez, orijinal döner.
    `faces` verilirse o üst sınıra decimate edilir ve ayrı dosyaya önbelleklenir
    (F6 çözünürlük seçici); yoksa varsayılan _VIEW_MAX_FACES.
    NOT: decimation ham UV/dokuyu korumaz; kaynakta baseColorTexture VARSA
    xatlas yeni UV üretilir ve doku orijinal mesh'ten yeni düzene yeniden
    bake edilir (_rebake_view_texture) — böylece beyaz kılcal çizgi/üçgen
    artefaktı oluşmaz. Doku yoksa hafif gri fallback dokusu atanır.
    """
    cap = faces or _VIEW_MAX_FACES
    src = _mesh_path(project_id)
    view = _view_mesh_path(project_id, faces)
    if view.exists() and view.stat().st_mtime >= src.stat().st_mtime:
        return view

    import numpy as np

    m = trimesh.load(str(src), force="mesh")
    uv = getattr(m.visual, "uv", None)
    has_uv = uv is not None and len(uv) == len(m.vertices)
    if len(m.faces) <= cap and has_uv:
        return src

    # Orijinal doku (baseColorTexture) + UV'yi decimation'dan ÖNCE yakala. View
    # mesh'i yeniden parametrize edilecekse (aşağıda) dokuyu bu kaynaktan yeniden
    # bake'leriz; aksi halde yeni UV düzeni orijinal dokunun boş/gutter (beyaz)
    # bölgelerine denk gelir → düşük/orta çözünürlükte beyaz kılcal çizgiler ve
    # beyaz ince üçgenler (T1). Doku yoksa eski gri fallback korunur.
    orig_uv = np.asarray(uv, dtype=np.float64) if has_uv else None
    orig_tex = None
    if orig_uv is not None:
        _mat = getattr(m.visual, "material", None)
        _btex = getattr(_mat, "baseColorTexture", None) if _mat is not None else None
        if _btex is not None:
            try:
                orig_tex = np.asarray(_btex.convert("RGB"), dtype=np.uint8)
            except Exception:  # noqa: BLE001 — doku okunamazsa gri fallback
                orig_tex = None

    vertices, tris = m.vertices, m.faces
    if len(tris) > cap:
        # ÖNCE KAYNAKLA (weld): UV seam'leri vertexleri çoğaltır — motif-bake
        # mesh'leri binlerce topolojik kopuk parçaya bölünür (canlı vaka: 7317).
        # Kaynaksız decimation çatlak açar, xatlas binlerce mini ada üretir →
        # dövme "paramparça mozaik" görünür (canlı ekran kanıtı, 2026-07-06).
        # Renk zaten orijinal (kaynaklanmamış) mesh'ten yeniden bake ediliyor,
        # bu yüzden weld'in UV kaybetmesi sorun değil.
        w = m.copy()
        try:
            w.merge_vertices(merge_tex=True, merge_norm=True)
        except TypeError:  # eski trimesh imzası
            w.merge_vertices()
        vertices, tris = w.vertices, w.faces
        import fast_simplification
        vertices, tris = fast_simplification.simplify(
            np.asarray(vertices, dtype=np.float32),
            np.asarray(tris, dtype=np.int64),
            target_count=cap)
        has_uv = False  # decimation UV korumaz

    out = trimesh.Trimesh(vertices=np.asarray(vertices), faces=np.asarray(tris), process=False)
    if not has_uv:
        import xatlas
        vmapping, indices, uvs = xatlas.parametrize(
            np.asarray(out.vertices), np.asarray(out.faces))
        out = trimesh.Trimesh(vertices=out.vertices[vmapping], faces=indices, process=False)
        from PIL import Image
        tex_img = None
        if orig_tex is not None:
            try:
                # Bake boyutu ORİJİNAL dokuyu izler (1024 tabanı, 2048 tavanı):
                # 2048'lik dokuyu sabit 1024'e düşürmek yüksek çözünürlük seçen
                # kullanıcıya "kötü/bulanık" görünüyordu (canlı şikâyet, 200k/500k).
                bake_size = int(min(2048, max(_VIEW_BAKE_SIZE, max(orig_tex.shape[:2]))))
                tex_img = _rebake_view_texture(
                    np.asarray(m.vertices, dtype=np.float64), np.asarray(m.faces),
                    orig_uv, orig_tex,
                    np.asarray(out.vertices, dtype=np.float64),
                    np.asarray(uvs, dtype=np.float64), np.asarray(out.faces),
                    size=bake_size)
            except Exception:  # noqa: BLE001 — bake düşerse gri fallback (view yine üretilir)
                logging.getLogger("gateway.projects").warning(
                    "view dokusu yeniden bake edilemedi (%s, faces=%s); gri fallback",
                    project_id, faces, exc_info=True)
                tex_img = None
        if tex_img is None:
            tex_img = Image.new("RGB", (16, 16), (204, 204, 204))
        out.visual = trimesh.visual.TextureVisuals(
            uv=uvs,
            material=trimesh.visual.material.PBRMaterial(baseColorTexture=tex_img))
    out.export(str(view))
    return view


def _view_or_build_async(project_id: str, faces: int | None = None) -> Path:
    """view hazırsa onu döndür; değilse arka planda üretmeye başla ve ŞİMDİLİK
    orijinali döndür (xatlas 300k face'te dakikalar sürebilir — istek bloklanmaz,
    sonraki açılışlar hafif kopyayı alır). Build durumu (faces) çözünürlük başına
    ayrı anahtarlanır ki farklı çözünürlükler birbirini kilitlemesin."""
    src = _mesh_path(project_id)
    view = _view_mesh_path(project_id, faces)
    if view.exists() and view.stat().st_mtime >= src.stat().st_mtime:
        return view
    # Açık düşük/orta hedef (faces verilmiş) SENKRON üretilir: kullanıcı "Düşük
    # (20k)" seçtiyse anında düşük gelmeli — aksi halde tam mesh döner, fizik
    # ">30k vertex" diye reddeder ve ayar "çalışmıyor" hissi verir (canlı vaka).
    # Küçük hedeflerde decimation saniyeler sürer; xatlas fallback'i büyük
    # kaynaklarda yine asenkron kalsın diye yalnız faces<=40000'de senkronuz.
    if faces is not None and faces <= 40000:
        try:
            return _ensure_view_mesh(project_id, faces)
        except Exception:  # noqa: BLE001 — üretim düşerse orijinale düş
            logging.getLogger("gateway.projects").warning(
                "senkron mesh_view üretilemedi (%s, faces=%s)", project_id, faces,
                exc_info=True)
            return src
    key = f"{project_id}:{faces}"
    if _VIEW_STATE.get(key) == "src":
        return src
    with _VIEW_LOCK:
        if _VIEW_STATE.get(key) == "building":
            return src
        _VIEW_STATE[key] = "building"

    def _run() -> None:
        try:
            result = _ensure_view_mesh(project_id, faces)
            _VIEW_STATE[key] = "src" if result == src else "view"
        except Exception:  # noqa: BLE001
            logging.getLogger("gateway.projects").warning(
                "mesh_view üretilemedi (%s, faces=%s)", project_id, faces, exc_info=True)
            _VIEW_STATE.pop(key, None)

    threading.Thread(target=_run, daemon=True, name=f"mesh-view-{project_id}-{faces}").start()
    return src


@router.put("/{project_id}/thumbnail", response_model=ProjectOut)
def upload_thumbnail(project_id: str, file: UploadFile, db: Session = Depends(get_db)) -> Project:
    proj = _get_or_404(db, project_id)
    path = _thumb_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(file.file.read())
    proj.thumbnail_path = str(path)
    db.commit()
    db.refresh(proj)
    return proj


_EXPORT_MEDIA = {
    "glb": "model/gltf-binary",
    "stl": "model/stl",
    "obj": "text/plain",
    "ply": "application/octet-stream",
}


@public_router.get("/{project_id}/mesh")
def get_mesh(project_id: str, faces: str | None = None, db: Session = Depends(get_db)) -> FileResponse:
    """Viewer mesh'i. `faces` (R2 serbest çözünürlük seçici) verilirse o üst
    sınıra decimate edilmiş ayrı bir viewer kopyası servis edilir; yoksa
    varsayılan (mesh_view.glb / _VIEW_MAX_FACES). faces serbesttir ama
    1_000..1_000_000 aralığında olmalıdır; aralık dışı / sayı-olmayan → 422.
    Küçük hedefler (faces<=40000) senkron üretilir; daha büyük değerler
    _view_or_build_async içindeki mevcut asenkron yola düşer (istek bloklanmaz).

    Özel değer `faces=full` (R3): KANONİK tam çözünürlük mesh.glb'yi (decimate
    edilmemiş, view kopyası DEĞİL) doğrudan servis eder — düşük çözünürlükte
    görüntülerken bile tam çözünürlük dışa-aktarma için."""
    _get_or_404(db, project_id)
    src = _stored_mesh_path(db, project_id)
    if not src.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mesh yok")
    # faces=full → kanonik tam mesh.glb'yi doğrudan ver (view kopyası üretme/servis etme)
    if faces == "full":
        return FileResponse(src, media_type="model/gltf-binary", filename=f"{project_id}.glb")
    faces_int: int | None = None
    if faces is not None:
        try:
            faces_int = int(faces)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Geçersiz çözünürlük: {faces!r} (tam sayı ya da 'full' olmalı)")
        if not (_VIEW_FACE_MIN <= faces_int <= _VIEW_FACE_MAX):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(f"Geçersiz çözünürlük: {faces_int} "
                        f"(izinli aralık {_VIEW_FACE_MIN}..{_VIEW_FACE_MAX})"))
    path = src
    try:
        path = _view_or_build_async(project_id, faces_int)
    except Exception:  # noqa: BLE001 — view üretilemezse görüntüleme yine de çalışsın
        logging.getLogger("gateway.projects").warning(
            "mesh_view kontrolü başarısız (%s), orijinal servis ediliyor", project_id, exc_info=True)
    return FileResponse(path, media_type="model/gltf-binary")


@public_router.get("/{project_id}/mesh.{ext}")
def get_mesh_format(project_id: str, ext: str, db: Session = Depends(get_db)) -> FileResponse:
    ext = ext.lower()
    if ext not in _EXPORT_MEDIA:
        raise HTTPException(422, f"Desteklenmeyen format: {ext} ({list(_EXPORT_MEDIA)})")
    src = _stored_mesh_path(db, project_id)
    if not src.exists():
        raise HTTPException(404, "Mesh bulunamadı")
    if ext == "glb":
        return FileResponse(src, media_type=_EXPORT_MEDIA["glb"], filename=f"{project_id}.glb")
    out = src.with_suffix(f".{ext}")
    if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
        loaded = trimesh.load(str(src), force="scene")
        mesh = loaded.to_geometry() if isinstance(loaded, trimesh.Scene) else loaded
        mesh.export(str(out))
    return FileResponse(out, media_type=_EXPORT_MEDIA[ext], filename=f"{project_id}.{ext}")


@public_router.get("/{project_id}/thumbnail")
def get_thumbnail(project_id: str, db: Session = Depends(get_db)) -> FileResponse:
    _get_or_404(db, project_id)
    path = _thumb_path(project_id)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thumbnail yok")
    return FileResponse(path, media_type="image/png")


@public_router.get("/{project_id}/variations/{name}")
def get_variation_glb(project_id: str, name: str, db: Session = Depends(get_db)) -> FileResponse:
    """Varyant GLB'si (drape/retopo/upscale çıktıları — viewer Authorization gönderemez).
    Yalnız basit dosya adı (path-traversal koruması)."""
    _get_or_404(db, project_id)
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.glb", name):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Geçersiz ad")
    path = Path(get_settings().projects_dir) / _USER / project_id / "variations" / name
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Varyant yok")
    return FileResponse(path, media_type="model/gltf-binary")


@public_router.get("/{project_id}/decals/{name}")
def get_decal(project_id: str, name: str, db: Session = Depends(get_db)) -> FileResponse:
    """Motif decal PNG (token'sız: <Decal>/TextureLoader Authorization gönderemez).
    Yalnız basit dosya adı (path-traversal koruması)."""
    _get_or_404(db, project_id)
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.png", name):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Geçersiz ad")
    path = Path(get_settings().projects_dir) / _USER / project_id / "decals" / name
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Decal yok")
    return FileResponse(path, media_type="image/png")


# ---------------------------------------------------------------------------
# Sonuçlar (outputs): mesh üretmeyen motorların (face4d, gaussian_scene) medya
# çıktıları. Manifest token'lı; medya public_router'da (decals/thumbnail gibi —
# <video>/<img> Authorization gönderemez). Spec:
# docs/superpowers/specs/2026-07-12-outputs-viewer-design.md
_OUTPUT_ROOTS = ("face4d", "gaussian_scene")
_OUTPUT_KINDS = {".mp4": "video", ".gif": "gif", ".ply": "ply"}
_OUTPUT_MEDIA = {".mp4": "video/mp4", ".gif": "image/gif",
                 ".ply": "application/octet-stream"}


def _outputs_base(project_id: str) -> Path:
    return Path(get_settings().projects_dir) / _USER / project_id


@router.get("/{project_id}/outputs")
def list_outputs(project_id: str, db: Session = Depends(get_db)) -> list[dict]:
    _get_or_404(db, project_id)
    base = _outputs_base(project_id)
    items: list[dict] = []
    for root in _OUTPUT_ROOTS:
        rootdir = base / root
        if not rootdir.is_dir():
            continue
        for f in sorted(rootdir.rglob("*")):
            kind = _OUTPUT_KINDS.get(f.suffix.lower())
            if kind is None or not f.is_file():
                continue
            items.append({"kind": kind, "name": f.name,
                          "path": f.relative_to(base).as_posix(),
                          "size": f.stat().st_size})
    return items


@public_router.get("/{project_id}/outputs/{subpath:path}")
def get_output_file(project_id: str, subpath: str,
                    db: Session = Depends(get_db)) -> FileResponse:
    _get_or_404(db, project_id)
    media = _OUTPUT_MEDIA.get(Path(subpath).suffix.lower())
    base = _outputs_base(project_id).resolve()
    try:
        target = (base / subpath).resolve()
    except OSError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Çıktı yok")
    ok = (
        media is not None
        and target.is_relative_to(base)
        and target != base
        and target.relative_to(base).parts[0] in _OUTPUT_ROOTS
        and target.is_file()
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Çıktı yok")
    return FileResponse(target, media_type=media)
