/**
 * Column shapes shared between the Abos table (``useAbosColumns``) and the
 * WaitingListAbos page: display-id, member, share-type-variation, quantity
 * and default-delivery-station-day. One source so the two tables can't
 * drift apart; each page supplies its own data sources, per-row lock rule
 * and layout tweaks (widths / alignment) and keeps its page-specific
 * columns (admin status, waiting-list position, ...) local.
 */

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type {
  EditableColumnConfig,
  SelectOption,
} from "@shared/tables/BasicEditableTable/types";
import type { AboRecord } from "@features/abos/pages/types";
import { useTenant, useVariationLabel } from "@hooks/index";

type AboColumn = EditableColumnConfig<AboRecord>;

interface SharedAboColumnOptions {
  /** Per-row lock rule — Abos: admin-confirmed; waiting list: term started. */
  disabled: AboColumn["disabled"];
  memberOptions: AboColumn["options"];
  memberWidth: string;
  shareTypeVariationOptions: AboColumn["options"];
  shareTypeVariationWidth: string;
  onShareTypeVariationChange: AboColumn["onFieldChange"];
  /** Optional custom cell renderer (Abos chips on-off variations). */
  shareTypeVariationRender?: AboColumn["render"];
  deliveryStationDayOptions: AboColumn["options"];
  deliveryStationDayAlign: AboColumn["align"];
}

