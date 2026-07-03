import { useDateFormat } from "@hooks/index";
import { Input, Space, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useTranslation } from "react-i18next";
import type { SettingConfig } from "./SettingsRenderer";

const { Text } = Typography;

// Mirror of the backend ``_render_remittance`` (apps/payments/services.py):
// same placeholders + German month names, so the office's live preview matches
// the text actually written into the pain.008 ``Ustrd`` at export.
const DE_MONTHS = [
  "Januar",
  "Februar",
  "März",
  "April",
  "Mai",
  "Juni",
  "Juli",
  "August",
  "September",
  "Oktober",
  "November",
  "Dezember",
];

const PLACEHOLDERS = [
  "{creditor}",
  "{member}",
  "{month}",
  "{period}",
  "{amount}",
];

// Same default the backend falls back to when the template is blank.
const DEFAULT_TEMPLATE = "{creditor} - {month}";

function renderPreview(template: string, dateFormat: string): string {
  const now = dayjs();
  const sample: Record<string, string> = {
    "{creditor}": "Marillenhof",
    "{member}": "Anna Huber",
    "{month}": `${DE_MONTHS[now.month()]} ${now.year()}`,
    "{period}": `${now.startOf("month").format(dateFormat)}–${now
      .endOf("month")
      .format(dateFormat)}`,
    "{amount}": "25.00",
  };
  let text = (template || "").trim() || DEFAULT_TEMPLATE;
  for (const [token, value] of Object.entries(sample)) {
    text = text.split(token).join(value);
  }
  return text.slice(0, 140);
}

interface Props {
  setting: SettingConfig;
  value: string;
  onChange: (value: string) => void;
}

/**
 * Editor for the SEPA remittance template (the bank-statement text). A plain
 * text field is opaque — a user has no way to know which ``{placeholders}``
 * exist or what the result looks like. This adds: clickable chips that append
 * each supported placeholder, and a live preview rendered with sample data so
 * the office sees exactly what a member will read on their statement.
 */
export function RemittanceTemplateInput({ setting, value, onChange }: Props) {
  const { t } = useTranslation();
  const { dateFormat } = useDateFormat();
  const current = value || "";

  return (
    <div>
      <Text strong>{setting.label}</Text>
      <Input
        value={current}
        onChange={(e) => onChange(e.target.value)}
        placeholder={DEFAULT_TEMPLATE}
        maxLength={setting.maxLength}
        style={{ marginTop: 4 }}
      />
      <Space size={4} wrap style={{ marginTop: 8 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {t("tenant.sepa.remittance_insert")}
        </Text>
        {PLACEHOLDERS.map((token) => (
          <Tag
            key={token}
            onClick={() => onChange(`${current}${token}`)}
            style={{ cursor: "pointer", margin: 0 }}
          >
            {token}
          </Tag>
        ))}
      </Space>
      <div style={{ marginTop: 8 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {t("tenant.sepa.remittance_preview")}:{" "}
        </Text>
        <Text code style={{ fontSize: 12 }}>
          {renderPreview(current, dateFormat)}
        </Text>
      </div>
    </div>
  );
}
