import { useEffect } from "react";
import { useDesign } from "../store/design";
import { useFabricCatalog } from "../store/fabrics";
import { FABRIC_MATERIAL_PREFIX, fabricIdFromMaterial } from "../api/fabrics";
import { useT } from "../i18n";

// F4 kumaş hazır ayarları — Tasarımcı'daki iki kullanım:
//  * FabricPresetPicker: Malzeme panelinde; seçilince kıyafete kumaşın PBR
//    değerlerini uygular (renk + roughness/metalness/sheen). material değeri
//    "fabric:<id>" olarak kaydedilir; GarmentMesh değerleri katalogdan okur.
//  * FabricSelect: kumaş simülasyonu (drape) için fabric_id seçimi.
// Katalog alınamazsa (gateway eski sürüm vb.) bölüm sessizce gizlenmez, kısa not gösterir.

export function FabricPresetPicker() {
  const { t, lang } = useT();
  const material = useDesign((s) => s.material);
  const setMaterial = useDesign((s) => s.setMaterial);
  const setColor = useDesign((s) => s.setColor);
  const fabrics = useFabricCatalog((s) => s.fabrics);
  const error = useFabricCatalog((s) => s.error);
  const load = useFabricCatalog((s) => s.load);
  useEffect(() => { void load(); }, [load]);
  const active = fabricIdFromMaterial(material);

  return (
    <div>
      <h3 className="text-sm text-zinc-400 mb-1">{t("fabric.presetTitle")}</h3>
      <p className="text-[11px] text-zinc-500 mb-2">{t("fabric.presetHint")}</p>
      {error && !fabrics && <p className="text-[11px] text-amber-400">{t("fabric.loadError")}</p>}
      <div className="flex flex-wrap gap-1">
        {(fabrics ?? []).map((f) => (
          <button key={f.id} title={f.desc_tr}
            onClick={() => { setMaterial(FABRIC_MATERIAL_PREFIX + f.id); setColor(f.pbr.base_color); }}
            className={`flex items-center gap-1.5 rounded px-2 py-1 text-xs ${active === f.id ? "bg-violet-600" : "bg-zinc-800 hover:bg-zinc-700"}`}>
            <span className="inline-block h-3 w-3 rounded-sm border border-white/30" style={{ background: f.pbr.base_color }} />
            {lang === "en" ? f.name_en : f.name_tr}
          </button>
        ))}
      </div>
    </div>
  );
}

export function FabricSelect({ value, onChange }: { value: string | null; onChange: (id: string | null) => void }) {
  const { t, lang } = useT();
  const fabrics = useFabricCatalog((s) => s.fabrics);
  const load = useFabricCatalog((s) => s.load);
  useEffect(() => { void load(); }, [load]);
  return (
    <label className="block text-xs text-zinc-400">
      {t("fabric.simLabel")}
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}
        className="mt-1 w-full rounded bg-zinc-800 px-2 py-1 text-xs text-zinc-200">
        <option value="">{t("fabric.simDefault")}</option>
        {(fabrics ?? []).map((f) => (
          <option key={f.id} value={f.id}>{lang === "en" ? f.name_en : f.name_tr}</option>
        ))}
      </select>
    </label>
  );
}
