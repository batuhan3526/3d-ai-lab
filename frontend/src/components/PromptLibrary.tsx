import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useT } from "../i18n";

// --- API -----------------------------------------------------------------------
// Prompt/seed şablon kütüphanesi. Backend: /library/prompts (GET/POST/DELETE).
export type PromptTemplate = {
  id: string;
  title: string;
  prompt: string;
  engine_id?: string | null;
  params?: Record<string, unknown> | null;
  seed?: number | null;
  created_at: string;
};

export type PromptTemplateInput = {
  title: string;
  prompt: string;
  engine_id?: string | null;
  params?: Record<string, unknown> | null;
  seed?: number | null;
};

export const listPromptTemplates = () => api<PromptTemplate[]>("/library/prompts");
export const savePromptTemplate = (t: PromptTemplateInput) =>
  api<PromptTemplate>("/library/prompts", { method: "POST", body: JSON.stringify(t) });
export const deletePromptTemplate = (id: string) =>
  api<void>(`/library/prompts/${encodeURIComponent(id)}`, { method: "DELETE" });

export const PROMPT_LIBRARY_KEY = ["promptLibrary"];

// --- Drawer bileşeni -----------------------------------------------------------
// Sağdan açılan "Şablonlar" çekmecesi: kayıtlı prompt/motor/seed'leri listeler →
// tıkla → onApply ile forma yükle. Çöp kutusu ile sil.
export function PromptLibrary({
  onApply, onClose,
}: {
  onApply: (t: PromptTemplate) => void;
  onClose: () => void;
}) {
  const { t } = useT();
  const qc = useQueryClient();
  const { data = [], isLoading } = useQuery({
    queryKey: PROMPT_LIBRARY_KEY,
    queryFn: listPromptTemplates,
  });
  const del = useMutation({
    mutationFn: (id: string) => deletePromptTemplate(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: PROMPT_LIBRARY_KEY }),
  });

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex justify-end" onClick={onClose}>
      <aside className="bg-zinc-900 w-full max-w-md h-full flex flex-col shadow-2xl"
             onClick={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between px-5 py-3 border-b border-zinc-800">
          <span className="font-medium">{t("quality.tplTitle")} {data.length ? `(${data.length})` : ""}</span>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-200 text-xl">×</button>
        </header>
        <div className="flex-1 overflow-y-auto p-4 space-y-2">
          {isLoading && <p className="text-zinc-500 text-sm">…</p>}
          {!isLoading && data.length === 0 && (
            <p className="text-zinc-500 text-sm">{t("quality.tplEmpty")}</p>
          )}
          {data.map((tpl) => (
            <div key={tpl.id}
                 className="group rounded-lg bg-zinc-800 hover:bg-zinc-700/70 p-3 flex items-start gap-2">
              <button onClick={() => { onApply(tpl); onClose(); }}
                      className="flex-1 text-left min-w-0">
                <div className="font-medium text-sm truncate">{tpl.title}</div>
                <div className="text-xs text-zinc-400 line-clamp-2">{tpl.prompt}</div>
                <div className="mt-1 flex flex-wrap gap-1 text-[10px] text-zinc-400">
                  {tpl.engine_id && (
                    <span className="px-1.5 py-0.5 rounded bg-zinc-700">{tpl.engine_id}</span>
                  )}
                  {tpl.seed != null && (
                    <span className="px-1.5 py-0.5 rounded bg-zinc-700">
                      {t("quality.tplSeedLabel")}: {tpl.seed}
                    </span>
                  )}
                </div>
              </button>
              <button
                onClick={() => { if (window.confirm(t("quality.tplDeleteConfirm"))) del.mutate(tpl.id); }}
                title={t("quality.tplDelete")}
                className="text-zinc-500 hover:text-red-400 text-lg leading-none shrink-0">
                🗑
              </button>
            </div>
          ))}
        </div>
        <footer className="px-5 py-2 border-t border-zinc-800 text-xs text-zinc-500">
          {t("quality.tplFooterHint")}
        </footer>
      </aside>
    </div>
  );
}
