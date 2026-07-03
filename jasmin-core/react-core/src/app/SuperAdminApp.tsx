import { Navigate, Route, Routes } from "react-router-dom";
import SuperAdminDashboard from "@features/platform/pages/SuperAdminDashboard";
import SuperAdminLoginPage from "@features/platform/pages/SuperAdminLoginPage";
import SuperAdminOpsChecklist from "@features/platform/pages/SuperAdminOpsChecklist";
import TenantDetail from "@features/platform/pages/TenantDetail";
import { useAuth } from "@shared/contexts/AuthContext";

export default function SuperAdminApp() {
  // AuthContext performs a silent /refresh on boot. While that's in flight we
  // show a loading splash; once it settles we route on the real auth state.
  // Gate on ``bootstrapping`` (initial boot only), NOT the per-action
  // ``loading`` — the latter would remount the login page on every submit and
  // drop the 2FA step.
  const { isAuthenticated, isSuperAdmin, bootstrapping } = useAuth();
  const isSuperAdminLoggedIn = isAuthenticated && isSuperAdmin;

  if (bootstrapping) {
    return (
      <div
        className="flex-center"
        style={{
          height: "100vh",
          fontSize: "18px",
          color: "var(--color-text-secondary)",
        }}
      >
        <div>Loading Platform...</div>
      </div>
    );
  }

  if (!isSuperAdminLoggedIn) {
    return (
      <Routes>
        <Route path="/login" element={<SuperAdminLoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route path="/" element={<SuperAdminDashboard />} />
      <Route path="/tenants/:id" element={<TenantDetail />} />
      <Route path="/ops-checklist" element={<SuperAdminOpsChecklist />} />
      <Route path="/login" element={<Navigate to="/" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
