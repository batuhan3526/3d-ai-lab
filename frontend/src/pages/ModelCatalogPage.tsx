import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listEngines } from "../api/engines";
import { useT } from "../i18n";
import type { EngineSpec } from "../types";

const CAP_LABEL_KEYS: Record<string, string> = {
  "text-to-3d": "catalog.capText",
  "image-to-3d": "catalog.capImage",
  "multi-image-to-3d": "catalog.capMulti",
};

type TFn = (key: string, vars?: Record<string, string | number>) => string;

function gpuLine(e: EngineSpec, t: TFn): string {
  const allowed = (e.gpus ?? []).join("/");
  const gb = (e.vram_estimate_mb / 1000).toFixed(0);
  const rec = (e.gpus ?? []).includes(1) ? "1" : String((e.gpus ?? [0])[0]);
  return t("catalog.gpuLine", { allowed, rec, gb });
}

function isNonCommercial(license: string): boolean {
  return /non-commercial|ticari/i.test(license);
}

export default function ModelCatalogPage() {
  const navigate = useNavigate();
  const { t } = useT();
  const [open, setOpen] = useState<string | null>(null);
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["engines"], queryFn: listEngines, retry: 1,
  });

  const models = (data ?? [])
    .filter((m) => m.kind !== "edit")
    .sort((a, b) => (b.recommended ? 1 : 0) - (a.recommended ? 1 : 0));

  return (
    <div className="max-w-5xl mx-auto p-8">
      <button onClick={() => navigate("/dashboard")} className="text-zinc-400 mb-6">← {t("common.back")}</button>
      <h1 className="text-2xl font-semibold mb-2">{t("catalog.title")}</h1>
      <p className="text-zinc-400 mb-6">
        {t("catalog.subtitle")}
      </p>

      {isLoading && <p className="text-zinc-500">{t("catalog.loading")}</p>}
      {isError && (
        <div className="bg-amber-950/40 border border-amber-800 text-amber-200 rounded-lg px-3 py-2 mb-4">
          {t("catalog.error")}
          <button onClick={() => refetch()} className="ml-2 underline">{t("common.retry")}</button>
        </div>
      )}

      <div className="grid md:grid-cols-2 gap-4">
        {models.map((e) => {
          const seq = (e.device_modes ?? []).includes("sequential");
          const nc = isNonCommercial(e.license);
          const isOpen = open === e.id;
          const locked = !!e.cloud && !e.key_set;
          return (
            <div key={e.id} className={`bg-zinc-900 border rounded-xl p-5 flex flex-col ${e.recommended ? "border-violet-600" : e.cloud ? "border-sky-800" : "border-zinc-800"} ${locked ? "opacity-60" : ""}`}>
              {e.recommended && (
                <span className="self-start text-xs bg-violet-600 text-white rounded-full px-2.5 py-0.5 mb-2">
                  ⭐ {t("catalog.recommended")} · {e.recommended === "kalite" ? t("catalog.qualityGood") : t("catalog.fast")}
                </span>
              )}
              <div className="flex items-start justify-between gap-2">
                <h2 className="font-medium text-lg">{e.label}</h2>
                {e.cloud && (
                  <span className="text-[10px] px-2 py-0.5 rounded-full whitespace-nowrap bg-sky-900/60 text-sky-200 ml-auto">
                    {t("catalog.cloudBadge")}
                  </span>
                )}
                <span className={`text-[10px] px-2 py-0.5 rounded-full whitespace-nowrap ${nc ? "bg-amber-900/60 text-amber-200" : "bg-zinc-800 text-zinc-400"}`}>
                  {nc ? "⚠ " : ""}{e.license}
                </span>
              </div>
              {e.description && <p className="text-zinc-400 text-sm mt-1">{e.description}</p>}

              <div className="flex flex-wrap gap-1.5 mt-3">
                {(e.capabilities ?? []).map((c) => (
                  <span key={c} className="text-xs bg-violet-600/20 text-violet-300 border border-violet-700/40 rounded-full px-2 py-0.5">
                    {CAP_LABEL_KEYS[c] ? t(CAP_LABEL_KEYS[c]) : c}
                  </span>
                ))}
              </div>

              <div className="text-xs text-zinc-500 mt-3">
                {e.cloud ? t("catalog.noGpu") : gpuLine(e, t)}
                {e.cloud && e.price_note && (
                  <span className="ml-2 bg-sky-950/60 text-sky-200 rounded px-1.5 py-0.5">{e.price_note}</span>
                )}
                {seq && <span className="ml-2 bg-zinc-800 text-zinc-300 rounded px-1.5 py-0.5">{t("catalog.sequential")}</span>}
              </div>

              <button onClick={() => setOpen(isOpen ? null : e.id)} className="text-xs text-violet-400 mt-3 self-start">
                {isOpen ? `▾ ${t("catalog.hideDetails")}` : `▸ ${t("catalog.showParams", { count: e.params?.length ?? 0 })}`}
              </button>
              {isOpen && (
                <div className="mt-2 text-xs space-y-2 bg-zinc-950/50 rounded-lg p-3">
                  <div>
                    <span className="text-zinc-400">{t("catalog.qualityLevels")} </span>
                    {(e.quality_presets ?? []).join(", ") || "—"}
                  </div>
                  {(e.params ?? []).length > 0 ? (
                    <ul className="space-y-1">
                      {e.params.map((p) => (
                        <li key={p.key}>
                          <span className="text-zinc-200">{p.label}</span>
                          {p.desc && <span className="text-zinc-500"> — {p.desc}</span>}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-zinc-500">{t("catalog.noParams")}</p>
                  )}
                </div>
              )}

              {locked && (
                <p className="text-xs text-amber-300 mt-3">
                  {t("catalog.keyRequired", { key: e.requires_key ?? "API_KEY" })}
                </p>
              )}
              <button onClick={() => navigate(`/generate?engine=${e.id}`)} disabled={locked}
                className="bg-violet-600 hover:bg-violet-500 disabled:opacity-40 disabled:hover:bg-violet-600 disabled:cursor-not-allowed rounded-lg px-4 py-2 mt-4 self-start">
                {t("catalog.designWithModel")} →
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
