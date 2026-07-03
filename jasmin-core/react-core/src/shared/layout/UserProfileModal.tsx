import {
  ExclamationCircleOutlined,
  UserOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Descriptions,
  Form,
  Input,
  Modal,
  Space,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { authPartialUpdate } from "@shared/api/generated/auth/auth";
import { gdprRequestDeletionCreate } from "@shared/api/generated/gdpr/gdpr";
import { useAuth } from "@shared/contexts/AuthContext";
import { notify } from "@shared/utils";
import TwoFactorPanel from "@shared/profile/TwoFactorPanel";
import MyDataTab from "./MyDataTab";

const { Paragraph } = Typography;

export type UserProfileTab = "profile" | "my_data" | "two_factor";

interface UserProfileModalProps {
  open: boolean;
  onClose: () => void;
  /**
   * Tab to land on when the modal opens. ``"profile"`` shows the
   * basic user data + edit; ``"my_data"`` jumps to the role-aware
   * editable surface (address, payment, consents, JSON-Export/Delete).
   */
  initialTab?: UserProfileTab;
}

export default function UserProfileModal({
  open,
  onClose,
  initialTab = "profile",
}: UserProfileModalProps) {
  const { t } = useTranslation();
  const { user, logout, updateUser } = useAuth();

  const [editMode, setEditMode] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  const [deleteConfirmVisible, setDeleteConfirmVisible] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const handleSaveProfile = async () => {
    if (!user) return;
    setSaving(true);
    try {
      const values = await form.validateFields();
      await authPartialUpdate(String(user.id), values);
      updateUser({
        first_name: values.first_name,
        last_name: values.last_name,
      });
      notify.success(t("profile.saved"));
      setEditMode(false);
    } catch (error) {
      console.error("Operation failed:", error);
      notify.error(t("profile.save_error"));
    } finally {
      setSaving(false);
    }
  };

  const handleRequestDeletion = async () => {
    setDeleting(true);
    try {
      await gdprRequestDeletionCreate();
      setDeleteConfirmVisible(false);
      onClose();
      await logout();
    } catch (error) {
      console.error("Operation failed:", error);
      setDeleting(false);
    }
  };

  const handleOpen = () => {
    if (user) {
      form.setFieldsValue({
        first_name: (user as Record<string, unknown>).first_name || "",
        last_name: (user as Record<string, unknown>).last_name || "",
      });
    }
  };

  const profileTab = (
    <div>
      {!editMode ? (
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label={t("profile.email")}>
            {(user as Record<string, unknown> | null)?.email as string}
          </Descriptions.Item>
          <Descriptions.Item label={t("profile.first_name")}>
            {(user as Record<string, unknown> | null)?.first_name as string}
          </Descriptions.Item>
          <Descriptions.Item label={t("profile.last_name")}>
            {(user as Record<string, unknown> | null)?.last_name as string}
          </Descriptions.Item>
          <Descriptions.Item label={t("profile.role")}>
            <Tag color="green">
              {((user as Record<string, unknown> | null)?.role as string) ||
                ((user as Record<string, unknown> | null)
                  ?.userRole as string) ||
                "member"}
            </Tag>
          </Descriptions.Item>
        </Descriptions>
      ) : (
        <Form form={form} layout="vertical">
          <Form.Item
            name="first_name"
            label={t("profile.first_name")}
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="last_name"
            label={t("profile.last_name")}
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
        </Form>
      )}
      <div className="flex-end" style={{ marginTop: 16 }}>
        {editMode ? (
          <Space>
            <Button onClick={() => setEditMode(false)}>
              {t("common.cancel")}
            </Button>
            <Button
              type="primary"
              onClick={handleSaveProfile}
              loading={saving}
              style={{ background: "var(--color-primary-hover)" }}
            >
              {t("common.save")}
            </Button>
          </Space>
        ) : (
          <Button onClick={() => setEditMode(true)}>{t("common.edit")}</Button>
        )}
      </div>
    </div>
  );

  return (
    <Modal
      title={
        <span className="icon-title-row">
          <UserOutlined />
          {t("profile.title")}
        </span>
      }
      open={open}
      onCancel={onClose}
      afterOpenChange={(visible) => visible && handleOpen()}
      width={720}
      footer={null}
    >
      <Tabs
        // Re-key on open + initialTab so reopening the modal jumps to
        // the right tab without us having to mirror the state in
        // a useEffect.
        activeKey={undefined}
        defaultActiveKey={initialTab}
        key={`${open ? "open" : "closed"}-${initialTab}`}
        items={[
          {
            key: "profile",
            label: t("profile.tab_profile"),
            children: profileTab,
          },
          {
            key: "my_data",
            label: t("profile.tab_my_data"),
            children: (
              <MyDataTab
                onRequestDeletion={() => setDeleteConfirmVisible(true)}
              />
            ),
          },
          {
            key: "two_factor",
            label: t("profile.tab_two_factor"),
            children: <TwoFactorPanel />,
          },
        ]}
      />

      {/* Deletion Confirmation Modal */}
      <Modal
        title={
          <span className="icon-title-row">
            <ExclamationCircleOutlined style={{ color: "var(--color-error)" }} />
            {t("gdpr.confirm_deletion_title")}
          </span>
        }
        open={deleteConfirmVisible}
        onCancel={() => setDeleteConfirmVisible(false)}
        footer={[
          <Button key="cancel" onClick={() => setDeleteConfirmVisible(false)}>
            {t("common.cancel")}
          </Button>,
          <Button
            key="delete"
            danger
            type="primary"
            loading={deleting}
            onClick={handleRequestDeletion}
          >
            {t("gdpr.confirm_delete")}
          </Button>,
        ]}
      >
        <Alert
          message={t("gdpr.deletion_warning")}
          description={t("gdpr.deletion_warning_description")}
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
        />
        <Paragraph>{t("gdpr.deletion_consequences")}</Paragraph>
      </Modal>
    </Modal>
  );
}
