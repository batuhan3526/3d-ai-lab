import { api, ApiError } from "./client";
import type { Project, Customizations } from "../types";

export const listProjects = () => api<Project[]>("/projects");
export const getProject = (id: string) => api<Project>(`/projects/${id}`);

export const createProject = (body: {
  name: string;
  garment_type: string;
  template_id: string;
  customizations: Customizations;
}) => api<Project>("/projects", { method: "POST", body: JSON.stringify(body) });

export const updateProject = (
  id: string,
  body: { name?: string; customizations?: Customizations },
) => api<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(body) });

export const deleteProject = (id: string) =>
  api<void>(`/projects/${id}`, { method: "DELETE" });

export async function uploadThumbnail(id: string, png: Blob): Promise<void> {
  const form = new FormData();
  form.append("file", png, "thumbnail.png");
  // api() JSON varsayar; thumbnail için doğrudan fetch (Bearer header api() içinde değil)
  const { useAuth } = await import("../store/auth");
  const token = useAuth.getState().token;
  const resp = await fetch(`/api/projects/${id}/thumbnail`, {
    method: "PUT",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!resp.ok) throw new ApiError(resp.status, `Thumbnail upload başarısız: HTTP ${resp.status}`);
}

export const thumbnailUrl = (id: string) => `/api/projects/${id}/thumbnail`;
// F6: opsiyonel `faces` (görüntüleme çözünürlüğü) query param olarak eklenir;
// verilmezse gateway varsayılan viewer kopyasını (mesh_view.glb) servis eder.
export const meshUrl = (id: string, faces?: number) =>
  faces ? `/api/projects/${id}/mesh?faces=${faces}` : `/api/projects/${id}/mesh`;

export const duplicateProject = (id: string) =>
  api<Project>(`/projects/${id}/duplicate`, { method: "POST" });

// Sonuçlar (face4d/gaussian_scene çıktıları) — spec: 2026-07-12-outputs-viewer-design.md
export type OutputItem = { kind: "video" | "gif" | "ply"; name: string; path: string; size: number };
export const listOutputs = (id: string) => api<OutputItem[]>(`/projects/${id}/outputs`);
export const outputUrl = (id: string, path: string) => `/api/projects/${id}/outputs/${path}`;
