import { useQueryClient } from "@tanstack/react-query";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningCrateContentsCreate,
  commissioningCrateContentsDestroy,
  commissioningCrateContentsPartialUpdate,
  commissioningOrderContentsCreate,
  commissioningOrderContentsDestroy,
  commissioningOrderContentsPartialUpdate,
  commissioningSetOrderNotePartialUpdate,
  getCommissioningCrateContentsListQueryKey,
  getCommissioningDaysWithOrdersRetrieveQueryKey,
  getCommissioningDeliveryNotesRetrieveQueryKey,
  getCommissioningInvoicesRetrieveQueryKey,
  getCommissioningOrderContentsListQueryKey,
  useCommissioningCrateContentsList,
  useCommissioningDaysWithOrdersRetrieve,
  useCommissioningOrderContentsList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  BulkOperationResponse,
  CommissioningCrateContentsDestroyParams,
  CommissioningOrderContentsListParams,
  CrateOrderContentCreateRequest,
  CrateOrderSummary,
  OrderContent,
  OrderContentListItem,
} from "@shared/api/generated/models";
// Direct import from the helper-only files keeps @react-pdf/renderer
// out of useOrdersData's eager bundle. The historic *PDFGenerator.tsx
// files re-export these helpers for compat, but importing through
// them would drag the React component (and the static @react-pdf
// import it carries for ``<PDFViewer>``) into the eager chunk too.
import { generateAndUploadDeliveryNotePDF } from "@features/commissioning/pdfs/forResellers/generateDeliveryNotePDF";
import { generateAndUploadInvoicePDF } from "@features/commissioning/pdfs/forResellers/generateInvoicePDF";
import {
  computeTaxBreakdown,
  totalsFromBreakdown,
  type LineItemBase,
} from "@features/commissioning/pdfs/forResellers/pdfBase";
import { computeLineNetto, type LineNettoInput } from "@shared/utils/lineNetto";
// Direct module path (not the ``components/tables`` barrel): the barrel
// pulls in ``EditableTable``, which imports the ``hooks`` barrel — and that
// barrel re-exports this very module, forming a Rollup chunk cycle.
// ``wrapApiFunctions`` itself has only type-only deps, so the direct import
// is also strictly lighter.
import { wrapApiFunctions } from "@shared/tables/BasicEditableTable/wrapApiFunctions";
import type {
  ApiFunctions,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { pickTierPriceFromAmount } from "@shared/utils/tierPrice";
import { useCurrency } from "@hooks/configuration/useCurrency";
import { useTenant } from "@hooks/configuration/useTenant";
import { useNumberFormat } from "@hooks/useNumberFormat";

/**
 * A row in the OrderContent table.
 *
 * The hook's ``data`` array mixes two shapes:
 *   - Real ``OrderContentListItem`` rows from the server (every key
 *     present, nullable where the model says so).
 *   - Placeholder rows synthesised by ``OrderContentService`` for an
 *     offer that doesn't yet have an OrderContent. These carry the
 *     offer's id as ``id`` and have ``is_placeholder: true``.
 *
 * The ``line_netto`` / ``line_brutto`` augmentations are added locally
 * by ``withLineTotals``. ``key`` is the EditableTable per-row key.
 */
export type OrderContentRow = OrderContentListItem & {
  is_placeholder?: boolean;
  line_netto?: number;
  line_brutto?: number;
  key?: number;
};

/** Same idea for crate rows — see ``OrderContentRow`` for the rationale.
 * ``line_netto`` is re-typed to the locally-computed number; the server
 * sends it as a 2dp string, which ``withLineTotals`` parses for display. */
export type CrateOrderContentRow = Omit<CrateOrderSummary, "line_netto"> & {
  line_netto?: number;
  line_brutto?: number;
  key?: number;
};

export interface OrderState {
  orderId: string | number | null;
  orderNumber: string | number | null;
  usedOrderNumberPrefix: string | null;
  isOrderFinalized: boolean;
  deliveryNoteId: string | null;
  deliveryNoteNumber: string | number | null;
  deliveryNotePrefix: string | null;
  isDeliveryNoteFinalized: boolean;
  invoiceId: string | null;
  invoiceNumber: string | number | null;
  invoicePrefix: string | null;
  hasInvoice: boolean;
  hasFinalizedInvoice: boolean;
}

export interface OrderDays {
  harvesting_day: number | null;
  packing_day: number | null;
  washing_day: number | null;
  cleaning_day: number | null;
}

export interface OddDefaults {
  default_harvesting_day: number | null;
  default_packing_day: number | null;
  default_washing_day: number | null;
  default_cleaning_day: number | null;
}

export function useOrdersData() {
  // Computed at hook-run time (lazy initialisers), not at module load, so a
  // long-lived tab open across a day/week/year boundary still starts on the
  // correct current period rather than a value frozen at bundle load.
  const [selectedYear, setSelectedYear] = useState(() => dayjs().year());
  const [selectedWeek, setSelectedWeek] = useState(() => dayjs().isoWeek());
  const [selectedDay, setSelectedDay] = useState(() => {
    const currentIsoWeekday = dayjs().isoWeekday();
    return currentIsoWeekday - 1 === 6 ? 5 : currentIsoWeekday - 1;
  });
  const [selectedReseller, setSelectedReseller] = useState<string | null>(null);

  const [data, setData] = useState<OrderContentRow[]>([]);
  const [dataCrates, setDataCrates] = useState<CrateOrderContentRow[]>([]);
  const [showOnlyOrderedOffers, setShowOnlyOrderedOffers] = useState(false);
  const [activeTab, setActiveTab] = useState("offers");
  const [orderNote, setOrderNote] = useState("");
  // The note value the server currently holds — updated wherever
  // ``orderNote`` is seeded from the query (and after a successful
  // autosave). The autosave effect persists only when ``orderNote``
  // diverges from this, so server-originated values never trigger a
  // write-back. Replaces the old ``noteInitialized`` latch, whose
  // reset-vs-reseed ordering could swallow a same-tick first edit.
  const lastServerNote = useRef("");

  const [orderState, setOrderState] = useState<OrderState>({
    orderId: null,
    orderNumber: null,
    usedOrderNumberPrefix: null,
    isOrderFinalized: false,
    deliveryNoteId: null,
    deliveryNoteNumber: null,
    deliveryNotePrefix: null,
    isDeliveryNoteFinalized: false,
    invoiceId: null,
    invoiceNumber: null,
    invoicePrefix: null,
    hasInvoice: false,
    hasFinalizedInvoice: false,
  });

  const [orderDays, setOrderDays] = useState<OrderDays>({
    harvesting_day: null,
    packing_day: null,
    washing_day: null,
    cleaning_day: null,
  });

  const [oddDefaults, setOddDefaults] = useState<OddDefaults>({
    default_harvesting_day: null,
    default_packing_day: null,
    default_washing_day: null,
    default_cleaning_day: null,
  });

  const { getSetting, tenant, logoUrl, bioLogoUrl } = useTenant();
  const { currencySymbol } = useCurrency();
  const { format } = useNumberFormat();
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const defaultTaxRateArticles = (getSetting("default_tax_rate_articles") as number) ?? 7;
  const defaultTaxRateCrates = (getSetting("default_tax_rate_crates") as number) ?? 19;
  const used_tiers_for_offers = getSetting("used_tiers_for_offers") as number[] | undefined;
  // **Single-tier mode** when the tenant hasn't configured tiers: pass
  // ``[1]`` so ``pickTierPrice`` never escalates beyond ``price_1``.
  // No silent fallback to ``[1, 3, 5]`` — that bumped non-tier tenants
  // into 3-tier pricing.
  const finalTiers = useMemo<number[]>(
    () =>
      used_tiers_for_offers && used_tiers_for_offers.length > 0
        ? used_tiers_for_offers
        : [1],
    [used_tiers_for_offers],
  );

  const listParams = useMemo<CommissioningOrderContentsListParams>(
    () => ({
      year: selectedYear,
      delivery_week: selectedWeek,
      day_number: selectedDay,
      reseller: selectedReseller!,
    }),
    [selectedYear, selectedWeek, selectedDay, selectedReseller],
  );

  // --- Price calculations (kept for live edit rows; backend supplies these for fetched rows) ---

  const calculateLineNetto = useCallback(
    (item: Record<string, unknown>) => {
      // Recompute from the (possibly just-edited) inputs — deliberately does
      // NOT prefer a cached ``line_netto`` (that preference lives in
      // ``withLineTotals``). Only real line rows (offer / article / crate)
      // carry a price; everything else is 0.
      if (
        item.offer ||
        item.share_article ||
        item.crate_type ||
        item.crate_type_name
      ) {
        return Number(
          computeLineNetto(item as unknown as LineNettoInput).toFixed(2),
        );
      }
      return 0;
    },
    [],
  );

  const calculateLineBrutto = useCallback(
    (item: Record<string, unknown>, defaultTaxRate: number) => {
      const netto = parseFloat(String(item.line_netto ?? calculateLineNetto(item))) || 0;
      const tax = parseFloat(String(item.tax_rate));
      const rate = Number.isFinite(tax) ? tax : defaultTaxRate;
      return Number((netto * (1 + rate / 100)).toFixed(2));
    },
    [calculateLineNetto],
  );

  // Generic over the row type so callers preserve their concrete shape
  // (``OrderContentRow``, ``CrateOrderContentRow``) through the spread —
  // the line_netto/brutto math is field-name based and works for both.
  //
  // ``preferServerNetto`` keeps the backend-computed ``line_netto`` (a
  // canonical Decimal string) for freshly-fetched rows instead of
  // recomputing it in JS floating point. Live edit rows pass it falsy so
  // the inline preview recomputes from the edited amount/price.
  const withLineTotals = useCallback(
    <T,>(item: T, defaultTaxRate: number, preferServerNetto = false) => {
      const asRecord = item as Record<string, unknown>;
      const serverNetto = asRecord.line_netto;
      const hasServerNetto =
        preferServerNetto &&
        serverNetto !== undefined &&
        serverNetto !== null &&
        serverNetto !== "";
      const netto = hasServerNetto
        ? parseFloat(String(serverNetto)) || 0
        : calculateLineNetto(asRecord);
      return {
        ...item,
        line_netto: netto,
        line_brutto: calculateLineBrutto(
          { ...asRecord, line_netto: netto },
          defaultTaxRate,
        ),
      };
    },
    [calculateLineNetto, calculateLineBrutto],
  );

  const calculatePricePerUnit = useCallback(
    (amount: number | string, record: Record<string, unknown>) => {
      if (!amount || !record.offer) return null;
      // Single source of truth — see ``utils/tierPrice.ts``. Tier
      // thresholds are PU-based; the typed amount is the row's unit
      // (KG / PCS / BUNCH), so we divide through ``amount_per_pu``
      // inside the helper.
      return pickTierPriceFromAmount(
        amount,
        record.amount_per_pu as number | string | null,
        {
          price_1: record.price_1 as number | string | null,
          price_2: record.price_2 as number | string | null,
          price_3: record.price_3 as number | string | null,
        },
        finalTiers,
      );
    },
    [finalTiers],
  );

  // --- API functions ---

  // `data` mixes real OrderContent rows with placeholder rows for offers
  // that don't yet have an OrderContent. Each row carries an explicit
  // `is_placeholder` flag (see `_serialize_unused_offer` in
  // order_content_service.py). We need the freshest array inside the api
  // closures to look records up; a ref avoids re-creating apiFunctions on
  // every data change (which would invalidate EditableTable's initialData).
  const dataRef = useRef(data);
  useEffect(() => {
    dataRef.current = data;
  }, [data]);

  // UI-2: creating the first line/crate for a day creates the Order
  // server-side, so the day-selector dots (a separate DaysWithOrders query) must
  // refresh. The contents/crates lists stay uninvalidated on create per the
  // no-refetch-on-create policy — this only bumps the dots query.
  const invalidateDaysWithOrders = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningDaysWithOrdersRetrieveQueryKey(listParams),
    });
  }, [queryClient, listParams]);

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<OrderContent & TableRecord>({
      create: async (payload) => {
        const res = await commissioningOrderContentsCreate(payload);
        invalidateDaysWithOrders();
        return res;
      },
      update: async (id, payload) => {
        // Placeholder rows carry the offer's id (so React has a unique key)
        // but no OrderContent exists yet. Route those to CREATE — PATCH'ing
        // /order-contents/<offer.id>/ would 404.
        const record = dataRef.current.find(
          (r) => String(r.id) === String(id),
        );
        if (record?.is_placeholder) {
          const res = await commissioningOrderContentsCreate(payload);
          invalidateDaysWithOrders();
          return res;
        }
        return commissioningOrderContentsPartialUpdate(id, payload);
      },
      delete: async (id) => {
        const res = (await commissioningOrderContentsDestroy(id)) as
          | { order_deleted?: boolean }
          | undefined;
        // Always refetch so the OrderInfoPanel (totals, finalized flags,
        // order number) stays in sync.
        queryClient.invalidateQueries({
          queryKey: getCommissioningOrderContentsListQueryKey(listParams),
        });
        if (res?.order_deleted) {
          // The parent Order was cascade-deleted server-side. Clear the
          // derived state immediately so the panel updates this render —
          // don't wait for the refetch round-trip.
          setOrderState({
            orderId: null,
            orderNumber: null,
            usedOrderNumberPrefix: null,
            isOrderFinalized: false,
            deliveryNoteId: null,
            deliveryNoteNumber: null,
            deliveryNotePrefix: null,
            isDeliveryNoteFinalized: false,
            invoiceId: null,
            invoiceNumber: null,
            invoicePrefix: null,
            hasInvoice: false,
            hasFinalizedInvoice: false,
          });
          setDataCrates([]);
          lastServerNote.current = "";
          setOrderNote("");
          queryClient.invalidateQueries({
            queryKey: getCommissioningDaysWithOrdersRetrieveQueryKey(listParams),
          });
          queryClient.invalidateQueries({
            queryKey: getCommissioningCrateContentsListQueryKey(listParams),
          });
        }
      },
    }),
    [queryClient, listParams, invalidateDaysWithOrders],
  );

  const apiFunctionsCrates = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<CrateOrderContentCreateRequest & TableRecord>({
      create: async (payload) => {
        const res = await commissioningCrateContentsCreate(payload);
        invalidateDaysWithOrders();
        return res;
      },
      update: (id, payload) =>
        commissioningCrateContentsPartialUpdate(id, payload),
      delete: (id, data) =>
        // Deliberate directional bridge: the table hands the loose row
        // values, the destroy endpoint wants the typed query params
        // (year/week/day/reseller/order_id) — a genuinely different shape.
        commissioningCrateContentsDestroy(
          id,
          data as unknown as CommissioningCrateContentsDestroyParams,
        ),
    }),
    [invalidateDaysWithOrders],
  );

  // --- Data fetching (React Query) ---

  const { data: rawOrderData, isFetching: orderFetching } = useCommissioningOrderContentsList(
    listParams,
    { query: { enabled: !!selectedReseller } },
  );

  const { data: rawDaysData, isFetching: daysFetching } =
    useCommissioningDaysWithOrdersRetrieve(listParams);

  const hasOrder = useMemo(() => {
    // Read the top-level ``order`` block, NOT ``items[0]`` — a crates-only
    // order has zero OrderContent rows, so ``items`` is empty even though an
    // order exists. The crates query + order state below both gate on this.
    return !!rawOrderData?.order?.order_id;
  }, [rawOrderData]);

  const { data: rawCratesData, isFetching: cratesFetching } = useCommissioningCrateContentsList(
    listParams,
    { query: { enabled: hasOrder } },
  );

  // ``isFetching`` (not ``isLoading``): the Orders page is filter-driven
  // (year/week/day/reseller). With the global ``staleTime: 0`` a revisited
  // cached key has ``isLoading === false``, so only ``isFetching`` drives the
  // table's refresh spinner on a selector change.
  const loading = orderFetching || daysFetching || (hasOrder && cratesFetching);

  const daysWithOrders = useMemo(() => {
    if (!rawDaysData) return [] as number[];
    return rawDaysData.days ?? [];
  }, [rawDaysData]);

  // Sync order data from query to local DRAFT state. Unlike a plain
  // "mirror" anti-pattern, this state is genuinely editable — handleDataChange
  // mutates `data` locally before the user saves, and the saved mutation
  // refetches the query which re-seeds the draft. Don't convert to useMemo
  // without splitting "loaded vs draft" first.
  useEffect(() => {
    if (!rawOrderData) return;
    const orderData: OrderContentRow[] = rawOrderData.items ?? [];
    const defaults = rawOrderData.orders_delivery_day_defaults;

    setData(orderData);
    setOddDefaults({
      default_harvesting_day: defaults.default_harvesting_day ?? null,
      default_packing_day: defaults.default_packing_day ?? null,
      default_washing_day: defaults.default_washing_day ?? null,
      default_cleaning_day: defaults.default_cleaning_day ?? null,
    });

    // Seed from the top-level ``order`` block (present for crates-only orders
    // too), NOT ``items[0]`` — see ``hasOrder`` above.
    const order = rawOrderData.order;

    if (order?.order_id) {
      setOrderState({
        orderId: order.order_id,
        orderNumber: order.order_number,
        usedOrderNumberPrefix: order.order_number_prefix,
        isOrderFinalized: order.order_is_finalized || false,
        deliveryNoteId: order.delivery_note_id ?? null,
        deliveryNoteNumber: order.delivery_note_number,
        deliveryNotePrefix: order.delivery_note_prefix,
        isDeliveryNoteFinalized: order.delivery_note_is_finalized || false,
        invoiceId: order.invoice_id ?? null,
        invoiceNumber: order.invoice_number,
        invoicePrefix: order.invoice_prefix,
        hasInvoice: order.has_invoice,
        hasFinalizedInvoice: order.has_finalized_invoice,
      });

      const serverNote = order.order_note || "";
      lastServerNote.current = serverNote;
      setOrderNote(serverNote);

      setOrderDays({
        harvesting_day: order.harvesting_day ?? null,
        packing_day: order.packing_day ?? null,
        washing_day: order.washing_day ?? null,
        cleaning_day: order.cleaning_day ?? null,
      });
    } else {
      setDataCrates([]);
      setOrderState({
        orderId: null,
        orderNumber: null,
        usedOrderNumberPrefix: null,
        isOrderFinalized: false,
        deliveryNoteId: null,
        deliveryNoteNumber: null,
        deliveryNotePrefix: null,
        isDeliveryNoteFinalized: false,
        invoiceId: null,
        invoiceNumber: null,
        invoicePrefix: null,
        hasInvoice: false,
        hasFinalizedInvoice: false,
      });
      lastServerNote.current = "";
      setOrderNote("");
      setOrderDays({
        harvesting_day: defaults.default_harvesting_day ?? null,
        packing_day: defaults.default_packing_day ?? null,
        washing_day: defaults.default_washing_day ?? null,
        cleaning_day: defaults.default_cleaning_day ?? null,
      });
    }
  }, [rawOrderData]);

  // Sync crates data from query to local state
  useEffect(() => {
    if (!hasOrder) {
      setDataCrates([]);
      return;
    }
    if (!rawCratesData) return;
    // Directional re-type at the fetch boundary: the server sends
    // ``line_netto`` as a 2dp Decimal string, while ``CrateOrderContentRow``
    // carries the locally-computed number (see the type's docstring).
    // ``withLineTotals`` below parses the string into that number field.
    const responseData = rawCratesData as unknown as CrateOrderContentRow[];
    // Fetched rows carry a backend-computed Decimal ``line_netto`` string —
    // display it as-is instead of recomputing in JS float.
    setDataCrates(
      responseData.map((item) =>
        withLineTotals(item, defaultTaxRateCrates, true),
      ),
    );
  }, [rawCratesData, hasOrder, withLineTotals, defaultTaxRateCrates]);

  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningOrderContentsListQueryKey(listParams),
    });
    queryClient.invalidateQueries({
      queryKey: getCommissioningDaysWithOrdersRetrieveQueryKey(listParams),
    });
    if (hasOrder) {
      queryClient.invalidateQueries({
        queryKey: getCommissioningCrateContentsListQueryKey(listParams),
      });
    }
  }, [queryClient, listParams, hasOrder]);

  // --- Data change handlers ---

  // Mirror the initial-fetch ``setOrderState`` path: every row the
  // backend returns after a save carries the freshly-assigned order
  // metadata (and, once they exist, delivery-note / invoice ids).
  // The previous version of ``handleDataChange`` only propagated
  // ``order_number``, which meant ``orderState.orderId`` stayed null
  // after the very first save — the OrderInfoPanel's
  // ``BulkActionButton`` then gated to ``selectedIds=[]`` and the
  // "create delivery note" button looked disabled even though the
  // sum and order number had clearly updated. Same row → same sync,
  // so the offers, articles and crates tables all converge.
  const syncOrderStateFromRow = useCallback(
    (row: Record<string, unknown>) => {
      setOrderState((prev) => ({
        ...prev,
        ...(row.order_id !== undefined
          ? { orderId: (row.order_id as string | number | null) ?? null }
          : {}),
        // Guarded like the sibling fields below: a row that omits these (e.g.
        // a crate row before its serializer carried the prefix) must not
        // clobber a known prefix to ``undefined`` ("undefined-39").
        ...(row.order_number !== undefined
          ? { orderNumber: row.order_number as string | number }
          : {}),
        ...(row.order_number_prefix !== undefined
          ? { usedOrderNumberPrefix: row.order_number_prefix as string | null }
          : {}),
        ...(row.order_is_finalized !== undefined
          ? { isOrderFinalized: (row.order_is_finalized as boolean) || false }
          : {}),
        ...(row.delivery_note_id !== undefined
          ? {
              deliveryNoteId: (row.delivery_note_id as string | null) ?? null,
            }
          : {}),
        ...(row.delivery_note_number !== undefined
          ? {
              deliveryNoteNumber: row.delivery_note_number as
                | string
                | number
                | null,
              deliveryNotePrefix: row.delivery_note_prefix as string | null,
            }
          : {}),
        ...(row.delivery_note_is_finalized !== undefined
          ? {
              isDeliveryNoteFinalized:
                (row.delivery_note_is_finalized as boolean) || false,
            }
          : {}),
        ...(row.invoice_id !== undefined
          ? { invoiceId: (row.invoice_id as string | null) ?? null }
          : {}),
        ...(row.invoice_number !== undefined
          ? {
              invoiceNumber: row.invoice_number as string | number | null,
              invoicePrefix: row.invoice_prefix as string | null,
            }
          : {}),
        ...(row.has_invoice !== undefined
          ? { hasInvoice: row.has_invoice as boolean }
          : {}),
        ...(row.has_finalized_invoice !== undefined
          ? { hasFinalizedInvoice: row.has_finalized_invoice as boolean }
          : {}),
      }));
    },
    [],
  );

  const handleDataChange = useCallback(
    (newData: Record<string, unknown>[]) => {
      // Cast through unknown: the runtime shape is OrderContentRow, but
      // the EditableTable's onChange callback is typed generically.
      const dataWithTotals = newData.map((item) =>
        withLineTotals(item as unknown as OrderContentRow, defaultTaxRateArticles),
      );
      setData(dataWithTotals);

      if (newData && newData.length > 0 && newData[0].order_number) {
        syncOrderStateFromRow(newData[0]);
      }
    },
    [withLineTotals, defaultTaxRateArticles, syncOrderStateFromRow],
  );

  const handleCratesDataChange = useCallback(
    (newData: Record<string, unknown>[]) => {
      const dataWithTotals = newData.map((item) =>
        withLineTotals(
          item as unknown as CrateOrderContentRow,
          defaultTaxRateCrates,
        ),
      );
      setDataCrates(dataWithTotals);

      // The crates table also produces a backend-assigned order on
      // first save when none existed yet. Without this sync the
      // OrderInfoPanel's BulkActionButton stays disabled because
      // ``orderState.orderId`` is still null (its ``selectedIds``
      // collapses to ``[]`` and the button gates on that).
      if (newData && newData.length > 0 && newData[0].order_number) {
        syncOrderStateFromRow(newData[0]);
      }
    },
    [withLineTotals, defaultTaxRateCrates, syncOrderStateFromRow],
  );

  // --- Finalize success handlers ---

  const handleFinalizeInvoicesSuccess = useCallback(
    async (responseData: unknown) => {
      // Param stays ``unknown`` (OrderInfoPanel's prop contract); one
      // directional cast to the generated response type — BulkActionButton
      // hands through the client's parsed body.
      const body = responseData as BulkOperationResponse | undefined;
      const successResults = (body?.results ?? []).filter((r) => r.success);

      // Generate delivery note PDFs (if not already generated)
      for (const r of successResults) {
        if (r.delivery_note_id) {
          try {
            await generateAndUploadDeliveryNotePDF(r.delivery_note_id, t, tenant as Record<string, unknown>, getSetting, logoUrl, bioLogoUrl);
          } catch (err) {
            console.error(`DN PDF generation failed for ${r.delivery_note_id}:`, err);
          }
        }
      }

      // Generate invoice PDFs
      for (const r of successResults) {
        if (r.invoice_id) {
          try {
            await generateAndUploadInvoicePDF(r.invoice_id, t, tenant as Record<string, unknown>, getSetting, logoUrl, bioLogoUrl);
          } catch (err) {
            console.error(`PDF generation failed for invoice ${r.invoice_id}:`, err);
          }
        }
      }

      // Invalidate all detail queries so PDF buttons pick up uploaded files
      const invalidations: Promise<void>[] = [];
      for (const r of successResults) {
        if (r.delivery_note_id) {
          invalidations.push(queryClient.invalidateQueries({
            queryKey: getCommissioningDeliveryNotesRetrieveQueryKey(r.delivery_note_id),
          }));
        }
        if (r.invoice_id) {
          invalidations.push(queryClient.invalidateQueries({
            queryKey: getCommissioningInvoicesRetrieveQueryKey(r.invoice_id),
          }));
        }
      }
      await Promise.all(invalidations);
      invalidateData();
    },
    [t, tenant, getSetting, logoUrl, bioLogoUrl, invalidateData, queryClient],
  );

  const handleFinalizeDNSuccess = useCallback(
    async (responseData: unknown) => {
      // Same ``unknown``-param + single directional cast as
      // ``handleFinalizeInvoicesSuccess`` above.
      const body = responseData as BulkOperationResponse | undefined;
      const dnIds = (body?.results ?? [])
        .filter((r) => r.success && r.delivery_note_id)
        .map((r) => r.delivery_note_id);
      for (const id of dnIds) {
        try {
          await generateAndUploadDeliveryNotePDF(id, t, tenant as Record<string, unknown>, getSetting, logoUrl, bioLogoUrl);
        } catch (err) {
          console.error(`PDF generation failed for delivery note ${id}:`, err);
        }
      }
      // Invalidate detail queries so PDF buttons pick up uploaded files
      await Promise.all(
        dnIds.map((id) => queryClient.invalidateQueries({
          queryKey: getCommissioningDeliveryNotesRetrieveQueryKey(id),
        })),
      );
      invalidateData();
    },
    [t, tenant, getSetting, logoUrl, bioLogoUrl, invalidateData, queryClient],
  );

  const handleCreateInvoiceSuccess = useCallback(
    async (responseData: unknown) => {
      // Same ``unknown``-param + single directional cast as
      // ``handleFinalizeInvoicesSuccess`` above.
      const body = responseData as BulkOperationResponse | undefined;
      const dnIds = (body?.results ?? [])
        .filter((r) => r.success && r.delivery_note_id)
        .map((r) => r.delivery_note_id);
      for (const id of dnIds) {
        try {
          await generateAndUploadDeliveryNotePDF(id, t, tenant as Record<string, unknown>, getSetting, logoUrl, bioLogoUrl);
        } catch (err) {
          console.error(`DN PDF generation failed for ${id}:`, err);
        }
      }
      await Promise.all(
        dnIds.map((id) => queryClient.invalidateQueries({
          queryKey: getCommissioningDeliveryNotesRetrieveQueryKey(id),
        })),
      );
      invalidateData();
    },
    [t, tenant, getSetting, logoUrl, bioLogoUrl, invalidateData, queryClient],
  );

  // --- Filtering & sorting ---

  const { filteredDataOffers, filteredDataArticles, filteredDataArticlesCount, filteredDataOffersCount } = useMemo(() => {
    if (data && data.length > 0) {
      let offersData = data.filter((item) => item.offer);

      if (showOnlyOrderedOffers) {
        // ``amount`` is a decimal string on the wire (e.g. "1.500");
        // parse rather than cast-as-number so we don't silently compare
        // strings as if they were numbers.
        offersData = offersData.filter(
          (item) => item.amount != null && parseFloat(String(item.amount)) > 0,
        );
      }

      offersData = offersData.map((item) => withLineTotals(item, defaultTaxRateArticles));
      offersData.sort((a, b) =>
        ((a.offer_name as string) || "").toLowerCase().localeCompare(
          ((b.offer_name as string) || "").toLowerCase(),
        ),
      );

      let articlesData = data.filter((item) => !item.offer);
      articlesData = articlesData.map((item) => withLineTotals(item, defaultTaxRateArticles));
      articlesData.sort((a, b) => {
        const nameA = ((a.share_article_name as string) || "").toLowerCase();
        const nameB = ((b.share_article_name as string) || "").toLowerCase();
        return nameA.localeCompare(nameB);
      });

      return {
        filteredDataOffers: offersData,
        filteredDataArticles: articlesData,
        filteredDataArticlesCount: articlesData.length,
        // Same decimal-string note as above — empty string OR zero parsed
        // value both mean "no amount ordered" for this offer row.
        filteredDataOffersCount: offersData.filter(
          (item) =>
            item.amount != null &&
            item.amount !== "" &&
            parseFloat(String(item.amount)) !== 0,
        ).length,
      };
    }
    return {
      filteredDataOffers: [] as OrderContentRow[],
      filteredDataArticles: [] as OrderContentRow[],
      filteredDataArticlesCount: 0,
      filteredDataOffersCount: 0,
    };
  }, [data, showOnlyOrderedOffers, withLineTotals, defaultTaxRateArticles]);

  // --- Total sum (gross) ---

  const totalSum = useMemo(() => {
    const breakdown = computeTaxBreakdown(
      filteredDataOffers as unknown as LineItemBase[],
      filteredDataArticles as unknown as LineItemBase[],
      dataCrates as unknown as LineItemBase[],
    );
    const { brutto } = totalsFromBreakdown(breakdown);
    return brutto > 0 ? `${format(brutto, 2)} ${currencySymbol}` : "---";
  }, [filteredDataOffers, filteredDataArticles, dataCrates, currencySymbol, format]);

  // --- Summary ---

  const summaryColumns = useMemo(() => ["amount", "line_netto"], []);

  // Generic so it accepts both OrderContentRow[] (offer + article tables)
  // and CrateOrderContentRow[] (crates table) without forcing the caller
  // to widen to ``Record<string, unknown>[]``. The body only reads
  // ``amount`` / ``line_netto`` which both row types expose.
  const calculateSummaryData = useCallback(
    <T,>(summaryData: T[], isCrates = false) => {
      let totalAmount = 0;
      let totalLineNetto = 0;
      summaryData.forEach((row) => {
        const item = row as Record<string, unknown>;
        if (item.amount && (item.amount as number) > 0) totalAmount += parseFloat(String(item.amount)) || 0;
        if (item.line_netto) totalLineNetto += parseFloat(String(item.line_netto)) || 0;
      });
      return {
        amount: isCrates ? `${format(totalAmount, 0)}` : `${format(totalAmount, 1)} ${t("commissioning.pu")}`,
        line_netto: `${format(totalLineNetto, 2)} ${currencySymbol}`,
      };
    },
    [t, currencySymbol, format],
  );

  const summaryDataOffers = useMemo(() => calculateSummaryData(filteredDataOffers, false), [filteredDataOffers, calculateSummaryData]);
  const summaryDataArticles = useMemo(() => calculateSummaryData(filteredDataArticles, true), [filteredDataArticles, calculateSummaryData]);
  const summaryDataCrates = useMemo(() => calculateSummaryData(dataCrates, true), [dataCrates, calculateSummaryData]);

  // No-op: matches the codebase-wide policy of never re-fetching the
  // list on save (CREATE or UPDATE). EditableTable inserts the new row
  // at the top on create and replaces in place on update; refetching
  // would re-sort by the backend's default ordering and yank the row
  // away mid-flow. ``handleDataChange`` (separate callback) takes care
  // of the order metadata sync on every change.
  const handleSaveSuccess = useCallback(
    (_record: unknown, _action: "create" | "update") => {
      // intentional no-op — see comment above
    },
    [],
  );

  // The latest un-persisted note edit, tagged with the order it belongs to.
  // Tagging (rather than reading ``orderState.orderId`` at flush time) is what
  // lets a flush on order-switch / unmount target the *outgoing* order even
  // after the on-screen order (and ``lastServerNote``) has already moved on.
  const pendingNote = useRef<{ orderId: string; note: string } | null>(null);

  // Auto-save the order note with debounce. Persist only genuine user
  // edits: a value just seeded from the server (``lastServerNote``)
  // matches ``orderNote`` and is skipped, so there's no write-back on
  // load or order-switch. After a successful save the server value is
  // advanced so re-saving an unchanged note (or reverting to the exact
  // original) behaves correctly.
  useEffect(() => {
    if (!orderState.orderId) return;
    if (orderNote === lastServerNote.current) {
      pendingNote.current = null;
      return;
    }

    const orderId = String(orderState.orderId);
    pendingNote.current = { orderId, note: orderNote };

    const timer = setTimeout(async () => {
      const noteToSave = orderNote;
      pendingNote.current = null;
      try {
        await commissioningSetOrderNotePartialUpdate(orderId, {
          note: noteToSave,
        });
        lastServerNote.current = noteToSave;
      } catch (error) {
        console.error("Error saving order note:", error);
        // Re-arm so the edit is retried on the next flush instead of lost.
        pendingNote.current = { orderId, note: noteToSave };
      }
    }, 800);

    return () => clearTimeout(timer);
  }, [orderNote, orderState.orderId]);

  // Flush a pending edit when the order changes or the hook unmounts, so a note
  // typed within the debounce window isn't dropped when the user navigates away
  // before the 800ms elapses. React runs all effect cleanups before any setup,
  // so ``pendingNote`` still holds the outgoing order's edit here. Fire-and-
  // forget: cleanup is synchronous, so we can't await the PATCH (a hard tab
  // close can still race it — the in-app switch/unmount case is what's covered).
  useEffect(() => {
    return () => {
      const pending = pendingNote.current;
      if (!pending) return;
      pendingNote.current = null;
      commissioningSetOrderNotePartialUpdate(pending.orderId, {
        note: pending.note,
      }).catch((error) => {
        console.error("Error saving order note:", error);
      });
    };
  }, [orderState.orderId]);

  return {
    // Selection state
    selectedYear, setSelectedYear,
    selectedWeek, setSelectedWeek,
    selectedDay, setSelectedDay,
    selectedReseller, setSelectedReseller,
    activeTab, setActiveTab,
    showOnlyOrderedOffers, setShowOnlyOrderedOffers,

    // Data
    data,
    filteredDataOffers,
    filteredDataArticles,
    filteredDataArticlesCount,
    filteredDataOffersCount,
    dataCrates,
    dataCratesCount: dataCrates.length,
    daysWithOrders,
    loading,

    // Order state
    orderState,
    orderDays, setOrderDays,
    oddDefaults,
    orderNote, setOrderNote,
    totalSum,

    // API
    apiFunctions,
    apiFunctionsCrates,
    listParams,

    // Callbacks
    fetchData: invalidateData,
    fetchCratesData: invalidateData,
    handleDataChange,
    handleCratesDataChange,
    handleSaveSuccess,
    handleFinalizeInvoicesSuccess,
    handleFinalizeDNSuccess,
    handleCreateInvoiceSuccess,
    calculatePricePerUnit,
    calculateLineNetto,
    calculateLineBrutto,

    // Summary
    summaryColumns,
    summaryDataOffers,
    summaryDataArticles,
    summaryDataCrates,

    // Settings
    defaultTaxRateArticles,
    getSetting,
    tenant,
    logoUrl,
  };
}
