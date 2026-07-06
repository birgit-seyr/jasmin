/**
 * Abos (subscriptions) page. Deliberately thin: modal + row-selection
 * state and layout live here; the data sources are ``useAbosData``,
 * every column shape (incl. the valid_until auto-fill handlers) is
 * ``useAbosColumns``.
 */

import { AdminConfirmationModalAbos } from "@features/abos/modals/AdminConfirmationModalAbos";
import { CancelSubscriptionModal } from "@features/abos/modals/CancelSubscriptionModal";
import { RejectAboModal } from "@features/abos/modals/RejectAboModal";
import {
  commissioningAbosCreate,
  commissioningAbosDestroy,
  commissioningAbosPartialUpdate,
} from "@shared/api/generated/commissioning/commissioning";
import type { Subscription } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { LoggingModal } from "@shared/modals";
import {
  EditableTable,
  gatedByPermission,
  wrapApiFunctions,
} from "@shared/tables";
import type {
  ApiFunctions,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { DateRangeStatusLegend, ExplainerText } from "@shared/ui";
import { Badge, Button } from "antd";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
// Imported directly from the source module (not the ``hooks`` barrel) to
// avoid a Rollup chunk cycle: the barrel re-exports ``useAbosColumns`` while
// that module transitively depends back on the barrel (via the ``ui`` barrel).
import AbosBulkActions from "@features/abos/components/AbosBulkActions";
import { useAbosColumns } from "@features/abos/hooks/columns/useAbosColumns";
import { useAdminConfirmationModalAbos } from "@features/abos/hooks/modals/useAdminConfirmationModalAbos";
import { useRejectAboModal } from "@features/abos/hooks/modals/useRejectAboModal";
import { useAbosData } from "@features/abos/hooks/useAbosData";
import SubscriptionStatsCards from "@features/abos/components/SubscriptionStatsCards";
import { useDateFormat, useTableRowSelection } from "@hooks/index";
import { notify } from "@shared/utils";
import { getErrorCode } from "@shared/utils/apiError";
import type { AboRecord } from "./types";
import { validateCancelledDate as validateCancelledDatePure } from "./validation";

export default function Abos() {
  const { t } = useTranslation();
  const { dateFormat } = useDateFormat();
  const { isOffice } = useRoles();
  const permissions = useMemo(
    () => ({
      ...gatedByPermission(isOffice),
      // Per-row: admin-confirmed subscriptions are immutable from this
      // page. The only legitimate way to end one is the per-row Cancel
      // button (which routes through ``commissioningAbosCancelCreate``
      // → ``SubscriptionService.cancel_subscription``). Hiding the
      // edit + delete buttons keeps the UI honest about what's
      // possible; the backend mirrors this in
      // ``SubscriptionViewSet.destroy`` (409) +
      // ``SubscriptionSerializer.validate`` (LockedAfterAdminConfirmation).
      canEditRecord: (record: TableRecord) =>
        record.key === -1 ||
        // A REJECTED subscription's row is kept for statistics — not editable.
        (!(record as AboRecord).admin_confirmed &&
          !(record as AboRecord).admin_rejected_at),
      canDeleteRecord: (record: TableRecord) =>
        record.key === -1 ||
        (!(record as AboRecord).admin_confirmed &&
          // A REJECTED subscription's row is kept for statistics — not deletable.
          !(record as AboRecord).admin_rejected_at &&
          (!record.id || record.can_be_deleted !== false)),
    }),
    [isOffice],
  );

  // row selection state and handler:
  const {
    selectedRowKeys,
    onSelectedRowsChange: handleRowSelectionChange,
    rowSelection: rowSelectionConfig,
    clearSelection,
  } = useTableRowSelection((record: TableRecord) => record.key === -1);
  const [loggingModalOpen, setLoggingModalOpen] = useState(false);
  const [loggingRecord, setLoggingRecord] = useState<AboRecord | null>(null);
  const [cancelModalOpen, setCancelModalOpen] = useState(false);
  const [cancelRecord, setCancelRecord] = useState<AboRecord | null>(null);

  const {
    data,
    isFetching,
    invalidateData,
    onSaveSuccess,
    onDeleteSuccess,
    recentlyAddedIds,
    members,
    paymentCycles,
    allShareTypeVariations,
    variationDeliveryCycleById,
    getDeliveryStationDaysForRow,
    getShareTypeVariationsForRow,
  } = useAbosData();

  // Thin i18n wrapper over the pure validation in
  // ``pages/abos/validation.ts``. Pulled out so the date math is
  // unit-tested independently from React / i18n.
  const validateCancelledDate = useCallback(
    (record: AboRecord) => {
      const result = validateCancelledDatePure(record, dateFormat);
      if (result.isValid) return { isValid: true };
      const message =
        result.messageKey ===
        "validation.cancelled_date_must_be_between_valid_dates"
          ? t(result.messageKey, {
              validFrom: result.validFrom,
              validUntil: result.validUntil,
            })
          : t(result.messageKey ?? "validation.date_validation_error");
      return { isValid: false, message };
    },
    [dateFormat, t],
  );

  const customEdit = useCallback(
    (
      record: TableRecord,
      form: { setFieldsValue: (values: Record<string, unknown>) => void },
    ) => {
      // If it's a new row (key === -1), set default values
      if (record.key === -1) {
        const defaultValues = {
          is_trial: false,
          quantity: 1,
          payment_cycle: paymentCycles[0]?.value || null,
        };

        // Set the form values with defaults
        form.setFieldsValue(defaultValues);

        // Return the record with defaults applied
        return { ...record, ...defaultValues };
      }

      // For existing rows, return as-is
      return record;
    },
    [paymentCycles],
  );

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => {
      const validation = validateCancelledDate(transformedData as AboRecord);
      if (!validation.isValid) {
        // Show error message
        notify.validationError(
          validation.message ?? t("common.validation_error"),
        );

        // Throw error to prevent save
        throw new Error(validation.message ?? t("common.validation_error"));
      }

      return {
        ...transformedData,
        is_trial: (transformedData as AboRecord).is_trial ?? false,
      };
    },
    [validateCancelledDate, t],
  );

  const {
    isAdminConfirmationModalOpen,
    selectedAboForConfirmation,
    loading: adminModalLoading,
    handleOpenAdminConfirmationModal,
    handleCloseAdminConfirmationModal,
    handleConfirmAbo,
    getAdminStatus,
    getAdminStatusSorter,
  } = useAdminConfirmationModalAbos();

  // The admin-status column is sortable on click only (the table no longer
  // auto-sorts — see useAbosColumns, so new rows pin to the top in natural
  // order). When the office DOES sort by it, wrap the base sorter so
  // freshly-added ids (tracked by ``useInvalidateAfterTableMutation``) stay
  // pinned at the top regardless of sort direction — same shape as the
  // ``key === -1`` placeholder pin already inside ``getAdminStatusSorter``.
  const getAdminStatusSorterPinned = useCallback(
    (a: TableRecord, b: TableRecord, sortOrder?: "ascend" | "descend") => {
      const aPinned = a.id != null && recentlyAddedIds.has(String(a.id));
      const bPinned = b.id != null && recentlyAddedIds.has(String(b.id));
      if (aPinned && !bPinned) return sortOrder === "descend" ? 1 : -1;
      if (!aPinned && bPinned) return sortOrder === "descend" ? -1 : 1;
      return getAdminStatusSorter(a, b, sortOrder);
    },
    [recentlyAddedIds, getAdminStatusSorter],
  );

  const {
    isRejectModalOpen,
    selectedAboForRejection,
    loading: rejectModalLoading,
    reason: rejectionReason,
    setReason: setRejectionReason,
    handleOpenRejectModal,
    handleCloseRejectModal,
    rejectAbo,
  } = useRejectAboModal();

  const handleCancelRow = useCallback((record: AboRecord) => {
    setCancelRecord(record);
    setCancelModalOpen(true);
  }, []);

  const handleShowLog = useCallback((record: AboRecord) => {
    setLoggingRecord(record);
    setLoggingModalOpen(true);
  }, []);

  const { columns } = useAbosColumns({
    members,
    paymentCycles,
    allShareTypeVariations,
    variationDeliveryCycleById,
    getDeliveryStationDaysForRow,
    getShareTypeVariationsForRow,
    getAdminStatus,
    onOpenAdminConfirmation: handleOpenAdminConfirmationModal,
    adminStatusSorter: getAdminStatusSorterPinned,
    recentlyAddedIds,
    onCancel: handleCancelRow,
    onShowLog: handleShowLog,
  });

  // No ``list``: this page owns the data via ``useCommissioningAbosList``
  // (passed as ``initialData``). Supplying ``list`` would make EditableTable
  // double-fetch the same endpoint (it auto-fetches when ``showSearchBar`` +
  // ``apiFunctions.list`` are both set). Search filters client-side; mutations
  // refresh through the ``onSaveSuccess``/``onDeleteSuccess`` invalidation.
  const apiFunctions = useMemo<ApiFunctions>(() => {
    // A sold-out variation / full station-day 409s a normal save. Don't
    // dead-end the office — redo the save as a waiting-list entry (same as the
    // member subscribe modal; the backend records WHY on the waiting-list
    // page), then invalidate so the now-waiting-listed row LEAVES this
    // (on_waiting_list=false) grid instead of lingering as a phantom draft that
    // inflates the pending-confirmation count.
    const overCapacityCode = (error: unknown): string | null => {
      const code = getErrorCode(error);
      return code === "share_type_variation.over_capacity" ||
        code === "delivery_station.over_capacity"
        ? code
        : null;
    };
    const notifyWaitingListed = (code: string) =>
      notify.info(
        t(
          code === "share_type_variation.over_capacity"
            ? "abos.waiting_listed_variation_full"
            : "abos.waiting_listed_station_full",
        ),
      );
    return wrapApiFunctions<Subscription & TableRecord>({
      create: async (data) => {
        try {
          return await commissioningAbosCreate(data);
        } catch (error) {
          const code = overCapacityCode(error);
          if (!code) throw error;
          const created = await commissioningAbosCreate({
            ...data,
            on_waiting_list: true,
          });
          notifyWaitingListed(code);
          invalidateData();
          return created;
        }
      },
      update: async (id, data) => {
        try {
          return await commissioningAbosPartialUpdate(id, data);
        } catch (error) {
          const code = overCapacityCode(error);
          if (!code) throw error;
          const updated = await commissioningAbosPartialUpdate(id, {
            ...data,
            on_waiting_list: true,
          });
          notifyWaitingListed(code);
          invalidateData();
          return updated;
        }
      },
      delete: (id) => commissioningAbosDestroy(id),
    });
  }, [t, invalidateData]);

  // "Needs attention" quick filter toggled by the page badge below: the
  // subscriptions still awaiting admin confirmation (unconfirmed, not rejected,
  // not cancelled). Filters the loaded rows client-side.
  const [attentionActive, setAttentionActive] = useState(false);
  const pendingConfirmationCount = useMemo(
    () =>
      data.filter(
        (row) =>
          !(row as AboRecord).admin_confirmed &&
          !(row as AboRecord).admin_rejected_at &&
          !(row as AboRecord).cancelled_at,
      ).length,
    [data],
  );
  const displayData = useMemo(() => {
    if (!attentionActive) return data;
    return data.filter(
      (row) =>
        !(row as AboRecord).admin_confirmed &&
        !(row as AboRecord).admin_rejected_at &&
        !(row as AboRecord).cancelled_at,
    );
  }, [data, attentionActive]);

  return (
    <div>
      <h1>{t("abos.abos")}</h1>

      <SubscriptionStatsCards />

      {pendingConfirmationCount > 0 && (
        <Badge count={pendingConfirmationCount} size="small">
          <Button
            size="small"
            type={attentionActive ? "primary" : "default"}
            onClick={() => setAttentionActive((prev) => !prev)}
          >
            {t("abos.attention_chip")}
          </Button>
        </Badge>
      )}
      <div className="bulk-actions-header">
        <strong>{t("commissioning.for_selected")}</strong>
      </div>
      {isOffice && (
        <AbosBulkActions
          selectedRowKeys={selectedRowKeys}
          onClearSelection={clearSelection}
          onInvalidate={invalidateData}
        />
      )}

      <EditableTable
        columns={columns}
        apiFunctions={apiFunctions}
        focusIndex="member_string"
        initialData={displayData}
        loading={isFetching}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        customSave={customSave}
        customEdit={customEdit}
        permissions={permissions}
        pagination={true}
        showSearchBar={true}
        rowSelection={rowSelectionConfig}
        onSelectedRowsChange={handleRowSelectionChange}
        selectedRowKeys={selectedRowKeys}
        rowClassName={(record) =>
          (record as AboRecord).member_cancelled_at ? "abo-row--cancelled" : ""
        }
      />
      <DateRangeStatusLegend />

      <ExplainerText title={t("common.info")}>
        {t("explainers.abos")}
      </ExplainerText>

      <AdminConfirmationModalAbos
        isOpen={isAdminConfirmationModalOpen}
        onClose={handleCloseAdminConfirmationModal}
        abo={selectedAboForConfirmation}
        onConfirm={() => handleConfirmAbo(invalidateData)}
        onReject={() => {
          const target = selectedAboForConfirmation;
          handleCloseAdminConfirmationModal();
          if (target) {
            handleOpenRejectModal(target);
          }
        }}
        loading={adminModalLoading}
      />

      <RejectAboModal
        isOpen={isRejectModalOpen}
        onClose={handleCloseRejectModal}
        abo={selectedAboForRejection}
        reason={rejectionReason}
        onReasonChange={setRejectionReason}
        loading={rejectModalLoading}
        onReject={async () => {
          await rejectAbo();
          invalidateData();
        }}
      />

      <LoggingModal
        isOpen={loggingModalOpen}
        onClose={() => {
          setLoggingModalOpen(false);
          setLoggingRecord(null);
        }}
        record={loggingRecord}
        title={`${t("logging.title")} - ${loggingRecord?.member_first_name || ""} ${loggingRecord?.member_last_name || ""}`}
      />

      <CancelSubscriptionModal
        isOpen={cancelModalOpen}
        onClose={() => {
          setCancelModalOpen(false);
          setCancelRecord(null);
        }}
        abo={cancelRecord}
        onCancelled={invalidateData}
      />
    </div>
  );
}
