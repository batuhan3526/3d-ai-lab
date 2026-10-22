import { useEffect, useRef, useState } from "react";
import { uploadStyleImage, type StyleSource } from "../api/generate";
import { useT } from "../i18n";

type Box = { x0: number; y0: number; x1: number; y1: number };

/** Stil transferi kaynağı: görsel yükle + üstünde sürükleyerek süslü bölgeyi seç.
 * Seçili kutu + AI bayrağını parent'a StyleSource olarak verir (motif/bake kaynağı). */
export function StyleTransferPanel({ style, setStyle }: {
  style: StyleSource | null;
  setStyle: (s: StyleSource | null) => void;
}) {
  const { t } = useT();
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [imageName, setImageName] = useState<string | null>(null);
  const [ai, setAi] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [box, setBox] = useState<Box | null>(null);
  const dragStart = useRef<{ x: number; y: number } | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);

  // Kaynak hazırsa parent'a bildir (image + geçerli kutu); değilse temizle.
  useEffect(() => {
    if (imageName && box) {
      const crop: [number, number, number, number] = [
        Math.min(box.x0, box.x1), Math.min(box.y0, box.y1),
        Math.max(box.x0, box.x1), Math.max(box.y0, box.y1),
      ];
      if (crop[2] - crop[0] >= 0.02 && crop[3] - crop[1] >= 0.02) {
        setStyle({ image_name: imageName, crop, ai });
        return;
      }
    }
    setStyle(null);
  }, [imageName, box, ai, setStyle]);

  async function onFile(f: File) {
    setPreviewUrl(URL.createObjectURL(f));
    setBox(null); setImageName(null);
    setUploading(true);
    try { const r = await uploadStyleImage(f); setImageName(r.image_name); }
    catch { setImageName(null); }
    finally { setUploading(false); }
  }

  function pt(e: React.MouseEvent) {
    const r = imgRef.current!.getBoundingClientRect();
    return {
      x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
      y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)),
    };
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-zinc-300">{t("style.title")}</p>
        {uploading && <span className="text-xs text-zinc-500">{t("style.uploading")}</span>}
      </div>
      <label className="block">
        <span className="text-xs text-zinc-400">{t("style.imageLabel")}</span>
        <input type="file" accept="image/*" className="block w-full text-xs mt-1"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); }} />
      </label>
      {previewUrl && (
        <>
          <p className="text-[11px] text-zinc-500">{t("style.dragHint")}</p>
          <div className="relative inline-block select-none w-full"
            onMouseDown={(e) => { dragStart.current = pt(e); setBox(null); }}
            onMouseMove={(e) => {
              if (!dragStart.current) return;
              const p = pt(e);
              setBox({ x0: dragStart.current.x, y0: dragStart.current.y, x1: p.x, y1: p.y });
            }}
            onMouseUp={() => { dragStart.current = null; }}
            onMouseLeave={() => { dragStart.current = null; }}>
            <img ref={imgRef} src={previewUrl} alt={t("style.previewAlt")} draggable={false}
              className="w-full rounded border border-zinc-700 block" />
            {box && (
              <div className="absolute border-2 border-violet-400 bg-violet-400/20 pointer-events-none"
                style={{
                  left: `${Math.min(box.x0, box.x1) * 100}%`,
                  top: `${Math.min(box.y0, box.y1) * 100}%`,
                  width: `${Math.abs(box.x1 - box.x0) * 100}%`,
                  height: `${Math.abs(box.y1 - box.y0) * 100}%`,
                }} />
            )}
          </div>
          <label className="flex items-center gap-2 text-xs text-zinc-300">
            <input type="checkbox" checked={ai} onChange={(e) => setAi(e.target.checked)} />
            {t("style.aiLabel")}
          </label>
          <p className="text-[11px] text-zinc-500">
            {style ? t("style.selected") : t("style.selectRegion")}
          </p>
        </>
      )}
    </div>
  );
}
