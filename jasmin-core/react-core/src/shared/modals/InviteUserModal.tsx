import {  Checkbox, Form, Input, Modal, Select } from "antd";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { CUSTOMER_COMPATIBLE_ROLES, ROLES, type Role } from "@shared/auth/roles";
import { useRoleOptions } from "@shared/auth/useRoleOptions";
import ResellerSelector from "@shared/selectors/ResellerSelector";
import { authAdminUsersCreate } from "@shared/api/generated/auth/auth";
import type { AdminUserCreateRequest } from "@shared/api/generated/models";
import { getErrorMessage } from "@shared/utils/apiError";
import { notify } from "@shared/utils";

export interface InviteUserValues {
  first_name: string;
  last_name: string;
  email: string;
  roles: Role[];
  language?: string;
  reseller_id?: string | null;
}

interface InviteUserModalProps {
  open: boolean;
  onClose: () => void;
  /** Called after a successful invite so the parent can refresh its list. */
  onCreated?: (values: InviteUserValues) => void;
  /**
   * Callable that performs the invitation POST. Defaults to the staff/admin
   * user-create endpoint via the generated client. Pass a function that wraps
   * a different generated client call for other invite flows (e.g.
   * `commissioningMembersSendInvitationCreate`).
   */
  submitFn?: (body: Record<string, unknown>) => Promise<unknown>;
  /** Roles ticked by default. */
  defaultRoles?: Role[];
  /**
   * Pre-filled form values (e.g. when opening the modal for an existing
   * Member row, pass `first_name`, `last_name`, `email`). Re-applied each
   * time the modal transitions from closed to open.
   */
  initialValues?: Partial<InviteUserValues>;
  /**
   * Roles that are pre-checked AND disabled (e.g. force `MEMBER` when invited
   * from the members page).
   */
  lockedRoles?: Role[];
  /**
   * If provided, only these roles are shown in the role picker. Anything not
   * in the list is hidden entirely (use this when other roles aren't valid in
   * the current flow).
   */
  allowedRoles?: Role[];
  /**
   * Roles that should be hidden from the picker entirely (use this from
   * Configuration → Users to hide ``member`` since the role is granted via
   * the Members page only).
   */
  disallowedRoles?: Role[];
  /** Override the modal title. */
  title?: ReactNode;
  /** Override the OK button text. */
  okText?: ReactNode;
  /**
   * Optional hook to do extra work (e.g. create a Member row first) before
   * the standard invite POST is fired. Throwing aborts the invite. Returns
   * optional values to merge into the POST body (e.g. `{ member_id: "..." }`).
   */
  beforeSubmit?: (
    values: InviteUserValues,
  ) => Promise<Record<string, unknown> | void> | Record<string, unknown> | void;
}

export default function InviteUserModal({
  open,
  onClose,
  onCreated,
  submitFn,
  defaultRoles,
  initialValues,
  lockedRoles = [],
  allowedRoles,
  disallowedRoles,
  title,
  okText,
  beforeSubmit,
}: InviteUserModalProps) {
  const { t } = useTranslation();
  const [form] = Form.useForm<InviteUserValues>();
  const [submitting, setSubmitting] = useState(false);
  const allRoleOptions = useRoleOptions();

  const initialRoles = (
    defaultRoles && defaultRoles.length > 0
      ? defaultRoles
      : lockedRoles.length > 0
        ? lockedRoles
        : [ROLES.OFFICE]
  ) as Role[];

  // Re-seed roles whenever the modal is opened.
  useEffect(() => {
    if (open)
      form.setFieldsValue({
        roles: [...initialRoles],
        ...(initialValues ?? {}),
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const lockedRolesSet = new Set(lockedRoles);
  const allowedRolesSet = allowedRoles ? new Set(allowedRoles) : null;
  const disallowedRolesSet = disallowedRoles ? new Set(disallowedRoles) : null;
  const roleOptions = allRoleOptions
    .filter((o) => !allowedRolesSet || allowedRolesSet.has(o.value as Role))
    .filter(
      (o) => !disallowedRolesSet || !disallowedRolesSet.has(o.value as Role),
    )
    .map((o) => ({
      ...o,
      disabled: lockedRolesSet.has(o.value as Role),
    }));

  const watchedRoles =
    (Form.useWatch("roles", form) as Role[] | undefined) || [];
  const showResellerSelector = watchedRoles.includes(ROLES.CUSTOMER);

  // Customer is exclusive: when picked, disable every other role except
  // those in CUSTOMER_COMPATIBLE_ROLES (member). When NOT picked, disable
  // "customer" if any incompatible role is already selected so the user
  // sees why ticking it would be invalid (must un-tick the others first).
  const customerCompatible = new Set<string>(CUSTOMER_COMPATIBLE_ROLES);
  const hasIncompatibleWithCustomer = watchedRoles.some(
    (r) => !customerCompatible.has(r),
  );
  const roleOptionsWithExclusivity = roleOptions.map((o) => {
    if (lockedRolesSet.has(o.value as Role)) return o;
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

  const handleFinish = async (values: InviteUserValues) => {
    const merged: InviteUserValues = {
      ...values,
      roles: Array.from(new Set([...(values.roles || []), ...lockedRoles])),
    };
    if (!merged.roles.includes(ROLES.CUSTOMER)) {
      merged.reseller_id = null;
    }
    setSubmitting(true);
    try {
      const extra = beforeSubmit ? await beforeSubmit(merged) : undefined;
      const body = { ...merged, ...(extra || {}) } as Record<string, unknown>;
      if (submitFn) {
        await submitFn(body);
      } else {
        await authAdminUsersCreate(
          body as unknown as AdminUserCreateRequest,
        );
      }
      notify.success(
        t("users.invitation_sent_to", {
          email: merged.email,
        }),
      );
      onCreated?.(merged);
      form.resetFields();
      onClose();
    } catch (err: unknown) {
      notify.error(
        getErrorMessage(err, t("users.create_failed")),
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title={title ?? t("users.invite_title")}
      open={open}
      onCancel={() => {
        form.resetFields();
        onClose();
      }}
      onOk={() => form.submit()}
      confirmLoading={submitting}
      okText={okText ?? t("users.send_invitation")}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" onFinish={handleFinish}>
        <Form.Item
          name="first_name"
          label={t("users.first_name")}
          rules={[
            { required: true, message: t("validation.required") },
          ]}
        >
          <Input />
        </Form.Item>
        <Form.Item
          name="last_name"
          label={t("users.last_name")}
          rules={[
            { required: true, message: t("validation.required") },
          ]}
        >
          <Input />
        </Form.Item>
        <Form.Item
          name="email"
          label={t("users.email")}
          rules={[
            { required: true, message: t("validation.required") },
            {
              type: "email",
              message: t("validation.invalid_email"),
            },
          ]}
        >
          <Input />
        </Form.Item>
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
          <Checkbox.Group options={roleOptionsWithExclusivity} />
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

/**
 * Adapter that lets <ResellerSelector> work as an Ant `Form.Item` field.
 * Ant Form passes `value`/`onChange` props automatically.
 */
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
