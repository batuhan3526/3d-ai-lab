import type { ReactNode } from "react";
import { ApiError } from "../../api/client";

// Atölye ortak parçaları: anlaşılır hata metni, büyük buton sınıfları, bölüm kutusu.
// Son kullanıcı teknik değil → "HTTP 404" / "Not Found" gibi ham metinler yerine
// ne olduğunu ve ne yapılacağını söyleyen Türkçe (çevrilebilir) mesajlar.

type T = (key: string, vars?: Record<string, string | number>) => string;

export function friendlyError(err: unknown, t: T): string {
  if (err instanceof ApiError) {
    const raw = err.message || "";
    // FastAPI'nin kendi (İngilizce) 404/405'i = uç sunucuda yok (gateway yeni kodla
    // başlatılmamış). Uçlarımızın kendi 404'leri Türkçe detail taşır → aynen göster.
    if ((err.status === 404 && /^(Not Found|HTTP 404)$/i.test(raw)) || err.status === 405) {
      return t("atelier.err.notReady");
    }
    if (err.status === 408) return t("atelier.err.timeout");
    if (err.status === 422 && /^HTTP 422$/.test(raw)) return t("atelier.err.invalid");
    if (err.status >= 500 && (/^HTTP \d+$/.test(raw) || /internal server error/i.test(raw))) {
      return t("atelier.err.server");
    }
    if (err.status === 401) return t("atelier.err.session");
    return raw || t("atelier.err.generic");
  }
  // fetch ağ hatası (sunucu kapalı / bağlantı yok) TypeError fırlatır.
  if (err instanceof TypeError) return t("atelier.err.network");
  if (err instanceof Error && err.message) return err.message;
  return t("atelier.err.generic");
}

export const btnPrimary =
  "rounded-xl bg-violet-600 hover:bg-violet-500 disabled:opacity-50 disabled:cursor-not-allowed px-5 py-3 text-base font-medium text-white";
export const btnSecondary =
  "rounded-xl bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 px-4 py-2.5 text-sm text-zinc-100";
export const btnDanger =
  "rounded-xl bg-zinc-800 hover:bg-red-700 disabled:opacity-50 px-3 py-2 text-sm text-zinc-200";
export const inputCls =
  "w-full rounded-xl bg-zinc-800 border border-zinc-700 px-3 py-2.5 text-base text-zinc-100 focus:outline-none focus:ring-2 focus:ring-violet-500";

export function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-4 sm:p-5 space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-zinc-100">{title}</h2>
        {hint && <p className="text-sm text-zinc-400 mt-1">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

export function ErrorBox({ message }: { message: string | null | undefined }) {
  if (!message) return null;
  return (
    <div role="alert" className="rounded-xl border border-red-800 bg-red-950/50 px-4 py-3 text-sm text-red-200 break-words">
      {message}
    </div>
  );
}

export function WarningList({ items }: { items: string[] | undefined }) {
  if (!items || items.length === 0) return null;
  return (
    <ul className="rounded-xl border border-amber-800 bg-amber-950/40 px-4 py-3 text-sm text-amber-200 space-y-1 list-disc list-inside">
      {items.map((w, i) => <li key={i}>{w}</li>)}
    </ul>
  );
}

/** "Gelişmiş" katlanır bölüm — varsayılan kapalı (az alan, sade ekran). */
export function Advanced({ label, children, onToggle }: { label: string; children: ReactNode; onToggle?: (open: boolean) => void }) {
  return (
    <details className="rounded-xl border border-zinc-800 bg-zinc-950/40"
      onToggle={(e) => onToggle?.((e.currentTarget as HTMLDetailsElement).open)}>
      <summary className="cursor-pointer select-none px-4 py-3 text-sm text-zinc-300 hover:text-white">
        {label}
      </summary>
      <div className="px-4 pb-4 pt-1 space-y-4">{children}</div>
    </details>
  );
}

/** Sayı girişi metni → sayı ("162,5" de kabul). Geçersizse null. */
export function parseNum(s: string): number | null {
  const n = Number(s.trim().replace(",", "."));
  return s.trim() !== "" && Number.isFinite(n) ? n : null;
}
