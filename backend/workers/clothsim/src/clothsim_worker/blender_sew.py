"""Blender headless: 2D kalıp parçalarını mankene DİKEN kumaş simülasyonu (F2).

Kullanım (Blender içinde çalışır):
    blender -b -P blender_sew.py -- <girdi.json> <çıktı.glb>
                                     [--preview <önek>] [--report <rapor.json>]

Girdi JSON'u `sew_prep.build_sew_input` üretir (bu dosya geometri HESAPLAMAZ; yalnız
kurar + simüle eder + yazar). Koordinatlar glTF çerçevesinde (metre, Y-yukarı, ön +Z);
Blender'a (x, -z, y) olarak çevrilir, glTF export'u (export_yup) geri çevirir.

Akış:
1. Manken = COLLISION modifier'lı mesh (kumaştan önce sahneye girer).
2. Kumaş = TÜM parçalar tek obje: yüzler + dikiş yayları (yüzsüz "loose edge").
   Blender cloth `use_sewing_springs` bu yüzsüz kenarları sıfır boya çeker.
   Dinlenme şekli = düz kalıp atlası ("rest" shape key) → kumaş gerçek kalıp ölçüsünü
   korur; UV = aynı atlas.
3. İki aşama (keyframe'li): ilk ~%45 karede yerçekimi neredeyse sıfır (dikişler kapanır),
   sonra normal yerçekimine yumuşak geçiş (kumaş mankene oturur).
4. Son kare depsgraph'tan mesh'e PİŞİRİLİR (export_apply TUZAĞI: cloth modifier'ı
   export_apply ile dinlenme pozunda yeniden değerlendirilir → deformasyon kaybolur;
   bkz. blender_drape.py). Dikiş yayları silinir, dikiş vertexleri birleştirilir
   (merge-by-distance), YALNIZ kıyafet GLB olarak yazılır.
5. Opsiyonel: mankenli ön + yan önizleme PNG'si (Cycles, CPU — GPU KULLANILMAZ).

NOT: `bpy` YALNIZ Blender'ın python'unda vardır; bu dosya worker tarafından IMPORT
EDİLMEZ (pytest de import etmez). bpy/bmesh import'u main() içindedir.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time


def _pop_flag(argv: list[str], flag: str) -> tuple[list[str], str | None]:
    """argv'den `flag <değer>` çiftini çıkar; (kalan argv, değer|None)."""
    if flag not in argv:
        return argv, None
    i = argv.index(flag)
    if i + 1 >= len(argv):
        raise SystemExit(f"{flag} bir değer bekliyor")
    return argv[:i] + argv[i + 2:], argv[i + 1]


def _parse_args() -> tuple[str, str, str | None, str | None]:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    argv, preview = _pop_flag(argv, "--preview")
    argv, report = _pop_flag(argv, "--report")
    if len(argv) < 2:
        raise SystemExit("kullanım: -- <girdi.json> <çıktı.glb> [--preview önek] [--report rapor.json]")
    return argv[0], argv[1], preview, report


def _to_b(p):
    """glTF (Y-yukarı) → Blender (Z-yukarı)."""
    return (p[0], -p[2], p[1])


