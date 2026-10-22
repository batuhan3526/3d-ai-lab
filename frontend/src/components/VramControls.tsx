import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { releaseAll } from "../api/engines";
import { useT } from "../i18n";

export default function VramControls() {
  const { t } = useT();
  const [toast, setToast] = useState<string | null>(null);

  function showToast(msg: string) {
    setToast(msg);
    setTimeout(() => setToast(null), 3000);
  }

  const rel = useMutation({
    mutationFn: (mode: "cache" | "model") => releaseAll(mode),
    onSuccess: (_, mode) =>
      showToast(mode === "cache" ? t("vram.cache_cleared") : t("vram.models_freed")),
    onError: () => showToast(t("vram.error")),
  });

  return (
    <div className="flex items-center gap-2">
      <button
        disabled={rel.isPending}
        onClick={() => rel.mutate("cache")}
        className="text-xs bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 rounded px-2.5 py-1.5 text-zinc-300 transition-colors"
        title={t("vram.clear_cache_title")}
      >
        {t("vram.clear_cache")}
      </button>
      <button
        disabled={rel.isPending}
        onClick={() => rel.mutate("model")}
        className="text-xs bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 rounded px-2.5 py-1.5 text-zinc-300 transition-colors"
        title={t("vram.free_models_title")}
      >
        {t("vram.free_models")}
      </button>
      {toast && (
        <span className="text-xs text-zinc-400 ml-1">{toast}</span>
      )}
    </div>
  );
}
