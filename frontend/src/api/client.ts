import { useAuth } from "../store/auth";

const BASE = "/api"; // Vite proxy -> gateway (prefix strip)

// Bu uçlarda 401 kimlik-doğrulama akışının parçasıdır; oturumu düşürmeyiz.
const AUTH_PATHS = ["/auth/login", "/auth/setup", "/auth/needs-setup"];

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function authHeaders(): Record<string, string> {
  const token = useAuth.getState().token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function api<T>(path: string, opts: RequestInit & { timeoutMs?: number } = {}): Promise<T> {
  const headers: Record<string, string> = {
    ...(opts.body ? { "Content-Type": "application/json" } : {}),
    ...authHeaders(),
    ...(opts.headers as Record<string, string>),
  };
  const { timeoutMs, ...fetchOpts } = opts;
  // Caller-provided AbortSignal'i koru; timeoutMs varsa kendi AbortController'ı kur.
  let signal = opts.signal;
  let timeoutId: ReturnType<typeof setTimeout> | undefined;
  if (timeoutMs) {
    const ctrl = new AbortController();
    timeoutId = setTimeout(() => ctrl.abort(), timeoutMs);
    signal = ctrl.signal;
  }
  try {
    const resp = await fetch(`${BASE}${path}`, { ...fetchOpts, headers, signal });
    if (resp.status === 401) {
      // Auth uçlarında 401 BEKLENEN sonuçtur (yanlış parola / kurulum kontrolü);
      // token'ı temizlemeyiz — çağıran (LoginPage) hatayı gösterir. Diğer tüm
      // uçlarda 401 = oturum düştü → token'ı temizle: ProtectedRoute (token=null)
      // otomatik `/login`'e yönlendirir (hard reload olmadan, SPA içinde).
      if (!AUTH_PATHS.some((p) => path.startsWith(p))) {
        useAuth.getState().clear();
      }
      throw new ApiError(401, "Oturum geçersiz");
    }
    if (!resp.ok) {
      // FastAPI hataları JSON {detail: "..."} taşır — kullanıcıya gerçek nedeni
      // göstermek için parse et (parse edilemezse HTTP koduna düş).
      let msg = `HTTP ${resp.status}`;
      try {
        const body = (await resp.json()) as { detail?: unknown };
        if (typeof body.detail === "string" && body.detail) msg = body.detail;
      } catch { /* gövde JSON değil — HTTP kodu yeter */ }
      throw new ApiError(resp.status, msg);
    }
    if (resp.status === 204) return undefined as T;
    return resp.json() as Promise<T>;
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new ApiError(408, `İstek zaman aşımına uğradı (${timeoutMs}ms)`);
    }
    throw e;
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
  }
}

/** Projeye ait dosya (ör. variations/ altındaki pozlu manken GLB'si). */
export function projectFileUrl(projectId: string, sub: string, name: string): string {
  return `${BASE}/projects/${projectId}/${sub}/${name}`;
}

export function assetUrl(relPath: string): string {
  return `${BASE}/template-assets/${relPath}`;
}
