import { useQueryClient } from "@tanstack/react-query";
import { Button, Space, Tag } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningAbosCreate,
  commissioningAbosDestroy,
  commissioningAbosPartialUpdate,
  getCommissioningAbosListQueryKey,
  useCommissioningAbosList,
  useCommissioningAbosOfferSpotCreate,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningAbosListParams,
  Subscription,
} from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { AdminConfirmationModalAbos } from "@features/abos/modals/AdminConfirmationModalAbos";
import { CapacityOverview } from "@features/abos/components/CapacityOverview";
import { OfferSpotModal } from "@features/abos/modals/OfferSpotModal";
import {
  capacityWindowParams,
  termCapacity,
  termWeekKeys,
} from "@features/abos/utils/stationCapacity";
import { EditableTable, wrapApiFunctions } from "@shared/tables";
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
  useTenant,
} from "@hooks/index";
import { useAdminConfirmationModalAbos } from "@features/abos/hooks/modals/useAdminConfirmationModalAbos";
import { useSharedAboColumns } from "@features/abos/hooks/columns/useSharedAboColumns";
import { notify, toApiDate } from "@shared/utils";
import { parseDateLoose } from "@shared/utils/endOfTerm";
import { getErrorCode } from "@shared/utils/apiError";
import type { AboRecord } from "./types";

