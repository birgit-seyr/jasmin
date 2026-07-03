import { FormEvent, useState } from "react";

import axiosService from "@shared/services/api";
import { SUPER_ADMIN_ENDPOINTS } from "@features/platform/services/superAdmin";
import { getErrorMessage } from "@shared/utils/apiError";

interface CreateTenantModalProps {
  onClose: () => void;
  onSuccess: () => void;
}

export default function CreateTenantModal({ onClose, onSuccess }: CreateTenantModalProps) {
  const [formData, setFormData] = useState({
    schema_name: "",
    name: "",
    domain: "",
    tenant_language: "de",
    admin_email: "",
    admin_password: "",
    admin_first_name: "",
    admin_last_name: "",
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      await axiosService.post(SUPER_ADMIN_ENDPOINTS.tenants, formData);
      onSuccess();
    } catch (err) {
      setError(getErrorMessage(err, "Failed to create tenant"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="sa-modal-overlay"
      onClick={onClose}
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-tenant-title"
        className="sa-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="create-tenant-title" className="sa-modal-title">
          Create New Tenant
        </h2>

        <form onSubmit={handleSubmit}>
          <div className="sa-form-group">
            <label className="sa-form-label">Schema Name *</label>
            <input
              type="text"
              placeholder="e.g., solawi_berlin"
              value={formData.schema_name}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  schema_name: e.target.value.toLowerCase().replace(/-/g, "_"),
                })
              }
              required
              pattern="[a-z0-9_]+"
              className="sa-form-input"
            />
            <small className="sa-help-text">
              Lowercase letters, numbers, and underscores only
            </small>
          </div>

          <div className="sa-form-group">
            <label className="sa-form-label">Tenant Name *</label>
            <input
              type="text"
              placeholder="e.g., Solawi Berlin"
              value={formData.name}
              onChange={(e) =>
                setFormData({ ...formData, name: e.target.value })
              }
              required
              className="sa-form-input"
            />
          </div>

          <div className="sa-form-group">
            <label className="sa-form-label">Domain *</label>
            <input
              type="text"
              placeholder="e.g., solawi.localhost"
              value={formData.domain}
              onChange={(e) =>
                setFormData({ ...formData, domain: e.target.value })
              }
              required
              className="sa-form-input"
            />
            <small className="sa-help-text">
              Dev: subdomain.localhost | Prod: subdomain.yourdomain.com
            </small>
          </div>

          <div className="sa-form-group">
            <label className="sa-form-label">Language</label>
            <select
              value={formData.tenant_language}
              onChange={(e) =>
                setFormData({ ...formData, tenant_language: e.target.value })
              }
              className="sa-form-input"
            >
              <option value="de">Deutsch</option>
              <option value="en">English</option>
              <option value="fr">Français</option>
            </select>
          </div>

          <hr className="sa-form-divider" />
          <h3
            style={{
              margin: "0 0 16px 0",
              fontSize: "16px",
              fontWeight: "600",
            }}
          >
            Admin User
          </h3>

          <div className="sa-form-row">
            <div>
              <label className="sa-form-label">First Name</label>
              <input
                type="text"
                placeholder="First name"
                value={formData.admin_first_name}
                onChange={(e) =>
                  setFormData({ ...formData, admin_first_name: e.target.value })
                }
                className="sa-form-input"
              />
            </div>
            <div>
              <label className="sa-form-label">Last Name</label>
              <input
                type="text"
                placeholder="Last name"
                value={formData.admin_last_name}
                onChange={(e) =>
                  setFormData({ ...formData, admin_last_name: e.target.value })
                }
                className="sa-form-input"
              />
            </div>
          </div>

          <div className="sa-form-group">
            <label className="sa-form-label">Admin Email *</label>
            <input
              type="email"
              placeholder="admin@example.com"
              value={formData.admin_email}
              onChange={(e) =>
                setFormData({ ...formData, admin_email: e.target.value })
              }
              required
              className="sa-form-input"
            />
          </div>

          <div className="sa-form-group">
            <label className="sa-form-label">Admin Password *</label>
            <input
              type="password"
              placeholder="Password"
              value={formData.admin_password}
              onChange={(e) =>
                setFormData({ ...formData, admin_password: e.target.value })
              }
              required
              minLength={8}
              className="sa-form-input"
            />
          </div>


          {error && (
            <div className="alert-error" style={{ marginBottom: 20 }}>
              {error}
            </div>
          )}

          <div className="sa-modal-actions">
            <button
              type="button"
              onClick={onClose}
              className="sa-btn sa-btn--cancel"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="sa-btn sa-btn--primary"
            >
              {loading ? "Creating..." : "Create Tenant"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
