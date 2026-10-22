"""Blender-tarafı FBX dışa-aktarma betiği — Task E (2026-07-06).

`blender -b -P blender_export.py -- <in.glb> <out.fbx>` biçiminde ÇAĞRILIR.
Gateway venv'i DEĞİL, Blender'ın gömülü Python yorumlayıcısı içinde koşar; bu
yüzden yalnız `bpy` + stdlib kullanır (gateway bağımlılıkları burada YOK).

Akış: fabrika ayarlarına dön (boş sahne) → glTF/GLB'yi içe aktar → FBX'e aktar.
`--` işaretinden sonraki argümanlar sırasıyla girdi GLB ve çıktı FBX yollarıdır
(Blender kendi argümanlarını `--`'den önce tüketir; biz sonrasını okuruz).
"""
import sys


def main() -> int:
    import bpy  # yalnız Blender içinde mevcut

    argv = sys.argv
    if "--" not in argv:
        sys.stderr.write("blender_export: '--' ayıracından sonra argüman yok\n")
        return 2
    args = argv[argv.index("--") + 1:]
    if len(args) < 2:
        sys.stderr.write("blender_export: girdi ve çıktı yolu gerekli\n")
        return 2
    in_glb, out_fbx = args[0], args[1]

    # Boş sahneden başla (varsayılan küp/kamera/ışık gelmesin).
    bpy.ops.wm.read_factory_settings(use_empty=True)
    # GLB/glTF içe aktar.
    bpy.ops.import_scene.gltf(filepath=in_glb)
    # FBX'e aktar (binary; dokular gömülü).
    bpy.ops.export_scene.fbx(filepath=out_fbx, path_mode="COPY", embed_textures=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
