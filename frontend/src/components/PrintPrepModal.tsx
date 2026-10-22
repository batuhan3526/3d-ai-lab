import { useState } from "react";
import { useT } from "../i18n";
import { api } from "../api/client";

// Task E3: "🖨️ 3D baskıya hazırla" modalı — gateway'e print-prep isteği atar
// (trimesh: delik doldur + watertight kontrol + ölçek + STL). Raporu gösterir ve
// üretilen STL'i indirmeye link verir. STL servis GET public (mesh deseni), bu
// yüzden düz <a> ile indirilebilir.

interface PrintReport {
  watertight_before: boolean;
  watertight_after: boolean;
  holes_filled: number;
  dims_mm: [number, number, number];
  volume_cm3: number;
  stl_url: string;
}

type Phase = "form" | "working" | "ready" | "error";

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-zinc-400">{label}</span>
      <span className="text-zinc-100 font-medium">{value}</span>
    </div>
  );
}

export function PrintPrepModal({
  projectId,
  onClose,
}: {
  projectId: string;
  onClose: () => void;
}) {
  const { t } = useT();
  const [phase, setPhase] = useState<Phase>("form");
  const [height, setHeight] = useState("");
  const [report, setReport] = useState<PrintReport | null>(null);

  async function prepare() {
    setPhase("working");
    const trimmed = height.trim();
    const target = trimmed === "" ? null : Number(trimmed);
    try {
      const body = await api<PrintReport>(`/projects/${projectId}/print-prep`, {
        method: "POST",
        body: JSON.stringify({
          target_height_mm: target !== null && Number.isFinite(target) ? target : null,
        }),
      });
      setReport(body);
      setPhase("ready");
    } catch (err) {
      console.error("print-prep failed", err);
      setPhase("error");
    }
  }

  const yn = (v: boolean) => (v ? t("print.yes") : t("print.no"));

  return (
    <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="w-full max-w-md rounded-2xl bg-zinc-900 border border-zinc-800 p-6 space-y-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="font-medium text-zinc-100">{t("print.title")}</h2>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-200 text-xl">×</button>
        </div>

        {phase === "form" && (
          <div className="space-y-4">
            <label className="block space-y-1">
              <span className="text-sm text-zinc-300">{t("print.targetHeight")}</span>
              <input
                type="number"
                min={1}
                value={height}
                onChange={(e) => setHeight(e.target.value)}
                placeholder="200"
                className="w-full rounded-lg bg-zinc-800 border border-zinc-700 px-3 py-2 text-sm text-zinc-100"
              />
              <span className="text-xs text-zinc-500">{t("print.targetHeightHint")}</span>
            </label>
            <button
              onClick={prepare}
              className="w-full rounded-lg bg-violet-600 hover:bg-violet-500 px-4 py-2.5 text-sm text-white"
            >
              {t("print.prepare")}
            </button>
          </div>
        )}

        {phase === "working" && (
          <p className="text-sm text-zinc-400 py-8 text-center">{t("print.working")}</p>
        )}

        {phase === "error" && (
          <p className="text-sm text-red-400 py-8 text-center">{t("print.error")}</p>
        )}

        {phase === "ready" && report && (
          <div className="space-y-4">
            <div className="space-y-2 rounded-lg bg-zinc-800/50 p-4">
              <Row label={t("print.watertightBefore")} value={yn(report.watertight_before)} />
              <Row label={t("print.watertightAfter")} value={yn(report.watertight_after)} />
              <Row label={t("print.holesFilled")} value={report.holes_filled} />
              <Row
                label={t("print.dims")}
                value={report.dims_mm.map((d) => d.toFixed(1)).join(" × ")}
              />
              <Row label={t("print.volume")} value={report.volume_cm3.toFixed(2)} />
            </div>
            {/* STL GET public → düz link ile indirilir (Authorization gerekmez). */}
            <a
              href={`/api${report.stl_url}`}
              download
              className="flex items-center justify-center rounded-lg bg-zinc-800 hover:bg-zinc-700 px-4 py-2.5 text-sm text-zinc-100"
            >
              {t("print.download")}
            </a>
          </div>
        )}
      </div>
    </div>
  );
}
