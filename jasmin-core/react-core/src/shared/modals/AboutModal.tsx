import { CheckCircleTwoTone } from "@ant-design/icons";
import { List, Modal, Space, Typography } from "antd";
import { useTranslation } from "react-i18next";

const { Title, Text } = Typography;

// Order shown in the modal. Each id maps to ``about.feature_<id>_{title,desc}``.
const FEATURE_IDS = [
  "cooperative",
  "configurable",
  "delivery",
  "working_lists",
  "bio",
  "documents",
  "selfservice",
  "trial",
  "sepa",
  "security",
  "multilingual",
  "cultivation",
  "economics",
  "staff",
  "gdpr",
  "a11y",
  "opensource",
] as const;

interface AboutModalProps {
  open: boolean;
  onClose: () => void;
}

export default function AboutModal({ open, onClose }: AboutModalProps) {
  const { t } = useTranslation();

  return (
    <Modal
      title={t("about.title")}
      open={open}
      onCancel={onClose}
      footer={null}
      width={620}
    >
      <Title level={5} style={{ marginTop: 0 }}>
        {t("about.features_title")}
      </Title>
      <List
        size="small"
        split={false}
        dataSource={[...FEATURE_IDS]}
        renderItem={(id) => (
          <List.Item style={{ padding: "6px 0", alignItems: "flex-start" }}>
            <Space align="start" size={10}>
              <CheckCircleTwoTone
                aria-hidden
                twoToneColor="#52c41a"
                style={{ marginTop: 4, fontSize: 16 }}
              />
              <span>
                <Text strong>{t(`about.feature_${id}_title`)}</Text>
                <br />
                <Text type="secondary">{t(`about.feature_${id}_desc`)}</Text>
              </span>
            </Space>
          </List.Item>
        )}
      />
      <a href="https://github.com/birgit-seyr/jasmin.git">GitHub</a>
    </Modal>
  );
}
