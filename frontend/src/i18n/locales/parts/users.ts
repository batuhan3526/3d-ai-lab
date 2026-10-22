// users/auth/gallery alanı TR/EN anahtarları (2026-07-06 özellik seti: ev/LAN
// çok-kullanıcı login + paylaşım galerisi). en/tr anahtar kümeleri eş olmalı.
export const en: Record<string, string> = {
  // Auth (hesap tabanlı login + ilk kurulum)
  "auth.loginTitle": "Sign in",
  "auth.setupTitle": "Create admin account",
  "auth.setupHint": "No users yet — this first account becomes the administrator.",
  "auth.username": "Username",
  "auth.password": "Password",
  "auth.loginSubmit": "Sign in",
  "auth.setupSubmit": "Create account",
  "auth.loginError": "Wrong username or password.",
  "auth.useToken": "Use an access token instead",
  "auth.useAccount": "Use username and password",
  // Navbar
  "nav.dashboard": "Dashboard",
  "nav.gallery": "Gallery",
  "nav.storage": "Storage",
  "nav.jobs": "Jobs",
  "nav.logout": "Log out",
  // Galeri (paylaşılan tasarımlar)
  "gallery.title": "Shared gallery",
  "gallery.empty": "No shared designs yet.",
  "gallery.loadError": "Could not load the gallery.",
  "gallery.owner": "by {name}",
  "gallery.open": "Open",
  "gallery.unshare": "Unshare",
};

export const tr: Record<string, string> = {
  // Auth
  "auth.loginTitle": "Giriş yap",
  "auth.setupTitle": "Yönetici hesabı oluştur",
  "auth.setupHint": "Henüz kullanıcı yok — bu ilk hesap yönetici olur.",
  "auth.username": "Kullanıcı adı",
  "auth.password": "Parola",
  "auth.loginSubmit": "Giriş yap",
  "auth.setupSubmit": "Hesap oluştur",
  "auth.loginError": "Kullanıcı adı veya parola hatalı.",
  "auth.useToken": "Bunun yerine erişim anahtarı kullan",
  "auth.useAccount": "Kullanıcı adı ve parola kullan",
  // Navbar
  "nav.dashboard": "Panel",
  "nav.gallery": "Galeri",
  "nav.storage": "Depolama",
  "nav.jobs": "İşler",
  "nav.logout": "Çıkış",
  // Galeri
  "gallery.title": "Paylaşılan galeri",
  "gallery.empty": "Henüz paylaşılan tasarım yok.",
  "gallery.loadError": "Galeri yüklenemedi.",
  "gallery.owner": "sahibi {name}",
  "gallery.open": "Aç",
  "gallery.unshare": "Paylaşımı kaldır",
};
