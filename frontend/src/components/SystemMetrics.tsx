import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useT } from "../i18n";
import { M } from "./MetricRow";

// Host kaynak metrikleri (CPU/RAM/disk/GPU) — /system/stats poll eder.
// Hem Dashboard'da (layout="grid", geniş) hem Design metrik panelinde (layout="list") kullanılır.

type SysStats = {
  cpu: { percent: number; load1: number; cores: number };
  ram: { used_gb: number; total_gb: number; percent: number };
  disk: { read_mbs: number; write_mbs: number };
  gpus: { index: number; util: number; vram_used_gb: number; vram_total_gb: number; temp: number }[];
  default_gpu?: number; // DEFAULT_GPU — 3D motorlarının çalıştığı kart
};

export function SystemMetrics({ layout = "list" }: { layout?: "list" | "grid" }) {
  const { t } = useT();
  const { data: sys, isError } = useQuery({
    queryKey: ["system-stats"],
    queryFn: () => api<SysStats>("/system/stats"),
    refetchInterval: 2000,
  });

  if (isError) return <p className="text-[11px] text-zinc-600">{t("metrics.sysReadError")}</p>;
  if (!sys) return <p className="text-[11px] text-zinc-600">{t("metrics.loading")}</p>;

  const cpu = <M label={t("metrics.cpuLabel")} value={`%${sys.cpu.percent}`} bar={sys.cpu.percent}
    desc={t("metrics.cpuDesc", { load: sys.cpu.load1, cores: sys.cpu.cores })} />;
  const ram = <M label={t("metrics.ramLabel")} value={`${sys.ram.used_gb}/${sys.ram.total_gb} GB`} bar={sys.ram.percent}
    desc={t("metrics.ramDesc")} />;
  const disk = <M label={t("metrics.diskLabel")} value={`↓${sys.disk.read_mbs} ↑${sys.disk.write_mbs} MB/s`}
    bar={Math.min((sys.disk.read_mbs + sys.disk.write_mbs) / 5, 100)}
    desc={t("metrics.diskDesc")} />;
  const gpus = sys.gpus.map((g) => (
    <div key={g.index} className="space-y-1 rounded bg-zinc-900/50 p-2">
      <M label={t("metrics.gpuUtilLabel", { i: g.index })} value={`%${g.util}`} bar={g.util}
        desc={g.index === (sys.default_gpu ?? 0) ? t("metrics.gpuUtilDesc1") : t("metrics.gpuUtilDesc0")} />
      <M label={t("metrics.gpuVramLabel", { i: g.index })} value={`${g.vram_used_gb}/${g.vram_total_gb} GB`}
        bar={g.vram_total_gb ? (g.vram_used_gb / g.vram_total_gb) * 100 : 0}
        desc={t("metrics.gpuVramDesc")} />
      <M label={t("metrics.gpuTempLabel", { i: g.index })} value={`${g.temp}°C`} bar={g.temp}
        desc={t("metrics.gpuTempDesc")} />
    </div>
  ));

  if (layout === "grid") {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">{cpu}</div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">{ram}</div>
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">{disk}</div>
        {gpus.map((el, i) => (
          <div key={i} className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">{el}</div>
        ))}
      </div>
    );
  }
  return <div className="space-y-2">{cpu}{ram}{disk}{gpus}</div>;
}
