import { useCallback, useEffect, useRef, useState } from "react";
import { useT } from "../../i18n";

// Basit yakınlaştır/kaydır SVG önizleyici (kalıp ve kumaş yerleşimi). Bağımlılık
// yok: <img> + CSS transform. Fare tekeri / +− butonları ile yakınlaştırma, sürükle
// (fare ya da parmak) ile kaydırma, "Sığdır" ile tamamı ekrana.

const MIN_SCALE = 0.02;
const MAX_SCALE = 8;

export function SvgViewer({ src, alt, heightClass = "h-[55vh] min-h-[320px]" }: { src: string; alt: string; heightClass?: string }) {
  const { t } = useT();
  const boxRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const [view, setView] = useState({ x: 0, y: 0, s: 1 });
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const drag = useRef<{ px: number; py: number; x: number; y: number } | null>(null);

  const fit = useCallback(() => {
    const box = boxRef.current, img = imgRef.current;
    if (!box || !img || !img.naturalWidth) return;
    const pad = 16;
    const s = Math.min((box.clientWidth - pad * 2) / img.naturalWidth, (box.clientHeight - pad * 2) / img.naturalHeight);
    const sc = Math.max(MIN_SCALE, Math.min(MAX_SCALE, s));
    setView({
      s: sc,
      x: (box.clientWidth - img.naturalWidth * sc) / 2,
      y: (box.clientHeight - img.naturalHeight * sc) / 2,
    });
  }, []);

  useEffect(() => { setFailed(false); setLoaded(false); }, [src]);

  function zoomAt(factor: number, cx?: number, cy?: number) {
    const box = boxRef.current;
    if (!box) return;
    const px = cx ?? box.clientWidth / 2, py = cy ?? box.clientHeight / 2;
    setView((v) => {
      const s = Math.max(MIN_SCALE, Math.min(MAX_SCALE, v.s * factor));
      const k = s / v.s;
      return { s, x: px - (px - v.x) * k, y: py - (py - v.y) * k };
    });
  }

  // Teker: sayfa kaymasın diye pasif olmayan dinleyici (React onWheel pasiftir).
  useEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = box.getBoundingClientRect();
      zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX - r.left, e.clientY - r.top);
    };
    box.addEventListener("wheel", onWheel, { passive: false });
    return () => box.removeEventListener("wheel", onWheel);
  }, []);

  return (
    <div className="space-y-2">
      <div ref={boxRef}
        className={`relative overflow-hidden rounded-xl bg-white ${heightClass} cursor-grab active:cursor-grabbing`}
        style={{ touchAction: "none" }}
        onPointerDown={(e) => {
          (e.currentTarget as HTMLDivElement).setPointerCapture(e.pointerId);
          drag.current = { px: e.clientX, py: e.clientY, x: view.x, y: view.y };
        }}
        onPointerMove={(e) => {
          const d = drag.current;
          if (!d) return;
          setView((v) => ({ ...v, x: d.x + e.clientX - d.px, y: d.y + e.clientY - d.py }));
        }}
        onPointerUp={() => { drag.current = null; }}
        onPointerCancel={() => { drag.current = null; }}>
        {!failed && (
          <img ref={imgRef} src={src} alt={alt} draggable={false}
            onLoad={() => { setLoaded(true); fit(); }}
            onError={() => setFailed(true)}
            className="absolute left-0 top-0 max-w-none select-none"
            style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.s})`, transformOrigin: "0 0" }} />
        )}
        {!loaded && !failed && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-zinc-500">{t("common.loading")}</div>
        )}
        {failed && (
          <div className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-red-600">
            {t("atelier.preview.loadError")}
          </div>
        )}
      </div>
      <div className="flex items-center gap-2">
        <button type="button" onClick={() => zoomAt(1.3)} aria-label={t("atelier.preview.zoomIn")}
          className="rounded-lg bg-zinc-800 hover:bg-zinc-700 w-11 h-11 text-xl">+</button>
        <button type="button" onClick={() => zoomAt(1 / 1.3)} aria-label={t("atelier.preview.zoomOut")}
          className="rounded-lg bg-zinc-800 hover:bg-zinc-700 w-11 h-11 text-xl">−</button>
        <button type="button" onClick={fit} className="rounded-lg bg-zinc-800 hover:bg-zinc-700 h-11 px-4 text-sm">
          {t("atelier.preview.fit")}
        </button>
        <span className="text-xs text-zinc-500 ml-auto hidden sm:inline">{t("atelier.preview.help")}</span>
      </div>
    </div>
  );
}
