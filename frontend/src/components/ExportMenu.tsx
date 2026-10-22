import { useState } from "react";
import JSZip from "jszip";
import type { Project } from "../types";
import { useDesign } from "../store/design";
import { useAuth } from "../store/auth";
import { useT } from "../i18n";
import { api, ApiError } from "../api/client";
import { glbToUsdz } from "../lib/arExport";

type RetopoResult = {
  variation_id: string;
  faces_before: number;
  faces_after: number;
  glb_url: string;
};

function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** 3D print / Blender formatları: sunucu tarafı trimesh dönüşümü. */
function downloadMeshFormat(projectId: string, ext: string, safeName: string) {
  const a = document.createElement("a");
  a.href = `/api/projects/${projectId}/mesh.${ext}`;
  a.download = `${safeName}.${ext}`;
  a.click();
}

/** R3: kanonik tam çözünürlük mesh.glb (view/decimate kopyası DEĞİL). GET /mesh
 * token'sız (public_router) → düz <a> yeter; faces=full decimate edilmemiş orijinali verir. */
function downloadFullMesh(projectId: string, safeName: string) {
  const a = document.createElement("a");
  a.href = `/api/projects/${projectId}/mesh?faces=full`;
  a.download = `${safeName}.glb`;
  a.click();
}

export function ExportMenu({
  project, getGlb, getPng,
}: {
  project: Project;
  getGlb: () => Promise<ArrayBuffer>;
  getPng: () => string;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [retopoBusy, setRetopoBusy] = useState(false);
  const [retopo, setRetopo] = useState<RetopoResult | null>(null);
  const [retopoErr, setRetopoErr] = useState<string | null>(null);
  const [export3dBusy, setExport3dBusy] = useState<"fbx" | "obj" | "usdz" | null>(null);
  const [export3dErr, setExport3dErr] = useState<string | null>(null);
  const toCustomizations = useDesign((s) => s.toCustomizations);
  const safeName = project.name.replace(/[^\w\-]+/g, "_");

  async function runRetopo() {
    setRetopoBusy(true);
    setRetopoErr(null);
    setRetopo(null);
    try {
      const res = await api<RetopoResult>(`/projects/${project.id}/retopo`, {
        method: "POST",
        body: JSON.stringify({ target_faces: 8000 }),
      });
      setRetopo(res);
    } catch (e) {
      // 422 = Instant Meshes kurulu değil (indirme beklemede).
      setRetopoErr(e instanceof ApiError && e.status === 422
        ? t("retopo.missing") : t("retopo.error"));
    } finally {
      setRetopoBusy(false);
    }
  }

  /** Sunucu-tarafı FBX/OBJ dışa-aktarma (Blender/trimesh köprüsü, authed indirme). */
  async function runExport3d(format: "fbx" | "obj") {
    setExport3dBusy(format);
    setExport3dErr(null);
    try {
      const { url } = await api<{ url: string; size_bytes: number }>(
        `/projects/${project.id}/export3d`,
        { method: "POST", body: JSON.stringify({ format }) },
      );
      // İndirme linki Authorization header ekleyemez → authed fetch + blob indir.
      const token = useAuth.getState().token;
      const resp = await fetch(`/api${url}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!resp.ok) throw new ApiError(resp.status, `HTTP ${resp.status}`);
      const blob = await resp.blob();
      download(blob, format === "obj" ? `${safeName}_obj.zip` : `${safeName}.fbx`);
      setOpen(false);
    } catch (e) {
      // 422 = Blender kurulu değil (indirme beklemede) ya da dönüşüm başarısız.
      setExport3dErr(e instanceof ApiError && e.status === 422
        ? t("exporting.blenderMissing") : t("exporting.export3dError"));
    } finally {
      setExport3dBusy(null);
    }
  }

  async function exportGlb() {
    const buf = await getGlb();
    download(new Blob([buf], { type: "model/gltf-binary" }), `${safeName}.glb`);
    setOpen(false);
  }

  function exportPng() {
    const dataUrl = getPng();
    fetch(dataUrl).then((r) => r.blob()).then((b) => download(b, `${safeName}.png`));
    setOpen(false);
  }

  async function exportZip() {
    const zip = new JSZip();
    const glb = await getGlb();
    const png = await (await fetch(getPng())).blob();
    zip.file("mesh.glb", glb);
    zip.file("thumbnail.png", png);
    zip.file("project.json", JSON.stringify({
      name: project.name, garment_type: project.garment_type,
      template_id: project.template_id, customizations: toCustomizations(),
    }, null, 2));
    const blob = await zip.generateAsync({ type: "blob" });
    download(blob, `${safeName}.zip`);
    setOpen(false);
  }

  function exportFormat(ext: string) {
    downloadMeshFormat(project.id, ext, safeName);
    setOpen(false);
  }

  /** R3: kanonik tam çözünürlük mesh.glb (görüntüleme düşük çözünürlükte olsa da
   * export tam çözünürlük olmalı). Yalnız üretilmiş (mesh_path) projelerde. */
  function exportGlbFull() {
    downloadFullMesh(project.id, safeName);
    setOpen(false);
  }

  /** USDZ (iOS Quick Look / bazı DCC'ler): tam çözünürlük GLB'yi client-side
   * çevirir (AR hattındaki glbToUsdz — sunucuya iş düşmez). */
  async function exportUsdz() {
    setExport3dBusy("usdz");
    setExport3dErr(null);
    try {
      const resp = await fetch(`/api/projects/${project.id}/mesh?faces=full`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const usdz = await glbToUsdz(await resp.arrayBuffer());
      download(usdz, `${safeName}.usdz`);
      setOpen(false);
    } catch (e) {
      setExport3dErr(e instanceof Error ? e.message : t("exporting.export3dError"));
    } finally {
      setExport3dBusy(null);
    }
  }

  return (
    <div className="relative">
      <button onClick={() => setOpen((o) => !o)}
        className="border border-zinc-700 rounded-lg px-4 py-1.5 text-sm">{t("export.button")}</button>
      {open && (
        <div className="absolute right-0 mt-1 bg-zinc-900 border border-zinc-800 rounded-lg overflow-hidden z-10 w-48">
          <button onClick={exportGlb} title={t("exporting.glbViewHint")}
            className="block w-full text-left px-4 py-2 text-sm hover:bg-zinc-800">{t("exporting.glbView")}</button>
          {project.mesh_path && (
            <>
              <button onClick={exportGlbFull} title={t("exporting.glbFullHint")}
                className="block w-full text-left px-4 py-2 text-sm hover:bg-zinc-800">{t("exporting.glbFull")}</button>
              <button onClick={() => exportFormat("stl")} className="block w-full text-left px-4 py-2 text-sm hover:bg-zinc-800">{t("export.stl")}</button>
              <button onClick={() => exportFormat("obj")} className="block w-full text-left px-4 py-2 text-sm hover:bg-zinc-800">{t("export.obj")}</button>
              <button onClick={() => exportFormat("ply")} className="block w-full text-left px-4 py-2 text-sm hover:bg-zinc-800">{t("export.ply")}</button>
              <button onClick={() => runExport3d("fbx")} disabled={export3dBusy !== null}
                title={t("exporting.fbxHint")}
                className="block w-full text-left px-4 py-2 text-sm hover:bg-zinc-800 disabled:opacity-50">
                {export3dBusy === "fbx" ? t("exporting.export3dWorking") : t("exporting.fbx")}
              </button>
              <button onClick={() => runExport3d("obj")} disabled={export3dBusy !== null}
                title={t("exporting.objTexturedHint")}
                className="block w-full text-left px-4 py-2 text-sm hover:bg-zinc-800 disabled:opacity-50">
                {export3dBusy === "obj" ? t("exporting.export3dWorking") : t("exporting.objTextured")}
              </button>
              <button onClick={exportUsdz} disabled={export3dBusy !== null}
                title={t("exporting.usdzHint")}
                className="block w-full text-left px-4 py-2 text-sm hover:bg-zinc-800 disabled:opacity-50">
                {export3dBusy === "usdz" ? t("exporting.export3dWorking") : t("exporting.usdz")}
              </button>
              {export3dErr && (
                <div className="px-4 py-2 text-xs text-rose-400">{export3dErr}</div>
              )}
            </>
          )}
          <button onClick={exportPng} className="block w-full text-left px-4 py-2 text-sm hover:bg-zinc-800">{t("export.png")}</button>
          <button onClick={exportZip} className="block w-full text-left px-4 py-2 text-sm hover:bg-zinc-800">{t("export.zip")}</button>
          {project.mesh_path && (
            <div className="border-t border-zinc-800">
              <button onClick={runRetopo} disabled={retopoBusy}
                title={t("retopo.buttonHint")}
                className="block w-full text-left px-4 py-2 text-sm hover:bg-zinc-800 disabled:opacity-50">
                {retopoBusy ? t("retopo.working") : t("retopo.button")}
              </button>
              {retopo && (
                <div className="px-4 py-2 text-xs text-zinc-400">
                  <div className="text-emerald-400">{t("retopo.done")}</div>
                  <div>{t("retopo.faces")}: {retopo.faces_before} → {retopo.faces_after}</div>
                </div>
              )}
              {retopoErr && (
                <div className="px-4 py-2 text-xs text-rose-400">{retopoErr}</div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
