import type { BodyInput } from "../api/mannequins";
import { useT } from "../i18n";

// "Ölçülerimden" giydirme formu (GeneratePage + Designer ortak): cinsiyet + boy/göğüs/bel/kalça (cm).
// Cinsiyet değişince o cinsiyetin varsayılanlarına döner (kadın ölçüleri erkekte anlamsız kalmasın).
export const BODY_DEFAULTS: Record<BodyInput["gender"], BodyInput> = {
  female: { gender: "female", height_cm: 165, chest_cm: 88, waist_cm: 72, hip_cm: 96 },
  male: { gender: "male", height_cm: 178, chest_cm: 100, waist_cm: 86, hip_cm: 100 },
};

const FIELDS = [
  ["height_cm", "body.height", 120, 220],
  ["chest_cm", "body.chest", 60, 160],
  ["waist_cm", "body.waist", 50, 160],
  ["hip_cm", "body.hip", 60, 170],
] as const;

// Tüm ölçüler girilmiş ve makul aralıkta mı (backend'e saçma beden gitmesin).
export const bodyValid = (b: BodyInput) =>
  FIELDS.every(([k, , min, max]) => b[k] >= min && b[k] <= max);

export function BodyInputs({ value, onChange, compact = false }: {
  value: BodyInput;
  onChange: (b: BodyInput) => void;
  compact?: boolean;   // Designer yan paneli: küçük yazı/dolgu
}) {
  const { t } = useT();
  const inp = compact
    ? "bg-zinc-800 rounded px-2 py-1 w-full text-xs"
    : "bg-zinc-800 rounded-lg px-3 py-2 w-full";
  const lbl = compact ? "flex flex-col gap-0.5 text-[11px] text-zinc-400" : "flex flex-col gap-1 text-sm";
  return (
    <div className={`grid gap-2 ${compact ? "grid-cols-2" : "grid-cols-5"}`}>
      <label className={lbl}>
        {t("body.gender")}
        <select value={value.gender} className={inp}
          onChange={(e) => onChange({ ...BODY_DEFAULTS[e.target.value as BodyInput["gender"]] })}>
          <option value="female">{t("body.female")}</option>
          <option value="male">{t("body.male")}</option>
        </select>
      </label>
      {FIELDS.map(([k, key, min, max]) => (
        <label key={k} className={lbl}>
          {t(key)}
          {/* Boş alan = 0 (gösterimde boş) → bodyValid false → gönder butonu kapalı. */}
          <input type="number" min={min} max={max} step={1} value={value[k] || ""} className={inp}
            onChange={(e) => {
              const n = parseFloat(e.target.value);
              onChange({ ...value, [k]: Number.isFinite(n) ? n : 0 });
            }} />
        </label>
      ))}
    </div>
  );
}
