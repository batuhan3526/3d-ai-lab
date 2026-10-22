import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useDesign } from "../store/design";
import { useMetrics } from "../store/metrics";
import { useT } from "../i18n";
import { M, Section } from "./MetricRow";
import { SystemMetrics } from "./SystemMetrics";

type HealthDeep = {
  status: "ok" | "degraded";
  redis: boolean;
  db: boolean;
  workers: Record<string, "ok" | "missing">;
};

// Backend /health/deep — redis/db/worker kuyruk sağlığı. 30 sn'de bir poll.
function WorkersSection() {
  const { t } = useT();
  const qc = useQueryClient();
  const { data, isError } = useQuery({
    queryKey: ["health-deep"],
    queryFn: () => api<HealthDeep>("/health/deep"),
    refetchInterval: 30000,
  });

  // T4: "Belleği boşalt" — GPU worker'larına engine.release fan-out'u (cache modu:
  // model önbelleğini boşaltır, VRAM/RAM iade eder). Sonrasında worker sağlığını tazele.
  const release = useMutation({
    mutationFn: () =>
      api<{ mode: string; released: unknown[] }>("/engines/release-all", {
        method: "POST",
        body: JSON.stringify({ mode: "cache" }),
      }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["health-deep"] }); },
  });

  const releaseControls = (
    <div className="space-y-1 border-t border-zinc-800/60 pt-2">
      <button
        onClick={() => release.mutate()}
        disabled={release.isPending}
        className="w-full rounded-lg px-3 py-1.5 text-xs bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50">
        {release.isPending ? t("metrics.releaseBusy") : `🧹 ${t("metrics.releaseButton")}`}
      </button>
      {release.isSuccess && (
        <p className="text-[11px] text-emerald-400">
          {release.data.released.length
            ? t("metrics.releaseDone", { n: release.data.released.length })
            : t("metrics.releaseNone")}
        </p>
      )}
      {release.isError && <p className="text-[11px] text-red-400">{t("metrics.releaseError")}</p>}
      <p className="text-[10px] leading-tight text-zinc-500">{t("metrics.releaseHint")}</p>
    </div>
  );

  if (isError) return (
    <div className="space-y-2">
      <p className="text-[11px] text-zinc-600">{t("metrics.workersError")}</p>
      {releaseControls}
    </div>
  );
  if (!data) return <p className="text-[11px] text-zinc-600">{t("metrics.workersLoading")}</p>;

  const queues = Object.entries(data.workers);
  const okCount = queues.filter(([, v]) => v === "ok").length;
  const degraded = data.status !== "ok";

  return (
    <div className="space-y-2">
      <div className={`text-xs font-medium ${degraded ? "text-amber-400" : "text-emerald-400"}`}>
        {degraded ? "⚠ " : "✓ "}
        {degraded ? t("metrics.workersStatusDegraded") : t("metrics.workersStatusOk")}
      </div>
      <M label={t("metrics.workersRedis")} value={data.redis ? t("metrics.workersUp") : t("metrics.workersDown")}
        desc="" />
      <M label={t("metrics.workersDb")} value={data.db ? t("metrics.workersUp") : t("metrics.workersDown")}
        desc="" />
      <M label={t("metrics.workersQueues")} value={t("metrics.workersSummary", { ok: okCount, total: queues.length })}
        desc={t("metrics.workersHint")} />
      <ul className="space-y-1">
        {queues.map(([q, v]) => (
          <li key={q} className="flex items-center justify-between text-[11px]">
            <span className="font-mono text-zinc-400">{q}</span>
            <span className={v === "ok" ? "text-emerald-400" : "text-zinc-600"}>
              {v === "ok" ? t("metrics.workersOk") : t("metrics.workersMissing")}
            </span>
          </li>
        ))}
      </ul>
      {releaseControls}
    </div>
  );
}

export function MetricsPanel() {
  const { t } = useT();
  const [open, setOpen] = useState(true); // varsayılan AÇIK — metrikler ilk bakışta görünsün
  const scene = useMetrics((s) => s.scene);
  const decalMetrics = useMetrics((s) => s.decal);
  const decals = useDesign((s) => s.decals);
  const selectedId = useDesign((s) => s.selectedId);
  const update = useDesign((s) => s.updateDecal);
  const sel = decals.find((d) => d.id === selectedId) ?? null;

  const dm = sel ? decalMetrics[sel.id] : undefined;
  const clip = dm ? Math.round((1 - dm.coverage) * 100) : 0;
  const depthFactor = sel?.depthFactor ?? 1.0;

  return (
    <div className="border-t border-zinc-800 pt-3">
      <button onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between text-sm text-zinc-300 hover:text-white">
        <span>📊 {t("metrics.panelTitle")}</span><span className="text-zinc-500">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="mt-3 space-y-4">
          <Section title={t("metrics.sectionSystem")}>
            <SystemMetrics layout="list" />
          </Section>

          <Section title={t("metrics.sectionWorkers")}>
            <WorkersSection />
          </Section>

          <Section title={t("metrics.sectionScene")}>
            <M label={t("metrics.fpsLabel")} value={`${scene.fps}`} desc={t("metrics.fpsDesc")} />
            <M label={t("metrics.trianglesLabel")} value={scene.triangles.toLocaleString()} desc={t("metrics.trianglesDesc")} />
            <M label={t("metrics.drawCallsLabel")} value={`${scene.drawCalls}`} desc={t("metrics.drawCallsDesc")} />
            <M label={t("metrics.texGeoLabel")} value={`${scene.textures} / ${scene.geometries}`} desc={t("metrics.texGeoDesc")} />
            <M label={t("metrics.meshResLabel")} value={t("metrics.meshResValue", { v: scene.meshVerts.toLocaleString(), f: scene.meshFaces.toLocaleString() })}
              desc={t("metrics.meshResDesc")} />
          </Section>

          <Section title={t("metrics.sectionDecal")}>
            {!sel && <p className="text-[11px] text-zinc-600">{t("metrics.selectDecal")}</p>}
            {sel && (
              <>
                <M label={t("metrics.fitLabel")} value={clip > 1 ? t("metrics.fitValuePartial", { fit: 100 - clip, clip }) : t("metrics.fitValueFull")}
                  bar={clip}
                  desc={clip > 15
                    ? t("metrics.fitDescBad")
                    : t("metrics.fitDescGood")} />
                <label className="block text-xs text-zinc-400">{t("metrics.projDepth", { d: depthFactor.toFixed(2) })}
                  <input type="range" min={0.05} max={1} step={0.01} value={depthFactor}
                    onChange={(e) => update(sel.id, { depthFactor: parseFloat(e.target.value) })} className="w-full" />
                </label>
                <p className="text-[10px] leading-tight text-zinc-500">
                  {t("metrics.projDepthHint")}
                </p>
                <M label={t("metrics.resLabel")} value={dm?.resW ? `${dm.resW}×${dm.resH} px` : "—"}
                  desc={t("metrics.resDesc")} />
                <M label={t("metrics.scaleLabel")} value={sel.scale.toFixed(2)} desc={t("metrics.scaleDesc")} />
                <M label={t("metrics.rotationLabel")} value={`${Math.round(((sel.spin ?? 0) * 180) / Math.PI)}°`} desc={t("metrics.rotationDesc")} />
                <M label={t("metrics.positionLabel")} value={sel.position.map((n) => n.toFixed(2)).join(", ")} desc={t("metrics.positionDesc")} />
              </>
            )}
          </Section>
        </div>
      )}
    </div>
  );
}
