/**
 * Column factory for the Abos page — every column shape plus the
 * field-change handlers that auto-fill ``valid_until`` (trial /
 * season / one-year term math) and ``price_per_delivery``. The page
 * supplies the data sources (from ``useAbosData``) and the modal
 * openers; everything else lives here.
 */

import { Tag } from "antd";
import dayjs from "dayjs";
import type { MouseEvent } from "react";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { adminConfirmationColumn } from "@shared/tables";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { LinkButton, StatusButton, ToolTipIcon } from "@shared/ui";
import type { AboRecord } from "@features/abos/pages/types";
import { parseDateLoose } from "@shared/utils/endOfTerm";
import { getNextSunday } from "@shared/utils/nextSunday";
import { useCurrency } from "@hooks/configuration/useCurrency";
import { useDateFormat } from "@hooks/configuration/useDateFormat";
import { useTenant } from "@hooks/configuration/useTenant";
import type { useAdminConfirmationModalAbos } from "../modals/useAdminConfirmationModalAbos";
import type { useAbosData } from "../useAbosData";
import { useNumberFormat } from "@hooks/useNumberFormat";
import { useSubscriptionTerm } from "@hooks/useSubscriptionTerm";
import { useActiveStatusColumn } from "@hooks/columns/useActiveStatusColumn";
import { useSepaMandateColumn } from "@hooks/columns/useSepaMandateColumn";
import { useTimeBoundColumns } from "@hooks/columns/useTimeBoundColumns";
import type { SepaMandateStatus } from "@shared/api/generated/models";
import { useSharedAboColumns } from "./useSharedAboColumns";

type AbosData = ReturnType<typeof useAbosData>;
type AdminConfirmation = ReturnType<typeof useAdminConfirmationModalAbos>;

