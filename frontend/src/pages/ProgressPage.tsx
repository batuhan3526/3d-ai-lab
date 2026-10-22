import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { jobWsUrl, getJob } from "../api/generate";
import { useT } from "../i18n";
import type { Job } from "../types";

const STAGE_KEYS: Record<string, string> = {
  shape: "progress.stageShape", paint: "progress.stagePaint", pack: "progress.stagePack",
};

export default function ProgressPage() {
  const { t } = useT();
  const { jobId } = useParams<{ jobId: string }>();
  const [params] = useSearchParams();
  const projectId = params.get("project");
  // Otomatik giydirme işi (GeneratePage "Üretimden sonra mankene giydir"): üretim SUCCESS
  // olunca ikinci aşama olarak izlenir; yoksa davranış eskisi gibi (SUCCESS → Designer).
  const dressJobId = params.get("dress");
  const navigate = useNavigate();
  const [job, setJob] = useState<Job | null>(null);
  const [dressJob, setDressJob] = useState<Job | null>(null);
  const [genDone, setGenDone] = useState(false);
  const [doneProjectId, setDoneProjectId] = useState<string | null>(null);
  const done = useRef(false);

  useEffect(() => {
    if (!jobId) return;
    function handle(j: Job) {
      setJob(j);
      if (done.current) return;
      if (j.state === "SUCCESS") {
        done.current = true;
        const pid = j.project_id ?? projectId;
        if (dressJobId) { setDoneProjectId(pid); setGenDone(true); }
        else navigate(`/design/${pid}`);
      }
    }
    const ws = new WebSocket(jobWsUrl(jobId));
    ws.onmessage = (e) => handle(JSON.parse(e.data) as Job);
    const poll = setInterval(async () => {
      try { handle(await getJob(jobId)); } catch { /* yoksay */ }
    }, 2000);
    return () => { ws.close(); clearInterval(poll); };
  }, [jobId, navigate, projectId, dressJobId]);

  // 2. aşama: giydirme işini SUCCESS/FAILURE'a kadar poll et. SUCCESS → Designer
  // (backend giydirilmiş mesh + pozlu manken + ölçüleri projeye zaten uyguladı).
  useEffect(() => {
    if (!genDone || !dressJobId) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function tick() {
      try {
        const j = await getJob(dressJobId!);
        if (stop) return;
        setDressJob(j);
        if (j.state === "SUCCESS") { navigate(`/design/${doneProjectId}`); return; }
        if (j.state === "FAILURE") return;
      } catch { /* yoksay — sonraki turda tekrar */ }
      if (!stop) timer = setTimeout(tick, 1500);
    }
    tick();
    return () => { stop = true; if (timer) clearTimeout(timer); };
  }, [genDone, dressJobId, doneProjectId, navigate]);

  const dressing = genDone && !!dressJobId;
  const dressFailed = dressing && dressJob?.state === "FAILURE";
  const pct = dressing ? (dressFailed ? 100 : dressJob?.percent ?? 50) : (job?.percent ?? 5);
  return (
    <div className="max-w-md mx-auto p-10 text-center space-y-4">
      <h1 className="text-lg">
        {dressing ? (dressFailed ? t("progress.dressFailed") : t("progress.dressTitle")) : t("progress.title")}
      </h1>
      {dressing && <p className="text-emerald-400 text-xs">{t("progress.genDone")}</p>}
      <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
        <div className={`h-full transition-all ${dressFailed ? "bg-red-500" : "bg-violet-500"}`} style={{ width: `${pct}%` }} />
      </div>
      <p className="text-zinc-400 text-sm">
        {dressing
          ? (dressFailed ? (dressJob?.error ?? "") : t("progress.dressing"))
          : job?.state === "FAILURE"
            ? t("progress.failed")
            : STAGE_KEYS[job?.stage ?? ""] ? t(STAGE_KEYS[job?.stage ?? ""]) : t("progress.starting")}
      </p>
      {!dressing && job?.state === "FAILURE" &&
        <button onClick={() => navigate("/generate")} className="underline text-violet-400">{t("progress.retry")}</button>}
      {/* Giydirme başarısız olsa da üretim tamam → tasarımı yine de açabilsin (sürerken de
          beklemeden geçilebilir; giydirme arka planda bitince projeye uygulanır). */}
      {dressing &&
        <button onClick={() => navigate(`/design/${doneProjectId}`)}
          className={dressFailed ? "underline text-violet-400" : "text-xs text-zinc-500 hover:text-zinc-300 underline"}>
          {dressFailed ? t("progress.openDesign") : t("progress.skipDress")}
        </button>}
    </div>
  );
}
