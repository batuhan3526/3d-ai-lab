import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { enginesStatus, releaseGpu } from "../api/engines";
import { useT } from "../i18n";

export default function GpuStatusPanel() {
  const { t } = useT();
  const qc = useQueryClient();
  // refetchInterval 4s -> 15s: backend her /engines/status için family×gpu sayısı kadar
  // sequential Celery task gönderir; offline worker başına 2.5s timeout yatar.
  // 7 family × 2 GPU = ~35s hang tek istek; 4s polling sırada birikme yapar.
  const status = useQuery({
    queryKey: ["engines-status"],
    queryFn: enginesStatus,
    refetchInterval: 15000,
    retry: false,
    staleTime: 10000,
  });
  const rel = useMutation({
    mutationFn: ({ family, gpu, mode }: { family: string; gpu: number; mode: "cache" | "model" }) =>
      releaseGpu(family, gpu, mode),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["engines-status"] }),
  });

  const onlineCount = (status.data ?? []).filter((g) => g.online).length;
  // İstek timeout'a düşerse büyük olasılıkla worker'ların çoğu kapalı (sequential 2.5s × N timeout).
  // 408 (kendi client timeout'umuz) gateway hatası değil, "worker yok" sinyali.
  const isTimeout = status.isError && (status.error as { status?: number })?.status === 408;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-zinc-400">{t("gpu.title")}</h2>
        <span className="text-xs text-zinc-500">
          {status.isLoading && t("gpu.loading")}
          {isTimeout && t("gpu.timeout")}
          {status.isError && !isTimeout && t("gpu.gatewayError")}
          {status.isSuccess && t("gpu.workerCount", { online: onlineCount, total: status.data.length })}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-3">
        {(status.data ?? []).map((g) => (
          <div key={`${g.family}-${g.gpu}`} className="bg-zinc-900 rounded-lg p-3 text-sm space-y-1">
            <div className="flex justify-between">
              <span className="font-medium">{g.family} · GPU {g.gpu}</span>
              <span className={g.online ? "text-green-400" : "text-zinc-500"}>
                {g.online ? t("gpu.online") : t("gpu.offline")}
              </span>
            </div>
            <div className="text-zinc-400">
              {t("gpu.vramReserved", { gb: Math.round((g.reserved_mb / 1024) * 10) / 10 })}
            </div>
            <div className="text-zinc-500 text-xs">
              {g.loaded.length ? t("gpu.loaded", { list: g.loaded.join(", ") }) : t("gpu.notLoaded")}
            </div>
            <div className="flex gap-2 pt-1">
              <button disabled={!g.online || rel.isPending}
                onClick={() => rel.mutate({ family: g.family, gpu: g.gpu, mode: "cache" })}
                className="text-xs bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 rounded px-2 py-1">
                {t("gpu.clearCache")}
              </button>
              <button disabled={!g.online || rel.isPending}
                onClick={() => rel.mutate({ family: g.family, gpu: g.gpu, mode: "model" })}
                className="text-xs bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 rounded px-2 py-1">
                {t("gpu.unloadModel")}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
