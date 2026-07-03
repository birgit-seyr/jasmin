import { CheckOutlined } from "@ant-design/icons";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import ToolTipIcon from "@shared/ui/ToolTipIcon";

interface FinalColumnConfig {
  tooltipTitle?: string;
}

export const useFinalColumn = (config: FinalColumnConfig = {}) => {
  const { t } = useTranslation();
  const { tooltipTitle } = config;

  const finalColumn: EditableColumnConfig<TableRecord> = useMemo(
    () => ({
      title: (
        <>
          <ToolTipIcon title={tooltipTitle || t("tooltip.final_column")} />
        </>
      ),
      dataIndex: "is_finalized",
      key: "is_finalized",
      align: "center",
      readOnly: true,
      disabled: true,
      fixed: true,
      width: "2em",
      render: (value: unknown) =>
        value ? (
          <>
            <CheckOutlined aria-hidden className="text-success" />
            <span className="sr-only">{t("commissioning.finalized")}</span>
          </>
        ) : (
          <span className="sr-only">{t("commissioning.not_finalized")}</span>
        ),
    }),

    [t, tooltipTitle],
  );

  return {
    finalColumn,
  };
};