export function useSharedAboColumns({
  disabled,
  memberOptions,
  memberWidth,
  shareTypeVariationOptions,
  shareTypeVariationWidth,
  onShareTypeVariationChange,
  shareTypeVariationRender,
  deliveryStationDayOptions,
  deliveryStationDayAlign,
}: SharedAboColumnOptions) {
  const { t } = useTranslation();
  const { getSetting } = useTenant();
  // Waiting list off → a full/sold-out option must NOT be re-enabled or
  // relabeled "waiting list"; it stays greyed and unselectable.
  const allowsWaitingList = Boolean(
    getSetting("allows_waiting_list_for_subscriptions", true),
  );
  // Localize the raw size baked into ``share_type_variation_string`` so the
  // read cell matches the (localized) edit dropdown options.
  const variationLabel = useVariationLabel();

  // Quick-text capacity hints in the dropdowns (the colour tag lives in the
  // member modal). A sold-out variation / full station stays SELECTABLE — saving
  // it routes to the waiting list (the abos table catches the over-capacity 409
  // and retries as a waiting-list entry). Both rely on the option's ``disabled``
  // flag, which the per-row option builders set term-aware; here we un-grey it
  // and append the text tag.
  const soldOutLabel = t("abos.sold_out");
  const variationOptions = useMemo(() => {
    const decorate = (opts: SelectOption[]): SelectOption[] =>
      opts.map((opt) =>
        opt.disabled && allowsWaitingList
          ? { ...opt, disabled: false, label: `${opt.label} — ${soldOutLabel}` }
          : opt,
      );
    if (typeof shareTypeVariationOptions === "function") {
      const fn = shareTypeVariationOptions;
      return (record: AboRecord) => decorate(fn(record));
    }
    return decorate(shareTypeVariationOptions ?? []);
  }, [shareTypeVariationOptions, soldOutLabel, allowsWaitingList]);

  // Full station-days are already flagged ``disabled`` (term-aware, per row) by
  // ``getDeliveryStationDaysForRow``. Instead of greying them out, keep them
  // SELECTABLE and tag them "full – waiting list" — picking one routes the save
  // to the waiting list (via the abos table's over-capacity 409 retry).
  const fullLabel = t("abos.station_full_waiting_list");
  const stationOptions = useMemo(() => {
    const decorate = (opts: SelectOption[]): SelectOption[] =>
      opts.map((opt) =>
        opt.disabled && allowsWaitingList
          ? { ...opt, disabled: false, label: `${opt.label} — ${fullLabel}` }
          : opt,
      );
    if (typeof deliveryStationDayOptions === "function") {
      const fn = deliveryStationDayOptions;
      return (record: AboRecord) => decorate(fn(record));
    }
    return decorate(deliveryStationDayOptions ?? []);
  }, [deliveryStationDayOptions, fullLabel, allowsWaitingList]);

  const displayIdColumn = useMemo<AboColumn>(
    () => ({
      title: <>ID</>,
      dataIndex: "display_id",
      key: "display_id",
      inputType: "select",
      required: false,
      disabled: true,
      readOnly: true,
      align: "center",
      width: "9em",
      sortable: true,
      render: (value: unknown) => (
        <span style={{ fontSize: "0.7em" }}>{value as string}</span>
      ),
    }),
    [],
  );

  const memberColumn = useMemo<AboColumn>(
    () => ({
      title: <>{t("members.member")}</>,
      dataIndex: "member_string",
      key: "member_string",
      inputType: "select",
      required: true,
      fixed: true,
      align: "left",
      width: memberWidth,
      options: memberOptions,
      foreignKey: {
        valueField: "member",
        displayField: "member_string",
      },
      sortable: true,
      disabled,
    }),
    [t, memberWidth, memberOptions, disabled],
  );

  const shareTypeVariationColumn = useMemo<AboColumn>(
    () => ({
      title: <>{t("members.share_type_variation")}</>,
      dataIndex: "share_type_variation_string",
      key: "share_type_variation_string",
      inputType: "select",
      required: true,
      fixed: true,
      align: "left",
      width: shareTypeVariationWidth,
      options: variationOptions,
      foreignKey: {
        valueField: "share_type_variation",
        displayField: "share_type_variation_string",
      },
      sortable: true,
      disabled,
      onFieldChange: onShareTypeVariationChange,
      render:
        shareTypeVariationRender ??
        ((value: unknown) => variationLabel(value as string)),
    }),
    [
      t,
      shareTypeVariationWidth,
      variationOptions,
      disabled,
      onShareTypeVariationChange,
      shareTypeVariationRender,
      variationLabel,
    ],
  );

  const quantityColumn = useMemo<AboColumn>(
    () => ({
      title: <>{t("members.quantity")}</>,
      dataIndex: "quantity",
      key: "quantity",
      inputType: "positive_integer",
      required: true,
      align: "center",
      width: "5em",
      disabled,
    }),
    [t, disabled],
  );

  const deliveryStationDayColumn = useMemo<AboColumn>(
    () => ({
      title: <>{t("members.default_delivery_station")}</>,
      dataIndex: "default_delivery_station_day_string",
      key: "default_delivery_station_day",
      inputType: "select",
      required: true,
      align: deliveryStationDayAlign,
      width: "16em",
      options: stationOptions,
      foreignKey: {
        valueField: "default_delivery_station_day",
        displayField: "default_delivery_station_day_string",
      },
      disabled,
      render: (value: unknown, record: AboRecord) => {
        // Use the backend annotation for editing, but translate for display.
        // Explicit null check — the wire sends day_number as a NUMBER and
        // Monday is 0, so a falsy guard skipped the translated render for
        // every Monday row.
        if (
          record.delivery_day_number == null ||
          record.delivery_day_number === "" ||
          record.delivery_station_name === undefined
        ) {
          return value as string;
        }

        const dayMapping: Record<number, string> = {
          0: t("delivery.mo"),
          1: t("delivery.di"),
          2: t("delivery.mi"),
          3: t("delivery.do"),
          4: t("delivery.fr"),
          5: t("delivery.sa"),
          6: t("delivery.su"),
        };

        const translatedDay = dayMapping[Number(record.delivery_day_number)];
        return translatedDay && record.delivery_station_name
          ? `${translatedDay} - ${record.delivery_station_name}`
          : (value as string);
      },
    }),
    [t, deliveryStationDayAlign, stationOptions, disabled],
  );

  return {
    displayIdColumn,
    memberColumn,
    shareTypeVariationColumn,
    quantityColumn,
    deliveryStationDayColumn,
  };
}
