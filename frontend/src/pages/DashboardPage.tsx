import { useEffect, useRef, useState } from "react";
import { useNavigate, Navigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { listProjects, deleteProject, duplicateProject, thumbnailUrl, meshUrl, uploadThumbnail } from "../api/projects";
import { getManifest } from "../api/templates";
import { assetUrl } from "../api/client";
import { useAuth } from "../store/auth";
import GpuStatusPanel from "../components/GpuStatusPanel";
import VramControls from "../components/VramControls";
import { SystemMetrics } from "../components/SystemMetrics";
import { createThumbnailer } from "../lib/thumbnailer";
import { useT } from "../i18n";
import type { Project } from "../types";

// Mesh üretmeyen motorlar: kart Designer yerine Sonuçlar sayfasına açılır.
const OUTPUT_ENGINES = new Set(["faceanything-4d", "gaussiangpt-scene"]);
const isOutputs = (p: Project) => !p.mesh_path && OUTPUT_ENGINES.has(p.engine_id ?? "");

export default function DashboardPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const clear = useAuth((s) => s.clear);
  const { t } = useT();

  const { data: projects, isLoading, isError } = useQuery({
    queryKey: ["projects"],
    queryFn: listProjects,
  });

  // Eksik thumbnail'ları arka planda doldur (mesh'i olup önizlemesi olmayanlar).
  // Tek gizli renderer ile sırayla üret + kaydet; bir kez çalışır, sonra normal resim olarak görünür.
  const backfilledRef = useRef(false);
  const [thumbProgress, setThumbProgress] = useState<{ done: number; total: number } | null>(null);
  useEffect(() => {
    if (!projects || backfilledRef.current) return;
    const missing = projects.filter((p) => !p.thumbnail_path);
    if (missing.length === 0) return;
    backfilledRef.current = true;
    let cancelled = false;
    (async () => {
      // Üretilen tasarımlar mesh.glb'den; şablon-başlangıçları manifest'teki template GLB'sinden.
      const manifest = await getManifest().catch(() => null);
      const urlFor = (p: typeof missing[number]): string | null => {
        if (p.mesh_path) return meshUrl(p.id);
        const g = manifest?.garments.find((x) => x.type === p.garment_type);
        const tpl = g?.templates.find((t) => t.id === p.template_id);
        return tpl ? assetUrl(tpl.glb) : null;
      };
      const thumber = createThumbnailer();
      let done = 0;
      setThumbProgress({ done: 0, total: missing.length });
      for (const p of missing) {
        if (cancelled) break;
        const url = urlFor(p);
        if (url) {
          try {
            const blob = await thumber.render(url);
            if (blob) await uploadThumbnail(p.id, blob);
          } catch { /* bu projeyi atla */ }
        }
        done += 1;
        setThumbProgress({ done, total: missing.length });
      }
      thumber.dispose();
      if (!cancelled) {
        setThumbProgress(null);
        qc.invalidateQueries({ queryKey: ["projects"] });
      }
    })();
    return () => { cancelled = true; };
  }, [projects, qc]);

  const del = useMutation({
    mutationFn: deleteProject,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });

  // listProjects 401 -> api client token'ı temizledi -> login'e dön.
  if (isError) return <Navigate to="/login" replace />;

  return (
    <div className="max-w-5xl mx-auto p-8">
      <header className="flex items-center justify-between mb-8">
        <h1 className="text-2xl font-semibold">{t("dashboard.title")}</h1>
        <div className="flex items-center gap-3">
          <VramControls />
          <button onClick={() => navigate("/storage")}
            className="text-sm text-zinc-400 hover:text-zinc-200">
            {t("dashboard.storage")}
          </button>
          <button onClick={() => navigate("/jobs")}
            className="text-sm text-zinc-400 hover:text-zinc-200">
            {t("dashboard.jobs")}
          </button>
          <button onClick={() => navigate("/new")}
            className="bg-violet-600 hover:bg-violet-500 rounded-lg px-4 py-2 font-medium">
            {t("dashboard.newDesign")}
          </button>
          <button onClick={() => { clear(); navigate("/login"); }}
            className="border border-zinc-700 rounded-lg px-4 py-2 text-zinc-400">
            {t("dashboard.logout")}
          </button>
        </div>
      </header>

      <section className="mb-8">
        <h2 className="text-[11px] font-semibold uppercase tracking-wide text-zinc-400 mb-2">{t("dashboard.systemMetrics")}</h2>
        <SystemMetrics layout="grid" />
      </section>

      {isLoading && <p className="text-zinc-500">{t("common.loading")}</p>}
      {thumbProgress && (
        <p className="text-zinc-500 text-sm mb-3">
          {t("dashboard.thumbProgress", { done: thumbProgress.done, total: thumbProgress.total })}
        </p>
      )}

      {projects && projects.length === 0 && (
        <p className="text-zinc-500">{t("dashboard.empty")}</p>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {projects?.map((p) => (
          <div key={p.id}
            className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden group">
            <button onClick={() => navigate(isOutputs(p) ? `/outputs/${p.id}` : `/design/${p.id}`)} className="block w-full text-left">
              <div className="aspect-square bg-zinc-800 flex items-center justify-center">
                {p.thumbnail_path
                  ? <img src={thumbnailUrl(p.id)} alt={p.name} className="w-full h-full object-cover" />
                  : isOutputs(p)
                    ? <span className="text-sm bg-violet-600/20 text-violet-300 rounded-full px-3 py-1">{t("outputs.badge")}</span>
                    : <span className="text-4xl">👕</span>}
              </div>
              <div className="p-3">
                <div className="font-medium truncate">{p.name}</div>
                <div className="text-xs text-zinc-500">{p.garment_type}</div>
              </div>
            </button>
            <div className="flex border-t border-zinc-800">
              <button
                onClick={async (e) => {
                  e.stopPropagation();
                  await duplicateProject(p.id);
                  qc.invalidateQueries({ queryKey: ["projects"] });
                }}
                className="flex-1 text-xs text-zinc-400 py-1 hover:bg-zinc-800/60 transition-colors"
              >
                {t("dashboard.duplicate")}
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  if (confirm(t("dashboard.confirmDelete", { name: p.name }))) del.mutate(p.id);
                }}
                disabled={del.isPending}
                className="flex-1 text-xs text-red-400 py-1 hover:bg-red-950/30 disabled:opacity-40 transition-colors"
              >
                {del.isPending ? t("dashboard.deleting") : t("common.delete")}
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-10">
        <GpuStatusPanel />
      </div>
    </div>
  );
}
