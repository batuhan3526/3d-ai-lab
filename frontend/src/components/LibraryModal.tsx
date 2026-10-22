import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { listLibrary, addFavorite, removeFavorite, type Variation } from "../api/variations";
import { decalUrl } from "../api/generate";
import { useT } from "../i18n";

// Motif kütüphanesi: kayıtlı motifleri göster → tıkla → mevcut tasarıma ekle (decal).
export function LibraryModal({
  onSelect, onClose,
}: {
  onSelect: (v: Variation) => void;
  onClose: () => void;
}) {
  const { t } = useT();
  const [favOnly, setFavOnly] = useState(false);
  const { data = [] } = useQuery({
    queryKey: ["library", favOnly],
    queryFn: () => listLibrary(favOnly),
  });
  const fav = useMutation({
    mutationFn: ({ id, on }: { id: string; on: boolean }) =>
      on ? addFavorite(id) : removeFavorite(id),
  });
  const motifs = data.filter((v) => v.status === "SUCCESS" && v.result_path);

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6" onClick={onClose}>
      <div className="bg-zinc-900 rounded-2xl w-full max-w-4xl max-h-[90vh] flex flex-col overflow-hidden"
           onClick={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between px-5 py-3 border-b border-zinc-800">
          <span className="font-medium">{t("library.title")} {motifs.length ? `(${motifs.length})` : ""}</span>
          <div className="flex items-center gap-2">
            <button onClick={() => setFavOnly(false)}
              className={`rounded px-3 py-1 text-xs ${!favOnly ? "bg-violet-600" : "bg-zinc-700"}`}>{t("library.all")}</button>
            <button onClick={() => setFavOnly(true)}
              className={`rounded px-3 py-1 text-xs ${favOnly ? "bg-violet-600" : "bg-zinc-700"}`}>{t("library.favorites")}</button>
            <button onClick={onClose} className="text-zinc-400 hover:text-zinc-200 text-xl ml-2">×</button>
          </div>
        </header>
        <div className="flex-1 overflow-y-auto p-5">
          {motifs.length === 0 && (
            <p className="text-zinc-500 text-sm">
              {favOnly ? t("library.noFavorites") : t("library.empty")}
            </p>
          )}
          <div className="grid grid-cols-5 gap-3">
            {motifs.map((v) => (
              <div key={v.id} className="relative">
                <button onClick={() => { onSelect(v); onClose(); }}
                  className="aspect-square w-full rounded-lg bg-zinc-800 hover:ring-2 hover:ring-violet-500 overflow-hidden"
                  title={v.prompt ?? t("library.motifFallback")}>
                  <img src={decalUrl(v.project_id, v.result_path!)} alt="" className="w-full h-full object-contain" />
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); fav.mutate({ id: v.id, on: !v.favorite }); v.favorite = !v.favorite; }}
                  className="absolute top-1 right-1 text-lg leading-none">
                  {v.favorite ? "⭐" : "☆"}
                </button>
              </div>
            ))}
          </div>
        </div>
        <footer className="px-5 py-2 border-t border-zinc-800 text-xs text-zinc-500">
          {t("library.footerHint")}
        </footer>
      </div>
    </div>
  );
}
