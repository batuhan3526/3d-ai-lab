import { useState } from "react";
import type { Measurements } from "../types";
import { downloadBlob } from "../lib/recordTurntable";
import { useT } from "../i18n";

// Terzi ölçüleri tablosu (otomatik giydirme sonrası customizations.measurements).
// Kopyala = sekmeyle ayrılmış düz metin (tabloya/mesaja yapıştırılabilir); CSV istemci tarafında üretilir.
const fmt = (n?: number) => (typeof n === "number" && Number.isFinite(n) ? n.toFixed(1) : "");

export function MeasurementsTable({ m, mannequinLabel, fileBase }: {
  m: Measurements;
  mannequinLabel?: string;
  fileBase: string;   // CSV dosya adı tabanı (proje adı)
}) {
  const { t, lang } = useT();
  const [copied, setCopied] = useState(false);
  // Satır etiketi: bilinen anahtar → i18n; bilinmeyen → backend'in Türkçe etiketi.
  const label = (key: string, fallback: string) => {
    const k = `measure.${key}`;
    const v = t(k);
    return v === k ? fallback : v;
  };
  const header = [t("measure.colName"), t("measure.colGarment"), t("measure.colBody"), t("measure.colEase")];
  const rows = m.rows.map((r) => [label(r.key, r.label_tr), fmt(r.garment_cm), fmt(r.body_cm), fmt(r.ease_cm)]);

  async function copy() {
    const lines = [
      `${t("measure.height")}: ${fmt(m.height_cm)} cm`,
      header.join("\t"),
      ...rows.map((r) => r.map((c) => c || "-").join("\t")),
    ];
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* clipboard izni yok (http LAN) — sessiz */ }
  }

  function downloadCsv() {
    // TR Excel ';' ayırıcı + ondalık virgül bekler; EN'de ',' + nokta.
    const sep = lang === "tr" ? ";" : ",";
    const num = (c: string) => (lang === "tr" ? c.replace(".", ",") : c);
    const esc = (c: string) => (/[";,\n]/.test(c) ? `"${c.replace(/"/g, '""')}"` : c);
    const lines = [
      header.map(esc).join(sep),
      ...rows.map(([name, ...nums]) => [esc(name), ...nums.map(num)].join(sep)),
      "",
      [esc(t("measure.height")), num(fmt(m.height_cm))].join(sep),
    ];
    // BOM: Excel UTF-8'i (ğ/ş/ı) doğru açsın.
    const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
    downloadBlob(blob, `${fileBase.replace(/[^\w.-]+/g, "_") || "olculer"}_olculer.csv`);
  }

  return (
    <div className="space-y-1.5" data-testid="measurements-table">
      <div className="flex items-center justify-between">
        <h4 className="text-xs text-zinc-300">✂️ {t("measure.title")}</h4>
        <div className="flex gap-1">
          <button onClick={copy} className="rounded px-2 py-0.5 text-[11px] bg-zinc-800 hover:bg-zinc-700">
            {copied ? t("measure.copied") : t("measure.copy")}
          </button>
          <button onClick={downloadCsv} className="rounded px-2 py-0.5 text-[11px] bg-zinc-800 hover:bg-zinc-700">
            {t("measure.csv")}
          </button>
        </div>
      </div>
      <p className="text-[11px] text-zinc-500">
        {t("measure.heightLine", { cm: fmt(m.height_cm) })}
        {mannequinLabel ? ` · ${mannequinLabel}` : ""}
      </p>
      <table className="w-full text-[11px] tabular-nums">
        <thead>
          <tr className="text-zinc-500 border-b border-zinc-800">
            {header.map((h, i) => (
              <th key={h} className={`py-1 font-normal ${i === 0 ? "text-left" : "text-right"}`}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={m.rows[i].key} className="border-b border-zinc-900">
              {r.map((c, j) => (
                <td key={j} className={`py-1 ${j === 0 ? "text-left text-zinc-300" : "text-right text-zinc-200"}`}>
                  {c || <span className="text-zinc-600">—</span>}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