export default function WaitingListAbos() {
  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const { getSetting } = useTenant();
  // Reachable by direct URL even when the sidebar entry is hidden — gate the
  // offer affordance so legacy queued rows can't be offered a spot when off.
  const allowsWaitingList = Boolean(
    getSetting("allows_waiting_list_for_subscriptions", true),
  );
  // Waiting-list entries are created by the subscribe flow (a full variation /
  // station routes the order here), never added by hand — so no add + no
  // inline edit. The office can only remove an entry (delete).
  const permissions = useMemo(
    () => ({ canAdd: false, canEdit: false, canDelete: isOffice }),
    [isOffice],
  );
  const queryClient = useQueryClient();
  const { dateFormat, formatDate } = useDateFormat();

  const { members } = useMembers();

  const { paymentCycles } = usePaymentCycles();

  const shareTypeParams = useMemo(
    () => ({ active_at_date: toApiDate(dayjs())! }),
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
  // Wide fixed capacity window so both the variations and the station-days
  // carry ``capacity_by_week`` for the range-selectable capacity overview —
  // the SAME window the Abos table + new-subscription modal use.
  const capacityWindow = useMemo(() => capacityWindowParams(), []);
  // ``active_at_date_or_future`` (not ``active_at_date``): a station-day that
  // only STARTS next week is still relevant to capacity planning, so include
  // current + upcoming ones — otherwise the overview is empty until every
  // station-day's valid_from has passed.
  const { deliveryStationDays } = useDeliveryStationDays(
    useMemo(
      () => ({
        active_at_date_or_future: toApiDate(dayjs())!,
        ...capacityWindow,
      }),
      [capacityWindow],
    ),
  );

  // Literal-typed alias: the interface-based ``ShareTypeOption`` has no
  // implicit index signature, which the hook's index-signed ``ShareTypeRef``
  // parameter requires — this bridges the two without a cast.
  const shareTypeRefs: { id?: string | null }[] = shareTypes;
  const variationParams = useMemo(
    () => ({ ...shareParamsWithFuture, ...capacityWindow }),
    [shareParamsWithFuture, capacityWindow],
  );
  const { shareTypeVariations: allShareTypeVariations } =
    useAllShareTypeVariations(shareTypeRefs, variationParams);

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
        const cancelledDate = parseDateLoose(
          record.cancelled_effective_at,
          dateFormat,
        );
        const validFromDate = parseDateLoose(record.valid_from, dateFormat);
        const validUntilDate = parseDateLoose(record.valid_until, dateFormat);

        if (!cancelledDate || !validFromDate || !validUntilDate) {
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

  // ── Waiting-list offer: "is this row claimable now?" + the Notify button ──
  // A row is claimable when BOTH its variation (production cap) and its
  // station-day (logistics cap) have room for its term + quantity — the SAME
  // termCapacity evaluator the modal / abos-select / overview use. Offering
  // holds the slot, so an already-offered (SPOT_AVAILABLE) row reads as full
  // here and can't be double-offered.
  const offerMutation = useCommissioningAbosOfferSpotCreate();

  const variationById = useMemo(() => {
    const map = new Map<string, (typeof allShareTypeVariations)[number]>();
    for (const v of allShareTypeVariations) map.set(String(v.value), v);
    return map;
  }, [allShareTypeVariations]);
  const stationDayById = useMemo(() => {
    const map = new Map<string, (typeof deliveryStationDays)[number]>();
    for (const d of deliveryStationDays) map.set(String(d.value), d);
    return map;
  }, [deliveryStationDays]);

  const rowAvailability = useCallback(
    (record: AboRecord) => {
      const from = parseDateLoose(record.valid_from, dateFormat);
      if (!from) {
        return { variationFull: false, stationFull: false, claimable: false };
      }
      const until = parseDateLoose(record.valid_until, dateFormat);
      const weekKeys = termWeekKeys(from, until);
      const qty = Number(record.quantity) || 1;
      const variation = variationById.get(String(record.share_type_variation));
      const station = stationDayById.get(
        String(record.default_delivery_station_day),
      );
      const variationFull = variation
        ? termCapacity(
            variation.capacity,
            variation.capacity_by_week,
            weekKeys,
            qty,
          ).isFull
        : false;
      const stationFull = station
        ? termCapacity(
            station.capacity,
            station.capacity_by_week,
            weekKeys,
            qty,
          ).isFull
        : false;
      return {
        variationFull,
        stationFull,
        claimable: !variationFull && !stationFull,
      };
    },
    [variationById, stationDayById, dateFormat],
  );

  // The Notify button opens a "Review & send" modal (price adjustment) rather
  // than firing immediately.
  const [offerRecord, setOfferRecord] = useState<AboRecord | null>(null);
  const offerSuggestedPrice = useMemo(() => {
    if (!offerRecord) return null;
    const variation = variationById.get(
      String(offerRecord.share_type_variation),
    );
    const price = variation?.active_price_per_delivery;
    return price != null ? Number(price) : null;
  }, [offerRecord, variationById]);

  const handleOffer = useCallback(
    (record: AboRecord, price: number | null) => {
      if (!record.id) return;
      offerMutation.mutate(
        {
          id: String(record.id),
          data: {
            price_per_delivery: price != null ? String(price) : null,
          },
        },
        {
          onSuccess: () => {
            notify.success(t("abos.offer_sent"));
            setOfferRecord(null);
            invalidateData();
          },
          onError: (error) => {
            const code = getErrorCode(error);
            notify.error(
              code === "share_type_variation.over_capacity"
                ? t("abos.offer_variation_full")
                : code === "delivery_station.over_capacity"
                  ? t("abos.offer_station_full")
                  : t("abos.offer_failed"),
            );
          },
        },
      );
    },
    [offerMutation, invalidateData, t],
  );

  const {
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
        // Server-inferred at enqueue: which capacity gate sent this to the
        // list (variation sold out / station full), or a manual office queue.
        title: <>{t("abos.waiting_list_reason")}</>,
        dataIndex: "waiting_list_reason",
        key: "waiting_list_reason",
        disabled: true,
        readOnly: true,
        align: "center",
        width: "9em",
        sortable: true,
        render: (value: unknown) => {
          const reason = (value as string | null) ?? null;
          if (!reason) return null;
          const color =
            reason === "variation_full"
              ? "orange"
              : reason === "delivery_station_full"
                ? "gold"
                : "default";
          return (
            <Tag color={color}>{t(`abos.waiting_list_reason_${reason}`)}</Tag>
          );
        },
      },
      {
        // "Can this row be given a spot now?" + the Notify button. Once offered
        // (SPOT_AVAILABLE) the row shows an awaiting-response tag instead.
        title: <>{t("abos.availability")}</>,
        dataIndex: "waiting_list_status",
        key: "availability",
        disabled: true,
        readOnly: true,
        align: "left",
        width: "24em",
        render: (_value: unknown, record: AboRecord) => {
          if (record.key === -1) return null;
          if (record.waiting_list_status === "spot_available") {
            return (
              <Tag color="blue">
                {record.notification_expires_at
                  ? t("abos.offered_until", {
                      date: formatDate(record.notification_expires_at),
                    })
                  : t("abos.offered")}
              </Tag>
            );
          }
          const { claimable, variationFull, stationFull } =
            rowAvailability(record);
          if (!claimable) {
            const reason = variationFull
              ? t("abos.availability_variation_full")
              : stationFull
                ? t("abos.availability_station_full")
                : t("abos.availability_waiting");
            return (
              <span style={{ color: "var(--color-text-tertiary)" }}>
                {reason}
              </span>
            );
          }
          return (
            <Space>
              <Tag color="green">{t("abos.available_now")}</Tag>
              {isOffice && allowsWaitingList && (
                <Button
                  size="small"
                  type="primary"
                  onClick={() => setOfferRecord(record)}
                >
                  {t("abos.notify_member")}
                </Button>
              )}
            </Space>
          );
        },
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
      memberColumn,
      shareTypeVariationColumn,
      quantityColumn,
      deliveryStationDayColumn,
      rowAvailability,
      isOffice,
      allowsWaitingList,
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

      <CapacityOverview
        variations={allShareTypeVariations}
        stationDays={deliveryStationDays}
      />

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
        uniqueCheckMessage={t(
          "validation.unique.member_share_type_variation_valid_from",
        )}
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

      <OfferSpotModal
        open={offerRecord !== null}
        record={offerRecord}
        suggestedPrice={offerSuggestedPrice}
        loading={offerMutation.isPending}
        onCancel={() => setOfferRecord(null)}
        onConfirm={(price) => {
          if (offerRecord) handleOffer(offerRecord, price);
        }}
      />
    </div>
  );
}
