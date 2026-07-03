import { EditOutlined } from "@ant-design/icons";
import { Button, Form, Input, Space, Tag } from "antd";
import type { FormItemProps } from "antd";
import { useTranslation } from "react-i18next";

/**
 * Form-row helper for fields that are stored encrypted in the database
 * (IBAN, ``account_owner``) and never echoed back as plaintext.
 *
 * Two states:
 *  * Not editing → shows a "✓ gespeichert" / "nicht hinterlegt" tag
 *    (or the ``maskedValue`` if provided) + an "Ändern" / "Hinterlegen"
 *    button.
 *  * Editing     → shows an Input bound to the form field plus a
 *    Cancel button that restores the previous state without sending.
 *
 * The parent owns the ``editing`` boolean and the form instance — this
 * component is intentionally controlled so the parent can clear the
 * field value on cancel (see ``form.setFieldValue(name, "")``) and
 * strip empty values on submit before PATCHing.
 *
 * ``maskedValue`` (optional) shows a recognizable masked form of the
 * stored value (e.g. ``DE •••• 3000``) instead of a generic "stored"
 * tag — used where the API exposes a ``*_masked`` companion. ``rules``
 * (optional) attaches validation to the edit input (e.g. an IBAN check).
 */
export default function StoredOrEditField({
  name,
  label,
  stored,
  editing,
  onStartEdit,
  onCancelEdit,
  maskedValue,
  rules,
}: {
  name: string;
  label: string;
  stored: boolean;
  editing: boolean;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  maskedValue?: string;
  rules?: FormItemProps["rules"];
}) {
  const { t } = useTranslation();
  if (!editing) {
    return (
      <Form.Item label={label}>
        <Space>
          {stored ? (
            <Tag color="green">{maskedValue || t("gdpr.stored")}</Tag>
          ) : (
            <Tag>{t("profile.not_stored")}</Tag>
          )}
          <Button size="small" icon={<EditOutlined />} onClick={onStartEdit}>
            {stored
              ? t("profile.change_value")
              : t("profile.set_value")}
          </Button>
        </Space>
      </Form.Item>
    );
  }
  return (
    <Form.Item label={label}>
      <Space.Compact style={{ width: "100%" }}>
        <Form.Item name={name} noStyle rules={rules}>
          <Input
            aria-label={label}
            placeholder={t("profile.enter_new_value")}
          />
        </Form.Item>
        <Button onClick={onCancelEdit}>
          {t("common.cancel")}
        </Button>
      </Space.Compact>
    </Form.Item>
  );
}
