import { create } from "zustand";

// Render/decal metrikleri — 3D sahneden buraya yazılır, MetricsPanel okur.
// AYRI store: metrik tıkırtısı (FPS 2/sn) 3D sahneyi yeniden render ETMEZ.

export type SceneMetrics = {
  fps: number;
  triangles: number;
  drawCalls: number;
  textures: number;
  geometries: number;
  meshVerts: number;
  meshFaces: number;
};

export type DecalMetric = {
  coverage: number; // 0..1 — decal'ın yüzeye oturma oranı (1=tam; <1 kırpılıyor/kesik)
  resW: number;     // doku çözünürlüğü (px)
  resH: number;
};

const EMPTY_SCENE: SceneMetrics = {
  fps: 0, triangles: 0, drawCalls: 0, textures: 0, geometries: 0, meshVerts: 0, meshFaces: 0,
};

type MetricsState = {
  scene: SceneMetrics;
  decal: Record<string, DecalMetric>;
  setScene: (s: Partial<SceneMetrics>) => void;
  setDecal: (id: string, m: Partial<DecalMetric>) => void;
};

export const useMetrics = create<MetricsState>((set) => ({
  scene: EMPTY_SCENE,
  decal: {},
  setScene: (s) => set((st) => ({ scene: { ...st.scene, ...s } })),
  setDecal: (id, m) => set((st) => ({ decal: { ...st.decal, [id]: { ...(st.decal[id] ?? { coverage: 1, resW: 0, resH: 0 }), ...m } } })),
}));
