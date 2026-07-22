import { QuestionCircleOutlined } from "@ant-design/icons";
import { useRoles } from "@shared/auth";
import SupportDrawer from "@shared/support/SupportDrawer";
import { Button, theme } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ToolTipIcon } from "../ui";

/**
 * Top-bar "report a problem" control. Staff-only: it lives in the staff-layout
 * TopNavigation (member/customer layouts never mount it), and the ``isStaff``
 * gate is defense-in-depth on top of the backend's IsStaff enforcement.
 */
export default function HelpButton() {
  const { isStaff } = useRoles();
  const { t } = useTranslation();
  const { token } = theme.useToken();
  const [open, setOpen] = useState(false);

  if (!isStaff) return null;

  return (
    <>
      <Button
        type="text"
        icon={<QuestionCircleOutlined />}
        onClick={() => setOpen(true)}
        aria-label={t("support.help_button")}
        style={{ color: token.colorPrimary }}
      />
      <ToolTipIcon title={t("tooltip.support_button")} />
      <SupportDrawer open={open} onClose={() => setOpen(false)} />
    </>
  );
}
