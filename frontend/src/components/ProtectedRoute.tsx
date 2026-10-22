import { Navigate } from "react-router-dom";
import { useAuth } from "../store/auth";

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = useAuth((s) => s.token);
  if (!token) return <Navigate to="/login" replace />;
  // NOT: Önceki sürüm burada VramControls'ı `fixed top-0 right-0 z-50` olarak render
  // ediyordu; DesignerPage header'ındaki "Kaydet" + "Dışa Aktar" butonları sağ üstte
  // olduğu için panel onları örtüp tıklamayı yutuyordu. VramControls'ı Dashboard'a
  // taşıdık (kullanıcı zaten oradan kontrol edebilir).
  return <>{children}</>;
}
