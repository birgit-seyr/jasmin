import { FormEvent, useState } from "react";

import { Flex } from "antd";

import axiosService from "@shared/services/api";
import { SUPER_ADMIN_ENDPOINTS } from "@features/platform/services/superAdmin";
import { getErrorMessage } from "@shared/utils/apiError";
import { AVAILABLE_ROLES } from "@features/platform/userManagement";

interface CreateUserModalProps {
  tenantId: string;
  onClose: () => void;
  onSuccess: () => void;
}

export default function CreateUserModal({
  tenantId,
  onClose,
  onSuccess,
}: CreateUserModalProps) {
  const [formData, setFormData] = useState({
    first_name: "",
    last_name: "",
    email: "",
    password: "",
  });
  const [selectedRoles, setSelectedRoles] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

  const toggleRole = (role: string) => {
    setSelectedRoles((prev) =>
      prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role],
    );
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");
    setLoading(true);

    try {
      const response = await axiosService.post(
        SUPER_ADMIN_ENDPOINTS.tenantCreateUser(tenantId),
        { ...formData, roles: selectedRoles },
      );
      setSuccess(response.data.message);
      setTimeout(onSuccess, 1500);
    } catch (err) {
      setError(getErrorMessage(err, "Failed to create user"));
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
        aria-labelledby="create-user-title"
        className="sa-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="create-user-title" className="sa-modal-title">
          Create User
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

          <div className="sa-form-group">
            <label className="sa-form-label">Roles</label>
            <Flex gap="6px" wrap="wrap">
              {AVAILABLE_ROLES.map((role) => (
                <span
                  key={role}
                  onClick={() => toggleRole(role)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      toggleRole(role);
                    }
                  }}
                  role="checkbox"
                  aria-checked={selectedRoles.includes(role)}
                  tabIndex={0}
                  className={`sa-role-pill ${selectedRoles.includes(role) ? "sa-role-pill--selected" : ""}`}
                >
                  {role}
                </span>
              ))}
            </Flex>
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
              className="sa-btn sa-btn--detail"
              style={{
                padding: "10px 20px",
                fontSize: "14px",
                fontWeight: 500,
                borderRadius: "6px",
              }}
            >
              {loading ? "Creating..." : "Create User"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
