"""Blender headless kumaş-simülasyonu (drape) script'i.

Kullanım (Blender içinde çalışır):
    blender -b -P blender_drape.py -- <in.glb> <out.glb> [frames] [collider.glb]
                                      [--fabric <fabric.json>]

`--fabric <fabric.json>` (opsiyonel, konumdan bağımsız bayrak): `common.fabrics.
blender_params(id)` çıktısının JSON dökümü — anahtarlar Blender ClothSettings alan
adlarıdır ve cloth settings'e doğrudan uygulanır. Bayrak yoksa eski (denim) değerler
kullanılır → mevcut çağrılar birebir aynı davranır (geriye uyum).

Akış: GLB'yi içe aktar → ilk mesh'e Cloth modifier + yer-düzlemi (veya verilen
collider GLB) → N frame simüle → son frame'i GLB olarak dışa aktar.

NOT: `bpy` YALNIZ Blender'ın kendi python'unda vardır. Bu dosya worker tarafından
IMPORT EDİLMEZ — yalnız `blender -P` subprocess'i ile çalıştırılır (pytest bu
dosyayı import etmez; bpy'siz ortamda import zaten patlardı). O yüzden bpy import'u
main() içinde tutulur, modül seviyesinde değil.
"""
from __future__ import annotations

import json
import os
import sys

# Bayrak verilmezse uygulanan varsayılan = eski kalibre denim ayarları
# (common.fabrics "denim" ile AYNI; bu dosya Blender python'unda çalıştığı için
# common import edilmez, değerler burada sabit tutulur).
_DEFAULT_CLOTH = {
    "quality": 6,
    "tension_stiffness": 80.0,
    "compression_stiffness": 80.0,
    "shear_stiffness": 40.0,
    "bending_stiffness": 0.5,
}


def _pop_flag(argv: list[str], flag: str) -> tuple[list[str], str | None]:
    """argv'den `flag <değer>` çiftini çıkar; (kalan argv, değer|None) döndür."""
    if flag not in argv:
        return argv, None
    i = argv.index(flag)
    if i + 1 >= len(argv):
        raise SystemExit(f"{flag} bir dosya yolu bekliyor")
    return argv[:i] + argv[i + 2:], argv[i + 1]


def _load_fabric(path: str | None) -> dict:
    """--fabric JSON'unu oku; yoksa/boşsa varsayılan (denim) ayarlar."""
    if not path:
        return dict(_DEFAULT_CLOTH)
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise SystemExit("--fabric JSON bir nesne olmalı")
    return data


def _parse_args() -> tuple[str, str, int, str | None, dict]:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    argv, fabric_path = _pop_flag(argv, "--fabric")
    if len(argv) < 2:
        raise SystemExit("kullanım: -- <in.glb> <out.glb> [frames] [collider.glb]")
    in_glb = argv[0]
    out_glb = argv[1]
    frames = int(argv[2]) if len(argv) > 2 else 40
    collider = (argv[3] or None) if len(argv) > 3 else None
    return in_glb, out_glb, max(2, frames), collider, _load_fabric(fabric_path)


