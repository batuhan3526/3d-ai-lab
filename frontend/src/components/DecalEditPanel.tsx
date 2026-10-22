import { useDesign } from "../store/design";
import { useT } from "../i18n";

const COLORS = ["#ffffff", "#ef4444", "#f59e0b", "#22c55e", "#3b82f6", "#a855f7", "#111827"];

export function DecalEditPanel({ onMove }: { onMove: () => void }) {
  const { t } = useT();
  const decals = useDesign((s) => s.decals);
  const selectedId = useDesign((s) => s.selectedId);
  const select = useDesign((s) => s.selectDecal);
  const update = useDesign((s) => s.updateDecal);
  const duplicate = useDesign((s) => s.duplicateDecal);
  const reorder = useDesign((s) => s.reorderDecal);
  const remove = useDesign((s) => s.removeDecal);

  const sel = decals.find((d) => d.id === selectedId) ?? null;

  return (
    <div className="space-y-3">
      <h3 className="text-sm text-zinc-400">{t("decal.listTitle")}</h3>
      <ul className="space-y-1">
        {decals.map((d, i) => (
          <li key={d.id}>
            <button onClick={() => select(d.id)}
              className={`flex w-full items-center gap-2 rounded px-2 py-1 text-xs ${selectedId === d.id ? "bg-violet-600" : "bg-zinc-800 hover:bg-zinc-700"}`}>
              <img src={d.image} alt="" className="w-8 h-8 rounded bg-black object-contain" />
              <span>{t("decal.itemLabel", { n: i + 1 })}</span>
            </button>
          </li>
        ))}
        {decals.length === 0 && <li className="text-xs text-zinc-600">{t("decal.empty")}</li>}
      </ul>

      {sel ? (
        <div className="border-t border-zinc-800 pt-3 space-y-3">
          <label className="block text-xs text-zinc-400">{t("decal.scale")}
            <input type="range" min={0.05} max={1} step={0.01} value={sel.scale}
              onChange={(e) => update(sel.id, { scale: parseFloat(e.target.value) })} className="w-full" />
          </label>
          <label className="block text-xs text-zinc-400">{t("decal.rotate")}
            <input type="range" min={0} max={6.283} step={0.05} value={sel.spin ?? 0}
              onChange={(e) => update(sel.id, { spin: parseFloat(e.target.value) })} className="w-full" />
          </label>
          <label className="block text-xs text-zinc-400">{t("decal.opacity")}
            <input type="range" min={0} max={1} step={0.05} value={sel.opacity ?? 1}
              onChange={(e) => update(sel.id, { opacity: parseFloat(e.target.value) })} className="w-full" />
          </label>
          <div>
            <span className="text-xs text-zinc-400">{t("decal.color")}</span>
            <div className="flex gap-1 mt-1 flex-wrap">
              {COLORS.map((c) => (
                <button key={c} onClick={() => update(sel.id, { color: c === "#ffffff" ? null : c })}
                  className="w-6 h-6 rounded-full border border-zinc-600"
                  style={{ background: c }} title={c === "#ffffff" ? t("decal.reset") : c} />
              ))}
            </div>
          </div>
          <div className="flex gap-2">
            <button onClick={onMove} className="flex-1 bg-zinc-700 hover:bg-zinc-600 rounded px-2 py-1.5 text-xs">{t("decal.move")}</button>
            <button onClick={() => duplicate(sel.id)} className="flex-1 bg-zinc-700 hover:bg-zinc-600 rounded px-2 py-1.5 text-xs">{t("decal.duplicate")}</button>
            <button onClick={() => remove(sel.id)} className="flex-1 bg-red-600/80 hover:bg-red-600 rounded px-2 py-1.5 text-xs">{t("decal.delete")}</button>
          </div>
          <div className="flex gap-2">
            <button onClick={() => reorder(sel.id, "down")} className="flex-1 bg-zinc-700 hover:bg-zinc-600 rounded px-2 py-1.5 text-xs">{t("decal.layerDown")}</button>
            <button onClick={() => reorder(sel.id, "up")} className="flex-1 bg-zinc-700 hover:bg-zinc-600 rounded px-2 py-1.5 text-xs">{t("decal.layerUp")}</button>
          </div>
        </div>
      ) : (
        <p className="text-xs text-zinc-600 border-t border-zinc-800 pt-3">{t("decal.selectHint")}</p>
      )}
    </div>
  );
}
