import { FormEvent, useState } from "react";

import axiosService from "@shared/services/api";
import { SUPER_ADMIN_ENDPOINTS } from "@features/platform/services/superAdmin";
import { getErrorMessage } from "@shared/utils/apiError";

interface CreateAdminModalProps {
  tenantId: string;
  onClose: () => void;
  onSuccess: () => void;
}

export default function CreateAdminModal({
  tenantId,
  onClose,
  onSuccess,
}: CreateAdminModalProps) {
  const [formData, setFormData] = useState({
    first_name: "",
    last_name: "",
    email: "",
    password: "",
  });
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");
    setLoading(true);

    try {
      const response = await axiosService.post(
        SUPER_ADMIN_ENDPOINTS.tenantCreateAdmin(tenantId),
        formData,
      );
      setSuccess(response.data.message);
      setTimeout(onSuccess, 1500);
    } catch (err) {
      setError(getErrorMessage(err, "Failed to create admin user"));
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
        aria-labelledby="create-admin-title"
        className="sa-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="create-admin-title" className="sa-modal-title">
          Create Admin User
        </h2>

        <form onSubmit={handleSubmit}>
          <div className="sa-form-group">
            <label className="sa-form-label">First Name *</label>
            <input
              type="text"
              value={formData.first_name}
              onChange={(e) =>
                setFormData({ ...formData, first_name: e.target.value })
              }
              required
              className="sa-form-input"
            />
          </div>

          <div className="sa-form-group">
            <label className="sa-form-label">Last Name *</label>
            <input
              type="text"
              value={formData.last_name}
              onChange={(e) =>
                setFormData({ ...formData, last_name: e.target.value })
              }
              required
              className="sa-form-input"
            />
          </div>

          <div className="sa-form-group">
            <label className="sa-form-label">Email *</label>
            <input
              type="email"
              value={formData.email}
              onChange={(e) =>
                setFormData({ ...formData, email: e.target.value })
              }
              required
              className="sa-form-input"
            />
          </div>

          <div className="sa-form-group">
            <label className="sa-form-label">Password *</label>
            <input
              type="password"
              value={formData.password}
              onChange={(e) =>
                setFormData({ ...formData, password: e.target.value })
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

          {success && (
            <div className="alert-success" style={{ marginBottom: 20 }}>
              {success}
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
              {loading ? "Creating..." : "Create Admin"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
