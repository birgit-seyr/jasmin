import { EditOutlined, FormOutlined } from "@ant-design/icons";
import { Button } from "antd";
import { useTranslation } from "react-i18next";
import { useModal } from "@shared/contexts/ModalContext";
import { ToolTipIcon } from "../ui";

export default function ModalToggle() {
  const { isModalMode, toggleEditMode } = useModal();
  const { t } = useTranslation();

  return (
    <>
      <Button
        type="text"
        className="modal-toggle-button"
        icon={isModalMode ? <FormOutlined /> : <EditOutlined />}
        onClick={toggleEditMode}
        aria-label={t("tooltip.modal_toggle")}
      />
      <ToolTipIcon title={t("tooltip.modal_toggle")} />
    </>
  );
}
