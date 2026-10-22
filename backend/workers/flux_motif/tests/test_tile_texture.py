from pathlib import Path


def _make_motif_png(path: Path):
    from PIL import Image
    img = Image.new("RGBA", (64, 64), (255, 0, 0, 255))  # opak kırmızı kare
    img.save(path)


def test_build_tiled_texture_grid(tmp_path):
    from flux_motif_worker.tile import build_tiled_texture
    motif = tmp_path / "m.png"; _make_motif_png(motif)
    out = build_tiled_texture(str(motif), repeat=2, bg_color=(255, 255, 255), size=128)
    assert out.size == (128, 128)
    px = out.convert("RGB").load()
    # her hücrenin merkezi kırmızı (4 hücre)
    for cx, cy in [(32, 32), (96, 32), (32, 96), (96, 96)]:
        r, g, b = px[cx, cy]
        assert r > 200 and g < 60 and b < 60, f"hücre ({cx},{cy}) kırmızı değil: {(r,g,b)}"
