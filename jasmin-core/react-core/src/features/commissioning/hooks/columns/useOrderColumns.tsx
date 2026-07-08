import { useCallback, useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  useCratesColumns,
  useOfferOptions,
  useOfferTiers,
  useShareArticleColumn,
  useWashingCleaningColumns,
} from "..";
import {
  useCurrency,
  useNoteColumn,
  useNumberFormat,
  useUnitOptions,
} from "@hooks/index";
import type {
  CommissioningOffersListParams,
  CommissioningOrderContentsListParams,
} from "@shared/api/generated/models";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { activeAtDateForWeek } from "@shared/utils";
import { pickTierPrice } from "@shared/utils/tierPrice";
import { useAmountUnitSizeColumns } from "./useAmountUnitSizeColumns";

interface UseOrderColumnsParams {
  params: CommissioningOrderContentsListParams;
  dataCrates: Record<string, unknown>[];
}

export function useOrderColumns({ params, dataCrates }: UseOrderColumnsParams) {
  const { t } = useTranslation();
  const { currencySymbol } = useCurrency();
  const { format } = useNumberFormat();
  const { getUnitLabel } = useUnitOptions();
  const offersParams = useMemo<CommissioningOffersListParams>(
    () => ({
      year: params.year,
      delivery_week: params.delivery_week,
      reseller: params.reseller,
    }),
    [params.year, params.delivery_week, params.reseller],
  );
  const { offers } = useOfferOptions(offersParams);

  // Tier thresholds drive the live price-per-unit tier pick on amount
  // entry. Same source-of-truth as ``useOrdersData``'s save-time calc.
  // Single-tier mode (``[1]``) when the tenant hasn't configured tiers
  // — only ``price_1`` is ever picked, no quantity-based escalation.
  const finalTiers = useOfferTiers();

  const { washingCleaningColumns } = useWashingCleaningColumns();
  const { shareArticleColumn, handleUnitChange, handleAmountChange } =
    useShareArticleColumn({
      filters: {
        is_active: true,
        get_price_info: true,
        include_extra: true,
        // Suggest the tier prices active in THIS order's delivery week (not
        // today's) — mirrors offers (useOffersData). Without price_date the
        // backend skips the price annotation entirely, so direct article entry
        // got no suggestion. The office can still overwrite each price; the
        // entered value is what gets snapshotted on save (the backend stores it
        // verbatim and never recomputes).
        price_date: activeAtDateForWeek(params.year, params.delivery_week),
      },
      articleDefaults: "reseller",
      finalTiers,
    });

  const { amountUnitSizeColumns } = useAmountUnitSizeColumns({
    overrides: {
      unit: { onFieldChange: handleUnitChange },
      amount: {
        title: t("commissioning.ordered_amount"),
        width: "7em",
        inputType: "positive_decimal3",
        onFieldChange: handleAmountChange,
        render: (value: unknown, record: Record<string, unknown>) => {
          const numValue = Number(value);
          if (isNaN(numValue) || numValue === 0) return "";
          if (!record.unit) return format(numValue, 2);
          return record.unit === "KG"
            ? format(numValue, 2)
            : format(numValue, 1);
        },
      },
    },
  });
  const { cratesColumns: columnsCrates, crates: crateOptions } =
    useCratesColumns({ showNote: false });
  const { noteColumn } = useNoteColumn();

  // Offer-based order line: the per-unit price is the SELECTED offer's tier
  // price, picked by the ordered amount — which is already in PU here (the
  // article-entry amount, by contrast, is in the row's unit and divides by
  // amount_per_pu via handleAmountChange). The offer stays fixed per row; the
  // amount drives the re-pick. price_per_unit stays locked (disabled) in offer
  // mode — the offer's price is authoritative.
  const handleOfferPrice = useCallback(
    (
      offerValue: unknown,
      orderedAmountPu: unknown,
      form: { setFieldValue: (name: string, value: unknown) => void },
    ) => {
      const offer = offers.find(
        (o) => String(o.value) === String(offerValue),
      ) as Record<string, unknown> | undefined;
      if (!offer) return {};
      const price = pickTierPrice(
        Number(orderedAmountPu) || 0,
        {
          price_1: offer.price_1 as number | null,
          price_2: offer.price_2 as number | null,
          price_3: offer.price_3 as number | null,
        },
        finalTiers,
      );
      form.setFieldValue("price_per_unit", price);
      return {};
    },
    [offers, finalTiers],
  );

  const filteredColumnsCrates = useMemo(() => {
    const usedCrateTypes = new Set(dataCrates.map((item) => item.crate_type));
    const availableOptions = crateOptions.filter(
      (opt) => !usedCrateTypes.has(opt.value as string),
    );
    return columnsCrates.map((col) =>
      col.key === "crate_type_name"
        ? { ...col, options: availableOptions }
        : col,
    );
  }, [columnsCrates, crateOptions, dataCrates]);

  const columnsPrices: EditableColumnConfig<TableRecord>[] = [
    {
      title: <>{t("commissioning.single_price")}</>,
      dataIndex: "price_per_unit",
      key: "price_per_unit",
      inputType: "positive_decimal2",
      required: true,
      suffix: currencySymbol,
      align: "center",
      width: "8em",
      render: (_: unknown, record: Record<string, unknown>) => (
        <span>
          {record.price_per_unit
            ? `${format(Number(record.price_per_unit), 2)} ${currencySymbol}/${getUnitLabel(record.unit as string)}`
            : ""}
        </span>
      ),
    },
    {
      title: <>{t("commissioning.rabatt")}</>,
      dataIndex: "rabatt",
      key: "rabatt",
      inputType: "positive_integer",
      required: false,
      suffix: "%",
      align: "center",
      width: "7em",
      render: (_: unknown, record: Record<string, unknown>) =>
        record.rabatt ? `${record.rabatt} %` : "",
    },
    {
      title: <>{t("commissioning.line_netto")}</>,
      dataIndex: "line_netto",
      key: "line_netto",
      inputType: "positive_decimal2",
      required: false,
      readOnly: true,
      disabled: true,
      align: "right",
      width: "8em",
      render: (_: unknown, record: Record<string, unknown>) => (
        <span>
          {record.line_netto
            ? `${format(Number(record.line_netto), 2)} ${currencySymbol}`
            : ""}
        </span>
      ),
    },
    {
      title: <span className="text-xs">{t("commissioning.ust")}</span>,
      dataIndex: "tax_rate",
      key: "tax_rate",
      // Backend stores `DecimalField(max_digits=5, decimal_places=2)`, so
      // non-integer rates (e.g. historical / reduced 16.5 % regimes) need
      // a decimal input. `positive_decimal2` matches the backend precision.
      inputType: "positive_decimal2",
      required: false,
      align: "center",
      width: "4em",
      render: (_: unknown, record: Record<string, unknown>) => (
        <span className="text-xs">
          {record.tax_rate ? `${format(Number(record.tax_rate), 2)} %` : ""}
        </span>
      ),
    },
  ];

  const columnsOffers: EditableColumnConfig<TableRecord>[] = [
    ...washingCleaningColumns,
    {
      title: <>{t("commissioning.offers")}</>,
      dataIndex: "offer_name",
      key: "offer_name",
      inputType: "select",
      required: true,
      width: "26em",
      align: "left",
      options: offers,
      disabled: (record: TableRecord) => record.key != -1,
      foreignKey: { valueField: "offer", displayField: "offer_name" },
      sortable: true,
      // Seed the per-unit price from the picked offer (tier by the current
      // ordered amount, in PU). The ordered_amount column re-picks as the
      // amount changes.
      onFieldChange: (
        value: unknown,
        _record: Record<string, unknown>,
        form: {
          getFieldValue: (name: string) => unknown;
          setFieldValue: (name: string, value: unknown) => void;
        },
      ) => handleOfferPrice(value, form.getFieldValue("ordered_amount"), form),

      render: (value: unknown, record: Record<string, unknown>) => {
        const hasAmount = record.amount && (record.amount as number) > 0;
        return hasAmount ? (
          <span style={{ fontWeight: "bold", color: "#18817aff" }}>
            {value as ReactNode}
          </span>
        ) : (
          <span>{value as ReactNode}</span>
        );
      },
    },
    {
      title: (
        <span className="text-xs">
          {t("commissioning.still_available_offer_amount")}
        </span>
      ),
      dataIndex: "offer_available_amount",
      key: "offer_available_amount",
      inputType: "positive_integer",
      required: false,
      disabled: true,
      align: "center",
      width: "10em",
      render: (value: unknown) => {
        const displayValue = value == null ? 0 : value;
        return (
          <span
            style={{
              fontSize: "0.8em",
              color: displayValue === 0 ? "darkred" : "darkgreen",
            }}
          >
            {`${format(Number(displayValue), 1)} ${t("commissioning.pu")}`}
          </span>
        );
      },
    },
    {
      title: <>{t("commissioning.ordered_amount_pu")}</>,
      dataIndex: "ordered_amount",
      key: "ordered_amount",
      inputType: "positive_decimal2",
      // Not required: clearing the field removes the order (see
      // createCustomSaveOffers → __deleteOnSave). A required rule makes
      // ``form.validateFields()`` reject an EMPTY value before the save
      // handler can route it to delete — that's why typing 0 worked but
      // simply clearing the field did not.
      required: false,
      align: "center",
      width: "9em",
      // Re-pick the offer's tier price as the amount changes (PU here, so no
      // amount_per_pu division — contrast handleAmountChange for article rows).
      onFieldChange: (
        value: unknown,
        _record: Record<string, unknown>,
        form: {
          getFieldValue: (name: string) => unknown;
          setFieldValue: (name: string, value: unknown) => void;
        },
      ) => handleOfferPrice(form.getFieldValue("offer"), value, form),
      render: (value: unknown) => {
        const numValue = Number(value);
        if (isNaN(numValue) || numValue === 0) return "";
        return `${format(numValue, 1)} ${t("commissioning.pu")}`;
      },
    },

    ...columnsPrices.map((col) =>
      col.key === "price_per_unit" ? { ...col, disabled: true } : col,
    ),
    noteColumn,
  ];

  const columnsArticles: EditableColumnConfig<TableRecord>[] = [
    ...washingCleaningColumns,
    {
      ...shareArticleColumn,
      disabled: (record: TableRecord) => record.key != -1,
    },
    {
      title: <>{t("commissioning.sort")}</>,
      dataIndex: "sort",
      key: "sort",
      inputType: "text",
      required: false,
      width: "10em",
    },
    ...amountUnitSizeColumns,
    ...columnsPrices,
    noteColumn,
  ];

  // --- Custom save handlers ---

  const createCustomSave = useCallback(
    (
      selectedYear: number,
      selectedWeek: number,
      selectedDay: number,
      selectedReseller: string | null,
      orderDaysVal: {
        harvesting_day: number | null;
        packing_day: number | null;
        washing_day: number | null;
        cleaning_day: number | null;
      },
      dataItems: Record<string, unknown>[],
      calculatePricePerUnit: (
        amount: number | string,
        record: Record<string, unknown>,
      ) => number | null,
    ) => {
      return (
        transformedData: Record<string, unknown>,
        fullRecord?: Record<string, unknown>,
      ) => {
        if (!transformedData.offer && !transformedData.share_article)
          return null;
        if (
          transformedData.size === null ||
          transformedData.size === undefined ||
          transformedData.size === ""
        ) {
          transformedData.size = "M";
        }
        if (
          transformedData.offer &&
          (!transformedData.amount || (transformedData.amount as number) <= 0)
        ) {
          // Clearing an existing offer order removes the OrderContent (offers
          // with no order are placeholder stubs, not null-amount rows). A
          // placeholder / new row has nothing to persist, so abort instead.
          const isExistingOrderContent =
            !!fullRecord &&
            !fullRecord.is_placeholder &&
            fullRecord.key !== -1 &&
            !!fullRecord.id;
          return isExistingOrderContent ? { __deleteOnSave: true } : null;
        }

        const baseData: Record<string, unknown> = {
          ...transformedData,
          year: selectedYear,
          delivery_week: selectedWeek,
          day_number: selectedDay,
          reseller: selectedReseller,
          rabatt: transformedData.rabatt || null,
          harvesting_day: orderDaysVal.harvesting_day,
          packing_day: orderDaysVal.packing_day,
          washing_day: orderDaysVal.washing_day,
          cleaning_day: orderDaysVal.cleaning_day,
        };

        if (transformedData.offer && transformedData.amount) {
          const recordToUse = fullRecord || transformedData;
          let recordWithPrices = recordToUse;
          if (!recordWithPrices.price_1 && recordWithPrices.id) {
            recordWithPrices =
              dataItems.find((item) => item.id === recordWithPrices.id) ||
              recordWithPrices;
          }
          const calculatedPrice = calculatePricePerUnit(
            transformedData.amount as number,
            recordWithPrices,
          );
          if (calculatedPrice !== null)
            baseData.price_per_unit = calculatedPrice;
        }

        if (transformedData.share_article) {
          return {
            ...baseData,
            share_article: transformedData.share_article,
          };
        }
        return baseData;
      };
    },
    [],
  );

  const createCustomSaveOffers = useCallback(
    (
      selectedYear: number,
      selectedWeek: number,
      selectedDay: number,
      selectedReseller: string | null,
      orderDaysVal: {
        harvesting_day: number | null;
        packing_day: number | null;
        washing_day: number | null;
        cleaning_day: number | null;
      },
    ) => {
      return (
        transformedData: Record<string, unknown>,
        fullRecord?: Record<string, unknown>,
      ) => {
        if (!transformedData.offer && !transformedData.share_article)
          return null;
        if (
          transformedData.offer &&
          (!transformedData.ordered_amount ||
            (transformedData.ordered_amount as number) <= 0)
        ) {
          // Amount cleared. Offers without an order are placeholder stubs,
          // not null-amount rows — so on an EXISTING OrderContent this means
          // "remove my order": signal a delete. On a placeholder / new row
          // there's nothing persisted, so abort the save.
          const isExistingOrderContent =
            !!fullRecord &&
            !fullRecord.is_placeholder &&
            fullRecord.key !== -1 &&
            !!fullRecord.id;
          return isExistingOrderContent ? { __deleteOnSave: true } : null;
        }

        const baseData: Record<string, unknown> = {
          ...transformedData,
          year: selectedYear,
          delivery_week: selectedWeek,
          day_number: selectedDay,
          reseller: selectedReseller,
          rabatt: transformedData.rabatt || null,
          harvesting_day: orderDaysVal.harvesting_day,
          packing_day: orderDaysVal.packing_day,
          washing_day: orderDaysVal.washing_day,
          cleaning_day: orderDaysVal.cleaning_day,
        };

        // For an unused-offer row the user typically only edits `amount` —
        // `unit` / `size` / `sort` aren't in the table's edit form, so
        // `transformedData` is missing them and the DRF serializer rejects
        // the create with "Dieses Feld ist erforderlich". Backfill from the
        // original row, which carries those fields from the offer.
        if (transformedData.offer && fullRecord) {
          if (baseData.unit == null || baseData.unit === "")
            baseData.unit = fullRecord.unit;
          if (baseData.size == null || baseData.size === "")
            baseData.size = fullRecord.size;
          if (baseData.sort == null || baseData.sort === "")
            baseData.sort = fullRecord.sort;
        }

        if (transformedData.offer && transformedData.ordered_amount) {
          // Price the line from the SELECTED offer's tier prices, picked by the
          // ordered amount — already in PU here, so NO amount_per_pu division
          // (contrast the article save, where the amount is in the row's unit).
          // Read from the offers list: a freshly-picked offer row doesn't carry
          // price_1/2/3, so this is correct for new and existing lines alike.
          const offer = offers.find(
            (o) => String(o.value) === String(transformedData.offer),
          ) as Record<string, unknown> | undefined;
          if (offer) {
            baseData.price_per_unit = pickTierPrice(
              Number(transformedData.ordered_amount) || 0,
              {
                price_1: offer.price_1 as number | string | null,
                price_2: offer.price_2 as number | string | null,
                price_3: offer.price_3 as number | string | null,
              },
              finalTiers,
            );
          }
        }

        if (transformedData.share_article) {
          return {
            ...baseData,
            share_article: transformedData.share_article,
          };
        }

        if (transformedData.offer && transformedData.ordered_amount) {
          const orderedAmount = Number(transformedData.ordered_amount);
          const amountPerPu = Number(
            transformedData.amount_per_pu || fullRecord?.amount_per_pu,
          );
          if (!isNaN(orderedAmount) && !isNaN(amountPerPu) && amountPerPu > 0) {
            const calculatedAmount = orderedAmount * amountPerPu;
            baseData.amount = Number(
              calculatedAmount.toFixed(transformedData.unit === "KG" ? 2 : 1),
            );
          }
        }

        return baseData;
      };
    },
    [offers, finalTiers],
  );

  return {
    columnsOffers,
    columnsArticles,
    filteredColumnsCrates,
    createCustomSave,
    createCustomSaveOffers,
  };
}
