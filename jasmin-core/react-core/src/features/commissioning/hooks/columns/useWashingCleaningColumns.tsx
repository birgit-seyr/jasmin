import type { FormInstance } from "antd";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { EditableColumnConfig, TableRecord } from "@shared/tables/BasicEditableTable/types";
import ToolTipIcon from "@shared/ui/ToolTipIcon";

export const useWashingCleaningColumns = () => {
  const { t } = useTranslation();

  const handleWashingCleaningChange = useMemo(() => {
    return (value: unknown, _record: TableRecord, _form: FormInstance, fieldName: string): Record<string, unknown> | undefined => {
      if (value === true) {
        if (fieldName === "washing") return { cleaning: false };
        if (fieldName === "cleaning") return { washing: false };
      }
      return undefined;
    };
  }, []);

  const washingCleaningColumns = useMemo<EditableColumnConfig<TableRecord>[]>(
    () => [
      {
        title: (
          <>
            {t("commissioning.wash")}
            <ToolTipIcon title={t("tooltip.washing_checkbox")} />
          </>
        ),
        dataIndex: "washing",
        key: "washing",
        inputType: "checkbox",
        required: false,
        onFieldChange: handleWashingCleaningChange,
      },
      {
        title: (
          <>
            {t("commissioning.clean")}
            <ToolTipIcon title={t("tooltip.cleaning_checkbox")} />
          </>
        ),
        dataIndex: "cleaning",
        key: "cleaning",
        inputType: "checkbox",
        required: false,
        onFieldChange: handleWashingCleaningChange,
      },
      {
        title: (
          <>
            {t("commissioning.comes_from_long_term_storage")}
            <ToolTipIcon title={t("tooltip.comes_from_long_term_storage")} />
          </>
        ),
        dataIndex: "comes_from_long_term_storage",
        key: "comes_from_long_term_storage",
        inputType: "checkbox",
        required: false,
      },
    ],
    [t, handleWashingCleaningChange],
  );

  return { washingCleaningColumns };
};
