import { SettingOutlined } from "@ant-design/icons";
import { Button } from "antd";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useNavigation } from "@shared/contexts/NavigationContext";
import { ToolTipIcon } from "../ui";

/**
 * The configuration as an icon of the top bar, where it isn't a section of
 * the navigation (``configuration_section``): a text button like the icons
 * beside it, which opens the configuration with its sidebar, as the section's
 * entry would.
 */
export default function ConfigurationButton() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { switchSection, NAVIGATION_SECTIONS } = useNavigation();

  return (
    <>
      <Button
        type="text"
        className="configuration-button"
        icon={<SettingOutlined />}
        aria-label={t("nav.configuration")}
        onClick={() => {
          switchSection(NAVIGATION_SECTIONS.CONFIGURATION);
          navigate("/configuration/dashboard");
        }}
      />
      <ToolTipIcon title={t("tooltip.configuration_button")} />
    </>
  );
}
