// Paylaşılan metrik satırı + bölüm başlığı (MetricsPanel ve SystemMetrics kullanır).
// Açıklama her zaman altta (muted); bar verilirse renkli yüzde çubuğu (yüksek=kötü).

export function M({ label, value, desc, bar }: { label: string; value: string; desc: string; bar?: number }) {
  const col = bar === undefined ? "" : bar > 85 ? "#ef4444" : bar > 60 ? "#f59e0b" : "#22c55e";
  return (
    <div className="space-y-0.5">
      <div className="flex justify-between text-xs text-zinc-200">
        <span>{label}</span><span className="font-mono text-zinc-100">{value}</span>
      </div>
      {bar !== undefined && (
        <div className="h-1 rounded bg-zinc-800 overflow-hidden">
          <div className="h-1 rounded" style={{ width: `${Math.min(Math.max(bar, 0), 100)}%`, background: col }} />
        </div>
      )}
      <p className="text-[10px] leading-tight text-zinc-500">{desc}</p>
    </div>
  );
}

export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-zinc-400">{title}</p>
      {children}
    </div>
  );
}
