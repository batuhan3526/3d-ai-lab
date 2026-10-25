import { api } from "./client";
import type { Job, GenerateParams, DressOption } from "../types";
import { useAuth } from "../store/auth";

// dress_job_id: üretim SUCCESS olunca otomatik başlayan giydirme işi (dress verilmediyse null).
export type GenerateOut = { job_id: string; project_id: string; dress_job_id?: string | null };

// dress opsiyonel (trailing): verilmezse body'ye HİÇ girmez → istek birebir eskisi gibi.
export const generateText = (p: GenerateParams, dress?: DressOption | null) =>
  api<GenerateOut>("/generate/text", {
    method: "POST",
    body: JSON.stringify(dress ? { ...p, dress } : p),
  });

// Multipart uçlarda dress = JSON string form alanı (yalnız verildiyse eklenir).
const withDress = (form: FormData, dress?: DressOption | null) => {
  if (dress) form.append("dress", JSON.stringify(dress));
  return form;
};

export const generateImage = (form: FormData, dress?: DressOption | null) =>
  fetch("/api/generate/image", {
    method: "POST",
    headers: { Authorization: `Bearer ${useAuth.getState().token ?? ""}` },
    body: withDress(form, dress),
  }).then(async (r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json() as Promise<GenerateOut>;
  });

export const generateMultiImage = (form: FormData, dress?: DressOption | null) =>
  fetch("/api/generate/multi-image", {
    method: "POST",
    headers: { Authorization: `Bearer ${useAuth.getState().token ?? ""}` },
    body: withDress(form, dress),
  }).then(async (r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json() as Promise<GenerateOut>;
  });

// gpu opsiyonel: verilmezse body'den düşer → backend settings.default_gpu doldurur (tek-GPU sözleşmesi).
export const retexture = (source_project_id: string, prompt: string, prompt_enhance: boolean, gpu?: number) =>
  api<{ job_id: string; project_id: string }>("/generate/retexture", {
    method: "POST",
    body: JSON.stringify({ source_project_id, prompt, gpu, prompt_enhance }),
  });

// UltraTex: modeli bir referans görsele göre yeniden dokula (şekil aynı kalır).
// Görsel verilmezse kaynak projenin konsept görseli kullanılır.
export const retextureImage = (source_project_id: string, file?: File | null) => {
  const form = new FormData();
  form.append("source_project_id", source_project_id);
  if (file) form.append("file", file);
  return fetch("/api/generate/retexture-image", {
    method: "POST",
    headers: { Authorization: `Bearer ${useAuth.getState().token ?? ""}` },
    body: form,
  }).then(async (r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json() as Promise<{ job_id: string; project_id: string }>;
  });
};

// F5 v2: sadece işaretli UV bölgesini yeniden dokula (maske = UV-uzayı PNG)
// gpu opsiyonel: verilmezse form'a hiç girmez → backend default_gpu doldurur (tek-GPU sözleşmesi).
export const retextureRegion = (
  source_project_id: string,
  prompt: string,
  prompt_enhance: boolean,
  mask: Blob,
  gpu?: number,
) => {
  const form = new FormData();
  form.append("mask", mask, "mask.png");
  form.append("source_project_id", source_project_id);
  form.append("prompt", prompt);
  if (gpu !== undefined) form.append("gpu", String(gpu));
  form.append("prompt_enhance", String(prompt_enhance));
  return fetch("/api/generate/retexture-region", {
    method: "POST",
    headers: { Authorization: `Bearer ${useAuth.getState().token ?? ""}` },
    body: form,
  }).then(async (r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json() as Promise<{ job_id: string; project_id: string }>;
  });
};

// Stil transferi kaynağı: yüklenen görselden normalize kutu (+opsiyonel AI).
export type StyleSource = { image_name: string; crop: [number, number, number, number]; ai: boolean };

// Stil görseli yükle -> image_name (sonra style.image_name olarak kullanılır).
export const uploadStyleImage = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  return fetch("/api/generate/style-upload", {
    method: "POST",
    headers: { Authorization: `Bearer ${useAuth.getState().token ?? ""}` },
    body: form,
  }).then(async (r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json() as Promise<{ image_name: string }>;
  });
};

