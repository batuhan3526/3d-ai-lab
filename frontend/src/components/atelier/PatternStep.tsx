import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useT } from "../../i18n";
import {
  deletePattern, draftPattern, estimateMeasurements, getPattern, listDesigns, listPatterns,
  patternFileUrl, type PatternDesign,
} from "../../api/patterns";
import { listMannequins } from "../../api/mannequins";
import { BodyForm, BODY_DEFAULTS, toBody, type BodyDraft } from "./BodyForm";
import { SvgViewer } from "./SvgViewer";
import {
  Advanced, ErrorBox, Section, WarningList, btnDanger, btnPrimary, btnSecondary, friendlyError, inputCls, parseNum,
} from "./common";

// Adım 1 — Kalıp: tasarım seç → 5 ölçü → (Gelişmiş: tüm ölçüler, seçenekler,
// dikiş payı) → "Kalıbı oluştur" → SVG önizleme + PDF/SVG indir + parça listesi.
// Ayrıca kayıtlı kalıplar (aç / sil).

// Açı cinsinden ölçüler (FreeSewing): cm'e çevrilmez, derece olarak gösterilir.
const DEGREE_KEYS = new Set(["shoulderSlope"]);

function fmtDate(iso: string, lang: string) {
  try {
    return new Date(iso).toLocaleString(lang === "en" ? "en-GB" : "tr-TR", { dateStyle: "medium", timeStyle: "short" });
  } catch { return iso; }
}

