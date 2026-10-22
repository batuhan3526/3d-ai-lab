import { create } from "zustand";
import type { Customizations, Decal } from "../types";
import { uuid } from "../lib/uuid";

const HISTORY_CAP = 50;

// Statik manken durumu (Task D1). Customizations JSON'una `mannequin` anahtarı
// olarak yazılır (mevcut save hattı: updateProject / createVersion). Customizations
// tipi bu alanı bilmediği için read/write noktalarında yerel cast kullanılır.
export type MannequinTransform = {
  position: [number, number, number];
  rotation: [number, number, number];
  scale: number;
};
export type MannequinState = {
  id: string;
  visible: boolean;
  opacity: number;
  transform: MannequinTransform;
  // Otomatik oturtma bayrağı (S2): true ise transform kıyafete göre hesaplanmış
  // (veya kullanıcı gizmo ile dokunmuş) demektir → yeniden auto-fit yapılmaz.
  // Persist edilir (customizations JSON). resetMannequinTransform temizler →
  // bir sonraki kare auto-fit tekrar tetiklenir.
  fitted?: boolean;
  // "Mankene giydir" sonucu: kolları kıyafetin kolluklarına pozlanmış, projeye özel
  // manken GLB'si (projects/<id>/variations/<posed>). Yoksa şablon manken kullanılır.
  posed?: string | null;
};

// Manken varsayılan yerleşimi: ayaklar ~zemin (ContactShadows y=-0.8), kıyafet
// merkez ~0 civarı. Kullanıcı gizmo ile ince ayar yapar.
const DEFAULT_MANNEQUIN_TRANSFORM: MannequinTransform = {
  position: [0, -0.85, 0],
  rotation: [0, 0, 0],
  scale: 1,
};

type CustomizationsWithMannequin = Customizations & { mannequin?: MannequinState | null };

type DesignState = {
  color: string;
  decals: Decal[];
  material: string;
  mannequin: MannequinState | null;
  // Hafif drape (Task D2): önizleme fiziği. TRANSİENT — customizations'a YAZILMAZ
  // ve dirty tetiklemez (deneysel, kaydedilmeyen görsel önizleme). Gerçek kumaş
  // simülasyonu değil (o BATCH-H); üst %10 sabit + yay-sönüm + hafif rüzgâr.
  drapeEnabled: boolean;
  drapeIntensity: number;
  drapeAutoStopped: boolean;
  selectedId: string | null;
  dirty: boolean;
  past: Customizations[];
  future: Customizations[];
  _lastAction: string | null;
  load: (c: Customizations) => void;
  setColor: (hex: string) => void;
  setMaterial: (preset: string) => void;
  addDecal: (d: Decal) => void;
  removeDecal: (id: string) => void;
  selectDecal: (id: string | null) => void;
  updateDecal: (id: string, patch: Partial<Decal>) => void;
  duplicateDecal: (id: string) => void;
  reorderDecal: (id: string, dir: "up" | "down") => void;
  selectMannequin: (id: string | null) => void;
  setMannequinVisible: (visible: boolean) => void;
  setMannequinOpacity: (opacity: number) => void;
  updateMannequinTransform: (patch: Partial<MannequinTransform>, fitted?: boolean) => void;
  resetMannequinTransform: () => void;
  setDrapeEnabled: (enabled: boolean) => void;
  setDrapeIntensity: (intensity: number) => void;
  drapeAutoStop: () => void;
  undo: () => void;
  redo: () => void;
  markSaved: () => void;
  toCustomizations: () => CustomizationsWithMannequin;
};

