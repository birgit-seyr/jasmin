/**
 * Office/gardener view toggle + "round up to full VPE" checkbox for
 * the HarvestingList page. Desktop shows both controls in a row;
 * mobile shows only the checkbox (the gardener view is forced on
 * mobile by the page).
 */

import { AppstoreOutlined, UnorderedListOutlined } from "@ant-design/icons";
import { Button, Checkbox, Space } from "antd";
import { useTranslation } from "react-i18next";

export default function HarvestingListControls({
  isMobile,
  isGardenerView,
  onViewChange,
  roundUpToFullPU,
  onRoundUpChange,
}: {
  isMobile: boolean;
  isGardenerView: boolean;
  onViewChange: (isGardenerView: boolean) => void;
  roundUpToFullPU: boolean;
  onRoundUpChange: (checked: boolean) => void;
}) {
  const { t } = useTranslation();

  if (isMobile) {
    return (
      <div style={{ marginBottom: "8px" }}>
        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: "8px",
            cursor: "pointer",
          }}
        >
          <Checkbox
            checked={roundUpToFullPU}
            onChange={(e) => onRoundUpChange(e.target.checked)}
          />
          <span className="text-sm">
            {t("commissioning.round_up_to_full_vpe")}
          </span>
        </label>
      </div>
    );
  }

  return (
    <div
      style={{
        marginTop: "2em",
        marginBottom: "2em",
        display: "flex",
        alignItems: "center",
        gap: "1em",
      }}
    >
      <Space.Compact>
        <Button
          type={isGardenerView ? "default" : "primary"}
          icon={<UnorderedListOutlined />}
          onClick={() => onViewChange(false)}
        >
          {t("commissioning.office_view")}
        </Button>
        <Button
          type={isGardenerView ? "primary" : "default"}
          icon={<AppstoreOutlined />}
          onClick={() => onViewChange(true)}
        >
          {t("commissioning.gardener_view")}
        </Button>
      </Space.Compact>
      <label
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
          cursor: "pointer",
        }}
      >
        <Checkbox
          checked={roundUpToFullPU}
          onChange={(e) => onRoundUpChange(e.target.checked)}
        />
        <span>{t("commissioning.round_up_to_full_vpe")}</span>
      </label>
    </div>
  );
}