def main() -> None:
    import bpy  # Blender-only; bkz. modül docstring

    in_glb, out_glb, frames, collider, fabric = _parse_args()

    # Boş sahne ile başla (varsayılan küp/kamera/ışık olmadan).
    bpy.ops.wm.read_factory_settings(use_empty=True)

    bpy.ops.import_scene.gltf(filepath=in_glb)
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        raise SystemExit("GLB içinde mesh bulunamadı")
    # Kumaş = EN ÇOK poligonlu mesh (girdide eski simülasyonlardan sızmış zemin
    # düzlemleri olabilir — 2026-07-06 canlı vakası: 4×20m Plane; ilk mesh'i almak
    # düzlemi kumaş sanabilirdi). Kumaş dışındaki girdi mesh'lerini sahneden sil.
    cloth = max(meshes, key=lambda o: len(o.data.polygons))
    for o in meshes:
        if o is not cloth:
            bpy.data.objects.remove(o, do_unlink=True)

    # ASKI (pin) noktaları: kumaşın DÜNYA-Z ekseninde en üstteki %12'lik dilimindeki
    # vertisler sabitlenir → kıyafet omuzlarından asılı kalır, aşağısı sarkarak katlanır.
    # (Blender GLTF import sonrası Z-up; girdide translation-only serbest düşüş yerine
    #  gerçek deformasyon üretmek için pin ŞART — pinsiz kumaş bir bütün olarak düşer.)
    mtx = cloth.matrix_world
    world_zs = [(mtx @ v.co).z for v in cloth.data.vertices]
    z_min = min(world_zs)
    z_max = max(world_zs)
    z_span = z_max - z_min
    # Dejenere (düz) mesh'te bile en az bir vertex pinlensin; aksi halde her şey düşer.
    z_threshold = z_max - 0.12 * z_span if z_span > 0 else z_max
    pin_group = cloth.vertex_groups.new(name="pin")
    pinned = [i for i, z in enumerate(world_zs) if z >= z_threshold]
    if not pinned:  # z_span==0 veya kayan-nokta uç durumu — hiç değilse en üst vertex.
        top = max(range(len(world_zs)), key=lambda i: world_zs[i])
        pinned = [top]
    pin_group.add(pinned, 1.0, "REPLACE")

    # Collider: verilen manken GLB'si, yoksa basit büyük yer düzlemi (düşme temeli).
    if collider and os.path.exists(collider):
        before = set(bpy.context.scene.objects)
        bpy.ops.import_scene.gltf(filepath=collider)
        for obj in set(bpy.context.scene.objects) - before:
            if obj.type == "MESH":
                obj.modifiers.new("Collision", type="COLLISION")
    else:
        # NOT (ölçüm günlüğü 2026-07-06): kıyafet İÇİNE elipsoit gövde collider'ı
        # denendi — kollu tişörtte bbox genişliği kol uçlarını kapsadığından elipsoit
        # kumaşı deldi ve çözücü patladı (X %770). Gövde-collider'lı "giyilmiş drape"
        # için doğru yol MANKEN collider'ı (transformuyla) geçirmek — faz 2.
        bpy.ops.mesh.primitive_plane_add(size=20, location=(0.0, 0.0, 0.0))
        ground = bpy.context.active_object
        ground.modifiers.new("Collision", type="COLLISION")

    # Cloth modifier'ı kumaş mesh'ine ekle.
    bpy.context.view_layer.objects.active = cloth
    cloth_mod = cloth.modifiers.new("Cloth", type="CLOTH")
    # Pin grubunu kütle-vertex grubu olarak bağla → o vertisler sabit kalır (askı).
    cloth_mod.settings.vertex_group_mass = "pin"
    # Simülasyon kalitesini biraz artır (daha kararlı katlanma, daha az patlama).
    cloth_mod.settings.quality = 6
    # Denim-benzeri sertlik (Blender denim preset değerleri). Ölçüm günlüğü
    # (2026-07-06): pin'li SERBEST asılı tişört gövdesiz her ayarla ya sakızlaşıyor
    # (Y %130-230 uzama) ya da yüksek sertlikte patlıyor — çözüm sertlik değil,
    # kumaşın İÇİNE gövde collider'ı koymak (aşağıda). Sertlik yine denim kalsın:
    # AYAR GÜNLÜĞÜ (2026-07-06, canlı ölçümler — kalibre edilmiş en iyi konfig):
    #   g9.8+t15 (varsayılan): Y %230 uzama | g9.8+t80: %133 (EN İYİ stabil)
    #   g9.8+t200+q12+m0.15: patlama | torso elipsoit: patlama (%770)
    #   g1.5+t80+bend10: %159 (düşük g = savrulma). → t80/g9.8/bend0.5/q6 sabitlendi.
    # SINIR: gövdesiz asılı kıyafet "giyilmiş" duramaz; bu bir ASKI simülasyonudur
    # (deneysel). Gerçek giyilmiş drape = manken collider + transform (faz 2).
    # Kumaş ayarları: --fabric JSON'u (common.fabrics) ya da varsayılan denim.
    # Bilinmeyen anahtar (Blender sürüm farkı vb.) atlanır, sim yine koşar.
    for key, val in fabric.items():
        if hasattr(cloth_mod.settings, key):
            setattr(cloth_mod.settings, key, val)
        else:
            print(f"[drape] uyarı: bilinmeyen cloth ayarı atlandı: {key}")

    # Simülasyon aralığını ayarla ve frame frame ilerleyerek cloth cache'ini pişir.
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = int(frames)
    for f in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(f)

    # Deforme olmuş SON frame'i mesh'e PİŞİR (bake). export_apply=True cloth gibi
    # frame-bağımlı simülasyon modifier'larını YENİDEN dinlenme (rest) pozunda
    # değerlendirir → çıktı deforme OLMAZ (2026-07-06 ölçümü: bbox girdiyle aynı).
    # Bu yüzden evaluated depsgraph'tan son-frame mesh'ini alıp objeye yazıp
    # modifier'ı kaldırıyoruz; böylece sarkma kalıcı geometriye işlenmiş olur.
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_cloth = cloth.evaluated_get(depsgraph)
    baked = bpy.data.meshes.new_from_object(eval_cloth)
    old_mesh = cloth.data
    cloth.modifiers.clear()
    cloth.data = baked
    bpy.data.meshes.remove(old_mesh)

    # YALNIZ kumaşı export et — zemin/collider düzlemleri GLB'ye SIZMASIN
    # (canlı vaka: beyaz 20m düzlem "Projeye uygula" ile mesh'e girdi).
    out_dir = os.path.dirname(out_glb)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    cloth.select_set(True)
    bpy.context.view_layer.objects.active = cloth
    bpy.ops.export_scene.gltf(filepath=out_glb, export_format="GLB",
                              use_selection=True, export_apply=True)


if __name__ == "__main__":
    main()