export const useDesign = create<DesignState>((set, get) => {
  const pushHistory = (action: string) => set((s) => {
    // coalesce: ardışık aynı slider/renk değişimi tek undo adımı
    if (action === s._lastAction && (action.startsWith("update:") || action === "color")) return {};
    const past = [...s.past, { color: s.color, decals: s.decals }];
    if (past.length > HISTORY_CAP) past.shift();
    return { past, future: [], _lastAction: action };
  });
  const keepSel = (sel: string | null, decals: Decal[]) =>
    sel && decals.some((d) => d.id === sel) ? sel : null;
  return {
    color: "#cccccc",
    decals: [],
    material: "mat",
    mannequin: null,
    drapeEnabled: false,
    drapeIntensity: 0.5,
    drapeAutoStopped: false,
    selectedId: null,
    dirty: false,
    past: [],
    future: [],
    _lastAction: null,
    load: (c) => set({
      color: c.color ?? "#cccccc", decals: c.decals ?? [], material: c.material ?? "mat",
      mannequin: (c as CustomizationsWithMannequin).mannequin ?? null,
      drapeEnabled: false, drapeAutoStopped: false,
      dirty: false, selectedId: null, past: [], future: [], _lastAction: null,
    }),
    setColor: (hex) => { pushHistory("color"); set({ color: hex, dirty: true }); },
    setMaterial: (preset) => set({ material: preset, dirty: true }),
    addDecal: (d) => { pushHistory("add:" + d.id); set((s) => ({ decals: [...s.decals, d], selectedId: d.id, dirty: true })); },
    removeDecal: (id) => { pushHistory("remove:" + id); set((s) => ({
      decals: s.decals.filter((x) => x.id !== id),
      selectedId: s.selectedId === id ? null : s.selectedId, dirty: true,
    })); },
    selectDecal: (id) => set({ selectedId: id }),
    updateDecal: (id, patch) => { pushHistory("update:" + id + ":" + Object.keys(patch).join(",")); set((s) => ({
      decals: s.decals.map((d) => (d.id === id ? { ...d, ...patch } : d)), dirty: true,
    })); },
    duplicateDecal: (id) => { pushHistory("dup:" + id); set((s) => {
      const src = s.decals.find((d) => d.id === id);
      if (!src) return {};
      const copy: Decal = { ...src, id: uuid(),
        position: [src.position[0] + 0.02, src.position[1] + 0.02, src.position[2]] };
      return { decals: [...s.decals, copy], selectedId: copy.id, dirty: true };
    }); },
    reorderDecal: (id, dir) => { pushHistory("reorder:" + id + ":" + dir); set((s) => {
      const i = s.decals.findIndex((d) => d.id === id);
      if (i < 0) return {};
      const j = dir === "up" ? i + 1 : i - 1;
      if (j < 0 || j >= s.decals.length) return {};
      const next = s.decals.slice();
      [next[i], next[j]] = [next[j], next[i]];
      return { decals: next, dirty: true };
    }); },
    // Manken: undo/redo geçmişine dahil DEĞİL (past/future decal+renk snapshot'ı);
    // yalnızca dirty=true ile mevcut autosave hattına yazılır.
    selectMannequin: (id) => set((s) => {
      if (id === null) return { mannequin: null, dirty: true };
      if (s.mannequin && s.mannequin.id === id) return { mannequin: { ...s.mannequin, visible: true }, dirty: true };
      return {
        mannequin: { id, visible: true, opacity: 0.6, transform: { ...DEFAULT_MANNEQUIN_TRANSFORM } },
        dirty: true,
      };
    }),
    setMannequinVisible: (visible) => set((s) => (
      s.mannequin ? { mannequin: { ...s.mannequin, visible }, dirty: true } : {}
    )),
    setMannequinOpacity: (opacity) => set((s) => (
      s.mannequin ? { mannequin: { ...s.mannequin, opacity }, dirty: true } : {}
    )),
    // fitted opsiyonel: auto-fit yazarken true geçilir (persist edilir). Gizmo
    // sürüklemesi fitted argümanı vermez → mevcut fitted korunur (true kalır,
    // yeniden auto-fit'e düşmez). undefined geçilirse dokunulmaz.
    updateMannequinTransform: (patch, fitted) => set((s) => (
      s.mannequin
        ? {
            mannequin: {
              ...s.mannequin,
              transform: { ...s.mannequin.transform, ...patch },
              ...(fitted !== undefined ? { fitted } : {}),
            },
            dirty: true,
          }
        : {}
    )),
    // fitted temizlenir → Mannequin bileşeni bir sonraki karede yeniden auto-fit yapar.
    resetMannequinTransform: () => set((s) => (
      s.mannequin
        ? { mannequin: { ...s.mannequin, transform: { ...DEFAULT_MANNEQUIN_TRANSFORM }, fitted: false, posed: null }, dirty: true }
        : {}
    )),
    // Drape: transient önizleme durumu — dirty tetiklemez, customizations'a girmez.
    // Açarken auto-stop uyarısını temizle; auto-stop çözücü FPS düşünce çağrılır.
    setDrapeEnabled: (enabled) => set(enabled ? { drapeEnabled: true, drapeAutoStopped: false } : { drapeEnabled: false }),
    setDrapeIntensity: (intensity) => set({ drapeIntensity: intensity }),
    drapeAutoStop: () => set({ drapeEnabled: false, drapeAutoStopped: true }),
    undo: () => set((s) => {
      if (!s.past.length) return {};
      const prev = s.past[s.past.length - 1];
      return {
        color: prev.color, decals: prev.decals,
        past: s.past.slice(0, -1),
        future: [{ color: s.color, decals: s.decals }, ...s.future],
        selectedId: keepSel(s.selectedId, prev.decals), dirty: true, _lastAction: null,
      };
    }),
    redo: () => set((s) => {
      if (!s.future.length) return {};
      const next = s.future[0];
      return {
        color: next.color, decals: next.decals,
        past: [...s.past, { color: s.color, decals: s.decals }],
        future: s.future.slice(1),
        selectedId: keepSel(s.selectedId, next.decals), dirty: true, _lastAction: null,
      };
    }),
    markSaved: () => set({ dirty: false }),
    toCustomizations: () => ({
      color: get().color, decals: get().decals, material: get().material,
      mannequin: get().mannequin,
    }),
  };
});