def _stats(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    n = len(s)

    def q(f):
        return s[min(n - 1, max(0, int(round(f * (n - 1)))))]

    return {"n": n, "median": q(0.5), "p95": q(0.95), "max": s[-1], "mean": sum(s) / n}


def _hex_rgba(h: str, a: float = 1.0):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    # sRGB → lineer (Blender renk girdileri lineer).
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return (*lin, a)


def _fabric_material(bpy, pbr: dict):
    mat = bpy.data.materials.new("Kumas")
    mat.use_nodes = True
    mat.use_backface_culling = False  # glTF doubleSided (iç yüz de görünsün)
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = _hex_rgba(pbr.get("base_color", "#d8d2c8"))
        bsdf.inputs["Roughness"].default_value = float(pbr.get("roughness", 0.8))
        bsdf.inputs["Metallic"].default_value = float(pbr.get("metalness", 0.0))
        for key, val in (("Sheen Weight", pbr.get("sheen", 0.0)),
                         ("Sheen Roughness", pbr.get("sheen_roughness", 0.5))):
            if key in bsdf.inputs:
                bsdf.inputs[key].default_value = float(val)
        if "Sheen Tint" in bsdf.inputs and pbr.get("sheen_color"):
            try:
                bsdf.inputs["Sheen Tint"].default_value = _hex_rgba(pbr["sheen_color"])
            except (TypeError, ValueError):
                pass
    return mat


def _render_previews(bpy, prefix: str, garment, body, height: float,
                     views: tuple[str, ...] = ("front", "side")) -> list[str]:
    """Mankenli ön + yan önizleme (Cycles CPU, düşük örnek)."""
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 24
    try:
        scene.cycles.use_denoising = True
        scene.cycles.denoiser = "OPENIMAGEDENOISE"
    except (AttributeError, TypeError):
        scene.cycles.use_denoising = False
    scene.render.resolution_x = 600
    scene.render.resolution_y = 800
    scene.render.film_transparent = False
    world = bpy.data.worlds.new("Dunya")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs["Color"].default_value = (0.82, 0.84, 0.88, 1.0)
        bg.inputs["Strength"].default_value = 0.9
    scene.world = world
    # Manken malzemesi (açık gri, mat).
    bm = bpy.data.materials.new("Manken")
    bm.use_nodes = True
    b = bm.node_tree.nodes.get("Principled BSDF")
    if b is not None:
        b.inputs["Base Color"].default_value = (0.16, 0.17, 0.2, 1.0)
        b.inputs["Roughness"].default_value = 0.9
    body.data.materials.clear()
    body.data.materials.append(bm)
    # Işıklar.
    sun = bpy.data.lights.new("Gunes", type="SUN")
    sun.energy = 3.0
    so = bpy.data.objects.new("Gunes", sun)
    so.rotation_euler = (math.radians(50), math.radians(10), math.radians(-30))
    scene.collection.objects.link(so)
    # Ortografik kamera.
    cam = bpy.data.cameras.new("Kamera")
    cam.type = "ORTHO"
    cam.ortho_scale = height * 0.75
    co = bpy.data.objects.new("Kamera", cam)
    scene.collection.objects.link(co)
    scene.camera = co
    zc = height * 0.66
    out = []
    all_views = {
        # Blender'da ön yüz −Y'ye bakar (glTF +Z).
        "front": ((0.0, -6.0, zc), (math.radians(90), 0.0, 0.0)),
        "side": ((6.0, 0.0, zc), (math.radians(90), 0.0, math.radians(90))),
        "back": ((0.0, 6.0, zc), (math.radians(90), 0.0, math.radians(180))),
    }
    for name in views:
        loc, rot = all_views[name]
        co.location = loc
        co.rotation_euler = rot
        path = f"{prefix}_{name}.png"
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        out.append(path)
    return out


def main() -> None:
    import bmesh
    import bpy

    t0 = time.time()
    in_json, out_glb, preview, report_path = _parse_args()
    with open(in_json, encoding="utf-8") as fh:
        data = json.load(fh)
    frames = max(10, int(data.get("frames", 120)))
    fabric = data.get("fabric") or {}
    sim = data.get("sim") or {}

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = frames

    # --- manken (collider) ---
    bd = data["body"]
    bmesh_data = bpy.data.meshes.new("manken")
    bmesh_data.from_pydata([_to_b(p) for p in bd["vertices"]], [], [tuple(f) for f in bd["faces"]])
    bmesh_data.update()
    body = bpy.data.objects.new("Manken", bmesh_data)
    scene.collection.objects.link(body)
    body.modifiers.new("Collision", type="COLLISION")
    body.collision.thickness_outer = float(sim.get("body_thickness", 0.006))
    body.collision.thickness_inner = 0.02
    body.collision.cloth_friction = float(sim.get("body_friction", 5.0))
    body.collision.damping = 0.5

    # --- kumaş (tüm parçalar tek obje + dikiş yayları) ---
    verts = [_to_b(p) for p in data["vertices"]]
    faces = [tuple(f) for f in data["faces"]]
    springs = [tuple(s) for s in data["springs"]]
    me = bpy.data.meshes.new("kiyafet")
    me.from_pydata(verts, springs, faces)
    me.update()
    n_v = len(me.vertices)
    if n_v != len(verts):
        raise SystemExit("vertex sayısı değişti (from_pydata)")
    # UV: vertex başına → loop başına.
    uv = data["uv"]
    uvl = me.uv_layers.new(name="UVMap")
    loop_uv = []
    for lp in me.loops:
        u, v = uv[lp.vertex_index]
        loop_uv += [u, v]
    uvl.data.foreach_set("uv", loop_uv)
    me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
    cloth = bpy.data.objects.new("Kiyafet", me)
    scene.collection.objects.link(cloth)
    bpy.context.view_layer.objects.active = cloth

    # Dinlenme şekli: düz kalıp atlası (shape key).
    cloth.shape_key_add(name="Basis", from_mix=False)
    rest_key = cloth.shape_key_add(name="rest", from_mix=False)
    flat = []
    for p in data["rest"]:
        flat += [p[0], p[1], p[2] if len(p) > 2 else 0.0]
    rest_key.data.foreach_set("co", flat)
    rest_key.value = 0.0

    # AYAR GÜNLÜĞÜ (F2, 2026-10-17; teagan k/e + penelope + sandy, 120 kare):
    #   sewing_force 8 → kol takma dikişinde 13-23 mm açık; 15 → 7.7; 30 → 5.7 mm
    #   (25 seçildi). Çarpışma kalınlığı (manken 12 mm + kumaş 6 mm) kolu ~11 cm
    #   "kalınlaştırıyordu" → erkek mankende dar kol omuzda topaklandı (dikiş 215 mm
    #   açık); 6 + 4 mm ile kapandı (maks 6 mm). Öz-çarpışma kapatmak çözmedi.
    cm = cloth.modifiers.new("Cloth", type="CLOTH")
    st = cm.settings
    st.quality = 5
    for key, val in fabric.items():
        if hasattr(st, key):
            setattr(st, key, val)
        else:
            print(f"[sew] uyarı: bilinmeyen cloth ayarı atlandı: {key}")
    st.quality = max(int(st.quality), int(sim.get("min_quality", 6)))
    st.use_sewing_springs = True
    st.sewing_force_max = float(sim.get("sewing_force", 25.0))
    st.rest_shape_key = rest_key
    st.use_dynamic_mesh = False
    cs = cm.collision_settings
    cs.use_collision = True
    cs.distance_min = float(sim.get("distance_min", 0.004))
    cs.collision_quality = int(sim.get("collision_quality", 4))
    cs.use_self_collision = bool(sim.get("self_collision", True))
    cs.self_distance_min = float(sim.get("self_distance_min", 0.004))
    cs.self_friction = 5.0
    cm.point_cache.frame_start = 1
    cm.point_cache.frame_end = frames

    # İki aşama: dikiş kapanırken yerçekimi düşük, sonra normal.
    ew = st.effector_weights
    g_low = float(sim.get("gravity_low", 0.05))
    f_sew = max(2, int(frames * float(sim.get("sew_phase", 0.45))))
    f_full = min(frames, f_sew + max(5, int(frames * 0.15)))
    ew.gravity = g_low
    ew.keyframe_insert("gravity", frame=1)
    ew.keyframe_insert("gravity", frame=f_sew)
    ew.gravity = 1.0
    ew.keyframe_insert("gravity", frame=f_full)

    t_sim = time.time()
    for f in range(1, frames + 1):
        scene.frame_set(f)
        if f % 20 == 0 or f == frames:
            print(f"[sew] kare {f}/{frames} ({time.time() - t_sim:.0f} sn)", flush=True)
    sim_s = time.time() - t_sim

    # --- son kareyi pişir ---
    depsgraph = bpy.context.evaluated_depsgraph_get()
    ev = cloth.evaluated_get(depsgraph)
    baked = bpy.data.meshes.new_from_object(ev)
    co = [tuple(v.co) for v in baked.vertices]
    if len(co) != n_v:
        raise SystemExit("simülasyon sonrası vertex sayısı değişti")

    def dist(a, b):
        return math.sqrt(sum((a[k] - b[k]) ** 2 for k in range(3)))

    # Metrikler (birleştirmeden ÖNCE): dikiş aralığı + kenar uzama oranı.
    gaps = [dist(co[a], co[b]) * 1000.0 for a, b in springs]
    rest = data["rest"]
    ratios = []
    seen = set()
    for f in faces:
        for a, b in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
            k = (a, b) if a < b else (b, a)
            if k in seen:
                continue
            seen.add(k)
            r0 = math.sqrt(sum((rest[a][i] - rest[b][i]) ** 2 for i in range(len(rest[a]))))
            if r0 > 1e-9:
                ratios.append(dist(co[a], co[b]) / r0)
    seam_rep = []
    for s in data.get("seams", []):
        seam_rep.append(dict(s))
    # Parça bazlı dikiş aralığı (rapor için).
    xs = [p[0] for p in co]
    ys = [p[1] for p in co]
    zs = [p[2] for p in co]
    bbox_b = [[min(xs), min(ys), min(zs)], [max(xs), max(ys), max(zs)]]

    old = cloth.data
    cloth.modifiers.clear()
    cloth.data = baked
    try:
        cloth.shape_key_clear()
    except RuntimeError:
        pass
    bpy.data.meshes.remove(old)

    # Dikiş yaylarını sil + dikiş vertexlerini kaynat.
    bm = bmesh.new()
    bm.from_mesh(cloth.data)
    bm.verts.ensure_lookup_table()
    loose = [e for e in bm.edges if not e.link_faces]
    n_loose = len(loose)
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="EDGES")
    bm.verts.ensure_lookup_table()
    seam_ids = set(data.get("seam_vertices", []))
    seam_verts = [bm.verts[i] for i in seam_ids if i < len(bm.verts)]
    merge_m = float(sim.get("merge_mm", 4.0)) / 1000.0
    n_before = len(bm.verts)
    if seam_verts:
        bmesh.ops.remove_doubles(bm, verts=seam_verts, dist=merge_m)
    # Kopuk vertex (yüzsüz) kalmasın.
    lone = [v for v in bm.verts if not v.link_faces]
    if lone:
        bmesh.ops.delete(bm, geom=lone, context="VERTS")
    merged = n_before - len(bm.verts)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(cloth.data)
    bm.free()
    cloth.data.polygons.foreach_set("use_smooth", [True] * len(cloth.data.polygons))
    cloth.data.update()

    mat = _fabric_material(bpy, data.get("pbr") or {})
    cloth.data.materials.clear()
    cloth.data.materials.append(mat)

    # YALNIZ kıyafeti export et (manken GLB'ye girmez).
    out_dir = os.path.dirname(out_glb)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    cloth.select_set(True)
    bpy.context.view_layer.objects.active = cloth
    bpy.ops.export_scene.gltf(filepath=out_glb, export_format="GLB", use_selection=True,
                              export_apply=False, export_yup=True)

    previews: list[str] = []
    if preview:
        body.modifiers.clear()
        previews = _render_previews(bpy, preview, cloth, body,
                                    float(data.get("body_info", {}).get("height", 1.7)),
                                    tuple(sim.get("views") or ("front", "side")))

    rep = {
        "frames": frames,
        "sim_seconds": round(sim_s, 1),
        "total_seconds": round(time.time() - t0, 1),
        "vertices_in": n_v,
        "faces": len(faces),
        "springs": len(springs),
        "seam_gap_mm": _stats(gaps),
        "seam_gap_over_10mm": sum(1 for g in gaps if g > 10.0),
        "edge_stretch": _stats(ratios),
        "loose_edges_removed": n_loose,
        "merged_vertices": merged,
        "vertices_out": len(cloth.data.vertices),
        "bbox_blender": bbox_b,
        "previews": previews,
        "seams": seam_rep,
    }
    if sim.get("dump_coords"):
        # Doğrulama için: birleştirme öncesi son-kare koordinatları (glTF çerçevesi).
        rep["coords_gltf"] = [[round(p[0], 5), round(p[2], 5), round(-p[1], 5)] for p in co]
    if report_path:
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=1)
    print("[sew] rapor " + json.dumps({k: rep[k] for k in ("seam_gap_mm", "edge_stretch", "sim_seconds")}),
          flush=True)


if __name__ == "__main__":
    main()
