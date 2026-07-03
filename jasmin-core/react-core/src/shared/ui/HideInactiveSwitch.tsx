import { useTranslation } from "react-i18next";
import LabeledSwitch from "./LabeledSwitch";

interface HideInactiveSwitchProps {
  value: boolean;
  onChange: (checked: boolean) => void;
}

export default function HideInactiveSwitch({ value, onChange }: HideInactiveSwitchProps) {
  const { t } = useTranslation();
  return (
    <LabeledSwitch
      value={value}
      onChange={onChange}
      label={t("commissioning.hide_inactive")}
      size="small"
    />
  );
}
