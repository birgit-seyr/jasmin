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
    <div style={{ minHeight: 22 }}>
      {saving ? (
        <Space size="small">
          <SyncOutlined spin style={{ color: "var(--color-payments)" }} />
          <Text type="secondary">{t("settings.saving")}</Text>
        </Space>
      ) : showSaved && !hasChanges ? (
        <Space size="small">
          <CheckCircleOutlined style={{ color: "var(--color-success)" }} />
          <Text type="secondary">{t("settings.saved")}</Text>
        </Space>
      ) : null}
    </div>
  );
}
