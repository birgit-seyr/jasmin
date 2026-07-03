import { useEffect } from "react";
import type { FC } from "react";
import { Modal, Form, Input, Select, Checkbox } from "antd";
import { useShareArticleModal } from '@features/commissioning/hooks';
import { useEnterToSubmit } from "@shared/modals/shared";

interface ShareArticleModalProps {
  isOpen: boolean;
  onClose?: () => void;
  onSuccess?: (savedData: Record<string, unknown>) => void;
  defaultValues?: Record<string, unknown>;
}

const ShareArticleModal: FC<ShareArticleModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
  defaultValues = {},
}) => {
  const {
    isVisible,
    loading,
    form,
    unitOptions,
    fruit_and_veg_shares_are_separate,
    openModal,
    closeModal,
    saveShareArticle,
    t,
  } = useShareArticleModal();

  useEffect(() => {
    if (isOpen && !isVisible) {
      openModal(defaultValues);
    } else if (!isOpen && isVisible) {
      closeModal();
    }
  }, [isOpen, isVisible, openModal, closeModal, defaultValues]);

  const handleSave = () => {
    saveShareArticle((savedData: unknown) => {
      if (onSuccess) {
        onSuccess(savedData as Record<string, unknown>);
      }
      if (onClose) {
        onClose();
      }
    });
  };

  const handleCancel = () => {
    closeModal();
    if (onClose) {
      onClose();
    }
  };

  const handleKeyDown = useEnterToSubmit(handleSave);

  return (
    <Modal
      title={t("commissioning.add_share_article") || "Add Share Article"}
      open={isVisible}
      onOk={handleSave}
      onCancel={handleCancel}
      width="30em"
      okText={t("table.save") || "Save"}
      cancelText={t("table.cancel") || "Cancel"}
      confirmLoading={loading}
    >
      <Form form={form} layout="vertical" onKeyDown={handleKeyDown}>
        <Form.Item
          name="name"
          label={t("commissioning.name")}
          rules={[
            { required: true, message: t("commissioning.please_enter_a_name") },
          ]}
        >
          <Input />
        </Form.Item>

        <Form.Item
          name="default_movement_unit"
          label={t("commissioning.default_movement_unit")}
          rules={[
            { required: true, message: t("commissioning.please_select_a_unit") },
          ]}
        >
          <Select options={unitOptions} />
        </Form.Item>

        <Form.Item
          name="description"
          label={t("commissioning.description")}
          rules={[
            {
              required: false,
              message: t("commissioning.please_enter_a_description"),
            },
          ]}
        >
          <Input />
        </Form.Item>

        <div className="flex-center-y gap-8" style={{ marginBottom: "16px" }}>
          <Form.Item
            name="is_active"
            valuePropName="checked"
            style={{ margin: 0 }}
          >
            <Checkbox />
          </Form.Item>
          <span>{t("commissioning.is_active")}</span>
        </div>

        <div className="flex-center-y gap-8" style={{ marginBottom: "16px" }}>
          <Form.Item
            name="is_purchased"
            valuePropName="checked"
            style={{ margin: 0 }}
          >
            <Checkbox />
          </Form.Item>
          <span>{t("commissioning.is_purchased")}</span>
        </div>

        {!fruit_and_veg_shares_are_separate && (
          <div className="flex-center-y gap-8" style={{ marginBottom: "16px" }}>
            <Form.Item
              name="harvest_share"
              valuePropName="checked"
              style={{ margin: 0 }}
            >
              <Checkbox />
            </Form.Item>
            <span>{t("commissioning.for_harvest_share")}</span>
          </div>
        )}

        {fruit_and_veg_shares_are_separate && (
          <>
            <div className="flex-center-y gap-8" style={{ marginBottom: "16px" }}>
              <Form.Item
                name="harvest_share"
                valuePropName="checked"
                style={{ margin: 0 }}
              >
                <Checkbox />
              </Form.Item>
              <span>{t("commissioning.for_harvest_share_veg_only")}</span>
            </div>

            <div className="flex-center-y gap-8" style={{ marginBottom: "16px" }}>
              <Form.Item
                name="harvest_share_fruit"
                valuePropName="checked"
                style={{ margin: 0 }}
              >
                <Checkbox />
              </Form.Item>
              <span>{t("commissioning.for_harvest_share_fruits_only")}</span>
            </div>
          </>
        )}
      </Form>
    </Modal>
  );
};

export default ShareArticleModal;
