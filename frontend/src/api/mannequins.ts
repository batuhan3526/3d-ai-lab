import { api } from "./client";

// Mankenler: hazır taban mankenler + F3 ölçüden üretilmiş özel mankenler.
// GET /templates/mannequins ikisini birleşik döndürür (özel girdilerde custom:true).

export type BodyInput = {
  gender: "female" | "male";
  height_cm: number;
  chest_cm: number;
  waist_cm: number;
  hip_cm: number;
};

export type MannequinEntry = {
  id: string;
  label: string;
  file: string;
  url?: string;
  pose: "T" | "A";
  license: string;
  source_url: string;
  available?: boolean;
  custom?: boolean;
  base?: string;
  units?: string;
  body?: BodyInput;
  measured?: { height_cm: number; chest_cm: number; waist_cm: number; hip_cm: number };
  levels?: Record<string, number>;
};

export const listMannequins = () => api<MannequinEntry[]>("/templates/mannequins");

export const createCustomMannequin = (body: BodyInput & { label?: string }) =>
  api<MannequinEntry>("/mannequins/custom", {
    method: "POST",
    body: JSON.stringify(body),
    timeoutMs: 120_000,
  });

export const deleteCustomMannequin = (id: string) =>
  api<{ deleted: string }>(`/mannequins/custom/${encodeURIComponent(id)}`, { method: "DELETE" });
