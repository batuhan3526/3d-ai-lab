import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../store/auth";
import { api, ApiError } from "../api/client";
import { useT } from "../i18n";

type AuthResp = { token: string; username: string; is_admin: boolean };

// Hesap tabanlı login + ilk kurulum. `GET /auth/needs-setup` true dönerse (hiç
// kullanıcı yok) kurulum formu gösterilir; ilk hesap yönetici olur. Erişim
// anahtarı (APP_TOKEN / makine token'ı) ile giriş fallback olarak korunur
// (worker/e2e uyumu — token localStorage `clothing_token`'da tutulur).
export default function LoginPage() {
  const setToken = useAuth((s) => s.setToken);
  const navigate = useNavigate();
  const { t } = useT();

  const { data: setupInfo } = useQuery({
    queryKey: ["needs-setup"],
    queryFn: () => api<{ needs_setup: boolean }>("/auth/needs-setup"),
  });
  const needsSetup = setupInfo?.needs_setup ?? false;

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [tokenValue, setTokenValue] = useState("");
  const [tokenMode, setTokenMode] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (tokenMode) {
      if (!tokenValue.trim()) return;
      setToken(tokenValue.trim());
      navigate("/dashboard");
      return;
    }
    if (!username.trim() || !password) return;
    setBusy(true);
    try {
      const path = needsSetup ? "/auth/setup" : "/auth/login";
      const resp = await api<AuthResp>(path, {
        method: "POST",
        body: JSON.stringify({ username: username.trim(), password }),
      });
      setToken(resp.token);
      navigate("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? t("auth.loginError") : String(err));
    } finally {
      setBusy(false);
    }
  }

  const title = tokenMode
    ? t("login.title")
    : needsSetup
      ? t("auth.setupTitle")
      : t("auth.loginTitle");

  return (
    <div className="min-h-screen flex items-center justify-center">
      <form onSubmit={submit} className="bg-zinc-900 border border-zinc-800 rounded-xl p-8 w-96">
        <h1 className="text-2xl font-semibold mb-6">{title}</h1>

        {!tokenMode && needsSetup && (
          <p className="text-sm text-zinc-400 mb-4">{t("auth.setupHint")}</p>
        )}

        {tokenMode ? (
          <>
            <label className="block text-sm text-zinc-400 mb-2">{t("login.tokenLabel")}</label>
            <input
              type="password"
              value={tokenValue}
              onChange={(e) => setTokenValue(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-700 rounded-lg px-3 py-2 mb-4"
              placeholder={t("login.tokenPlaceholder")}
              autoFocus
            />
          </>
        ) : (
          <>
            <label className="block text-sm text-zinc-400 mb-2">{t("auth.username")}</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-700 rounded-lg px-3 py-2 mb-4"
              autoComplete="username"
              autoFocus
            />
            <label className="block text-sm text-zinc-400 mb-2">{t("auth.password")}</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-zinc-950 border border-zinc-700 rounded-lg px-3 py-2 mb-4"
              autoComplete={needsSetup ? "new-password" : "current-password"}
            />
          </>
        )}

        {error && <p className="text-red-400 text-sm mb-4">{error}</p>}

        <button
          type="submit"
          disabled={busy}
          className="w-full bg-violet-600 hover:bg-violet-500 disabled:opacity-50 rounded-lg py-2 font-medium"
        >
          {tokenMode
            ? t("login.submit")
            : needsSetup
              ? t("auth.setupSubmit")
              : t("auth.loginSubmit")}
        </button>

        <button
          type="button"
          onClick={() => { setTokenMode((v) => !v); setError(""); }}
          className="mt-4 w-full text-xs text-zinc-500 hover:text-zinc-300"
        >
          {tokenMode ? t("auth.useAccount") : t("auth.useToken")}
        </button>
      </form>
    </div>
  );
}
