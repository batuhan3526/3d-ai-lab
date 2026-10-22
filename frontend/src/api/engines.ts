import { api } from "./client";
import type { EngineSpec, GpuStatus } from "../types";

export const listEngines = () => api<EngineSpec[]>("/engines");

// /engines/status backend'i her family×gpu için sıralı Celery sorgusu yapar;
// offline worker başına 2.5s timeout = en kötü ~35s yanıt. Client timeout 6s yeterli:
// gateway cevap dönmezse panel "yükleniyor" durumunda kalır, sayfa kilitlenmez.
export const enginesStatus = () => api<GpuStatus[]>("/engines/status", { timeoutMs: 6000 });

export const releaseGpu = (family: string, gpu: number, mode: "cache" | "model") =>
  api<{ ok: boolean }>("/engines/release", {
    method: "POST",
    body: JSON.stringify({ family, gpu, mode }),
    timeoutMs: 10000,
  });

export const releaseAll = (mode: "cache" | "model") =>
  api<{ mode: string }>("/engines/release-all", {
    method: "POST",
    body: JSON.stringify({ mode }),
    timeoutMs: 30000,
  });
