import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import ToolTipIcon from "@shared/ui/ToolTipIcon";

// A single stable reference for the no-args case. Without this, `options = {}`
// allocates a fresh object on every call, which would invalidate the inner
// useMemo and hand callers a brand-new column each render.
const EMPTY_OPTIONS: Record<string, unknown> = {};

export const useIsActiveColumn = (
  options: Record<string, unknown> = EMPTY_OPTIONS,
) => {
  const { t } = useTranslation();

  const isActiveColumn = useMemo(
    () => ({
      title: (
        <>
          {t("commissioning.is_active")}
          <ToolTipIcon title={t("tooltip.is_active_description")} />
        </>
      ),
      dataIndex: "is_active",
      key: "is_active",
      inputType: "checkbox",
      required: false,
      sortable: true,
      ...options,
    }),
    [t, options],
  );

  return isActiveColumn;
};
