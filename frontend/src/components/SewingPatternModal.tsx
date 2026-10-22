import { useEffect, useRef, useState } from "react";
import { useT } from "../i18n";
import { api } from "../api/client";

// Task BATCH-G: "Dikiş kalıbı" modalı — gateway'e sewing-pattern isteği atar
// (xatlas unfold → gerçek ölçek chart poligonları → SVG 1:1 + A4-karo PDF).
// Chart özetini gösterir, SVG/PDF indirme linki verir. Servis GET public (mesh
// deseni) → düz <a> ile indirilir. Dürüst etiket: "deneysel — terzi kalıbı yaklaşığı".

interface Chart {
  polygon: [number, number][];
  seam_allowance: [number, number][];
  area_cm2: number;
}

interface SewingResult {
  svg_url: string;
  pdf_url: string;
  charts: Chart[];
  faces_in?: number | null;
  faces_used?: number | null;
  charts_total?: number | null;
  charts_drawn?: number | null;
  charts_dropped?: number | null;
  note: string;
}

type Phase = "form" | "working" | "ready" | "error";

export function SewingPatternModal({
  projectId,
  onClose,
}: {
  projectId: string;
  onClose: () => void;
}) {
  const { t } = useT();
  const [phase, setPhase] = useState<Phase>("form");
  const [height, setHeight] = useState("60");
  const [result, setResult] = useState<SewingResult | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [errorDetail, setErrorDetail] = useState<string | null>(null);
  const startRef = useRef(0);

  // Çalışırken geçen-saniye sayacı (açım büyük mesh'lerde uzun sürebilir; kullanıcı
  // takıldığını sanmasın diye canlı süre gösterilir).
  useEffect(() => {
    if (phase !== "working") return;
    startRef.current = Date.now();
    setElapsed(0);
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startRef.current) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [phase]);

  async function generate() {
    setErrorDetail(null);
    setPhase("working");
    const trimmed = height.trim();
    const h = trimmed === "" ? 100 : Number(trimmed);
    try {
      const body = await api<SewingResult>(`/projects/${projectId}/sewing-pattern`, {
        method: "POST",
        body: JSON.stringify({ height_cm: Number.isFinite(h) && h > 0 ? h : 100 }),
      });
      setResult(body);
      setPhase("ready");
    } catch (err) {
      console.error("sewing-pattern failed", err);
      setErrorDetail(err instanceof Error ? err.message : String(err));
      setPhase("error");
    }
  }

  const totalArea = result
    ? result.charts.reduce((s, c) => s + c.area_cm2, 0)
    : 0;

  return (
    <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="w-full max-w-md rounded-2xl bg-zinc-900 border border-zinc-800 p-6 space-y-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="font-medium text-zinc-100">{t("sewing.title")}</h2>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-200 text-xl">×</button>
        </div>
        <p className="text-xs text-amber-400">{t("sewing.experimental")}</p>

        {phase === "form" && (
          <div className="space-y-4">
            <label className="block space-y-1">
              <span className="text-sm text-zinc-300">{t("sewing.heightLabel")}</span>
              <input
                type="number"
                min={1}
                value={height}
                onChange={(e) => setHeight(e.target.value)}
                placeholder="60"
                className="w-full rounded-lg bg-zinc-800 border border-zinc-700 px-3 py-2 text-sm text-zinc-100"
              />
              <span className="text-xs text-zinc-500">{t("sewing.heightHint")}</span>
            </label>
            <button
              onClick={generate}
              className="w-full rounded-lg bg-violet-600 hover:bg-violet-500 px-4 py-2.5 text-sm text-white"
            >
              {t("sewing.generate")}
            </button>
          </div>
        )}

        {phase === "working" && (
          <div className="py-8 text-center space-y-2">
            <p className="text-sm text-zinc-400">
              {t("sewing.working")} {elapsed} {t("sewing.seconds")}
            </p>
            <p className="text-xs text-zinc-500">{t("sewing.expectation")}</p>
          </div>
        )}

        {phase === "error" && (
          <div className="py-8 text-center space-y-2">
            <p className="text-sm text-red-400">{t("sewing.error")}</p>
            {errorDetail && (
              <p className="text-xs text-red-300/80 break-words font-mono">{errorDetail}</p>
            )}
          </div>
        )}

        {phase === "ready" && result && (
          <div className="space-y-4">
            <div className="space-y-2 rounded-lg bg-zinc-800/50 p-4">
              <div className="flex items-center justify-between text-sm">
                <span className="text-zinc-400">{t("sewing.chartsCount")}</span>
                <span className="text-zinc-100 font-medium">
                  {result.charts_drawn ?? result.charts.length}
                </span>
              </div>
              {result.charts_dropped != null && result.charts_dropped > 0 && (
                <p className="text-xs text-zinc-500">
                  {t("sewing.droppedNote")
                    .replace("{dropped}", String(result.charts_dropped))
                    .replace("{total}", String(result.charts_total ?? ""))}
                </p>
              )}
              <div className="flex items-center justify-between text-sm">
                <span className="text-zinc-400">{t("sewing.totalArea")}</span>
                <span className="text-zinc-100 font-medium">{totalArea.toFixed(0)} cm²</span>
              </div>
              {result.faces_used != null && (
                <div className="flex items-center justify-between text-sm">
                  <span className="text-zinc-400">{t("sewing.facesUsed")}</span>
                  <span className="text-zinc-100 font-medium">
                    {result.faces_used.toLocaleString()}
                    {result.faces_in != null && result.faces_in !== result.faces_used
                      ? ` / ${result.faces_in.toLocaleString()}`
                      : ""}
                  </span>
                </div>
              )}
            </div>
            <p className="text-xs text-zinc-500">{t("sewing.legend")}</p>
            {/* GET public → düz link ile indirilir (Authorization gerekmez). */}
            <div className="grid grid-cols-2 gap-3">
              <a
                href={`/api${result.svg_url}`}
                download
                className="flex items-center justify-center rounded-lg bg-zinc-800 hover:bg-zinc-700 px-4 py-2.5 text-sm text-zinc-100"
              >
                {t("sewing.downloadSvg")}
              </a>
              <a
                href={`/api${result.pdf_url}`}
                download
                className="flex items-center justify-center rounded-lg bg-zinc-800 hover:bg-zinc-700 px-4 py-2.5 text-sm text-zinc-100"
              >
                {t("sewing.downloadPdf")}
              </a>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
