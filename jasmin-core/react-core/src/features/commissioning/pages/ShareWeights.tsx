import { useQueryClient } from "@tanstack/react-query";
import { Button } from "antd";
import { mondayOfIsoWeek, toApiDate } from "@shared/utils";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningSharesPartialUpdate,
  getCommissioningSharesListQueryKey,
  useCommissioningSharesList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningSharesListParams,
  Share,
} from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { useShareDeliveryDays } from "@features/commissioning/hooks";
import { ExportCsvShareWeights } from "@features/commissioning/modals";
import { WeekSelector } from "@shared/selectors";
import { SharesDeliveryDaySelector } from "@features/commissioning/selectors";
import {
  EditableTable,
  gatedByPermissionOnlyEdit,
  wrapApiFunctions,
} from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { EmptyHint, ExplainerText } from "@shared/ui";
import {
  useInvalidateAfterTableMutation,
  useNumberFormat,
  useShareTypeVariationSizeOptions,
  useYearWeekState,
} from "@hooks/index";

type ShareRow = Share & TableRecord;

export default function ShareWeights() {
  const { t } = useTranslation();
  const { format } = useNumberFormat();
  const { getShareTypeVariationSizeLabel } = useShareTypeVariationSizeOptions();
  // Writes here are office-only on the backend (ShareViewSet, IsOffice);
  // `canEdit` would offer gardener/staff a save the API refuses.
  const { isOffice } = useRoles();
  const permissions = useMemo(
    () => gatedByPermissionOnlyEdit(isOffice),
    [isOffice],
  );

  const { selectedYear, setSelectedYear, selectedWeek, setSelectedWeek } =
    useYearWeekState();
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const [csvExportVisible, setCsvExportVisible] = useState(false);

  const activeAtDate = useMemo(() => {
    if (!selectedWeek) return undefined;
    return toApiDate(mondayOfIsoWeek(selectedYear, selectedWeek))!;
  }, [selectedYear, selectedWeek]);

  const listParams = useMemo<CommissioningSharesListParams>(
    () => ({
      year: selectedYear,
      delivery_week: selectedWeek,
      delivery_day: selectedDay!,
    }),
    [selectedYear, selectedWeek, selectedDay],
  );

  // The week's delivery days, from the same query as the day selector. A day
  // picked in another week stays picked until they arrive and may not be one
  // of them, so the shares are asked for only once it is.
  const { shareDeliveryDays: weekDays, noDaysListed: weekHasNoDays } =
    useShareDeliveryDays(activeAtDate ? { active_at_date: activeAtDate } : {});
  const canFetch =
    !!selectedWeek && weekDays.some((day) => day.value === selectedDay);
  const queryClient = useQueryClient();

  // React Query — failures route through the global queryCache.onError
  // toast. Writes call `invalidateData()` to trigger a refetch.
  const { data: rawData, isFetching } = useCommissioningSharesList(listParams, {
    query: { enabled: canFetch },
  });
  const data = useMemo<ShareRow[]>(
    () =>
      canFetch
        ? ((rawData ?? []) as unknown as Share[]).map((item) => ({
            ...item,
            key: item.id ?? "",
          }))
        : [],
    [rawData, canFetch],
  );
  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningSharesListQueryKey(listParams),
    });
  }, [queryClient, listParams]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<Share & TableRecord>({
        update: (id, payload) => commissioningSharesPartialUpdate(id, payload),
      }),
    [],
  );

  const columns: EditableColumnConfig<ShareRow>[] = useMemo(
    () => [
      {
        title: "",
        dataIndex: "share_type_name",
        key: "share_label",
        readOnly: true,
        width: "14em",
        render: (_: unknown, record: ShareRow) => {
          const typeName = record.share_type_name ?? "";
          const sizeLabel = getShareTypeVariationSizeLabel(
            record.share_type_variation_size ?? "",
          );
          // lint-allow: no-raw-decimal — both args are display strings, not numbers.
          return `${typeName} ${sizeLabel}`.trim();
        },
      },
      {
        title: t("commissioning.target_weight"),
        dataIndex: "share_type_variation_average_weight",
        key: "target_weight",
        readOnly: true,
        disabled: true,
        width: "8em",
        align: "center",
        render: (_: unknown, record: ShareRow) => {
          const val = Number(record.share_type_variation_average_weight);
          return val > 0 ? `${format(val, 3)} kg` : "";
        },
      },
      ...[1, 2, 3, 4].map(
        (n): EditableColumnConfig<ShareRow> => ({
          title: `${t("commissioning.weight")} ${n}`,
          dataIndex: `weight${n}`,
          key: `weight${n}`,
          inputType: "decimal3",
          width: "8em",
          align: "center",
          render: (_: unknown, record: ShareRow) => {
            const val = Number(record[`weight${n}`]);
            return val > 0 ? format(val, 3) : "";
          },
        }),
      ),
      {
        title: "⌀",
        dataIndex: "weight_avg",
        key: "weight_avg",
        width: "8em",
        align: "center",
        readOnly: true,
        render: (_: unknown, record: ShareRow) => {
          const weights = [
            record.weight1,
            record.weight2,
            record.weight3,
            record.weight4,
          ]
            .map(Number)
            .filter((v) => v > 0);
          if (weights.length === 0) return "";
          const avg = weights.reduce((sum, v) => sum + v, 0) / weights.length;
          return `${format(avg, 2)} kg`;
        },
      },
    ],
    [t, getShareTypeVariationSizeLabel, format],
  );

  return (
    <div>
      <h1>{t("commissioning.share_weights")}</h1>

      <WeekSelector
        selectedYear={selectedYear}
        setSelectedYear={setSelectedYear}
        selectedWeek={selectedWeek}
        setSelectedWeek={setSelectedWeek}
      />

      <SharesDeliveryDaySelector
        selectedSharesDeliveryDay={selectedDay}
        setSelectedSharesDeliveryDay={setSelectedDay}
        active_at_date={activeAtDate}
        selectedYear={selectedYear}
        selectedWeek={selectedWeek}
      />

      {/* A pick still waiting for its week's days keeps the table, spinning. */}
      {selectedDay ? (
        <EditableTable
          key={`${selectedYear}-${selectedWeek}-${selectedDay}`}
          columns={columns}
          apiFunctions={apiFunctions}
          initialData={data}
          onSaveSuccess={onSaveSuccess}
          onDeleteSuccess={onDeleteSuccess}
          loading={!canFetch || isFetching}
          className="w-max custom-jasmin-table"
          permissions={permissions}
        />
      ) : weekHasNoDays ? (
        <EmptyHint>{t("commissioning.no_delivery_days_in_week")}</EmptyHint>
      ) : null}
      <ExplainerText title={t("common.info")}>
        {t("explainers.share_weights")}
      </ExplainerText>
      <div style={{ marginTop: 16, marginBottom: 16 }}>
        <Button
          onClick={() => setCsvExportVisible(true)}
          className="download-button"
        >
          {t("commissioning.csv_export_average_weight")}
        </Button>
      </div>
      <ExportCsvShareWeights
        open={csvExportVisible}
        onClose={() => setCsvExportVisible(false)}
      />
    </div>
  );
}
