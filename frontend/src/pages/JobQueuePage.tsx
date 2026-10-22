import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listJobs, type JobListItem } from "../api/jobs";
import { useT } from "../i18n";

const KIND_KEY: Record<string, string> = {
  text: "jobs.kindText", image: "jobs.kindImage", "multi-image": "jobs.kindMultiImage",
  motif: "jobs.kindMotif", "motif-bake": "jobs.kindMotifBake", retexture: "jobs.kindRetexture",
  "retexture-region": "jobs.kindRetextureRegion", tile: "jobs.kindTile",
};
const RUNNING = new Set(["SUBMITTED", "STARTED", "PROGRESS"]);

function badge(state: string) {
  if (state === "SUCCESS") return "bg-emerald-600/80";
  if (state === "FAILURE") return "bg-red-600/80";
  return "bg-amber-600/80";
}

export default function JobQueuePage() {
  const { t } = useT();
  const navigate = useNavigate();
  const { data = [] } = useQuery({
    queryKey: ["jobs-list"], queryFn: listJobs,
    refetchInterval: (q) => {
      const rows = (q.state.data as JobListItem[] | undefined) ?? [];
      return rows.some((j) => RUNNING.has(j.state)) ? 2000 : 5000;
    },
  });
  const running = data.filter((j) => RUNNING.has(j.state));
  const done = data.filter((j) => !RUNNING.has(j.state));

  const row = (j: JobListItem) => (
    <li key={j.job_id} className="flex items-center gap-3 bg-zinc-800 rounded-lg px-3 py-2 text-sm">
      <span className={`text-xs rounded px-2 py-0.5 ${badge(j.state)}`}>{j.state}</span>
      <span className="text-zinc-300">{KIND_KEY[j.kind ?? ""] ? t(KIND_KEY[j.kind ?? ""]) : (j.kind ?? t("jobs.kindDefault"))}</span>
      {RUNNING.has(j.state) && j.percent != null && (
        <div className="flex-1 h-1.5 rounded-full bg-zinc-700 overflow-hidden max-w-[200px]">
          <div className="h-full bg-violet-500" style={{ width: `${j.percent}%` }} />
        </div>
      )}
      <span className="flex-1" />
      {j.project_id && j.state === "SUCCESS" && (
        <button onClick={() => navigate(`/design/${j.project_id}`)}
          className="text-violet-400 hover:text-violet-300 text-xs">{t("jobs.open")}</button>
      )}
    </li>
  );

  return (
    <div className="min-h-screen p-6 max-w-3xl mx-auto">
      <button onClick={() => navigate("/dashboard")} className="text-zinc-400 text-sm">{t("jobs.back")}</button>
      <h1 className="text-xl font-semibold my-4">{t("jobs.title")}</h1>

      <h2 className="text-sm text-zinc-400 mb-2">{t("jobs.running", { n: running.length })}</h2>
      <ul className="space-y-1 mb-6">
        {running.map(row)}
        {running.length === 0 && <li className="text-xs text-zinc-600">{t("jobs.noneRunning")}</li>}
      </ul>

      <h2 className="text-sm text-zinc-400 mb-2">{t("jobs.recent", { n: done.length })}</h2>
      <ul className="space-y-1">
        {done.map(row)}
        {done.length === 0 && <li className="text-xs text-zinc-600">{t("jobs.noneDone")}</li>}
      </ul>
    </div>
  );
}
