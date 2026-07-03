import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import axiosService from "@shared/services/api";
import { useAuth } from "@shared/contexts/AuthContext";
import { SUPER_ADMIN_AUTH_ENDPOINTS } from "@shared/services/authEndpoints";
import { getErrorMessage } from "@shared/utils/apiError";

export default function SuperAdminLoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { setSession } = useAuth();

  const handleLogin = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      // axiosService is configured with withCredentials=true, so the
      // HttpOnly sa_refresh_token cookie set by Django will be stored
      // automatically. The response body carries only the short-lived access
      // token + user metadata.
      const response = await axiosService.post(SUPER_ADMIN_AUTH_ENDPOINTS.login, {
        email,
        password,
      });

      const { access, user, is_super_admin } = response.data;

      if (access && is_super_admin) {
        // Access token → in-memory store. NOT localStorage.
        // user metadata → AuthContext (persists to localStorage "auth" key,
        // tokens never touch localStorage).
        setSession(access, user);
        navigate("/");
      } else {
        setError("Not authorized as super admin");
      }
    } catch (err) {
      setError(getErrorMessage(err, "Login failed. Please try again."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="sa-fullscreen-state gradient-superadmin">
      <div
        className="sa-card"
        style={{ maxWidth: 400, width: "100%", padding: 40 }}
      >
        <div className="text-center" style={{ marginBottom: 30 }}>
          <h1
            style={{
              fontSize: "28px",
              fontWeight: 600,
              color: "var(--color-text-primary)",
              marginBottom: 8,
            }}
          >
            Platform Admin
          </h1>
          <p style={{ color: "var(--color-text-secondary)", fontSize: "14px" }}>
            Manage all tenants and platform settings
          </p>
        </div>

        <form onSubmit={handleLogin}>
          <div className="sa-form-group">
            <label className="sa-form-label">Email</label>
            <input
              type="email"
              placeholder="admin@platform.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="sa-form-input"
            />
          </div>

          <div className="sa-form-group">
            <label className="sa-form-label">Password</label>
            <input
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="sa-form-input"
            />
          </div>

          {error && (
            <div className="alert-error" style={{ marginBottom: 20 }}>
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="sa-btn sa-btn--primary w-full"
          >
            {loading ? "Logging in..." : "Login to Platform"}
          </button>
        </form>
      </div>
    </div>
  );
}
