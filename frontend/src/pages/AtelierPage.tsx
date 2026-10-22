import { useSearchParams } from "react-router-dom";
import { useT } from "../i18n";
import { PatternStep } from "../components/atelier/PatternStep";
import { NestStep } from "../components/atelier/NestStep";
import { Sew3dStep } from "../components/atelier/Sew3dStep";
import { MannequinStep } from "../components/atelier/MannequinStep";

// Atölye: kalıp → kumaşa yerleştir → 3D'de dik → manken. Teknik olmayan kullanıcı
// için adım adım, büyük butonlu, az alanlı akış. Seçili adım ve kalıp URL'de
// (?step=&pattern=) tutulur → sayfa yenilense de kaldığı yerden devam eder.

const STEPS = ["pattern", "nest", "sew", "mannequin"] as const;
type Step = (typeof STEPS)[number];

export default function AtelierPage() {
  const { t } = useT();
  const [params, setParams] = useSearchParams();
  const rawStep = params.get("step");
  const step: Step = (STEPS as readonly string[]).includes(rawStep ?? "") ? (rawStep as Step) : "pattern";
  const patternId = params.get("pattern");

  function update(next: { step?: Step; pattern?: string | null }) {
    const p = new URLSearchParams(params);
    if (next.step) p.set("step", next.step);
    if (next.pattern !== undefined) {
      if (next.pattern) p.set("pattern", next.pattern);
      else p.delete("pattern");
    }
    setParams(p, { replace: !next.step });
    if (next.step) window.scrollTo({ top: 0 });
  }

  const labels: Record<Step, string> = {
    pattern: t("atelier.step.pattern"),
    nest: t("atelier.step.nest"),
    sew: t("atelier.step.sew"),
    mannequin: t("atelier.step.mannequin"),
  };

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 py-6 space-y-5">
      <header>
        <h1 className="text-2xl font-bold text-zinc-100">{t("atelier.title")}</h1>
        <p className="text-sm text-zinc-400 mt-1">{t("atelier.subtitle")}</p>
      </header>

      <nav className="grid grid-cols-2 sm:grid-cols-4 gap-2" aria-label={t("atelier.title")}>
        {STEPS.map((s, i) => (
          <button key={s} type="button" onClick={() => update({ step: s })}
            aria-current={s === step ? "step" : undefined}
            className={`rounded-xl px-3 py-3 text-left ${s === step
              ? "bg-violet-600 text-white" : "bg-zinc-900 border border-zinc-800 text-zinc-300 hover:border-zinc-600"}`}>
            <span className="block text-xs opacity-80">{t("atelier.stepN", { n: i + 1 })}</span>
            <span className="block text-base font-semibold">{labels[s]}</span>
          </button>
        ))}
      </nav>

      {step === "pattern" && (
        <PatternStep patternId={patternId}
          onSelectPattern={(id) => update({ pattern: id })}
          onNext={() => update({ step: "nest" })} />
      )}
      {step === "nest" && <NestStep patternId={patternId} onGoPattern={() => update({ step: "pattern" })} />}
      {step === "sew" && <Sew3dStep patternId={patternId} onGoPattern={() => update({ step: "pattern" })} />}
      {step === "mannequin" && <MannequinStep />}
    </div>
  );
}
