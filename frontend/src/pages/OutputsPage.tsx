// Sonuçlar: mesh üretmeyen motorların (face4d, gaussiangpt-scene) çıktıları.
// Spec: docs/superpowers/specs/2026-07-12-outputs-viewer-design.md
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getProject, listOutputs, outputUrl, type OutputItem } from "../api/projects";
import type { Project } from "../types";
import PlyViewer from "../components/PlyViewer";
import { useT } from "../i18n";

export default function OutputsPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { t } = useT();
  const [project, setProject] = useState<Project | null>(null);
  const [items, setItems] = useState<OutputItem[] | null>(null);
  const [plyUrl, setPlyUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getProject(id), listOutputs(id)])
      .then(([p, o]) => { setProject(p); setItems(o); })
      .catch((e) => setError(String(e)));
  }, [id]);

  const group = (kind: OutputItem["kind"]) => (items ?? []).filter((i) => i.kind === kind);
  const dl = (i: OutputItem) => (
    <a href={outputUrl(id, i.path)} download={i.name}
      className="text-xs text-violet-400 hover:text-violet-300">{t("outputs.download")}</a>
  );

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 p-6">
      <div className="flex items-center gap-4 mb-6">
        <button onClick={() => navigate("/dashboard")}
          className="text-sm text-zinc-400 hover:text-zinc-200">{t("outputs.back")}</button>
        <h1 className="text-xl font-semibold">{t("outputs.title")}{project ? ` — ${project.name}` : ""}</h1>
        {project?.engine_id && (
          <span className="text-xs bg-zinc-800 rounded-full px-2 py-1 text-zinc-400">{project.engine_id}</span>
        )}
      </div>

      {error && <p className="text-red-400">{error}</p>}
      {!items && !error && <p className="text-zinc-500">{t("outputs.loading")}</p>}
      {items && items.length === 0 && <p className="text-zinc-500">{t("outputs.empty")}</p>}

      {group("video").length > 0 && (
        <section className="mb-8">
          <h2 className="text-sm font-medium text-zinc-400 mb-3">{t("outputs.videos")}</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {group("video").map((i) => (
              <div key={i.path} className="bg-zinc-900 border border-zinc-800 rounded-xl p-3">
                <video controls preload="metadata" className="w-full rounded-lg" src={outputUrl(id, i.path)} />
                <div className="flex justify-between items-center mt-2">
                  <span className="text-xs text-zinc-500 truncate">{i.name}</span>
                  {dl(i)}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {group("gif").length > 0 && (
        <section className="mb-8">
          <h2 className="text-sm font-medium text-zinc-400 mb-3">{t("outputs.gifs")}</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            {group("gif").map((i) => (
              <div key={i.path} className="bg-zinc-900 border border-zinc-800 rounded-xl p-3">
                <img src={outputUrl(id, i.path)} alt={i.name} className="w-full rounded-lg" />
                <div className="flex justify-between items-center mt-2">
                  <span className="text-xs text-zinc-500 truncate">{i.name}</span>
                  {dl(i)}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {group("ply").length > 0 && (
        <section className="mb-8">
          <h2 className="text-sm font-medium text-zinc-400 mb-3">{t("outputs.pointclouds")}</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {group("ply").map((i) => (
              <div key={i.path} className="bg-zinc-900 border border-zinc-800 rounded-xl p-3 flex flex-col gap-2">
                <span className="text-xs text-zinc-400 truncate">{i.path}</span>
                <span className="text-[10px] text-zinc-600">{(i.size / 1048576).toFixed(1)} MB</span>
                <div className="flex gap-3">
                  <button onClick={() => setPlyUrl(outputUrl(id, i.path))}
                    className="text-xs bg-violet-600/80 hover:bg-violet-600 rounded px-2 py-1">{t("outputs.view3d")}</button>
                  {dl(i)}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {plyUrl && <PlyViewer url={plyUrl} onClose={() => setPlyUrl(null)} />}
    </div>
  );
}
