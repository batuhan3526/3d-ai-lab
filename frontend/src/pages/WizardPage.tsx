import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useMutation } from "@tanstack/react-query";
import { getManifest } from "../api/templates";
import { createProject } from "../api/projects";
import { assetUrl } from "../api/client";
import { useT } from "../i18n";
import type { GarmentGroup, TemplateItem } from "../types";

const ICONS: Record<string, string> = {
  tshirt: "👕", shirt: "👔", pants: "👖", skirt: "👗", hat: "🧢", boots: "🥾",
};

export default function WizardPage() {
  const navigate = useNavigate();
  const { t } = useT();
  const [selected, setSelected] = useState<GarmentGroup | null>(null);
  const { data: manifest, isLoading, error } = useQuery({
    queryKey: ["manifest"], queryFn: getManifest,
  });

  const create = useMutation({
    mutationFn: (tpl: TemplateItem) =>
      createProject({
        name: t("wizard.projectName", { label: selected!.label }),
        garment_type: selected!.type,
        template_id: tpl.id,
        customizations: { color: "#cccccc", decals: [] },
      }),
    onSuccess: (proj) => navigate(`/design/${proj.id}`),
  });

  if (isLoading) return <div className="p-8 text-zinc-500">{t("common.loading")}</div>;
  if (error) return <div className="p-8 text-red-400">{t("wizard.templatesError")}</div>;

  return (
    <div className="max-w-5xl mx-auto p-8">
      <button onClick={() => (selected ? setSelected(null) : navigate("/dashboard"))}
        className="text-zinc-400 mb-6">← {t("common.back")}</button>

      {!selected && (
        <>
          <button onClick={() => navigate("/generate")}
            className="bg-violet-600 hover:bg-violet-500 rounded-lg px-4 py-2 mb-4">
            ✨ {t("wizard.designWithText")}
          </button>
          <h1 className="text-2xl font-semibold mb-6">{t("wizard.step1Title")}</h1>
          <div className="grid grid-cols-3 gap-4">
            {manifest!.garments.map((g) => (
              <button key={g.type} onClick={() => setSelected(g)}
                className="bg-zinc-900 border border-zinc-800 hover:border-violet-500 rounded-xl p-8 text-center">
                <div className="text-5xl mb-3">{ICONS[g.type] ?? "👚"}</div>
                <div className="font-medium">{g.label}</div>
              </button>
            ))}
          </div>
        </>
      )}

      {selected && (
        <>
          <h1 className="text-2xl font-semibold mb-6">{t("wizard.step2Title", { label: selected.label })}</h1>
          <div className="grid grid-cols-3 md:grid-cols-5 gap-4">
            {selected.templates.map((tpl) => (
              <button key={tpl.id} disabled={create.isPending}
                onClick={() => create.mutate(tpl)}
                className="bg-zinc-900 border border-zinc-800 hover:border-violet-500 rounded-xl overflow-hidden disabled:opacity-50">
                <div className="aspect-square bg-zinc-800">
                  <img src={assetUrl(tpl.thumbnail)} alt={tpl.name} className="w-full h-full object-cover"
                    onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
                </div>
                <div className="p-2 text-xs truncate">{tpl.name}</div>
              </button>
            ))}
          </div>
          {create.isPending && <p className="text-zinc-500 mt-4">{t("wizard.creating")}</p>}
        </>
      )}
    </div>
  );
}
