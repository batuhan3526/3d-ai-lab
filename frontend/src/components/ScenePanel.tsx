import { useState } from "react";
import { create } from "zustand";
import { useDesign } from "../store/design";
import { useT } from "../i18n";
import type { EnvPreset } from "./ThreeCanvas";
import { FabricPresetPicker } from "./FabricPresetPicker";

// R2: SERBEST görüntüleme çözünürlüğü seçici. Viewer mesh'inin face üst sınırı;
// kullanıcı tercihi localStorage'da tutulur. Artık üç sabit değere kilitli değil:
// 1k..1M arası herhangi bir değer (backend ile aynı aralık). 20k/40k/80k yalnız
// hızlı-seçim butonları. DesignerPage bu store'a abone olur (glbUrl'i hesaplayan
// bileşen) → seçim değişince mesh yeni çözünürlükte yeniden yüklenir.
export const VIEW_FACE_MIN = 1000;
export const VIEW_FACE_MAX = 1_000_000;
export const VIEW_FACE_QUICK = [20000, 40000, 80000] as const;
export type ViewFaces = number;
const DEFAULT_VIEW_FACES: ViewFaces = 80000;
const VIEW_FACES_KEY = "viewFaces";

/** Değeri geçerli aralığa sıkıştır (backend 1k..1M dışını 422 reddeder). */
export function clampViewFaces(n: number): ViewFaces {
  if (!Number.isFinite(n)) return DEFAULT_VIEW_FACES;
  return Math.min(VIEW_FACE_MAX, Math.max(VIEW_FACE_MIN, Math.round(n)));
}

function loadViewFaces(): ViewFaces {
  try {
    const raw = Number(localStorage.getItem(VIEW_FACES_KEY));
    if (Number.isFinite(raw) && raw >= VIEW_FACE_MIN && raw <= VIEW_FACE_MAX) {
      return Math.round(raw);
    }
  } catch { /* localStorage yoksa (SSR/test) varsayılan */ }
  return DEFAULT_VIEW_FACES;
}

export const useViewFaces = create<{ faces: ViewFaces; setFaces: (f: ViewFaces) => void }>((set) => ({
  faces: loadViewFaces(),
  setFaces: (faces) => {
    const clamped = clampViewFaces(faces);
    try { localStorage.setItem(VIEW_FACES_KEY, String(clamped)); } catch { /* yoksay */ }
    set({ faces: clamped });
  },
}));

const MATERIALS: { key: string }[] = [
  { key: "mat" },
  { key: "deri" },
  { key: "kot" },
  { key: "saten" },
  { key: "parlak" },
  { key: "metalik" },
];

const ENVS: { key: EnvPreset }[] = [
  { key: "city" },
  { key: "studio" },
  { key: "sunset" },
  { key: "dawn" },
  { key: "night" },
  { key: "apartment" },
];

export function ScenePanel({
  env, setEnv, autoRotate, setAutoRotate, turnSeconds, setTurnSeconds,
}: {
  env: EnvPreset;
  setEnv: (e: EnvPreset) => void;
  autoRotate: boolean;
  setAutoRotate: (v: boolean) => void;
  /** F1: bir tam tur için saniye (4..30). */
  turnSeconds: number;
  setTurnSeconds: (v: number) => void;
}) {
  const { t } = useT();
  const material = useDesign((s) => s.material);
  const setMaterial = useDesign((s) => s.setMaterial);
  const viewFaces = useViewFaces((s) => s.faces);
  const setViewFaces = useViewFaces((s) => s.setFaces);
  // Serbest sayı girişi: yazarken ham metin, blur/Enter'da kaydet (clamp).
  const [facesInput, setFacesInput] = useState<string>(String(viewFaces));
  const commitFaces = () => {
    const n = Number(facesInput.replace(/[^0-9]/g, ""));
    if (Number.isFinite(n) && n > 0) {
      const clamped = clampViewFaces(n);
      setViewFaces(clamped);
      setFacesInput(String(clamped));
    } else {
      setFacesInput(String(viewFaces)); // geçersiz → eski değere geri dön
    }
  };

  return (
    <div className="space-y-3 border-t border-zinc-800 pt-3">
      <div>
        <h3 className="text-sm text-zinc-400 mb-2">{t("scene.material")}</h3>
        <div className="flex flex-wrap gap-1">
          {MATERIALS.map((m) => (
            <button key={m.key} onClick={() => setMaterial(m.key)}
              className={`rounded px-2 py-1 text-xs ${material === m.key ? "bg-violet-600" : "bg-zinc-800 hover:bg-zinc-700"}`}>
              {t(`scene.material_${m.key}`)}
            </button>
          ))}
        </div>
      </div>
      <FabricPresetPicker />
      <div>
        <h3 className="text-sm text-zinc-400 mb-2">{t("view.resolution")}</h3>
        <div className="flex flex-wrap gap-1 mb-2">
          {VIEW_FACE_QUICK.map((f) => (
            <button key={f} onClick={() => { setViewFaces(f); setFacesInput(String(f)); }}
              className={`rounded px-2 py-1 text-xs ${viewFaces === f ? "bg-violet-600" : "bg-zinc-800 hover:bg-zinc-700"}`}>
              {f / 1000}k
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <input
            type="number"
            min={VIEW_FACE_MIN}
            max={VIEW_FACE_MAX}
            step={1000}
            value={facesInput}
            onChange={(e) => setFacesInput(e.target.value)}
            onBlur={commitFaces}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commitFaces(); } }}
            aria-label={t("view.resolution")}
            className="w-28 rounded bg-zinc-800 px-2 py-1 text-xs text-zinc-200 hover:bg-zinc-700 focus:outline-none focus:ring-1 focus:ring-violet-500" />
          <span className="text-[11px] text-zinc-500">{t("view.facesUnit")}</span>
        </div>
        <p className="text-[11px] text-zinc-500 mt-1">{t("view.facesHint")}</p>
      </div>
      <div>
        <h3 className="text-sm text-zinc-400 mb-2">{t("scene.lighting")}</h3>
        <div className="flex flex-wrap gap-1">
          {ENVS.map((e) => (
            <button key={e.key} onClick={() => setEnv(e.key)}
              className={`rounded px-2 py-1 text-xs ${env === e.key ? "bg-violet-600" : "bg-zinc-800 hover:bg-zinc-700"}`}>
              {t(`scene.env_${e.key}`)}
            </button>
          ))}
        </div>
      </div>
      <label className="flex items-center justify-between text-sm text-zinc-300">
        <span>{t("scene.turntable")}</span>
        <button onClick={() => setAutoRotate(!autoRotate)}
          className={`rounded-lg px-3 py-1 text-xs ${autoRotate ? "bg-emerald-600" : "bg-zinc-700"}`}>
          {autoRotate ? t("scene.on") : t("scene.off")}
        </button>
      </label>
      {autoRotate && (
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs text-zinc-400">
            <span>{t("scene.turn_speed")}</span>
            <span>{turnSeconds}s / {t("scene.turn_unit")}</span>
          </div>
          <input type="range" min={4} max={30} step={1} value={turnSeconds}
            onChange={(e) => setTurnSeconds(Number(e.target.value))}
            className="w-full accent-emerald-600" />
          <p className="text-[11px] text-zinc-500">{t("scene.turn_speed_hint")}</p>
        </div>
      )}
    </div>
  );
}
