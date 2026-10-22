import { useDesign } from "../store/design";
import { useT } from "../i18n";

const SWATCHES = ["#cccccc", "#ef4444", "#3b82f6", "#22c55e", "#eab308", "#a855f7", "#111827", "#ffffff"];

export function ColorPicker() {
  const { t } = useT();
  const color = useDesign((s) => s.color);
  const setColor = useDesign((s) => s.setColor);
  return (
    <div>
      <h3 className="text-sm text-zinc-400 mb-2">{t("color.title")}</h3>
      <div className="flex flex-wrap gap-2 mb-3">
        {SWATCHES.map((c) => (
          <button key={c} onClick={() => setColor(c)} title={c}
            className={`w-8 h-8 rounded-full border-2 ${color === c ? "border-violet-400" : "border-zinc-700"}`}
            style={{ background: c }} />
        ))}
      </div>
      <input type="color" value={color} onChange={(e) => setColor(e.target.value)}
        className="w-full h-10 bg-transparent rounded cursor-pointer" />
    </div>
  );
}
