import {  Checkbox, Form, Modal } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { CUSTOMER_COMPATIBLE_ROLES, ROLES, type Role } from "@shared/auth/roles";
import { useRoleOptions } from "@shared/auth/useRoleOptions";
import ResellerSelector from "@shared/selectors/ResellerSelector";
import { authAdminUsersPartialUpdate } from "@shared/api/generated/auth/auth";
import type { AdminUserUpdateRequest } from "@shared/api/generated/models";
import { getErrorMessage } from "@shared/utils/apiError";
import { notify } from "@shared/utils";

export interface EditUserRolesModalUser {
  id: string;
  first_name: string;
  last_name: string;
  roles: string[];
  reseller_id?: string | null;
}

interface EditUserRolesModalProps {
  /** When non-null, the modal is open and editing this user's roles. */
  user: EditUserRolesModalUser | null;
  onClose: () => void;
  /** Called after a successful save so the parent can refresh its list. */
  onSaved?: () => void;
}

export default function EditUserRolesModal({
  user,
  onClose,
  onSaved,
}: EditUserRolesModalProps) {
  const { t } = useTranslation();
  const [form] = Form.useForm<{ roles: Role[]; reseller_id?: string | null }>();
  const [saving, setSaving] = useState(false);
  const roleOptions = useRoleOptions();

  // Re-seed the form whenever a different user is opened.
  useEffect(() => {
    if (user)
      form.setFieldsValue({
        roles: [...(user.roles || [])] as Role[],
        reseller_id: user.reseller_id ?? null,
      });
  }, [user, form]);

  const watchedRoles =
    (Form.useWatch("roles", form) as Role[] | undefined) || [];
  const showResellerSelector = watchedRoles.includes(ROLES.CUSTOMER);

  const customerCompatible = new Set<string>(CUSTOMER_COMPATIBLE_ROLES);
  const hasIncompatibleWithCustomer = watchedRoles.some(
    (r) => !customerCompatible.has(r),
  );
  // The "member" role is owned by the Members page (it follows whether a
  // Member row is linked to the user). Show it as locked here so admins
  // know it cannot be toggled from this surface.
  const roleOptionsWithExclusivity = roleOptions.map((o) => {
    if (o.value === ROLES.MEMBER) {
      return { ...o, disabled: true };
    }
    if (showResellerSelector && !customerCompatible.has(o.value)) {
      return { ...o, disabled: true };
    }
    if (
      !showResellerSelector &&
      o.value === ROLES.CUSTOMER &&
      hasIncompatibleWithCustomer
    ) {
      return { ...o, disabled: true };
    }
    return o;
  });

  const handleFinish = async (values: {
    roles: Role[];
    reseller_id?: string | null;
  }) => {
    if (!user) return;
    const payload: Record<string, unknown> = { roles: values.roles };
    // Only send reseller_id when customer role is in the new role set;
    // otherwise the backend will clear any existing link automatically.
    if (values.roles.includes(ROLES.CUSTOMER)) {
      payload.reseller_id = values.reseller_id ?? null;
    }
    setSaving(true);
    try {
      await authAdminUsersPartialUpdate(
        user.id,
        payload as AdminUserUpdateRequest,
      );
      notify.success(t("users.roles_updated"));
      onSaved?.();
      onClose();
      form.resetFields();
    } catch (err: unknown) {
      notify.error(
        getErrorMessage(
          err,
          t("users.roles_update_failed"),
        ),
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={
        user
          ? `${t("users.edit_roles")} — ${user.first_name} ${user.last_name}`
          : t("users.edit_roles")
      }
      open={!!user}
      onCancel={onClose}
      onOk={() => form.submit()}
      confirmLoading={saving}
      okText={t("common.save")}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" onFinish={handleFinish}>
        <Form.Item
          name="roles"
          label={t("users.roles")}
          rules={[
            {
              required: true,
              message: t("users.pick_at_least_one_role"),
            },
          ]}
        >
          <Checkbox.Group
            options={roleOptionsWithExclusivity}
            className="flex-col gap-8"
          />
        </Form.Item>
        {showResellerSelector && (
          <Form.Item
            name="reseller_id"
            label={t("users.link_reseller")}
            rules={[
              {
                required: true,
                message: t("users.reseller_required_for_customer"),
              },
            ]}
          >
            <ResellerSelectorField />
          </Form.Item>
        )}
      </Form>
    </Modal>
  );
}

function ResellerSelectorField({
  value,
  onChange,
}: {
  value?: string | null;
  onChange?: (value: string | null) => void;
}) {
  return (
    <ResellerSelector
      selectedReseller={value ?? null}
      setSelectedReseller={(v) => onChange?.(v)}
      userType="reseller"
    />
  );
}
