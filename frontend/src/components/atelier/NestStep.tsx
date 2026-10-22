import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useT } from "../../i18n";
import { nestPattern, patternFileUrl, type NestResult } from "../../api/patterns";
import { SvgViewer } from "./SvgViewer";
import { Advanced, ErrorBox, Section, WarningList, btnPrimary, btnSecondary, friendlyError, inputCls, parseNum } from "./common";

// Adım 2 — Kumaşa yerleştir (F5 nesting): kumaş eni + boşluk → yerleşim planı,
// "x cm kumaş gerekir, verim %y" büyük yazıyla, uyarılar, nest.svg önizleme.

const WIDTH_PRESETS = [90, 110, 140, 150];

export function NestStep({ patternId, onGoPattern }: { patternId: string | null; onGoPattern: () => void }) {
  const { t } = useT();
  const [width, setWidth] = useState("150");
  const [gap, setGap] = useState("5");
  const [directional, setDirectional] = useState(false);
  const [result, setResult] = useState<{ id: string; res: NestResult; at: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const nestMut = useMutation({
    mutationFn: async () => {
      setError(null);
      const w = parseNum(width), g = parseNum(gap);
      if (w === null || w <= 0 || w > 1000) throw new Error(t("atelier.nest.widthInvalid"));
      if (g === null || g < 0 || g > 100) throw new Error(t("atelier.nest.gapInvalid"));
      return nestPattern(patternId!, {
        fabric_width_cm: w, gap_mm: g,
        // Desenli / tüylü kumaşta parçalar ters çevrilmez ve 180° döndürülmez.
        allow_flip: !directional, allow_rotate_180: !directional,
      });
    },
    onSuccess: (res) => setResult({ id: patternId!, res, at: Date.now() }),
    onError: (e) => setError(friendlyError(e, t)),
  });

  if (!patternId) {
    return (
      <Section title={t("atelier.nest.title")}>
        <p className="text-base text-zinc-300">{t("atelier.needPattern")}</p>
        <button type="button" onClick={onGoPattern} className={btnPrimary}>{t("atelier.goPattern")}</button>
      </Section>
    );
  }

  const shown = result && result.id === patternId ? result : null;

  return (
    <div className="space-y-5">
      <Section title={t("atelier.nest.title")} hint={t("atelier.nest.hint")}>
        <div className="space-y-2">
          <span className="text-sm text-zinc-300">{t("atelier.nest.width")}</span>
          <div className="flex flex-wrap gap-2">
            {WIDTH_PRESETS.map((w) => (
              <button key={w} type="button" onClick={() => setWidth(String(w))}
                className={`rounded-xl px-4 py-2.5 text-base ${width === String(w)
                  ? "bg-violet-600 text-white" : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700"}`}>
                {w} cm
              </button>
            ))}
          </div>
          <div className="relative max-w-xs">
            <input inputMode="decimal" value={width} onChange={(e) => setWidth(e.target.value)}
              aria-label={t("atelier.nest.width")} className={`${inputCls} pr-12`} />
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-zinc-500">cm</span>
          </div>
          <p className="text-xs text-zinc-500">{t("atelier.nest.widthHint")}</p>
        </div>
        <label className="flex items-start gap-3 rounded-xl bg-zinc-800/60 px-4 py-3 cursor-pointer">
          <input type="checkbox" checked={directional} onChange={(e) => setDirectional(e.target.checked)}
            className="mt-1 h-5 w-5 accent-violet-500" />
          <span>
            <span className="block text-base text-zinc-100">{t("atelier.nest.directional")}</span>
            <span className="block text-xs text-zinc-400">{t("atelier.nest.directionalHint")}</span>
          </span>
        </label>
        <Advanced label={t("atelier.advanced")}>
          <label className="block space-y-1 max-w-xs">
            <span className="text-sm text-zinc-300">{t("atelier.nest.gap")}</span>
            <div className="relative">
              <input inputMode="decimal" value={gap} onChange={(e) => setGap(e.target.value)} className={`${inputCls} pr-12`} />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-zinc-500">mm</span>
            </div>
            <span className="text-xs text-zinc-500">{t("atelier.nest.gapHint")}</span>
          </label>
        </Advanced>
        <ErrorBox message={error} />
        <button type="button" disabled={nestMut.isPending} onClick={() => nestMut.mutate()} className={`${btnPrimary} w-full`}>
          {nestMut.isPending ? t("atelier.nest.working") : t("atelier.nest.run")}
        </button>
      </Section>

      {shown && (
        <Section title={t("atelier.nest.resultTitle")}>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="rounded-xl bg-violet-950/50 border border-violet-800 p-4">
              <p className="text-sm text-violet-200">{t("atelier.nest.needLabel")}</p>
              <p className="text-3xl font-bold text-white mt-1">
                {t("atelier.nest.needValue", { cm: shown.res.used_length_cm.toFixed(1) })}
              </p>
              <p className="text-xs text-violet-300 mt-1">
                {t("atelier.nest.onWidth", { w: shown.res.fabric_width_cm })}
              </p>
            </div>
            <div className="rounded-xl bg-zinc-800/70 border border-zinc-700 p-4">
              <p className="text-sm text-zinc-300">{t("atelier.nest.efficiency")}</p>
              <p className="text-3xl font-bold text-white mt-1">%{shown.res.efficiency_pct.toFixed(1)}</p>
              <p className="text-xs text-zinc-400 mt-1">{t("atelier.nest.efficiencyHint")}</p>
            </div>
          </div>
          <WarningList items={shown.res.warnings} />
          <SvgViewer src={patternFileUrl(patternId, "nest.svg", shown.at)} alt={t("atelier.nest.resultTitle")} />
          <a href={patternFileUrl(patternId, "nest.svg", shown.at)} download className={`${btnSecondary} block text-center`}>
            {t("atelier.nest.download")}
          </a>
          <p className="text-xs text-zinc-500">{t("atelier.nest.legend")}</p>
        </Section>
      )}
    </div>
  );
}
