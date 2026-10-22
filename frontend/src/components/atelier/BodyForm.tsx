import { useT } from "../../i18n";
import type { BodyInput, MannequinEntry } from "../../api/mannequins";
import { inputCls, parseNum } from "./common";

// 5 basit ölçü formu (cinsiyet, boy, göğüs, bel, kalça). Kalıp ve manken
// adımlarında ortak. Değerler metin olarak tutulur (yazarken "16" gibi ara
// durumlar bozulmasın); toBody() sayıya çevirir.

export type BodyDraft = { gender: "female" | "male"; height: string; chest: string; waist: string; hip: string };

export const BODY_DEFAULTS: Record<"female" | "male", BodyDraft> = {
  female: { gender: "female", height: "165", chest: "90", waist: "72", hip: "98" },
  male: { gender: "male", height: "178", chest: "100", waist: "86", hip: "100" },
};

export function toBody(d: BodyDraft): BodyInput | null {
  const h = parseNum(d.height), c = parseNum(d.chest), w = parseNum(d.waist), p = parseNum(d.hip);
  if (h === null || c === null || w === null || p === null) return null;
  return { gender: d.gender, height_cm: h, chest_cm: c, waist_cm: w, hip_cm: p };
}

function sameValues(a: BodyDraft, b: BodyDraft) {
  return a.height === b.height && a.chest === b.chest && a.waist === b.waist && a.hip === b.hip;
}

export function BodyForm({
  value, onChange, savedMannequins,
}: {
  value: BodyDraft;
  onChange: (d: BodyDraft) => void;
  /** Ölçüleri doldurmak için kayıtlı özel mankenler (body alanı olanlar). */
  savedMannequins?: MannequinEntry[];
}) {
  const { t } = useT();
  const withBody = (savedMannequins ?? []).filter((m) => m.custom && m.body);

  function setGender(g: "female" | "male") {
    if (g === value.gender) return;
    // Kullanıcı ölçülere dokunmadıysa varsayılanları da cinsiyete göre değiştir.
    if (sameValues(value, BODY_DEFAULTS[value.gender])) onChange(BODY_DEFAULTS[g]);
    else onChange({ ...value, gender: g });
  }

  function fillFrom(id: string) {
    const m = withBody.find((x) => x.id === id);
    if (!m?.body) return;
    onChange({
      gender: m.body.gender,
      height: String(m.body.height_cm),
      chest: String(m.body.chest_cm),
      waist: String(m.body.waist_cm),
      hip: String(m.body.hip_cm),
    });
  }

  const fields: { key: keyof Omit<BodyDraft, "gender">; label: string }[] = [
    { key: "height", label: t("atelier.body.height") },
    { key: "chest", label: t("atelier.body.chest") },
    { key: "waist", label: t("atelier.body.waist") },
    { key: "hip", label: t("atelier.body.hip") },
  ];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label={t("atelier.body.gender")}>
        {(["female", "male"] as const).map((g) => (
          <button key={g} type="button" role="radio" aria-checked={value.gender === g}
            onClick={() => setGender(g)}
            className={`rounded-xl px-4 py-3 text-base font-medium ${value.gender === g
              ? "bg-violet-600 text-white" : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700"}`}>
            {g === "female" ? t("atelier.body.female") : t("atelier.body.male")}
          </button>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-3">
        {fields.map((f) => (
          <label key={f.key} className="block space-y-1">
            <span className="text-sm text-zinc-300">{f.label}</span>
            <div className="relative">
              <input inputMode="decimal" value={value[f.key]}
                onChange={(e) => onChange({ ...value, [f.key]: e.target.value })}
                className={`${inputCls} pr-12`} />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-zinc-500">cm</span>
            </div>
          </label>
        ))}
      </div>
      {withBody.length > 0 && (
        <label className="block space-y-1">
          <span className="text-sm text-zinc-400">{t("atelier.body.fillFromMannequin")}</span>
          <select value="" onChange={(e) => fillFrom(e.target.value)} className={inputCls}>
            <option value="">{t("atelier.body.chooseMannequin")}</option>
            {withBody.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
        </label>
      )}
      <p className="text-xs text-zinc-500">{t("atelier.body.hint")}</p>
    </div>
  );
}
