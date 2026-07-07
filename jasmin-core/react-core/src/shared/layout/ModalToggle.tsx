import { EditOutlined, FormOutlined } from "@ant-design/icons";
import { Button, theme } from "antd";
import { useTranslation } from "react-i18next";
import { useModal } from "@shared/contexts/ModalContext";
import { ToolTipIcon } from "../ui";

export default function ModalToggle() {
  const { editMode, toggleEditMode, loading, EDIT_MODES } = useModal();
  const { t } = useTranslation();

  const isModalMode = editMode === EDIT_MODES.MODAL;
  const { token } = theme.useToken();



  return (
    <>
      <Button
        type="text"
        icon={isModalMode ? <FormOutlined /> : <EditOutlined />}
        onClick={() => {
          toggleEditMode();
        }}
        loading={loading}
        aria-label={t("tooltip.modal_toggle")}
        style={{
          color: token.colorPrimary,
        }}
      />
      <ToolTipIcon title={t("tooltip.modal_toggle")} />
    </>
  );
}
