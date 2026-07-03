import { useQueryClient } from "@tanstack/react-query";
import { Alert, Modal } from "antd";
import ModalCloseFooter from "@shared/modals/ModalCloseFooter";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningCoopSharesCreate,
  commissioningCoopSharesDestroy,
  commissioningCoopSharesPartialUpdate,
  getCommissioningCoopSharesListQueryKey,
  getCommissioningMembersListQueryKey,
  useCommissioningCoopSharesConfirmCreate,
  useCommissioningCoopSharesList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningCoopSharesListParams,
  CoopShare,
} from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import {
  adminConfirmationColumn,
  EditableTable,
  gatedByPermission,
  wrapApiFunctions,
} from "@shared/tables";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import AdminConfirmationModalCoopShares from "./AdminConfirmationModalCoopShares";
import {
  useCurrency,
  useDateFormat,
  useInvalidateAfterTableMutation,
  useNoteColumn,
  useNumberFormat,
  useTenant,
} from "@hooks/index";
import { ExplainerText } from "@shared/ui";

/**
 * A coop-share row as it flows through this modal's EditableTable: the full
 * generated ``CoopShare`` read shape (every field optional — the placeholder
 * ``key === -1`` add-row starts empty) plus the table-only ``key``.
 * ``admin_confirmed_by_name`` is narrowed from the generated ``string | null``
 * so rows stay assignable to the shared admin-confirmation modal record,
 * which declares it as optional ``string`` and only reads it truthily.
 */
type CoopShareRecord = TableRecord &
  Partial<CoopShare> & {
    admin_confirmed_by_name?: string;
  };

interface CoopSharesModalProps {
  isOpen: boolean;
  onClose: () => void;
  memberId: string | null;
  memberName?: string;
  isTrial?: boolean;
  adminConfirmed?: boolean;
  /** The member's GenG exit date (``cancelled_effective_at``) when cancelled.
   *  Non-null ⇒ the member has left: no new shares may be subscribed and the
   *  min/max range banner is replaced with the exit-date notice. */
  memberCancelledEffectiveAt?: string | null;
}

