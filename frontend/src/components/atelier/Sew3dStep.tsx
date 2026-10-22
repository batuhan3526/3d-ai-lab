import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useT } from "../../i18n";
import { getPattern, sew3d } from "../../api/patterns";
import { listMannequins } from "../../api/mannequins";
import { getJob } from "../../api/generate";
import { useFabricCatalog } from "../../store/fabrics";
import type { Job } from "../../types";
import { Advanced, ErrorBox, Section, btnPrimary, friendlyError, inputCls, parseNum } from "./common";

// Adım 3 — 3D'de dik (F2): manken + kumaş seç → POST /patterns/{id}/sew3d →
// jobs API ile ilerleme (ProgressPage/DesignerPage'teki getJob poll deseni) →
// tamamlanınca "Tasarımda aç" (/design/<project_id>).

type Run = { jobId: string; projectId: string; job: Job | null };

export function Sew3dStep({ patternId, onGoPattern }: { patternId: string | null; onGoPattern: () => void }) {
  const { t, lang } = useT();
  const navigate = useNavigate();
  const metaQ = useQuery({
    queryKey: ["patterns", "meta", patternId],
    queryFn: () => getPattern(patternId!),
    enabled: !!patternId,
    retry: false,
  });
  const mannequinsQ = useQuery({ queryKey: ["mannequins"], queryFn: listMannequins, retry: false });
  const fabrics = useFabricCatalog((s) => s.fabrics);
  const fabricsDefault = useFabricCatalog((s) => s.defaultId);
  const fabricsError = useFabricCatalog((s) => s.error);
  const loadFabrics = useFabricCatalog((s) => s.load);
  useEffect(() => { void loadFabrics(); }, [loadFabrics]);

  const mannequins = (mannequinsQ.data ?? []).filter((m) => m.available !== false);
  const [mannequinId, setMannequinId] = useState<string | null>(null);
  const [fabricId, setFabricId] = useState<string | null>(null);
  const [frames, setFrames] = useState("60");
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    if (!mannequinId && mannequins.length) {
      setMannequinId((mannequins.find((m) => m.id === "female-a") ?? mannequins[0]).id);
    }
  }, [mannequins, mannequinId]);
  useEffect(() => {
    if (!fabricId && fabrics?.length) setFabricId(fabricsDefault ?? fabrics[0].id);
  }, [fabrics, fabricsDefault, fabricId]);

  // İş takibi: 1.5 sn'de bir poll; bitince durur. Bileşen kapanınca da durur.
  const runRef = useRef<Run | null>(null);
  runRef.current = run;
  useEffect(() => {
    if (!run || run.job?.state === "SUCCESS" || run.job?.state === "FAILURE") return;
    let live = true;
    const id = setInterval(async () => {
      try {
        const job = await getJob(run.jobId);
        if (live && runRef.current?.jobId === run.jobId) setRun({ ...runRef.current, job });
      } catch { /* geçici ağ hatası — sonraki turda tekrar dene */ }
    }, 1500);
    return () => { live = false; clearInterval(id); };
  }, [run?.jobId, run?.job?.state]); // eslint-disable-line react-hooks/exhaustive-deps

  async function start() {
    setError(null);
    const f = parseNum(frames);
    if (f === null || f < 10 || f > 200) { setError(t("atelier.sew.framesInvalid")); return; }
    if (!mannequinId || !fabricId) { setError(t("atelier.sew.chooseBoth")); return; }
    setStarting(true);
    try {
      const res = await sew3d(patternId!, { mannequin_id: mannequinId, fabric_id: fabricId, frames: Math.round(f) });
      setRun({ jobId: res.job_id, projectId: res.project_id, job: null });
    } catch (e) {
      setError(friendlyError(e, t));
    } finally {
      setStarting(false);
    }
  }

  if (!patternId) {
    return (
      <Section title={t("atelier.sew.title")}>
        <p className="text-base text-zinc-300">{t("atelier.needPattern")}</p>
        <button type="button" onClick={onGoPattern} className={btnPrimary}>{t("atelier.goPattern")}</button>
      </Section>
    );
  }

  const meta = metaQ.data;
  if (meta && !meta.sew3d) {
    return (
      <Section title={t("atelier.sew.title")}>
        <p className="text-base text-amber-200">{t("atelier.sew.notSupported", { name: meta.label_tr })}</p>
        <button type="button" onClick={onGoPattern} className={btnPrimary}>{t("atelier.goPattern")}</button>
      </Section>
    );
  }

  const state = run?.job?.state;
  const running = !!run && state !== "SUCCESS" && state !== "FAILURE";
  const pct = Math.max(3, Math.min(100, run?.job?.percent ?? (running ? 3 : 0)));

  return (
    <div className="space-y-5">
      <Section title={t("atelier.sew.title")} hint={meta ? t("atelier.sew.hint", { name: meta.label_tr }) : undefined}>
        <ErrorBox message={metaQ.error ? friendlyError(metaQ.error, t) : null} />
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-zinc-300">{t("atelier.sew.mannequin")}</h3>
          {mannequinsQ.isLoading && <p className="text-sm text-zinc-400">{t("common.loading")}</p>}
          <ErrorBox message={mannequinsQ.error ? friendlyError(mannequinsQ.error, t) : null} />
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {mannequins.map((m) => (
              <button key={m.id} type="button" onClick={() => setMannequinId(m.id)} aria-pressed={m.id === mannequinId}
                className={`text-left rounded-xl border px-4 py-3 ${m.id === mannequinId
                  ? "border-violet-500 bg-violet-950/40 ring-2 ring-violet-500" : "border-zinc-800 bg-zinc-900 hover:border-zinc-600"}`}>
                <span className="block text-sm text-zinc-100">{m.label}</span>
                {m.custom && <span className="text-[11px] text-sky-300">{t("atelier.sew.customBadge")}</span>}
              </button>
            ))}
          </div>
        </div>

        <div className="space-y-2">
          <h3 className="text-sm font-medium text-zinc-300">{t("atelier.sew.fabric")}</h3>
          <ErrorBox message={fabricsError && !fabrics ? t("atelier.sew.fabricsError") : null} />
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
            {(fabrics ?? []).map((f) => (
              <button key={f.id} type="button" onClick={() => setFabricId(f.id)} aria-pressed={f.id === fabricId}
                className={`text-left rounded-xl border p-3 flex gap-3 ${f.id === fabricId
                  ? "border-violet-500 bg-violet-950/40 ring-2 ring-violet-500" : "border-zinc-800 bg-zinc-900 hover:border-zinc-600"}`}>
                <span className="h-10 w-10 shrink-0 rounded-lg border border-white/20" style={{ background: f.pbr.base_color }} />
                <span className="min-w-0">
                  <span className="block text-base text-zinc-100">{lang === "en" ? f.name_en : f.name_tr}</span>
                  <span className="block text-xs text-zinc-400 line-clamp-2">{f.desc_tr}</span>
                </span>
              </button>
            ))}
          </div>
        </div>

        <Advanced label={t("atelier.advanced")}>
          <label className="block space-y-1 max-w-xs">
            <span className="text-sm text-zinc-300">{t("atelier.sew.frames")}</span>
            <input inputMode="numeric" value={frames} onChange={(e) => setFrames(e.target.value)} className={inputCls} />
            <span className="text-xs text-zinc-500">{t("atelier.sew.framesHint")}</span>
          </label>
        </Advanced>

        <ErrorBox message={error} />
        <button type="button" disabled={starting || running || !meta} onClick={start} className={`${btnPrimary} w-full`}>
          {starting ? t("atelier.sew.starting") : running ? t("atelier.sew.running") : t("atelier.sew.run")}
        </button>
      </Section>

      {run && (
        <Section title={t("atelier.sew.progressTitle")}>
          <div className="h-3 bg-zinc-800 rounded-full overflow-hidden">
            <div className={`h-full transition-all ${state === "FAILURE" ? "bg-red-600" : state === "SUCCESS" ? "bg-emerald-500" : "bg-violet-500"}`}
              style={{ width: `${state === "SUCCESS" ? 100 : pct}%` }} />
          </div>
          {running && (
            <p className="text-base text-zinc-300">
              {t("atelier.sew.runningDetail", { pct: Math.round(pct) })}
              <span className="block text-xs text-zinc-500 mt-1">{t("atelier.sew.waitHint")}</span>
            </p>
          )}
          {state === "FAILURE" && (
            <ErrorBox message={run.job?.error ? `${t("atelier.sew.failed")} ${run.job.error}` : t("atelier.sew.failed")} />
          )}
          {state === "SUCCESS" && (
            <>
              <p className="text-base text-emerald-300">{t("atelier.sew.done")}</p>
              <button type="button" onClick={() => navigate(`/design/${run.job?.project_id ?? run.projectId}`)}
                className={`${btnPrimary} w-full`}>
                {t("atelier.sew.openDesign")}
              </button>
            </>
          )}
        </Section>
      )}
    </div>
  );
}
