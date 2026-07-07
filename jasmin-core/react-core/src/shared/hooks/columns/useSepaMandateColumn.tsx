import { ToolTipIcon } from "@/shared/ui";
import type { SepaMandateStatus } from "@shared/api/generated/models";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { isSepaMandateActiveForTerm } from "@shared/utils";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

interface SepaMandateColumnOptions {
  /** Resolve the mandate status for a row's member (from ``useSepaMandateStatus``). */
  getMandateForMember: (
    memberId?: string | null,
  ) => SepaMandateStatus | undefined;
  /** Open the mandate-details modal for the clicked row. */
  onShowDetails: (
    status: SepaMandateStatus | undefined,
    record: TableRecord,
  ) => void;
  /** Row field holding the member id. Default ``"member"``. */
  memberField?: string;
  /** Row field holding the subscription's end date. Default ``"valid_until"``. */
  validUntilField?: string;
  width?: string;
}

/**
 * Compact "does this subscription's member have a SEPA mandate active during
 * its term?" column — a green square (active) / dark-red square (not),
 * click-through to the mandate details. Same shape + footprint as
 * ``useActiveStatusColumn`` so it sits naturally alongside the other status
 * squares. The square is a real ``<button>`` with an aria-label so the
 * colour-only state is announced and keyboard-reachable.
 */
export const useSepaMandateColumn = (
  options: SepaMandateColumnOptions,
): EditableColumnConfig<TableRecord> => {
  const { t } = useTranslation();
  const {
    getMandateForMember,
    onShowDetails,
    memberField = "member",
    validUntilField = "valid_until",
    width = "3.5em",
  } = options;

  return useMemo<EditableColumnConfig<TableRecord>>(
    () => ({
      title: (
        <div className="checkbox-column-title">
          sepa
          <ToolTipIcon title={t("sepa.column_tooltip")} />
        </div>
      ),
      dataIndex: "has_active_sepa_mandate",
      key: "has_active_sepa_mandate",
      align: "center",
      readOnly: true,
      disabled: true,
      width,
      showSorterTooltip: false,
      sorter: (
        a: TableRecord,
        b: TableRecord,
        sortOrder?: "ascend" | "descend",
      ) => {
        // Keep the unsaved add-row placeholder on top, like the sibling status
        // columns (AntD reverses the comparator for "descend").
        if (a.key === -1) return sortOrder === "descend" ? 1 : -1;
        if (b.key === -1) return sortOrder === "descend" ? -1 : 1;
        const activeA = isSepaMandateActiveForTerm(
          getMandateForMember(a[memberField] as string | undefined),
          a[validUntilField] as string | null | undefined,
        );
        const activeB = isSepaMandateActiveForTerm(
          getMandateForMember(b[memberField] as string | undefined),
          b[validUntilField] as string | null | undefined,
        );
        return Number(activeA) - Number(activeB);
      },
      render: (_: unknown, record: TableRecord) => {
        // No square for the placeholder add-row (not a real subscription yet).
        if (record.key === -1) return null;
        const status = getMandateForMember(
          record[memberField] as string | undefined,
        );
        const active = isSepaMandateActiveForTerm(
          status,
          record[validUntilField] as string | null | undefined,
        );
        const label = active
          ? t("sepa.mandate_active")
          : t("sepa.mandate_missing");
        return (
          <button
            type="button"
            aria-label={`${label} — ${t("sepa.view_details")}`}
            className={`sepa-mandate-square sepa-mandate-square--${
              active ? "active" : "inactive"
            }`}
            onClick={() => onShowDetails(status, record)}
          />
        );
      },
    }),
    [
      t,
      getMandateForMember,
      onShowDetails,
      memberField,
      validUntilField,
      width,
    ],
  );
};
