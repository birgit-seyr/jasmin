import { CheckCircleOutlined, SyncOutlined } from "@ant-design/icons";
import { Space, Typography } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

const { Text } = Typography;

interface AutoSaveIndicatorProps {
  saving: boolean;
  hasChanges: boolean;
}

export default function AutoSaveIndicator({
  saving,
  hasChanges,
}: AutoSaveIndicatorProps) {
  const { t } = useTranslation();
  const [showSaved, setShowSaved] = useState(false);

  useEffect(() => {
    if (!saving && !hasChanges && showSaved) {
      const timer = setTimeout(() => setShowSaved(false), 2000);
      return () => clearTimeout(timer);
    }
  }, [saving, hasChanges, showSaved]);

  useEffect(() => {
    if (saving) {
      setShowSaved(true);
    }
  }, [saving]);

  return (
    // Polite live region so the saving/saved transition is announced without
    // stealing focus; the spinner/check icons are decorative (the text carries
    // the meaning), so hide them from assistive tech.
    <div role="status" aria-live="polite" style={{ minHeight: 22 }}>
      {saving ? (
        <Space size="small">
          <SyncOutlined
            spin
            aria-hidden
            style={{ color: "var(--color-future-blue)" }}
          />
          <Text type="secondary">{t("settings.saving")}</Text>
        </Space>
      ) : showSaved && !hasChanges ? (
        <Space size="small">
          <CheckCircleOutlined
            aria-hidden
            style={{ color: "var(--color-success)" }}
          />
          <Text type="secondary">{t("settings.saved")}</Text>
        </Space>
      ) : null}
    </div>
  );
}
