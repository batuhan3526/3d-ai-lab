import { api } from "./client";
import type { StyleSource } from "./generate";

export type VariationKind = "motif" | "style" | "drape" | "upscale" | "fit";

export type Variation = {
  id: string;
  group_id: string;
  project_id: string;
  kind: VariationKind;
  seed: number;
  prompt: string | null;
  job_id: string | null;
  status: "SUBMITTED" | "SUCCESS" | "FAILURE";
  result_path: string | null;
  thumbnail_path: string | null;
  size_bytes: number | null;
  favorite: boolean;
  created_at: string;
};

export type BatchJob = { job_id: string; variation_id: string; seed: number };
export type BatchResult = { group_id: string; jobs: BatchJob[] };

export type BatchRequest = {
  kind: VariationKind;
  project_id: string;
  count: number;
  prompt?: string;
  style?: StyleSource | null;
  gpu?: number;
  prompt_enhance?: boolean;
  seed_base?: number | null;
  engine_id?: string; // motif/stil motoru; yoksa gateway "flux-motif" kullanır
};

export const batchGenerate = (req: BatchRequest) =>
  api<BatchResult>("/generate/batch", {
    method: "POST",
    // Do not hardcode gpu: when omitted, the gateway fills settings.default_gpu
    // (0 on a single-GPU cloner). A caller may still pass req.gpu explicitly.
    body: JSON.stringify({ prompt_enhance: true, ...req }),
  });

export const listVariations = (groupId: string) =>
  api<Variation[]>(`/variations?group_id=${encodeURIComponent(groupId)}`);

// Kütüphane: tüm kayıtlı motifler (group_id yok → hepsi) veya sadece favoriler.
export const listLibrary = (favorite = false) =>
  api<Variation[]>(`/variations${favorite ? "?favorite=true" : ""}`);

export type StorageGroup = {
  group_id: string; kind: VariationKind; prompt: string | null;
  count: number; bytes: number; created_at: string; variations: Variation[];
};
export type Storage = { total_bytes: number; count: number; groups: StorageGroup[] };

export const getStorage = () => api<Storage>("/variations/storage");

export const addFavorite = (id: string) =>
  api<{ ok: boolean }>(`/variations/${id}/favorite`, { method: "POST" });
export const removeFavorite = (id: string) =>
  api<{ ok: boolean }>(`/variations/${id}/favorite`, { method: "DELETE" });
export const deleteVariation = (id: string) =>
  api<{ ok: boolean }>(`/variations/${id}`, { method: "DELETE" });
// F7: 3D varyantı (drape/upscale .glb sonucu) projenin mesh.glb'sinin üzerine yaz.
export const applyVariant = (id: string) =>
  api<{ ok: boolean; project_id: string }>(`/variations/${id}/apply`, { method: "POST" });
export const deleteVariationGroup = (groupId: string) =>
  api<{ deleted: number }>(`/variations/group/${encodeURIComponent(groupId)}`, { method: "DELETE" });
