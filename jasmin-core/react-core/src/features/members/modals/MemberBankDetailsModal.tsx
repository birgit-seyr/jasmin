import { useQueryClient } from "@tanstack/react-query";
import { Alert, Form, Modal, Space, Typography } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  getCommissioningMembersListQueryKey,
  useCommissioningMembersPartialUpdate,
} from "@shared/api/generated/commissioning/commissioning";
import StoredOrEditField from "@shared/layout/MyDataTab/StoredOrEditField";
import { ModalCancelSaveFooter } from "@shared/modals/shared";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import { checkIban, formatIbanError } from "@shared/utils/iban";

const { Text } = Typography;

interface MemberBankDetailsModalProps {
  open: boolean;
  memberId: string | null;
  /** Masked current values (``DE •••• 3000`` / ``A•• L•••••••``) from the
   *  list row — the API never returns the decrypted value. */
  ibanMasked?: string;
  accountOwnerMasked?: string;
  onClose: () => void;
  /** Called after a successful save so the parent can refresh its list. */
  onSaved?: () => void;
}

/**
 * Office-side edit surface for a member's stored bank details
 * (``Member.iban`` / ``Member.account_owner``).
 *
 * The bulk members grid shows only the masked companion fields, so this
 * modal is how the office sets/changes the real value on a member's behalf
 * — essential for members with no linked user account (who can't use the
 * self-service ``MyDataTab`` path).
 *
 * Reuses the same {@link StoredOrEditField} the self-service tab uses: each
 * field shows the masked current value + an "edit" toggle, and the cleartext
 * is only sent when the office explicitly opens the field for editing. The
 * backend ``MemberViewSet`` step-up-gates the change, so a fresh-auth modal
 * pops automatically on save (handled by the axios interceptor).
 */
export default function MemberBankDetailsModal({
  open,
  memberId,
  ibanMasked,
  accountOwnerMasked,
  onClose,
  onSaved,
}: MemberBankDetailsModalProps) {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const queryClient = useQueryClient();
  const [editingIban, setEditingIban] = useState(false);
  const [editingAccountOwner, setEditingAccountOwner] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Reset edit toggles + form each time the modal (re)opens for a member.
  useEffect(() => {
    if (open) {
      form.resetFields();
      setEditingIban(false);
      setEditingAccountOwner(false);
      setSubmitError(null);
    }
  }, [open, memberId, form]);

  const { mutate, isPending } = useCommissioningMembersPartialUpdate({
    mutation: {
      onSuccess: () => {
        notify.success(t("profile.saved"));
        void queryClient.invalidateQueries({
          queryKey: getCommissioningMembersListQueryKey(),
          exact: true,
        });
        onSaved?.();
        onClose();
      },
      onError: (err) => {
        setSubmitError(getErrorMessage(err, t("common.error")));
      },
    },
  });

  const handleSave = async () => {
    setSubmitError(null);
    if (!memberId) return;
    let values: Record<string, unknown>;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    // Only send a field the office actually opened for editing — mirrors the
    // self-service strip-empty pattern so "save" can't blank a value the
    // office can't currently see.
    const payload: Record<string, unknown> = {};
    if (editingIban) payload.iban = values.iban ?? "";
    if (editingAccountOwner) payload.account_owner = values.account_owner ?? "";
    if (Object.keys(payload).length === 0) {
      onClose();
      return;
    }
    mutate({ id: memberId, data: payload as never });
  };

  return (
    <Modal
      open={open}
      title={t("members.edit_bank_details")}
      onCancel={onClose}
      footer={
        <ModalCancelSaveFooter
          onCancel={onClose}
          onPrimary={handleSave}
          loading={isPending}
          primaryLabel={t("common.save")}
        />
      }
      width={560}
    >
      <Space direction="vertical" size="middle" className="w-full">
        <Text type="secondary" style={{ fontSize: 12 }}>
          {t("members.edit_bank_details_intro")}
        </Text>
        <Form form={form} layout="vertical">
          <StoredOrEditField
            name="account_owner"
            label={t("members.account_owner")}
            stored={Boolean(accountOwnerMasked)}
            maskedValue={accountOwnerMasked}
            editing={editingAccountOwner}
            onStartEdit={() => setEditingAccountOwner(true)}
            onCancelEdit={() => {
              form.setFieldValue("account_owner", "");
              setEditingAccountOwner(false);
            }}
          />
          <StoredOrEditField
            name="iban"
            label={t("members.iban")}
            stored={Boolean(ibanMasked)}
            maskedValue={ibanMasked}
            editing={editingIban}
            onStartEdit={() => setEditingIban(true)}
            onCancelEdit={() => {
              form.setFieldValue("iban", "");
              setEditingIban(false);
            }}
            rules={[
              {
                validator: (_, value) => {
                  const result = checkIban(value as string | null | undefined);
                  if (result.valid) return Promise.resolve();
                  return Promise.reject(
                    new Error(formatIbanError(result.reasons, t)),
                  );
                },
              },
            ]}
          />
        </Form>
        {submitError && <Alert type="error" showIcon message={submitError} />}
      </Space>
    </Modal>
  );
}
