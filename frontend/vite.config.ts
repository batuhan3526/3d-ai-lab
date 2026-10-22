import { defineConfig, loadEnv, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

// Ayarlar repo kökündeki .env'den okunur (gateway ile aynı dosya).
const LOCAL = ["127.0.0.1", "::1", "::ffff:127.0.0.1"];

// AUTO_LOGIN=true: aynı makineden (localhost) açılan tarayıcıya APP_TOKEN'ı
// localStorage'a yazıp giriş ekranını atlar. LAN'dan gelen isteklere token verilmez.
function autoLogin(token: string): Plugin {
  return {
    name: "auto-login",
    configureServer(server) {
      server.middlewares.use("/__autologin.js", (req, res) => {
        const addr = (req as { socket?: { remoteAddress?: string } }).socket?.remoteAddress;
        const local = LOCAL.indexOf(addr ?? "") >= 0;
        res.setHeader("Content-Type", "application/javascript");
        res.setHeader("Cache-Control", "no-store");
        res.end(
          local
            ? `localStorage.setItem("clothing_token", ${JSON.stringify(token)});` +
                `if (location.pathname.startsWith("/login")) history.replaceState(null, "", "/");`
            : "",
        );
      });
    },
    transformIndexHtml(html) {
      return html.replace("<head>", `<head><script src="/__autologin.js"></script>`);
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "..", "");
  const gatewayPort = env.GATEWAY_PORT || "9000";
  const auto = env.AUTO_LOGIN === "true" && env.APP_TOKEN;
  return {
    plugins: [react(), ...(auto ? [autoLogin(env.APP_TOKEN)] : [])],
    server: {
      host: "0.0.0.0",
      port: Number(env.FRONTEND_PORT || 3000),
      strictPort: true,
      proxy: {
        "/api": {
          target: `http://localhost:${gatewayPort}`,
          changeOrigin: true,
          // Telefonun kullandığı gerçek host'u gateway'e taşı (AR landing mutlak
          // URL'leri bunu okur; yoksa Host=localhost:9000 görünür ve QR linkleri kırılır).
          xfwd: true,
          ws: true,
          rewrite: (path) => path.replace(/^\/api/, ""),
        },
      },
    },
  };
});
