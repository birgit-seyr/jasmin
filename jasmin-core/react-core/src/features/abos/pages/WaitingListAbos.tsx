import { useQueryClient } from "@tanstack/react-query";
import dayjs from "dayjs";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningAbosCreate,
  commissioningAbosDestroy,
  commissioningAbosPartialUpdate,
  getCommissioningAbosListQueryKey,
  useCommissioningAbosList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningAbosListParams,
  Subscription,
} from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { AdminConfirmationModalAbos } from "@features/abos/modals/AdminConfirmationModalAbos";
import {
  EditableTable,
  gatedByPermission,
  wrapApiFunctions,
} from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { DateRangeStatusLegend, ExplainerText } from "@shared/ui";
import {
  useAllShareTypeVariations,
  useDateFormat,
  useDeliveryStationDays,
  useInvalidateAfterTableMutation,
  useMembers,
  usePaymentCycles,
  useShareTypes,
  useTableRowSelection,
} from "@hooks/index";
import { useAdminConfirmationModalAbos } from "@features/abos/hooks/modals/useAdminConfirmationModalAbos";
import { useSharedAboColumns } from "@features/abos/hooks/columns/useSharedAboColumns";
import { notify } from "@shared/utils";
import type { AboRecord } from "./types";

export default function WaitingListAbos() {
  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const permissions = useMemo(() => gatedByPermission(isOffice), [isOffice]);
  const queryClient = useQueryClient();
  const { dateFormat, formatDate } = useDateFormat();

  const { members } = useMembers();

  const { paymentCycles } = usePaymentCycles();

  const shareTypeParams = useMemo(
    () => ({ active_at_date: dayjs().format("YYYY-MM-DD") }),
    [],
  );
  // Share types + their variations include current AND upcoming ones so the
  // picker can offer not-yet-started options; delivery-station-days keep the
  // active-only window (include_future only applies to the share-type endpoints).
  const shareParamsWithFuture = useMemo(
    () => ({ ...shareTypeParams, include_future: true }),
    [shareTypeParams],
  );
  const { shareTypes } = useShareTypes(shareParamsWithFuture);
  const { deliveryStationDays } = useDeliveryStationDays(shareTypeParams);

  // Literal-typed alias: the interface-based ``ShareTypeOption`` has no
  // implicit index signature, which the hook's index-signed ``ShareTypeRef``
  // parameter requires — this bridges the two without a cast.
  const shareTypeRefs: { id?: string | null }[] = shareTypes;
  const { shareTypeVariations: allShareTypeVariations } =
    useAllShareTypeVariations(shareTypeRefs, shareParamsWithFuture);

  // row selection state and handler:
  const {
    selectedRowKeys,
    onSelectedRowsChange: handleRowSelectionChange,
    rowSelection: rowSelectionConfig,
  } = useTableRowSelection((record: TableRecord) => record.key === -1);

  const validateCancelledDate = useCallback(
    (record: AboRecord) => {
      if (!record.cancelled_effective_at) {
        return { isValid: true };
      }

      if (!record.valid_from || !record.valid_until) {
        return {
          isValid: false,
          message: t("validation.valid_dates_required_for_cancellation"),
        };
      }

      try {
        let cancelledDate: dayjs.Dayjs;
        let validFromDate: dayjs.Dayjs;
        let validUntilDate: dayjs.Dayjs;

        if (typeof record.cancelled_effective_at === "string") {
          cancelledDate = dayjs(
            record.cancelled_effective_at,
            dateFormat,
            true,
          );
          if (!cancelledDate.isValid()) {
            cancelledDate = dayjs(
              record.cancelled_effective_at,
              "YYYY-MM-DD",
              true,
            );
          }
        } else {
          cancelledDate = dayjs(record.cancelled_effective_at);
        }

        if (typeof record.valid_from === "string") {
          validFromDate = dayjs(record.valid_from, dateFormat, true);
          if (!validFromDate.isValid()) {
            validFromDate = dayjs(record.valid_from, "YYYY-MM-DD", true);
          }
        } else {
          validFromDate = dayjs(record.valid_from);
        }

        if (typeof record.valid_until === "string") {
          validUntilDate = dayjs(record.valid_until, dateFormat, true);
          if (!validUntilDate.isValid()) {
            validUntilDate = dayjs(record.valid_until, "YYYY-MM-DD", true);
          }
        } else {
          validUntilDate = dayjs(record.valid_until);
        }

        if (
          !cancelledDate.isValid() ||
          !validFromDate.isValid() ||
          !validUntilDate.isValid()
        ) {
          return {
            isValid: false,
            message: t("validation.invalid_date_format"),
          };
        }

        if (
          cancelledDate.isSameOrAfter(validFromDate, "day") &&
          cancelledDate.isSameOrBefore(validUntilDate, "day")
        ) {
          return { isValid: true };
        } else {
          return {
            isValid: false,
            message: t(
              "validation.cancelled_date_must_be_between_valid_dates",
              {
                validFrom: validFromDate.format(dateFormat),
                validUntil: validUntilDate.format(dateFormat),
              },
            ),
          };
        }
      } catch (error) {
        console.error("Error validating cancelled date:", error);
        return {
          isValid: false,
          message: t("validation.date_validation_error"),
        };
      }
    },
    [dateFormat, t],
  );

  const customEdit = useCallback(
    (
      record: TableRecord,
      form: { setFieldsValue: (v: Record<string, unknown>) => void },
    ) => {
      if (record.key === -1) {
        const defaultValues = {
          is_trial: false,
          quantity: 1,
          payment_cycle: paymentCycles[0]?.value || null,
        };
        form.setFieldsValue(defaultValues);
        return { ...record, ...defaultValues };
      }
      return record;
    },
    [paymentCycles],
  );

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => {
      const validation = validateCancelledDate(transformedData as AboRecord);
      if (!validation.isValid) {
        notify.validationError(
          validation.message ?? t("common.validation_error"),
        );
        throw new Error(validation.message);
      }

      return {
        ...transformedData,
        is_trial: transformedData.is_trial ?? false,
        // Rows created on this page ARE waiting-list entries — without the
        // flag the backend would create a normal draft (reserving capacity,
        // 409 on a full station) that immediately vanishes from this
        // on_waiting_list=true filtered list.
        on_waiting_list: true,
      };
    },
    [validateCancelledDate, t],
  );

  const {
    isAdminConfirmationModalOpen,
    selectedAboForConfirmation,
    loading: adminModalLoading,
    handleCloseAdminConfirmationModal,
    confirmAbo,
  } = useAdminConfirmationModalAbos();

  const listParams = useMemo<CommissioningAbosListParams>(
    () => ({ on_waiting_list: true }),
    [],
  );

  const { data: rawData, isLoading } = useCommissioningAbosList(listParams);

  const data = useMemo(
    () => (rawData ?? []) as unknown as AboRecord[],
    [rawData],
  );

  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningAbosListQueryKey(listParams),
    });
  }, [queryClient, listParams]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

  const aboHasStarted = useCallback((record: AboRecord) => {
    if (record.key === -1) return false;
    if (record.valid_from) {
      const validFromDate = dayjs(record.valid_from);
      const today = dayjs().startOf("day");
      if (validFromDate.isBefore(today)) return true;
    }
    return false;
  }, []);

  const handleShareTypeVariationChange = useCallback(
    (
      value: unknown,
      _record: AboRecord,
      form: { setFieldsValue: (v: Record<string, unknown>) => void },
    ) => {
      if (!value) return {};

      try {
        const selectedVariation = allShareTypeVariations.find(
          (variation) => variation.value === value,
        );

        if (selectedVariation && selectedVariation.active_price_per_delivery) {
          form.setFieldsValue({
            price_per_delivery: selectedVariation.active_price_per_delivery,
          });
          return {
            price_per_delivery: selectedVariation.active_price_per_delivery,
          };
        }
      } catch (error) {
        console.error("Error setting weekly_price:", error);
      }

      return {};
    },
    [allShareTypeVariations],
  );

  const {
    displayIdColumn,
    memberColumn,
    shareTypeVariationColumn,
    quantityColumn,
    deliveryStationDayColumn,
  } = useSharedAboColumns({
    disabled: aboHasStarted,
    memberOptions: members,
    memberWidth: "18em",
    shareTypeVariationOptions: allShareTypeVariations,
    shareTypeVariationWidth: "14em",
    onShareTypeVariationChange: handleShareTypeVariationChange,
    deliveryStationDayOptions: deliveryStationDays,
    deliveryStationDayAlign: "center",
  });

  const columns: EditableColumnConfig<AboRecord>[] = useMemo(
    () => [
      displayIdColumn,
      {
        // FIFO queue position per station-day — informational; the office may
        // promote out of order via the normal confirm flow.
        title: <>{t("abos.waiting_list_position")}</>,
        dataIndex: "waiting_list_position",
        key: "waiting_list_position",
        inputType: "text",
        required: false,
        disabled: true,
        readOnly: true,
        align: "center",
        width: "5em",
        sortable: true,
        defaultSortOrder: "ascend" as const,
      },
      {
        title: <>{t("members.created_at")}</>,
        dataIndex: "created_at",
        key: "created_at",
        inputType: "date",
        required: true,
        align: "center",
        width: "8em",
        disabled: aboHasStarted,
        render: (value: unknown) => formatDate(value as string),
      },
      memberColumn,
      shareTypeVariationColumn,
      quantityColumn,
      deliveryStationDayColumn,
    ],
    [
      t,
      aboHasStarted,
      formatDate,
      displayIdColumn,
      memberColumn,
      shareTypeVariationColumn,
      quantityColumn,
      deliveryStationDayColumn,
    ],
  );

  // No ``list``: this page owns the data via ``useCommissioningAbosList``
  // (passed as ``initialData``). Supplying ``list`` would make EditableTable
  // double-fetch the same endpoint (it auto-fetches when ``showSearchBar`` +
  // ``apiFunctions.list`` are both set). Search filters client-side; mutations
  // refresh through the ``onSaveSuccess``/``onDeleteSuccess`` invalidation.
  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<Subscription & TableRecord>({
        create: (data) => commissioningAbosCreate(data),
        update: (id, data) => commissioningAbosPartialUpdate(id, data),
        delete: (id) => commissioningAbosDestroy(id),
      }),
    [],
  );

  return (
    <div>
      <h1>{t("abos.waiting_list")}</h1>

      <EditableTable
        columns={columns}
        apiFunctions={apiFunctions}
        focusIndex="member_string"
        initialData={data}
        loading={isLoading}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        customSave={customSave}
        customEdit={customEdit}
        uniqueCheck={["member", "share_type_variation", "valid_from"]}
        uniqueCheckMessage={t("validation.unique.member_share_type_variation_valid_from")}
        permissions={permissions}
        pagination={true}
        showSearchBar={true}
        rowSelection={rowSelectionConfig}
        onSelectedRowsChange={handleRowSelectionChange}
        selectedRowKeys={selectedRowKeys}
      />
      <DateRangeStatusLegend />

      <ExplainerText title={t("common.info")}>
        {t("explainers.waiting_list")}
      </ExplainerText>

      <AdminConfirmationModalAbos
        isOpen={isAdminConfirmationModalOpen}
        onClose={handleCloseAdminConfirmationModal}
        abo={selectedAboForConfirmation}
        onConfirm={confirmAbo}
        loading={adminModalLoading}
      />
    </div>
  );
}
