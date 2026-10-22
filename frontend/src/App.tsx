import { Routes, Route, Navigate, Link, useNavigate } from "react-router-dom";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { useAuth } from "./store/auth";
import { useT } from "./i18n";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import ModelCatalogPage from "./pages/ModelCatalogPage";
import DesignerPage from "./pages/DesignerPage";
import OutputsPage from "./pages/OutputsPage";
import GeneratePage from "./pages/GeneratePage";
import ProgressPage from "./pages/ProgressPage";
import StoragePage from "./pages/StoragePage";
import GalleryPage from "./pages/GalleryPage";
import JobQueuePage from "./pages/JobQueuePage";
import AtelierPage from "./pages/AtelierPage";

// Hub sayfaları için ince, akış içinde (fixed değil — tam-ekran 3D tasarımcıyı
// örtmesin diye) bir gezinme çubuğu. Login ve tasarımcı/üretim gibi tam-ekran
// araçlarda gösterilmez.
function NavShell({ children }: { children: React.ReactNode }) {
  const { t } = useT();
  const navigate = useNavigate();
  const clear = useAuth((s) => s.clear);
  function logout() {
    clear();
    navigate("/login");
  }
  return (
    <div>
      <nav className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 sm:px-6 py-3 border-b border-zinc-800 text-sm">
        <span className="font-semibold">{t("brand.name")}</span>
        <Link to="/dashboard" className="text-zinc-300 hover:text-white">{t("nav.dashboard")}</Link>
        <Link to="/gallery" className="text-zinc-300 hover:text-white">{t("nav.gallery")}</Link>
        <Link to="/storage" className="text-zinc-300 hover:text-white">{t("nav.storage")}</Link>
        <Link to="/jobs" className="text-zinc-300 hover:text-white">{t("nav.jobs")}</Link>
        <Link to="/atelier" className="text-zinc-300 hover:text-white">{t("nav.atelier")}</Link>
        <button onClick={logout} className="ml-auto text-zinc-400 hover:text-white">
          {t("nav.logout")}
        </button>
      </nav>
      {children}
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/dashboard" element={<ProtectedRoute><NavShell><DashboardPage /></NavShell></ProtectedRoute>} />
      <Route path="/gallery" element={<ProtectedRoute><NavShell><GalleryPage /></NavShell></ProtectedRoute>} />
      <Route path="/storage" element={<ProtectedRoute><NavShell><StoragePage /></NavShell></ProtectedRoute>} />
      <Route path="/jobs" element={<ProtectedRoute><NavShell><JobQueuePage /></NavShell></ProtectedRoute>} />
      <Route path="/atelier" element={<ProtectedRoute><NavShell><AtelierPage /></NavShell></ProtectedRoute>} />
      <Route path="/new" element={<ProtectedRoute><ModelCatalogPage /></ProtectedRoute>} />
      <Route path="/design/:id" element={<ProtectedRoute><DesignerPage /></ProtectedRoute>} />
      <Route path="/outputs/:id" element={<ProtectedRoute><NavShell><OutputsPage /></NavShell></ProtectedRoute>} />
      <Route path="/generate" element={<ProtectedRoute><GeneratePage /></ProtectedRoute>} />
      <Route path="/progress/:jobId" element={<ProtectedRoute><ProgressPage /></ProtectedRoute>} />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
