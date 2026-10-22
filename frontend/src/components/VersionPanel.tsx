import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { listVersions, createVersion, deleteVersion, type Version } from "../api/versions";
import { useDesign } from "../store/design";
import { useT } from "../i18n";

export function VersionPanel({
  projectId, onRestore, onCompare,
}: {
  projectId: string;
  onRestore: (v: Version) => void;
  onCompare: (v: Version) => void;
}) {
  const { t } = useT();
  const qc = useQueryClient();
  const toCustomizations = useDesign((s) => s.toCustomizations);
  const { data: versions = [] } = useQuery({
    queryKey: ["versions", projectId], queryFn: () => listVersions(projectId),
  });
  const inval = () => qc.invalidateQueries({ queryKey: ["versions", projectId] });
  const save = useMutation({
    mutationFn: (name: string) => createVersion(projectId, name, toCustomizations(), false),
    onSuccess: inval,
  });
  const del = useMutation({ mutationFn: (id: string) => deleteVersion(projectId, id), onSuccess: inval });

  return (
    <div className="space-y-2 border-t border-zinc-800 pt-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm text-zinc-400">{t("version.title")}</h3>
        <button
          onClick={() => { const n = prompt(t("version.namePrompt")); if (n && n.trim()) save.mutate(n.trim()); }}
          className="bg-violet-600 hover:bg-violet-500 rounded px-2 py-1 text-xs">{t("version.saveCurrent")}</button>
      </div>
      <ul className="space-y-1">
        {versions.map((v) => (
          <li key={v.id} className="flex items-center gap-1 text-xs bg-zinc-800 rounded px-2 py-1">
            <span className={`flex-1 truncate ${v.auto ? "text-zinc-500 italic" : ""}`}>
              {v.auto ? `↺ ${v.name}` : v.name}
            </span>
            <button onClick={() => onRestore(v)} className="text-emerald-400 hover:text-emerald-300">{t("version.restore")}</button>
            <button onClick={() => onCompare(v)} className="text-cyan-400 hover:text-cyan-300">{t("version.compare")}</button>
            <button onClick={() => del.mutate(v.id)} className="text-red-400 hover:text-red-300">{t("version.delete")}</button>
          </li>
        ))}
        {versions.length === 0 && <li className="text-xs text-zinc-600">{t("version.empty")}</li>}
      </ul>
    </div>
  );
}
