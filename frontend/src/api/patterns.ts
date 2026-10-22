import { api } from "./client";
import type { BodyInput } from "./mannequins";

// F1 FreeSewing kalıpları + F5 kumaşa yerleştirme + F2 3D dikiş istemcisi.
// Dosya uçları (svg/pdf/pieces/nest.svg) public → düz <img>/<a> ile /api öneki
// üzerinden açılır (vite yalnız /api'yi gateway'e proxy'ler).

export type DesignChoice = { id: string; label_tr: string };
export type DesignOption = { id: string; label_tr: string; default: string; choices: DesignChoice[] };

export type PatternDesign = {
  id: string;
  label_tr: string;
  category: string;
  category_tr: string;
  description_tr: string;
  gender: string;
  difficulty: number;
  sew3d: boolean;
  measurements: string[];
  estimable: boolean;
  options: DesignOption[];
  license: string;
};

export type PieceSummary = { name: string; label_tr: string; quantity: number };

export type PatternSummary = {
  pattern_id: string;
  design: string;
  label_tr: string;
  sew3d: boolean;
  created_at: string;
  svg_url: string;
  pdf_url: string;
  pieces_url: string;
  pieces: PieceSummary[];
  warnings: string[];
};

export type PatternMeta = Omit<PatternSummary, "pieces"> & {
  category?: string;
  sa_mm: number;
  body?: BodyInput | null;
  measurements_source?: string;
  measurements: Record<string, number>;
  options?: Record<string, string>;
  svg_size_mm?: { width_mm: number; height_mm: number };
  fold_edges?: Record<string, string | null>;
  pieces: (PieceSummary & { mirror?: boolean; fold_edge?: string | null; area_cm2?: number })[];
};

export type DraftRequest = {
  design: string;
  body?: BodyInput;
  measurements?: Record<string, number>;
  options?: Record<string, string>;
  sa_mm?: number;
};

export type NestRequest = {
  fabric_width_cm: number;
  gap_mm?: number;
  allow_flip?: boolean;
  allow_rotate_180?: boolean;
};

export type NestPlacement = {
  piece: string;
  label_tr: string;
  copy: number;
  total: number;
  flipped: boolean;
  unfolded: boolean;
};

export type NestResult = {
  svg_url: string;
  json_url: string;
  pattern_id: string;
  used_length_cm: number;
  fabric_width_cm: number;
  efficiency_pct: number;
  pieces_area_cm2: number;
  gap_mm: number;
  verified: boolean;
  warnings: string[];
  placements: NestPlacement[];
};

export type Sew3dRequest = { mannequin_id: string; fabric_id: string; frames?: number };

export const listDesigns = () => api<PatternDesign[]>("/patterns/designs");

export const estimateMeasurements = (body: BodyInput) =>
  api<{ measurements: Record<string, number>; units: string; note: string }>(
    "/patterns/measurements/estimate",
    { method: "POST", body: JSON.stringify(body) },
  );

export const draftPattern = (req: DraftRequest) =>
  api<PatternSummary>("/patterns/draft", { method: "POST", body: JSON.stringify(req), timeoutMs: 120_000 });

export const listPatterns = () => api<PatternSummary[]>("/patterns");

export const getPattern = (id: string) => api<PatternMeta>(`/patterns/${encodeURIComponent(id)}`);

export const deletePattern = (id: string) =>
  api<{ deleted: string }>(`/patterns/${encodeURIComponent(id)}`, { method: "DELETE" });

export const nestPattern = (id: string, req: NestRequest) =>
  api<NestResult>(`/patterns/${encodeURIComponent(id)}/nest`, {
    method: "POST",
    body: JSON.stringify(req),
    timeoutMs: 120_000,
  });

export const sew3d = (id: string, req: Sew3dRequest) =>
  api<{ job_id: string; project_id: string }>(`/patterns/${encodeURIComponent(id)}/sew3d`, {
    method: "POST",
    body: JSON.stringify(req),
  });

/** Public kalıp dosyası URL'i (/api önekiyle). `bust` aynı adı taşıyan ama yeniden
 *  üretilen dosyada (ör. nest.svg) tarayıcı önbelleğini aşmak için. */
export function patternFileUrl(
  id: string,
  name: "pattern.svg" | "pattern.pdf" | "pieces.json" | "nest.svg" | "nest.json",
  bust?: string | number,
): string {
  const q = bust !== undefined ? `?v=${encodeURIComponent(String(bust))}` : "";
  return `/api/patterns/${encodeURIComponent(id)}/${name}${q}`;
}