export function useAbosColumns({
  members,
  paymentCycles,
  allShareTypeVariations,
  variationDeliveryCycleById,
  getDeliveryStationDaysForRow,
  getShareTypeVariationsForRow,
  getAdminStatus,
  onOpenAdminConfirmation,
  adminStatusSorter,
  recentlyAddedIds,
  onCancel,
  onShowLog,
  getMandateForMember,
  onShowSepaDetails,
}: {
  members: AbosData["members"];
  paymentCycles: AbosData["paymentCycles"];
  allShareTypeVariations: AbosData["allShareTypeVariations"];
  variationDeliveryCycleById: AbosData["variationDeliveryCycleById"];
  getDeliveryStationDaysForRow: AbosData["getDeliveryStationDaysForRow"];
  getShareTypeVariationsForRow: AbosData["getShareTypeVariationsForRow"];
  getAdminStatus: AdminConfirmation["getAdminStatus"];
  onOpenAdminConfirmation: AdminConfirmation["handleOpenAdminConfirmationModal"];
  /** Pinned wrapper around ``getAdminStatusSorter`` — the page owns it
   *  because the pin set (``recentlyAddedIds``) comes from the table
   *  mutation hook. */
  adminStatusSorter: (
    a: TableRecord,
    b: TableRecord,
    sortOrder?: "ascend" | "descend",
  ) => number;
  /** Freshly-added row ids, pinned to the top of the status sort. */
  recentlyAddedIds: ReadonlySet<string>;
  onCancel: (record: AboRecord) => void;
  onShowLog: (record: AboRecord) => void;
  /** Resolve a member's SEPA mandate status (from ``useSepaMandateStatus``). */
  getMandateForMember: (memberId?: string | null) => SepaMandateStatus | undefined;
  /** Open the SEPA mandate-details modal for a clicked row. */
  onShowSepaDetails: (
    status: SepaMandateStatus | undefined,
    record: AboRecord,
  ) => void;
}) {
  const { t } = useTranslation();
  const { getSetting } = useTenant();
  const { currencySymbol } = useCurrency();
  const { format } = useNumberFormat();
  const { dateFormat, formatDate } = useDateFormat();

  const subscriptions_are_auto_renewed = getSetting(
    "subscriptions_are_auto_renewed",
    true,
  );
  // End-of-term rules (which tenant flags drive ``valid_until``, the trial
  // span, season/one-year math) live in one shared hook so the abos table
  // and the NewSubscriptionModal can't drift apart. ``min_weeks_to_cancel_
  // before_ending`` is consumed server-side; the auto-renewal column shows
  // the backend-computed deadline directly.
  const {
    allowsTrial: allows_trial_subscriptions,
    computeValidUntil,
    disabledValidFromDate,
  } = useSubscriptionTerm();

  // future → active → past (blue-green-grey), consistent with the other
  // status-column tables. ``pinnedIds`` keeps a freshly-added row on TOP despite
  // the sort — without it the column sort overrides EditableTable's data-order
  // pin and yanks the new row into the middle / onto page 2.
  const activeStatusColumn = useActiveStatusColumn({
    defaultSortOrder: "descend",
    pinnedIds: recentlyAddedIds,
  });
  // "Does this subscription's member have a SEPA mandate active during its
  // term?" — green/red square, click-through to the mandate details.
  const sepaMandateColumn = useSepaMandateColumn({
    getMandateForMember,
    onShowDetails: (status, record) =>
      onShowSepaDetails(status, record as AboRecord),
  });
  const { validFromColumn, validUntilColumn } = useTimeBoundColumns({
    width: "9em",
    validUntilRequired: true,
  });

  // Lock the subscription's editable columns once the office has
  // admin-confirmed it. From that moment on, the only way to alter the
  // term is to ``cancel`` through the per-row Cancel button (which
  // routes through ``SubscriptionService.cancel_subscription`` so
  // ShareDeliveries get cleaned up + PLANNED charges get dropped). The
  // placeholder "add new row" (``key === -1``) is always editable.
  const aboIsConfirmed = useCallback((record: AboRecord) => {
    if (record.key === -1) return false;
    return Boolean(record.admin_confirmed);
  }, []);

  // When ``valid_from`` (or ``is_trial``) changes, compute
  // ``valid_until``.
  //
  // Priority among the tenant flags (highest first):
  //   1. ``is_trial=true`` AND
  //      ``allowed_trial_subscription_duration >= 1`` — short ad-hoc
  //      term: ``valid_from + N weeks - 1 day``. Overrides the
  //      season / one-year branches so a trial inside a season-based
  //      tenant still gets the right short window.
  //   2. ``subscriptions_end_at_end_of_season`` — every subscription
  //      ends together at season end, regardless of when it started.
  //      Computed as ``season_start + 52 weeks - 1 day`` so the
  //      result lands on a Sunday (TimeBoundMixin requires that).
  //      Falls through to (3) when ``season_start`` is not configured.
  //   3. ``subscriptions_end_after_one_year`` — original behaviour:
  //      one year minus one day from ``valid_from``.
  //   4. None applicable — no auto-fill; the office picks
  //      ``valid_until`` manually.
  //
  // ``valid_until`` stays editable so the office can override the
  // computed value (non-weekly cycles, custom trial lengths, ...).
  //
  // ``min_weeks_to_cancel_before_ending`` only feeds the
  // ``automatically_renewed_at`` field on tenants where
  // ``subscriptions_are_auto_renewed`` is on. The value shown is the
  // LAST date a member can cancel before the auto-renew fires —
  // i.e. ``valid_until - min_weeks * 7 days``. Office reads it as
  // "if not cancelled by here, this subscription rolls over".
  const recomputeValidUntil = useCallback(
    (
      validFromValue: unknown,
      record: AboRecord,
      form: {
        setFieldsValue: (values: Record<string, unknown>) => void;
        getFieldValue?: (name: string) => unknown;
      },
      overrideIsTrial?: boolean,
      overrideVariationId?: string,
    ) => {
      if (!validFromValue) return undefined;

      // The trial branch is gated on the form's CURRENT ``is_trial``
      // — the office may have toggled the checkbox earlier in the
      // same edit session. ``overrideIsTrial`` lets the
      // is_trial-onChange handler pass the post-toggle value
      // directly, before the form has flushed it to the field
      // store. Null/undefined fall back to the record-level value.
      const formIsTrial = form.getFieldValue?.("is_trial");
      const isTrialNow =
        overrideIsTrial !== undefined
          ? overrideIsTrial
          : formIsTrial !== undefined
            ? formIsTrial
            : record.is_trial;

      // Cycle-aware trial span: look up the picked variation's
      // delivery_cycle from the prebuilt map. Same ``override``
      // pattern as ``isTrial`` — the share-type-variation onChange
      // handler hasn't flushed the new value to the form store yet
      // when its own callback fires, so it passes the post-pick id
      // explicitly. Unknown variation → ``weeksPerDelivery``
      // defaults to 1 (WEEKLY).
      const variationId =
        overrideVariationId ??
        (form.getFieldValue?.("share_type_variation") as string | undefined) ??
        (record.share_type_variation as string | undefined);
      const cycle =
        variationId != null
          ? variationDeliveryCycleById.get(String(variationId))
          : null;

      const validFromDate = parseDateLoose(validFromValue, dateFormat);
      if (!validFromDate) return undefined;

      const validUntilDate = computeValidUntil(validFromDate, {
        isTrial: isTrialNow === true,
        cycle,
      });
      if (!validUntilDate) return undefined;

      const patch = {
        valid_until: validUntilDate.format(dateFormat),
      };
      form.setFieldsValue(patch);
      return patch;
    },
    [dateFormat, computeValidUntil, variationDeliveryCycleById],
  );

  const handleValidFromChange = useCallback(
    (
      value: unknown,
      record: AboRecord,
      form: {
        setFieldsValue: (values: Record<string, unknown>) => void;
        getFieldValue?: (name: string) => unknown;
      },
    ) => recomputeValidUntil(value, record, form),
    [recomputeValidUntil],
  );

  // Toggling ``is_trial`` flips the auto-fill branch in
  // ``recomputeValidUntil``. Read ``valid_from`` from the form store
  // (it may have been typed in the same edit) and pass the new
  // ``is_trial`` value explicitly — the AntD Form hasn't flushed the
  // checkbox change to ``getFieldValue("is_trial")`` yet when this
  // handler fires.
  const handleIsTrialChange = useCallback(
    (
      newValue: unknown,
      record: AboRecord,
      form: {
        setFieldsValue: (values: Record<string, unknown>) => void;
        getFieldValue?: (name: string) => unknown;
      },
    ) => {
      const validFromValue =
        form.getFieldValue?.("valid_from") ?? record.valid_from;
      return recomputeValidUntil(
        validFromValue,
        record,
        form,
        newValue === true,
      );
    },
    [recomputeValidUntil],
  );

  const handleShareTypeVariationChange = useCallback(
    (
      value: unknown,
      record: AboRecord,
      form: {
        setFieldsValue: (values: Record<string, unknown>) => void;
        getFieldValue?: (name: string) => unknown;
      },
    ) => {
      if (!value) return undefined;

      const patch: Record<string, unknown> = {};

      try {
        // Find the selected variation from allShareTypeVariations
        const selectedVariation = allShareTypeVariations.find(
          (variation: {
            value: string;
            active_price_per_delivery?: string;
            price_per_delivery?: string;
          }) => variation.value === value,
        );

        if (selectedVariation && selectedVariation.active_price_per_delivery) {
          patch.price_per_delivery =
            selectedVariation.active_price_per_delivery;
          form.setFieldsValue({
            price_per_delivery: selectedVariation.active_price_per_delivery,
          });
        }
      } catch (error) {
        console.error("Error setting weekly_price:", error);
      }

      // Different variation can mean a different ``delivery_cycle`` —
      // recompute ``valid_until`` so the cycle-aware trial span
      // updates without the office having to re-pick valid_from.
      // ``recomputeValidUntil`` no-ops for non-trial rows (the
      // season/year branches don't depend on the variation), so
      // calling it unconditionally is safe.
      const validFromValue =
        form.getFieldValue?.("valid_from") ?? record.valid_from;
      const validUntilPatch = recomputeValidUntil(
        validFromValue,
        record,
        form,
        undefined,
        value as string,
      );
      if (validUntilPatch) {
        Object.assign(patch, validUntilPatch);
      }

      return Object.keys(patch).length > 0 ? patch : undefined;
    },
    [allShareTypeVariations, recomputeValidUntil],
  );

  // Already-cancelled members must not be selectable for a NEW subscription.
  // Disable (don't drop) them so existing rows still resolve their label and
  // the office sees why a member is unavailable.
  const memberOptions = useMemo(
    () => members.map((m) => ({ ...m, disabled: Boolean(m.cancelled_at) })),
    [members],
  );

  // Variation id → its own valid_from, so the valid_from picker can ALSO block
  // dates before a (future) variation starts — a subscription can't begin
  // before the variation it's for exists. Only NARROWS the existing
  // today+waiting_period rule (never widens it).
  const variationValidFromById = useMemo(() => {
    const map = new Map<string, string>();
    for (const variation of allShareTypeVariations) {
      if (variation.valid_from) {
        map.set(String(variation.value), variation.valid_from);
      }
    }
    return map;
  }, [allShareTypeVariations]);

  const disabledValidFromForRow = useCallback(
    (current: unknown, record?: AboRecord): boolean => {
      // Base rule (Monday + today + waiting period) first.
      if (disabledValidFromDate(current)) return true;
      const date = current as dayjs.Dayjs;
      const variationId = record?.share_type_variation as string | undefined;
      const variationFrom = variationId
        ? variationValidFromById.get(variationId)
        : undefined;
      return Boolean(
        variationFrom && date && date.isBefore(dayjs(variationFrom), "day"),
      );
    },
    [disabledValidFromDate, variationValidFromById],
  );

  // On-off variations bill per opted-in delivery (not every period);
  // chip it so the office knows the subscription has per-delivery
  // semantics. Plain string otherwise (preserves the default display).
  const renderShareTypeVariation = useCallback(
    (value: unknown, record: AboRecord) =>
      record.requires_optin ? (
        <span>
          {value as string}
          <Tag color="cyan" bordered={false} style={{ marginLeft: 8 }}>
            {t("abos.on_off_tag")}
          </Tag>
        </span>
      ) : (
        (value as string)
      ),
    [t],
  );

  const {
    displayIdColumn,
    memberColumn,
    shareTypeVariationColumn,
    quantityColumn,
    deliveryStationDayColumn,
  } = useSharedAboColumns({
    disabled: aboIsConfirmed,
    memberOptions,
    memberWidth: "16em",
    shareTypeVariationOptions: getShareTypeVariationsForRow,
    shareTypeVariationWidth: "16em",
    onShareTypeVariationChange: handleShareTypeVariationChange,
    shareTypeVariationRender: renderShareTypeVariation,
    deliveryStationDayOptions: getDeliveryStationDaysForRow,
    deliveryStationDayAlign: "left",
  });

  const columns: EditableColumnConfig<AboRecord>[] = useMemo(
    () => [
      activeStatusColumn as unknown as EditableColumnConfig<AboRecord>,
      {
        title: <div className="checkbox-column-title">Link</div>,
        dataIndex: "link",
        key: "link",
        align: "center",
        disabled: true,
        width: "3em",
        readOnly: true,

        render: (_: unknown, record: AboRecord) => {
          const isEditing = record.key === -1 || record.isEditing; // Check if row is being edited

          return (
            <LinkButton
              variant="view"
              to={isEditing ? "#" : `/members/members/${record.member}`}
              tooltip={isEditing ? "" : t("members.view_details")}
              disabled={isEditing}
              onClick={
                isEditing ? (e: MouseEvent) => e.preventDefault() : undefined
              }
            />
          );
        },
      },

      // Shared admin-confirmation status column (rotated title + StatusButton →
      // opens the confirmation modal). Same factory as the members table + the
      // coop-shares modal. ``adminStatusSorter`` still floats pending
      // applications to the top on demand (see ``getAdminStatus`` in
      // ``useModalAdminConfirmationAbos.ts`` for the ordering).
      adminConfirmationColumn<AboRecord>({
        t,
        getAdminStatus: (record) => getAdminStatus(record as never),
        onOpen: (record) => onOpenAdminConfirmation(record as never),
        sorter: adminStatusSorter as never,
      }),

      {
        title: <>{t("abos.subscription_number")}</>,
        dataIndex: "renewal_display_id",
        key: "subscription_number",
        align: "center",
        width: "4em",
        readOnly: true,
        disabled: true,
        // Sort by the (number, generation) pair so the chain reads
        // ``1, 1a, 1b, 2, 2a, …`` — NOT lexicographically on the label string.
        // Pin the placeholder add-row to the top (mirrors the status-column
        // sorters — AntD reverses for descend, so flip the sign ourselves) and
        // sort unnumbered rows LAST instead of colliding with the placeholder
        // at 0.
        sorter: (
          a: AboRecord,
          b: AboRecord,
          sortOrder?: "ascend" | "descend",
        ) => {
          if (a.key === -1) return sortOrder === "descend" ? 1 : -1;
          if (b.key === -1) return sortOrder === "descend" ? -1 : 1;
          // MAX_SAFE_INTEGER (not Infinity): two unnumbered rows must compare
          // 0, and Infinity - Infinity is NaN.
          const numberA = a.subscription_number ?? Number.MAX_SAFE_INTEGER;
          const numberB = b.subscription_number ?? Number.MAX_SAFE_INTEGER;
          return (
            numberA - numberB ||
            (a.renewal_generation ?? 0) - (b.renewal_generation ?? 0)
          );
        },
        render: (_: unknown, record: AboRecord) =>
          record.renewal_display_id ?? "",
      },

      memberColumn,
      sepaMandateColumn as unknown as EditableColumnConfig<AboRecord>,
      {
        ...validFromColumn,
        // Override the generic Monday-only rule with the subscription one:
        // Monday AND not before the tenant's earliest start week AND (for a
        // future variation) not before that variation's own valid_from.
        disabledDate: disabledValidFromForRow,
        disabled: aboIsConfirmed,
        onFieldChange: handleValidFromChange,
        sortable: true,
      },
      {
        ...validUntilColumn,
        // ``valid_until`` stays editable so the office can override
        // the auto-filled value — important for trial subs (toggled
        // mid-edit via ``is_trial``) which use ad-hoc short terms
        // that don't fit the seasonal/yearly cadence. The
        // deterministic value is still written into the form by
        // ``handleValidFromChange`` whenever ``valid_from`` changes,
        // so non-trial rows pick it up automatically; the office
        // just retains the ability to type a different date.
        disabled: aboIsConfirmed,
        sortable: true,
      },
      shareTypeVariationColumn,

      ...(allows_trial_subscriptions
        ? ([
            {
              title: <>{t("members.is_trial")}</>,
              dataIndex: "is_trial",
              key: "is_trial",
              inputType: "checkbox",
              required: false,
              align: "center",
              sortable: true,
              // Toggling ``is_trial`` recomputes ``valid_until``:
              //   * ON  → ``valid_from + allowed_trial_subscription_duration weeks - 1 day``
              //   * OFF → falls back to the season / one-year branch
              //     in ``computeValidUntil``.
              onFieldChange: handleIsTrialChange,
            },
          ] as EditableColumnConfig<AboRecord>[])
        : []),
      quantityColumn,

      deliveryStationDayColumn,

      {
        title: <>{t("members.weekly_price")}</>,
        dataIndex: "price_per_delivery",
        key: "price_per_delivery",
        inputType: "positive_decimal2",
        required: true,
        align: "center",
        width: "6em",
        suffix: currencySymbol,
        disabled: aboIsConfirmed,
        render: (_: unknown, record: AboRecord) => (
          <>
            {record.price_per_delivery
              ? format(Number(record.price_per_delivery), 2)
              : ""}{" "}
            {currencySymbol}
          </>
        ),
      },
      {
        title: <>{t("members.payment_cycle")}</>,
        dataIndex: "payment_cycle_name",
        key: "payment_cycle_name",
        inputType: "select",
        required: true,
        align: "center",
        width: "12em",
        options: paymentCycles,
        foreignKey: {
          valueField: "payment_cycle",
          displayField: "payment_cycle_name",
        },
        disabled: aboIsConfirmed,
        render: (value: unknown) =>
          value
            ? t(
                `configuration.payment_cycle_${(value as string).toLowerCase()}`,
                value as string,
              )
            : "",
      },
      {
        title: <>{t("members.deliveries")}</>,
        // Backend-annotated count of materialised ``ShareDelivery``
        // rows for the subscription, excluding joker-taken weeks
        // (see ``_build_subscription_queryset`` annotation). This is
        // the source of truth — replaces the prior frontend
        // calendar count which double-counted fortnightly cycles
        // (``ODD_WEEKS`` / ``EVEN_WEEKS``) and ignored jokers.
        //
        // ``0`` is a meaningful value: a draft (admin_confirmed=False)
        // subscription has not been materialised yet, so the row
        // legitimately shows ``0×``. The office reads that as
        // "needs admin-confirmation to materialise deliveries".
        dataIndex: "deliveries_count",
        key: "deliveries_count",
        inputType: "positive_integer",
        required: false,
        align: "center",
        disabled: true,
        readOnly: true,
        width: "9em",
        render: (_value: unknown, record: AboRecord) => {
          // Only show the count once the subscription is
          // admin-confirmed — that's when ``ShareDelivery`` rows get
          // materialised in ``SubscriptionService._post_confirm``.
          // Pre-confirmation the count is always ``0`` (correct but
          // misleading: looks like "no deliveries" instead of "not
          // materialised yet"). Show a placeholder dash for drafts
          // so the office reads the column as "needs confirmation".
          if (!aboIsConfirmed(record)) {
            return (
              <div className="text-center">
                <span style={{ color: "var(--color-text-tertiary)" }}>—</span>
              </div>
            );
          }
          const count = (record as Record<string, unknown>).deliveries_count;
          const display =
            typeof count === "number" && Number.isFinite(count) ? count : 0;
          return (
            <div className="text-center">
              <div style={{ fontWeight: "bold" }}>{display}x</div>
            </div>
          );
        },
      },
      // Auto-renewal cancellation deadline. Pre-computed server-side
      // (see ``SubscriptionSerializer.get_automatically_renewed_at``)
      // so this column doesn't redo dayjs parsing per row per render.
      // Backend returns ISO ``YYYY-MM-DD`` (or null = column stays
      // blank — trial sub, no valid_until, or deadline before
      // valid_from).
      ...(subscriptions_are_auto_renewed
        ? ([
            {
              title: (
                <>
                  {t("members.automatically_renewed_at")}
                  <ToolTipIcon title={t("tooltip.auto_renewal")} />
                </>
              ),
              dataIndex: "automatically_renewed_at",
              key: "automatically_renewed_at",
              align: "center",
              width: "8em",
              disabled: true,
              readOnly: true,
              render: (value: unknown) =>
                value ? formatDate(value as string) : "",
            },
          ] as EditableColumnConfig<AboRecord>[])
        : []),
      {
        title: <>{t("members.cancelled_effective_at")}</>,
        dataIndex: "cancelled_effective_at",
        key: "cancelled_effective_at",
        inputType: "date",
        required: false,
        align: "center",
        width: "9em",
        // Display-only. Cancellation runs through the per-row Cancel
        // button → ``CancelSubscriptionModal`` → ``commissioningAbosCancelCreate``
        // so the service-layer side effects (delete future deliveries,
        // drop PLANNED charges, recompute) actually fire. The backend
        // serializer locks this field too — see
        // ``SubscriptionSerializer.Meta.read_only_fields``.
        readOnly: true,
        disabled: true,
        render: (value: unknown) => formatDate(value as string),
      },
      displayIdColumn,
      {
        title: "",
        dataIndex: "cancel",
        key: "cancel",
        width: "3em",
        align: "center",
        readOnly: true,
        disabled: true,
        render: (_: unknown, record: AboRecord) => {
          // Only confirmed, not-yet-cancelled rows can be cancelled.
          // Placeholder ``key === -1`` rows aren't real subscriptions
          // yet; cancelled rows already have ``cancelled_at`` stamped.
          if (record.key === -1) return null;
          if (!record.admin_confirmed) return null;
          if (record.cancelled_at) return null;
          // Hide when there's no valid Sunday left between today and
          // ``valid_until``. The earliest possible cancellation date is
          // the next Sunday on or after today; if that already falls
          // past the natural term end, just let the term expire — the
          // backend would refuse the cancel anyway.
          if (record.valid_until) {
            const nextSunday = getNextSunday();
            if (nextSunday.isAfter(dayjs(record.valid_until), "day")) {
              return null;
            }
          }
          return (
            <StatusButton
              variant="cancel"
              onClick={() => onCancel(record)}
              tooltip={t("members.cancel_abo_button_tooltip")}
            />
          );
        },
      },
      {
        title: "",
        dataIndex: "logging",
        key: "logging",
        width: "3em",
        align: "center",
        readOnly: true,
        disabled: true,
        render: (_: unknown, record: AboRecord) => {
          if (record.key === -1) return null;
          return (
            <StatusButton
              variant="logging"
              onClick={() => onShowLog(record)}
              tooltip={t("logging.title")}
            />
          );
        },
      },
    ],
    [
      activeStatusColumn,
      sepaMandateColumn,
      t,
      memberColumn,
      shareTypeVariationColumn,
      quantityColumn,
      deliveryStationDayColumn,
      displayIdColumn,
      allows_trial_subscriptions,
      subscriptions_are_auto_renewed,
      validFromColumn,
      validUntilColumn,
      paymentCycles,
      handleValidFromChange,
      handleIsTrialChange,
      aboIsConfirmed,
      disabledValidFromForRow,
      formatDate,
      currencySymbol,
      getAdminStatus,
      onOpenAdminConfirmation,
      adminStatusSorter,
      onCancel,
      onShowLog,
      format,
    ],
  );

  return { columns };
}
