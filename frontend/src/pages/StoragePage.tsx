import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getStorage, deleteVariation, deleteVariationGroup } from "../api/variations";
import { decalUrl } from "../api/generate";
import { useT } from "../i18n";

function mb(bytes: number) { return (bytes / 1_048_576).toFixed(1); }

export default function StoragePage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { t } = useT();
  const { data } = useQuery({ queryKey: ["storage"], queryFn: getStorage });
  const inval = () => qc.invalidateQueries({ queryKey: ["storage"] });
  const delVar = useMutation({ mutationFn: deleteVariation, onSuccess: inval });
  const delGroup = useMutation({ mutationFn: deleteVariationGroup, onSuccess: inval });

  const total = data?.total_bytes ?? 0;
  const CAP = 500 * 1_048_576; // 500MB referans çubuk
  const pct = Math.min(100, (total / CAP) * 100);

  return (
    <div className="min-h-screen p-6 max-w-5xl mx-auto">
      <button onClick={() => navigate("/dashboard")} className="text-zinc-400 text-sm">← {t("common.back")}</button>
      <h1 className="text-xl font-semibold my-4">{t("storage.title")}</h1>

      <div className="mb-2 text-sm text-zinc-400">
        {t("storage.summary", { count: data?.count ?? 0, mb: mb(total) })}
      </div>
      <div className="h-3 rounded-full bg-zinc-800 overflow-hidden mb-6">
        <div className="h-full bg-violet-600" style={{ width: `${pct}%` }} />
      </div>

      <div className="space-y-4">
        {(data?.groups ?? []).map((g) => (
          <div key={g.group_id} className="border border-zinc-800 rounded-xl p-4">
            <div className="flex items-center justify-between mb-3">
              <div className="text-sm">
                <span className="font-medium">{g.prompt || t("storage.styleFallback")}</span>
                <span className="text-zinc-500">{t("storage.groupMeta", { kind: g.kind, count: g.count, mb: mb(g.bytes) })}</span>
              </div>
              <button onClick={() => delGroup.mutate(g.group_id)}
                className="text-red-400 hover:text-red-300 text-sm">{t("storage.deleteGroup")}</button>
            </div>
            <div className="grid grid-cols-6 gap-2">
              {g.variations.map((v) => (
                <div key={v.id} className="relative aspect-square rounded bg-zinc-800 overflow-hidden">
                  {v.result_path && (
                    <img src={decalUrl(v.project_id, v.result_path)} alt=""
                         className="w-full h-full object-contain" />
                  )}
                  {v.favorite && <span className="absolute top-0.5 left-0.5 text-sm">⭐</span>}
                  <button onClick={() => delVar.mutate(v.id)}
                    className="absolute top-0.5 right-0.5 text-red-400 text-xs">🗑</button>
                </div>
              ))}
            </div>
          </div>
        ))}
        {data && data.count === 0 && <p className="text-zinc-500 text-sm">{t("storage.empty")}</p>}
      </div>
    </div>
  );
}
