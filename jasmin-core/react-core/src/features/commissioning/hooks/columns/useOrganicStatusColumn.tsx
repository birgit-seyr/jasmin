import { useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { organicStatusOptions, useOrganicGate } from "@hooks/index";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";

/**
 * The tenant-gated organic-status SELECT column (organic / in transition /
 * conventional). Returns an EMPTY array when the tenant isn't organic-certified,
 * so callers can spread it straight into a columns array without their own gate.
 * Single source shared by ListShareArticles and DocumentationPurchase.
 */
export function useOrganicStatusColumn(): EditableColumnConfig<TableRecord>[] {
  const { t } = useTranslation();
  const { enabled } = useOrganicGate();

  return useMemo(() => {
    if (!enabled) return [];
    const organicOptions = organicStatusOptions(t);
    return [
      {
        title: <>{t("commissioning.organic_status")}</>,
        dataIndex: "organic_status",
        key: "organic_status",
        inputType: "select",
        required: false,
        sortable: true,
        options: organicOptions,
        render: (value: unknown): ReactNode => {
          const match = organicOptions.find(
            (o) => o.value === (value as string),
          );
          return match ? match.label : (value as string) || "-";
        },
      },
    ];
  }, [enabled, t]);
}
