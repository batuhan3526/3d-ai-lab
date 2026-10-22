import { useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useT } from "../i18n";

type GalleryItem = {
  id: string;
  name: string;
  thumb: string;
  owner_username: string | null;
  shared_at: string | null;
};

// thumb, `/projects/{id}/thumbnail` göreli yolu döner; <img src> Vite proxy
// üzerinden `/api` ön ekiyle çağırır (thumbnail GET public — auth header yok).
const API_BASE = "/api";

// Paylaşılan (shared=1) tasarımların galerisi — StoragePage deseninin klonu.
export default function GalleryPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { t } = useT();
  const { data, isError } = useQuery({
    queryKey: ["gallery"],
    queryFn: () => api<GalleryItem[]>("/projects/gallery"),
  });
  const unshare = useMutation({
    mutationFn: (id: string) => api(`/projects/${id}/share`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["gallery"] }),
  });

  const items = data ?? [];

  return (
    <div className="min-h-screen p-6 max-w-5xl mx-auto">
      <button onClick={() => navigate("/dashboard")} className="text-zinc-400 text-sm">
        ← {t("common.back")}
      </button>
      <h1 className="text-xl font-semibold my-4">{t("gallery.title")}</h1>

      {isError && <p className="text-red-400 text-sm mb-4">{t("gallery.loadError")}</p>}
      {!isError && items.length === 0 && (
        <p className="text-zinc-500 text-sm">{t("gallery.empty")}</p>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4">
        {items.map((it) => (
          <div key={it.id} className="border border-zinc-800 rounded-xl overflow-hidden bg-zinc-900">
            <button
              onClick={() => navigate(`/design/${it.id}`)}
              className="block w-full aspect-square bg-zinc-800"
            >
              <img
                src={`${API_BASE}${it.thumb}`}
                alt={it.name}
                className="w-full h-full object-contain"
              />
            </button>
            <div className="p-3">
              <div className="text-sm font-medium truncate">{it.name}</div>
              <div className="text-xs text-zinc-500">
                {t("gallery.owner", { name: it.owner_username ?? "—" })}
              </div>
              <div className="mt-2 flex items-center gap-2">
                <button
                  onClick={() => navigate(`/design/${it.id}`)}
                  className="text-xs text-violet-400 hover:text-violet-300"
                >
                  {t("gallery.open")}
                </button>
                <button
                  onClick={() => unshare.mutate(it.id)}
                  className="text-xs text-zinc-400 hover:text-zinc-200 ml-auto"
                >
                  {t("gallery.unshare")}
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
