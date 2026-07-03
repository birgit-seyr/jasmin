import { EditOutlined, EyeOutlined } from "@ant-design/icons";
import { Button, Card, Modal, Space, Tag, Typography } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useTenantsTenantsPartialUpdate } from "@shared/api/generated/tenants/tenants";
import type { Tenant } from "@shared/api/generated/models";
import RichTextEditorModal from "@shared/modals/RichTextEditorModal";
import { useTenant } from "@hooks/index";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import DefaultPrivacyPolicyTemplate from "@features/public/pages/DefaultPrivacyPolicyTemplate";

const { Text } = Typography;

/**
 * Per-tenant privacy-policy override (GDPR Art. 13/14 info duties).
 *
 * Mirrors the entry-line settings pattern: a trigger row inside a card
 * opens the shared ``RichTextEditorModal`` (same Quill-based component
 * the entry_line_* settings use). The only difference is the storage
 * layer — entry_lines write to the ``TenantSettings`` overlay,
 * ``privacy_policy_html`` is a ``Tenant`` row column so it can ride on
 * the anonymous ``CurrentTenantSerializer`` allowlist that the public
 * ``/privacy`` route reads.
 *
 * Trust boundary: identical to entry_lines — auth-gated office
 * endpoint, admin-edited content. The rendered HTML is consumed by
 * ``PrivacyPolicyPage`` via ``dangerouslySetInnerHTML``.
 *
 * Empty content → the public ``PrivacyPolicyPage`` falls back to the
 * static i18n template that pulls org name / address / contact from the
 * tenant scalars.
 */
export default function PrivacyPolicyEditorCard() {
  const { t } = useTranslation();
  const { tenant, refreshTenant } = useTenant();
  const tenantId = tenant?.id as string | undefined;
  const current = (tenant?.privacy_policy_html as string | undefined) ?? "";
  const hasCustomPolicy = current.trim().length > 0;

  const [modalVisible, setModalVisible] = useState(false);
  const [previewVisible, setPreviewVisible] = useState(false);
  // Same key-bump trick as ``SettingsPage`` — every open creates a fresh
  // ``RichTextEditorModal`` instance so its internal
  // ``useState(value || "")`` initialises with the value just passed in.
  const [modalNonce, setModalNonce] = useState(0);

  const { mutate, isPending } = useTenantsTenantsPartialUpdate({
    mutation: {
      onSuccess: async () => {
        notify.success(
          t("gdpr.privacy_policy_saved"),
        );
        await refreshTenant();
      },
      onError: (error) => {
        notify.error(
          getErrorMessage(
            error,
            t("gdpr.privacy_policy_save_failed"),
          ),
        );
      },
    },
  });

  const handleSave = (content: string) => {
    if (!tenantId) return;
    // Quill normalises an empty editor to ``<p><br></p>``; store that
    // as a true empty string so the public page falls back to the
    // i18n template rather than rendering an empty paragraph.
    const normalised =
      content.trim() === "" || content === "<p><br></p>" ? "" : content;
    mutate({
      id: tenantId,
      data: { privacy_policy_html: normalised } as unknown as Tenant,
    });
  };

  const handleRestoreDefault = () => {
    if (!tenantId) return;
    mutate({
      id: tenantId,
      data: { privacy_policy_html: "" } as unknown as Tenant,
    });
  };

  const openEditor = () => {
    setModalVisible(true);
    setModalNonce((n) => n + 1);
  };

  return (
    <>
      <Card
        className="settings-card-header"
        title={t("gdpr.privacy_policy_card_title")}
      >
        <Space direction="vertical" size="middle" className="w-full">
          <Space>
            <Text strong>{t("gdpr.privacy_policy_status")}:</Text>
            {hasCustomPolicy ? (
              <Tag color="green">
                {t("gdpr.privacy_policy_status_custom")}
              </Tag>
            ) : (
              <Tag>
                {t("gdpr.privacy_policy_status_default")}
              </Tag>
            )}
          </Space>

          <Space>
            <Button
              type="primary"
              icon={<EditOutlined />}
              onClick={openEditor}
              disabled={!tenantId || isPending}
              loading={isPending}
            >
              {t("gdpr.privacy_policy_edit_button")}
            </Button>
            <Button
              icon={<EyeOutlined />}
              onClick={() => setPreviewVisible(true)}
            >
              {t("gdpr.privacy_policy_preview_default")}
            </Button>
            {hasCustomPolicy && (
              <Button
                onClick={handleRestoreDefault}
                disabled={!tenantId || isPending}
              >
                {t("gdpr.privacy_policy_restore_default")}
              </Button>
            )}
          </Space>
        </Space>
      </Card>

      <RichTextEditorModal
        key={modalNonce}
        visible={modalVisible}
        onClose={() => setModalVisible(false)}
        value={current}
        onSave={handleSave}
        title={t("gdpr.privacy_policy_card_title")}
      />

      <Modal
        title={t("gdpr.privacy_policy_preview_title")}
        open={previewVisible}
        onCancel={() => setPreviewVisible(false)}
        footer={null}
        width={800}
      >
        <DefaultPrivacyPolicyTemplate tenant={tenant} />
      </Modal>
    </>
  );
}