// İşaretli bölgeye motif: FLUX ile 2D motif üret + matte -> mevcut projeye decal PNG.
// Kaynak: prompt YA DA style (stil transferi). Yeni proje OLUŞTURMAZ.
// gpu opsiyonel (trailing): verilmezse backend default_gpu doldurur.
// engine_id opsiyonel (trailing): yerel "flux-motif" (varsayılan) ise body'ye HİÇ
// eklenmez → yerel istek birebir aynı kalır; bulut motorları için gönderilir.
export const DEFAULT_MOTIF_ENGINE = "flux-motif";
const motifEngineField = (engine_id?: string) =>
  engine_id && engine_id !== DEFAULT_MOTIF_ENGINE ? { engine_id } : {};

export const generateMotif = (
  project_id: string, prompt: string, prompt_enhance: boolean,
  style?: StyleSource | null, gpu?: number, engine_id?: string,
) =>
  api<{ job_id: string; project_id: string }>("/generate/motif", {
    method: "POST",
    body: JSON.stringify({
      project_id, prompt, gpu, prompt_enhance, style: style ?? null,
      ...motifEngineField(engine_id),
    }),
  });

// Motif decal PNG'sinin token'sız servis URL'i (<Decal>/TextureLoader header gönderemez).
export const decalUrl = (projectId: string, relPath: string) =>
  `/api/projects/${projectId}/${relPath}`;

// BATCH-F: PBR kanal fırçası çıktısı. UV-uzayı grayscale PNG dataURL'leri —
// gri değer = kanalın 0-1 değeri (slider), şeffaflık = boyalı maske. Alan yoksa
// bake bugünkü davranışı (yalnız albedo); worker glTF metallicRoughnessTexture paketler.
export type PbrChannels = { roughness?: string; metallic?: string };

// İşaretli bölgeye motif DOKU olarak: FLUX motif üret + UV texture'a 3B projeksiyonla
// pişir → YENİ proje (decal değil, dokuya gömülü, dışa aktarımda kalıcı).
// channels opsiyonel (BATCH-F): verilmezse bugünkü davranış birebir korunur.
// gpu opsiyonel (trailing): verilmezse backend default_gpu doldurur.
export const generateMotifBake = (
  source_project_id: string, prompt: string,
  center: [number, number, number], normal: [number, number, number], scale: number,
  prompt_enhance: boolean, style?: StyleSource | null,
  channels?: PbrChannels | null, gpu?: number, engine_id?: string,
) =>
  api<{ job_id: string; project_id: string }>("/generate/motif-bake", {
    method: "POST",
    body: JSON.stringify({
      source_project_id, prompt, center, normal, scale, gpu, prompt_enhance,
      style: style ?? null, channels: channels ?? null,
      ...motifEngineField(engine_id),
    }),
  });

// Motifi tüm yüzeye desen olarak döşe → YENİ proje (dışa aktarılabilir doku).
// gpu opsiyonel: verilmezse backend default_gpu doldurur.
export const generateTile = (
  source_project_id: string, motif_rel: string, repeat: number, bg_color: string, gpu?: number,
) =>
  api<{ job_id: string; project_id: string }>("/generate/tile", {
    method: "POST",
    body: JSON.stringify({ source_project_id, motif_rel, repeat, bg_color, gpu }),
  });

// C1 foto ön-kırpma: fotoğrafı yükle → BiRefNet ile arka planı sil (flux worker).
// job SUCCESS olunca out_url (token'sız serve) kırpılmış RGBA PNG'yi gösterir.
export const matteImage = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  return fetch("/api/preprocess/matte", {
    method: "POST",
    headers: { Authorization: `Bearer ${useAuth.getState().token ?? ""}` },
    body: form,
  }).then(async (r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json() as Promise<{ job_id: string; out_url: string }>;
  });
};

// Ön-kırpma sonucunun token'sız servis URL'i (<img src> Authorization gönderemez).
export const matteUrl = (outUrl: string) => `/api${outUrl}`;

export const getJob = (id: string) => api<Job>(`/jobs/${id}`);

export function jobWsUrl(jobId: string): string {
  const token = useAuth.getState().token ?? "";
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/api/ws/jobs/${jobId}?token=${encodeURIComponent(token)}`;
}
