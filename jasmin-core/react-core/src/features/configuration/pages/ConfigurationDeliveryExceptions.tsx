import dayjs from "dayjs";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningDeliveryExceptionPeriodsCreate,
  commissioningDeliveryExceptionPeriodsDestroy,
  commissioningDeliveryExceptionPeriodsPartialUpdate,
  useCommissioningDeliveryExceptionPeriodsList,
} from "@shared/api/generated/commissioning/commissioning";
import type { DeliveryExceptionPeriod } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import {
  EditableTable,
  isUnprotectedRow,
  permissionsWithDeletable,
  wrapApiFunctions,
} from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  SelectOption,
  TablePermissions,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { DateRangeStatusLegend, ExplainerText } from "@shared/ui";
import {
  useInvalidateAfterTableMutation,
  useNoteColumn,
  useVariationLabel,
} from "@hooks/index";
import { useActiveStatusColumn } from "@hooks/columns/useActiveStatusColumn";
import { useTimeBoundColumns } from "@hooks/columns/useTimeBoundColumns";
import { useShareTypeVariations } from "@features/commissioning/hooks";
import { isoWeekRangeLabel } from "@shared/utils";

/**
 * "Lieferpausen" — per-ShareTypeVariation delivery-exception periods. During a
 * pause no ShareDelivery is materialised (hence no production demand and, since
 * billing is delivery-driven, no billing). Creating / editing / deleting a
 * period resyncs already-confirmed subscriptions' future deliveries backend-side.
 *
 * Reuses the shared TimeBound columns (valid_from Monday-only / valid_until
 * Sunday-only) + the active-status indicator, so the whole-week bounds and the
 * active/upcoming/expired badge behave exactly like every other TimeBound table.
 */
export default function ConfigurationDeliveryExceptions() {
  const { t } = useTranslation();
  const variationLabel = useVariationLabel();
  const { isOffice } = useRoles();
  // A started (active/past) pause is frozen — the backend rejects edit/delete
  // (is_locked), so grey out the row's edit + delete affordances here too.
  const permissions = useMemo<TablePermissions>(
    () => ({
      ...permissionsWithDeletable(isOffice),
      canEditRecord: (record) => !record.is_locked,
      canDeleteRecord: (record) =>
        isUnprotectedRow(record) && !record.is_locked,
    }),
    [isOffice],
  );

  const activeStatusColumn = useActiveStatusColumn();
  const { validFromColumn, validUntilColumn } = useTimeBoundColumns({
    validFromRequired: true,
    validUntilRequired: true,
    // Once valid_from is picked, valid_until may only be a Sunday in the future
    // relative to it — the earliest being that week's Sunday (a one-week pause).
    // Evaluated live against the in-edit valid_from; the backend enforces the
    // same "valid_until on or after valid_from" rule.
    validUntilFloor: (record) => {
      const validFrom = record.valid_from
        ? dayjs(record.valid_from as string)
        : null;
      return validFrom ? { minDate: validFrom.add(6, "day") } : {};
    },
  });
  const { noteColumn } = useNoteColumn();

  const { shareTypeVariations } = useShareTypeVariations();
  const variationOptions = useMemo<SelectOption[]>(
    () =>
      shareTypeVariations.map((variation) => ({
        value: String(variation.value),
        label: `${variation.share_type_name ?? ""} – ${variation.size ?? ""}`,
      })),
    [shareTypeVariations],
  );

  // The page owns the data (initialData); no ``list`` in apiFunctions so the
  // table never double-fetches. Saves don't refetch; deletes do.
  const {
    data: periodsData,
    refetch,
    isLoading,
  } = useCommissioningDeliveryExceptionPeriodsList();
  const data = useMemo<TableRecord[]>(
    () => (periodsData ?? []) as unknown as TableRecord[],
    [periodsData],
  );

  const invalidateData = useCallback(() => {
    void refetch();
  }, [refetch]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<DeliveryExceptionPeriod & TableRecord>({
        create: (payload) =>
          commissioningDeliveryExceptionPeriodsCreate(payload),
        update: (id, payload) =>
          commissioningDeliveryExceptionPeriodsPartialUpdate(id, payload),
        delete: (id) => commissioningDeliveryExceptionPeriodsDestroy(id),
      }),
    [],
  );

  const columns = useMemo<EditableColumnConfig<TableRecord>[]>(
    () => [
      activeStatusColumn,
      validFromColumn,
      validUntilColumn,
      {
        // Read-only summary of which ISO weeks the valid_from/valid_until range
        // covers (bounds are whole weeks — Monday → Sunday).
        title: <>{t("commissioning.KW")}</>,
        dataIndex: "iso_weeks_covered",
        key: "iso_weeks_covered",
        width: "9em",
        align: "center",
        readOnly: true,
        hideInModal: true,
        render: (_: unknown, record: TableRecord) =>
          isoWeekRangeLabel(
            record.valid_from as string,
            record.valid_until as string,
            t("commissioning.KW"),
          ),
      },
      {
        title: <>{t("commissioning.share_type_variation")}</>,
        dataIndex: "share_type_variation_string",
        key: "share_type_variation_string",
        inputType: "select",
        required: true,
        width: "14em",
        align: "left",
        options: variationOptions,
        foreignKey: {
          valueField: "share_type_variation",
          displayField: "share_type_variation_string",
        },
        sortable: true,
        render: (value: unknown) => variationLabel(value as string),
      },

      noteColumn,
    ],
    [
      t,
      activeStatusColumn,
      validFromColumn,
      validUntilColumn,
      variationOptions,
      noteColumn,
      variationLabel,
    ],
  );

  return (
    <div>
      <h1>{t("commissioning.delivery_exceptions")}</h1>

      <EditableTable
        columns={columns}
        apiFunctions={apiFunctions}
        focusIndex="share_type_variation_string"
        initialData={data}
        loading={isLoading}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        permissions={permissions}
        style={{ width: "70%" }}
      />
      <DateRangeStatusLegend />

      <ExplainerText title={t("common.info")}>
        {t("explainers.delivery_exceptions")}
      </ExplainerText>
    </div>
  );
}