export function PatternStep({
  patternId, onSelectPattern, onNext,
}: {
  patternId: string | null;
  onSelectPattern: (id: string | null) => void;
  onNext: () => void;
}) {
  const { t, lang } = useT();
  const qc = useQueryClient();
  const designsQ = useQuery({ queryKey: ["patterns", "designs"], queryFn: listDesigns, retry: false });
  const patternsQ = useQuery({ queryKey: ["patterns", "list"], queryFn: listPatterns, retry: false });
  const mannequinsQ = useQuery({ queryKey: ["mannequins"], queryFn: listMannequins, retry: false });

  const [designId, setDesignId] = useState<string>("teagan");
  const [body, setBody] = useState<BodyDraft>(BODY_DEFAULTS.female);
  const [options, setOptions] = useState<Record<string, string>>({});
  const [sa, setSa] = useState("10");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  // Gelişmiş: kullanıcının elle değiştirdiği ölçüler (FreeSewing anahtarı → metin, cm ya da °).
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);

  const designs = designsQ.data ?? [];
  const design: PatternDesign | undefined = designs.find((d) => d.id === designId);
  useEffect(() => {
    // Katalog gelince seçili tasarım listede yoksa ilkine geç.
    if (designs.length && !designs.some((d) => d.id === designId)) setDesignId(designs[0].id);
  }, [designs, designId]);
  useEffect(() => { setOptions({}); }, [designId]);

  const bodyValue = toBody(body);
  const estimateQ = useQuery({
    queryKey: ["patterns", "estimate", bodyValue],
    queryFn: () => estimateMeasurements(bodyValue!),
    enabled: advancedOpen && !!bodyValue,
    retry: false,
  });

  const shownKeys = useMemo(() => {
    const est = estimateQ.data?.measurements ?? {};
    const keys = design?.measurements?.length ? design.measurements : Object.keys(est);
    return keys.filter((k) => k in est || k in overrides);
  }, [design, estimateQ.data, overrides]);

  const draftMut = useMutation({
    mutationFn: async () => {
      setFormError(null);
      if (!bodyValue) throw new Error(t("atelier.body.invalid"));
      const saMm = parseNum(sa);
      if (saMm === null || saMm < 0 || saMm > 50) throw new Error(t("atelier.pattern.saInvalid"));
      const measurements: Record<string, number> = {};
      for (const [k, v] of Object.entries(overrides)) {
        const n = parseNum(v);
        if (n === null || n <= 0) throw new Error(t("atelier.pattern.measurementInvalid", { name: mLabel(k) }));
        measurements[k] = DEGREE_KEYS.has(k) ? n : Math.round(n * 10 * 10) / 10; // cm → mm
      }
      return draftPattern({
        design: designId,
        body: bodyValue,
        measurements: Object.keys(measurements).length ? measurements : undefined,
        options: Object.keys(options).length ? options : undefined,
        sa_mm: saMm,
      });
    },
    onSuccess: (res) => {
      onSelectPattern(res.pattern_id);
      qc.invalidateQueries({ queryKey: ["patterns", "list"] });
    },
    onError: (e) => setFormError(friendlyError(e, t)),
  });

  const metaQ = useQuery({
    queryKey: ["patterns", "meta", patternId],
    queryFn: () => getPattern(patternId!),
    enabled: !!patternId,
    retry: false,
  });

  const delMut = useMutation({
    mutationFn: (id: string) => deletePattern(id),
    onSuccess: (_r, id) => {
      if (id === patternId) onSelectPattern(null);
      qc.invalidateQueries({ queryKey: ["patterns", "list"] });
    },
  });

  function mLabel(k: string) {
    const key = `atelier.m.${k}`;
    const s = t(key);
    return s === key ? k : s;
  }

  const meta = metaQ.data;

  return (
    <div className="space-y-5">
      <Section title={t("atelier.pattern.chooseTitle")} hint={t("atelier.pattern.chooseHint")}>
        {designsQ.isLoading && <p className="text-sm text-zinc-400">{t("common.loading")}</p>}
        <ErrorBox message={designsQ.error ? friendlyError(designsQ.error, t) : null} />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {designs.map((d) => (
            <button key={d.id} type="button" onClick={() => setDesignId(d.id)}
              aria-pressed={d.id === designId}
              className={`text-left rounded-xl border p-4 transition ${d.id === designId
                ? "border-violet-500 bg-violet-950/40 ring-2 ring-violet-500" : "border-zinc-800 bg-zinc-900 hover:border-zinc-600"}`}>
              <div className="flex items-start justify-between gap-2">
                <span className="text-base font-semibold text-zinc-100">{d.label_tr}</span>
                {d.sew3d && (
                  <span className="shrink-0 rounded-full bg-emerald-700/60 px-2 py-0.5 text-[11px] text-emerald-100">
                    {t("atelier.pattern.sew3dBadge")}
                  </span>
                )}
              </div>
              <p className="text-xs text-zinc-400 mt-0.5">
                {d.category_tr} · {t("atelier.pattern.difficulty")}: {"●".repeat(Math.max(1, d.difficulty))}
              </p>
              <p className="text-sm text-zinc-300 mt-2 line-clamp-2">{d.description_tr}</p>
            </button>
          ))}
        </div>
      </Section>

      <Section title={t("atelier.pattern.measureTitle")} hint={t("atelier.pattern.measureHint")}>
        <BodyForm value={body} onChange={setBody} savedMannequins={mannequinsQ.data} />

        <Advanced label={t("atelier.advanced")} onToggle={setAdvancedOpen}>
          {design && design.options.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {design.options.map((o) => (
                <label key={o.id} className="block space-y-1">
                  <span className="text-sm text-zinc-300">{o.label_tr}</span>
                  <select value={options[o.id] ?? o.default}
                    onChange={(e) => setOptions((s) => ({ ...s, [o.id]: e.target.value }))}
                    className={inputCls}>
                    {o.choices.map((c) => <option key={c.id} value={c.id}>{c.label_tr}</option>)}
                  </select>
                </label>
              ))}
            </div>
          )}
          <label className="block space-y-1 max-w-xs">
            <span className="text-sm text-zinc-300">{t("atelier.pattern.sa")}</span>
            <div className="relative">
              <input inputMode="decimal" value={sa} onChange={(e) => setSa(e.target.value)} className={`${inputCls} pr-12`} />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-zinc-500">mm</span>
            </div>
            <span className="text-xs text-zinc-500">{t("atelier.pattern.saHint")}</span>
          </label>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium text-zinc-300">{t("atelier.pattern.allMeasurements")}</span>
              {Object.keys(overrides).length > 0 && (
                <button type="button" onClick={() => setOverrides({})} className="text-xs text-violet-300 underline">
                  {t("atelier.pattern.resetMeasurements")}
                </button>
              )}
            </div>
            <p className="text-xs text-zinc-500">{t("atelier.pattern.allMeasurementsHint")}</p>
            {estimateQ.isLoading && <p className="text-sm text-zinc-400">{t("common.loading")}</p>}
            <ErrorBox message={estimateQ.error ? friendlyError(estimateQ.error, t) : null} />
            {estimateQ.data && (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                {shownKeys.map((k) => {
                  const deg = DEGREE_KEYS.has(k);
                  const est = estimateQ.data!.measurements[k];
                  const estTxt = est === undefined ? "" : deg ? String(est) : (est / 10).toFixed(1);
                  const edited = k in overrides;
                  return (
                    <label key={k} className="block space-y-0.5">
                      <span className={`text-xs ${edited ? "text-violet-300" : "text-zinc-400"}`}>{mLabel(k)}</span>
                      <div className="relative">
                        <input inputMode="decimal" value={edited ? overrides[k] : estTxt}
                          onChange={(e) => setOverrides((s) => ({ ...s, [k]: e.target.value }))}
                          className="w-full rounded-lg bg-zinc-800 border border-zinc-700 px-2 py-1.5 pr-9 text-sm text-zinc-100" />
                        <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-zinc-500">{deg ? "°" : "cm"}</span>
                      </div>
                    </label>
                  );
                })}
              </div>
            )}
          </div>
        </Advanced>

        <ErrorBox message={formError} />
        <button type="button" disabled={draftMut.isPending || !design} onClick={() => draftMut.mutate()}
          className={`${btnPrimary} w-full`}>
          {draftMut.isPending ? t("atelier.pattern.drafting") : t("atelier.pattern.create")}
        </button>
      </Section>

      {patternId && (
        <Section title={t("atelier.pattern.resultTitle")}
          hint={meta ? `${meta.label_tr} · ${fmtDate(meta.created_at, lang)}` : undefined}>
          {metaQ.isLoading && <p className="text-sm text-zinc-400">{t("common.loading")}</p>}
          <ErrorBox message={metaQ.error ? friendlyError(metaQ.error, t) : null} />
          <SvgViewer src={patternFileUrl(patternId, "pattern.svg", meta?.created_at)} alt={t("atelier.pattern.resultTitle")} />
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <a href={patternFileUrl(patternId, "pattern.pdf")} download className={`${btnPrimary} text-center`}>
              {t("atelier.pattern.downloadPdf")}
            </a>
            <a href={patternFileUrl(patternId, "pattern.svg")} download className={`${btnSecondary} text-center py-3`}>
              {t("atelier.pattern.downloadSvg")}
            </a>
          </div>
          <p className="text-xs text-zinc-500">{t("atelier.pattern.printHint")}</p>
          {meta && (
            <>
              <WarningList items={meta.warnings} />
              <div>
                <h3 className="text-sm font-medium text-zinc-300 mb-2">{t("atelier.pattern.pieces")}</h3>
                <ul className="divide-y divide-zinc-800 rounded-xl border border-zinc-800">
                  {meta.pieces.map((p) => (
                    <li key={p.name} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
                      <span className="text-zinc-100">
                        {p.label_tr}
                        {p.mirror && p.fold_edge && (
                          <span className="ml-2 text-xs text-sky-300">{t("atelier.pattern.onFold")}</span>
                        )}
                        {p.mirror && !p.fold_edge && (
                          <span className="ml-2 text-xs text-sky-300">{t("atelier.pattern.pair")}</span>
                        )}
                      </span>
                      <span className="text-zinc-400 shrink-0">
                        {t("atelier.pattern.cutCount", { n: p.mirror && !p.fold_edge ? p.quantity * 2 : p.quantity })}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            </>
          )}
          <button type="button" onClick={onNext} className={`${btnPrimary} w-full`}>
            {t("atelier.pattern.next")}
          </button>
        </Section>
      )}

      <Section title={t("atelier.pattern.savedTitle")}>
        {patternsQ.isLoading && <p className="text-sm text-zinc-400">{t("common.loading")}</p>}
        <ErrorBox message={patternsQ.error ? friendlyError(patternsQ.error, t) : null} />
        <ErrorBox message={delMut.error ? friendlyError(delMut.error, t) : null} />
        {patternsQ.data && patternsQ.data.length === 0 && (
          <p className="text-sm text-zinc-500">{t("atelier.pattern.savedEmpty")}</p>
        )}
        <ul className="space-y-2">
          {(patternsQ.data ?? []).map((p) => (
            <li key={p.pattern_id}
              className={`flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3 ${p.pattern_id === patternId
                ? "border-violet-500 bg-violet-950/30" : "border-zinc-800 bg-zinc-900"}`}>
              <div className="min-w-0 flex-1">
                <p className="text-base text-zinc-100">{p.label_tr}</p>
                <p className="text-xs text-zinc-500">
                  {fmtDate(p.created_at, lang)} · {t("atelier.pattern.pieceCount", { n: p.pieces.length })}
                </p>
              </div>
              <button type="button" onClick={() => onSelectPattern(p.pattern_id)} className={btnSecondary}>
                {t("atelier.pattern.open")}
              </button>
              <button type="button" disabled={delMut.isPending}
                onClick={() => { if (window.confirm(t("atelier.pattern.confirmDelete", { name: p.label_tr }))) delMut.mutate(p.pattern_id); }}
                className={btnDanger}>
                {t("common.delete")}
              </button>
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}