export default function CoopSharesModal({
  isOpen,
  onClose,
  memberId,
  memberName,
  isTrial = false,
  adminConfirmed = false,
  memberCancelledEffectiveAt = null,
}: CoopSharesModalProps) {
  const queryClient = useQueryClient();

  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const memberCancelled = !!memberCancelledEffectiveAt;
  const { getSetting } = useTenant();

  // Whole-unit tenant setting (number on the wire). Coerce defensively for
  // the arithmetic below and the numeric create payload. ``undefined`` = the
  // tenant hasn't configured a share value yet.
  const value_one_coop_share_raw = getSetting("value_one_coop_share");
  const value_one_coop_share =
    value_one_coop_share_raw == null
      ? undefined
      : Number(value_one_coop_share_raw);

  // Permissions:
  //  * No ADDING once the member is cancelled — they've left the co-op, so no
  //    new Geschäftsanteile (existing rows stay editable so the office can
  //    still stamp payback / paid-back over the wind-down).
  //  * No ADDING until the tenant has configured ``value_one_coop_share`` — a
  //    create without it hits the NOT NULL column with an opaque 400 (the
  //    self-service path raises CoopShareValueNotConfigured; mirror it here).
  //  * An admin-confirmed coop share is committed equity — it must be cancelled,
  //    not deleted, so hide the per-row delete on confirmed rows (pending /
  //    self-subscribed rows stay deletable).
  const permissions = useMemo(
    () => ({
      ...gatedByPermission(isOffice),
      canAdd:
        isOffice && !memberCancelled && value_one_coop_share !== undefined,
      canDeleteRecord: (record: CoopShareRecord) => !record.admin_confirmed,
    }),
    [isOffice, memberCancelled, value_one_coop_share],
  );
  const { currencySymbol } = useCurrency();
  const { format } = useNumberFormat();
  const { formatDate, formatDateWithColor } = useDateFormat();
  const { noteColumn } = useNoteColumn();

  // Mirror backend rule (CoopShareService._bounds_apply_to): the
  // [min, max] window only constrains non-trial admin-confirmed
  // Mitglieder. Trial / pending members are exempt so the office can
  // build up their position incrementally.
  const boundsApply = adminConfirmed && !isTrial;
  const minShares = boundsApply
    ? (getSetting("min_number_coop_shares") ?? null)
    : null;
  const maxShares = boundsApply
    ? (getSetting("max_number_coop_shares") ?? null)
    : null;

  const listParams = useMemo<CommissioningCoopSharesListParams>(
    () => ({ member: memberId! }),
    [memberId],
  );

  const { data: rawData, isFetching } = useCommissioningCoopSharesList(
    listParams,
    { query: { enabled: isOpen && memberId != null } },
  );
  // ONE directional boundary cast: the generated ``CoopShare`` rows lack the
  // table-only ``key`` / index-signature surface EditableTable requires.
  const data = useMemo<CoopShareRecord[]>(
    () => (rawData ?? []) as unknown as CoopShareRecord[],
    [rawData],
  );

  // How many of this member's coop shares still await office confirmation —
  // surfaced as a banner so the sidebar's pending count is obviously anchored
  // here (mirrors the badge_viewsets "pending" filter: unconfirmed, not
  // rejected, not cancelled).
  const pendingConfirmationCount = useMemo(
    () =>
      data.filter(
        (share) =>
          !share.admin_confirmed &&
          !share.admin_rejected_at &&
          !share.cancelled_at,
      ).length,
    [data],
  );

  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningCoopSharesListQueryKey(listParams),
    });
    // Also refresh the parent Members list: it renders a server-computed
    // ``coop_shares_total`` per row, drives the ``total === 0`` min-equity
    // warning, and feeds the page total stat — none of which are keyed on the
    // coop-shares query, so they'd stay stale after an add / edit / delete here.
    queryClient.invalidateQueries({
      queryKey: getCommissioningMembersListQueryKey(),
    });
  }, [queryClient, listParams]);
  const { onSaveSuccess: trackRecentlyAdded, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

  // Adding / editing a coop-share row changes aggregates that live OUTSIDE the
  // table's local state: the header total banner + min/max range alert (both
  // computed from the list query ``data``, not the inserted row) and the
  // parent Members list's server-computed ``coop_shares_total``. The shared
  // hook only invalidates on delete, so wire a custom save handler that
  // refetches on every save too (still threading the recentlyAddedIds pin).
  const onSaveSuccess = useCallback(
    (record: CoopShareRecord, action: "create" | "update") => {
      trackRecentlyAdded(record, action);
      invalidateData();
    },
    [trackRecentlyAdded, invalidateData],
  );

  // Office admin-confirmation of a coop share goes through the same status
  // column + confirmation modal as members/abos. The confirm action ignores
  // the request body — it just flips admin_confirmed server-side (and admits
  // the member if they weren't yet).
  const [confirmRecord, setConfirmRecord] = useState<CoopShareRecord | null>(
    null,
  );
  const { mutate: confirmShare, isPending: confirming } =
    useCommissioningCoopSharesConfirmCreate({
      mutation: {
        onSuccess: () => {
          invalidateData();
          setConfirmRecord(null);
        },
      },
    });
  const handleConfirm = useCallback(() => {
    if (!confirmRecord) return;
    confirmShare({ id: String(confirmRecord.id) });
  }, [confirmShare, confirmRecord]);

  const columns: EditableColumnConfig<CoopShareRecord>[] = useMemo(
    () => [
      adminConfirmationColumn<CoopShareRecord>({
        t,
        getAdminStatus: (record) =>
          record.admin_confirmed
            ? { variant: "adminConfirmed", key: "admin_confirmed" }
            : { variant: "adminPending", key: "admin_pending" },
        onOpen: setConfirmRecord,
      }),
      {
        title: t("members.amount"),
        dataIndex: "amount_of_coop_shares",
        key: "amount_of_coop_shares",
        inputType: "positive_integer",
        align: "center",
        width: "6em",
        required: true,
        sortable: true,
        // Once confirmed, the committed Geschäftsanteil size is immutable
        // (GenG — you cancel a share, you don't resize it). Lock it; only the
        // cancellation/payback lifecycle fields stay editable on confirmed rows.
        disabled: (record: CoopShareRecord) => !!record.admin_confirmed,
        render: (value: unknown) => (value ? format(Number(value), 0) : ""),
      },
      {
        title: t("members.value"),
        dataIndex: "value",
        key: "value",
        inputType: "date",
        align: "center",
        required: false,
        disabled: true,
        readOnly: true,
        width: "6em",
        render: (_value: unknown, record: CoopShareRecord) => {
          if (!record.amount_of_coop_shares || !value_one_coop_share) return "";
          return (
            <div
              style={{
                fontSize: "0.85em",
                color: "var(--color-text-muted)",
                textAlign: "center",
              }}
            >
              {format(
                Number(record.amount_of_coop_shares) *
                  (value_one_coop_share || 0),
                0,
              )}{" "}
              {currencySymbol}
            </div>
          );
        },
      },
      {
        title: t("members.due_date"),
        dataIndex: "due_date",
        key: "due_date",
        inputType: "date",
        align: "center",
        required: false,
        width: "8em",
        sortable: true,
        disabled: (record: CoopShareRecord) => !!record.admin_confirmed,
        render: (value: unknown, record: CoopShareRecord) =>
          record.paid_at
            ? formatDate(value as string | null)
            : formatDateWithColor(value as string | null),
      },
      {
        title: t("members.paid_at"),
        dataIndex: "paid_at",
        key: "paid_at",
        inputType: "date",
        align: "center",
        required: false,
        sortable: true,
        render: (value: unknown) => formatDate(value as string | null),
      },
      {
        title: <>{t("members.pay_in_monthly_rates")}</>,
        dataIndex: "pay_in_monthly_rates",
        key: "pay_in_monthly_rates",
        inputType: "checkbox",
        required: false,
        align: "center",
        disabled: (record: CoopShareRecord) =>
          !!record.is_trial || !!record.admin_confirmed,
      },
      {
        title: t("members.is_increase"),
        dataIndex: "is_increase",
        key: "is_increase",
        inputType: "checkbox",
        align: "center",
        required: false,
        sortable: true,
        disabled: (record: CoopShareRecord) => !!record.admin_confirmed,
      },
      {
        // Read-only — snapshotted server-side at member cancellation
        // (= exit date + retention months). Populated only on cancelled shares.
        title: t("members.payback_due_date"),
        dataIndex: "payback_due_date",
        key: "payback_due_date",
        inputType: "date",
        align: "center",
        required: false,
        disabled: true,
        readOnly: true,
        sortable: true,
        render: (value: unknown) => formatDate(value as string | null),
      },
      {
        // Office stamps this when the cooperative equity is actually returned.
        title: t("members.paid_back_date"),
        dataIndex: "paid_back_date",
        key: "paid_back_date",
        inputType: "date",
        align: "center",
        required: false,
        sortable: true,
        render: (value: unknown) => formatDate(value as string | null),
      },

      noteColumn,
    ],
    [
      t,
      format,
      formatDate,
      formatDateWithColor,
      currencySymbol,
      value_one_coop_share,
      noteColumn,
    ],
  );

  // ``customSave`` runs once per save. We use it both for the payload
  // shape (member id + value_one_coop_share for the create endpoint)
  // AND as a client-side gate against out-of-range totals: throwing
  // surfaces the message in the table's save-error banner BEFORE the
  // round-trip, so the office gets immediate feedback. Backend still
  // re-validates — see ``CoopShareService.assert_within_min_max``.
  const customSave = useCallback(
    (
      transformedData: Record<string, unknown>,
      currentRecord: CoopShareRecord,
    ) => {
      if (boundsApply && (minShares != null || maxShares != null)) {
        const newAmount =
          Number(transformedData.amount_of_coop_shares as string | number) || 0;
        const otherTotal = data
          // Live equity only — cancelled (divested) shares count as 0, matching
          // the enforced backend bounds invariant.
          .filter((row) => row.id !== currentRecord.id && !row.cancelled_at)
          .reduce(
            (sum, row) => sum + (Number(row.amount_of_coop_shares) || 0),
            0,
          );
        const newTotal = otherTotal + newAmount;

        if (minShares != null && newTotal < minShares) {
          throw new Error(
            t("members.below_min_shares", {
              total: newTotal,
              min: minShares,
              defaultValue: `Total ({{total}}) would be below the minimum ({{min}}).`,
            }),
          );
        }
        if (maxShares != null && newTotal > maxShares) {
          throw new Error(
            t("members.above_max_shares", {
              total: newTotal,
              max: maxShares,
              defaultValue: `Total ({{total}}) would exceed the maximum ({{max}}).`,
            }),
          );
        }
      }

      return {
        ...transformedData,
        member: memberId,
        value_one_coop_share: value_one_coop_share,
      };
    },
    [
      data,
      memberId,
      value_one_coop_share,
      boundsApply,
      minShares,
      maxShares,
      t,
    ],
  );

  // Per-member current sum (across all rows, paid + unpaid). Drives
  // both the header banner and the "remaining headroom" hint.
  const currentTotal = useMemo(
    () =>
      data
        // Exclude cancelled (divested) shares so the banner total + range alert
        // match live equity (the enforced backend invariant).
        .filter((row) => !row.cancelled_at)
        .reduce(
          (sum, row) => sum + (Number(row.amount_of_coop_shares) || 0),
          0,
        ),
    [data],
  );

  const rangeAlertType: "success" | "warning" | "error" = boundsApply
    ? minShares != null && currentTotal < minShares
      ? "warning"
      : maxShares != null && currentTotal > maxShares
        ? "error"
        : "success"
    : "success";

  return (
    <Modal
      title={
        memberName
          ? `${t("members.coop_shares")} — ${memberName}`
          : t("members.coop_shares")
      }
      open={isOpen}
      onCancel={onClose}
      footer={[
        <ModalCloseFooter key="close" onClose={onClose} />,
      ]}
      width={1100}
      destroyOnHidden
    >
      {memberCancelled ? (
        // The member has left — the min/max equity window no longer applies;
        // show the exit date instead (their shares are winding down).
        <Alert
          style={{ marginBottom: 12 }}
          type="warning"
          showIcon
          message={t("members.member_cancelled_title", {
            date: formatDate(memberCancelledEffectiveAt),
          })}
        />
      ) : (
        boundsApply &&
        (minShares != null || maxShares != null) && (
          <Alert
            style={{ marginBottom: 12 }}
            type={rangeAlertType}
            showIcon
            message={
              <span>
                {t("members.shares_range_label")}:{" "}
                <strong>
                  {minShares ?? "—"} – {maxShares ?? "∞"}
                </strong>{" "}
                · {t("members.shares_current_total")}:{" "}
                <strong>{format(currentTotal, 0)}</strong>
              </span>
            }
          />
        )
      )}

      {pendingConfirmationCount > 0 && (
        <Alert
          style={{ marginBottom: 12 }}
          type="warning"
          showIcon
          message={t("members.coop_shares_awaiting_confirmation", {
            count: pendingConfirmationCount,
          })}
        />
      )}

      <EditableTable
        columns={columns}
        // No ``list``: the modal owns the data via
        // ``useCommissioningCoopSharesList`` (passed as ``initialData``).
        // Supplying ``list`` would make EditableTable double-fetch the same
        // endpoint (it auto-fetches when ``showSearchBar`` +
        // ``apiFunctions.list`` are both set). Mutations refresh via the
        // ``onSaveSuccess``/``onDeleteSuccess`` invalidation.
        apiFunctions={wrapApiFunctions<CoopShare & TableRecord>({
          create: (payload) => commissioningCoopSharesCreate(payload),
          update: (id, payload) =>
            commissioningCoopSharesPartialUpdate(id, payload),
          delete: (id) => commissioningCoopSharesDestroy(id),
        })}
        focusIndex="amount_of_coop_shares"
        initialData={data}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        loading={isFetching}
        customSave={customSave}
        permissions={permissions}
      />

      <ExplainerText title={t("common.info")}>
        {t("explainers.coop_shares")}
      </ExplainerText>

      <AdminConfirmationModalCoopShares
        isOpen={confirmRecord != null}
        coopShare={confirmRecord}
        onClose={() => setConfirmRecord(null)}
        onConfirm={handleConfirm}
        loading={confirming}
      />
    </Modal>
  );
}
