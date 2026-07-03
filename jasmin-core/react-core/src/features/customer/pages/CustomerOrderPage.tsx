import { useQueryClient } from "@tanstack/react-query";
import { Card, Col, Row, Table, Tag, Typography } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import {
  getCommissioningOffersListQueryKey,
  getCommissioningOrderContentsListQueryKey,
  useCommissioningOffersList,
  useCommissioningOrderContentsList,
  useCommissioningOrdersDeliveryDaysList,
  useCommissioningResellersRetrieve,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningOffersListParams,
  CommissioningOrderContentsListParams,
  OrderContentListItem,
} from "@shared/api/generated/models";
import type {
  CustomerOrderRow,
  CustomerOrderTableRow,
  OfferRow,
  OtherArticleRow,
} from "@features/customer/types";
import { DaySelector, WeekSelector } from "@shared/selectors";
import { useAuth } from "@shared/contexts/AuthContext";
import {
  useCurrency,
  useNumberFormat,
  useTenant,
  useTimeFormat,
} from "@hooks/index";
import CustomerDocumentsCard from "../components/CustomerDocumentsCard";
import CustomerOrderHeader from "../components/CustomerOrderHeader";
import { useCustomerOrderColumns } from "@features/customer/hooks/useCustomerOrderColumns";
import { useOtherArticleColumns } from "@features/customer/hooks/useOtherArticleColumns";
import { useCustomerOrderMutations } from "@features/customer/hooks/useCustomerOrderMutations";
import { useOrderingDeadline } from "@features/customer/hooks/useOrderingDeadline";

const { Text } = Typography;

const currentYear = dayjs().year();
const currentWeek = dayjs().isoWeek();

export default function CustomerOrderPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const { displayLogoUrl, getSetting } = useTenant();
  const { currencySymbol } = useCurrency();
  const { formatDateTime, dateFormat } = useTimeFormat();
  const { format } = useNumberFormat();
  const queryClient = useQueryClient();

  const { resellerId: resellerIdParam } = useParams<{ resellerId: string }>();
  const resellerId =
    resellerIdParam || (user?.reseller_id as string | undefined);

  const [selectedYear, setSelectedYear] = useState(currentYear);
  const [selectedWeek, setSelectedWeek] = useState<number | null>(currentWeek);
  const currentDay = dayjs().isoWeekday();
  const [selectedDay, setSelectedDay] = useState(
    currentDay - 1 === 6 ? 5 : currentDay - 1,
  );
  const { data: reseller } = useCommissioningResellersRetrieve(resellerId!, {
    query: { enabled: !!resellerId },
  });

  const { data: orderDeliveryDays } = useCommissioningOrdersDeliveryDaysList();
  const orderDayNumbers = useMemo(() => {
    const list = orderDeliveryDays ?? [];
    return list.map((odd) => odd.day_number as number).sort();
  }, [orderDeliveryDays]);

  useEffect(() => {
    if (orderDayNumbers.length > 0 && !orderDayNumbers.includes(selectedDay)) {
      setSelectedDay(orderDayNumbers[0]);
    }
  }, [orderDayNumbers, selectedDay]);

  const offersParams = useMemo<CommissioningOffersListParams>(
    () => ({
      year: selectedYear,
      delivery_week: selectedWeek ?? currentWeek,
      reseller: resellerId!,
    }),
    [selectedYear, selectedWeek, resellerId],
  );

  const { data: offers = [] } = useCommissioningOffersList(offersParams, {
    query: { enabled: !!resellerId },
  });

  const orderParams = useMemo<CommissioningOrderContentsListParams>(
    () => ({
      year: selectedYear,
      delivery_week: selectedWeek ?? currentWeek,
      day_number: selectedDay,
      reseller: resellerId!,
    }),
    [selectedYear, selectedWeek, selectedDay, resellerId],
  );

  const { data: rawOrderContents } = useCommissioningOrderContentsList(
    orderParams,
    { query: { enabled: !!resellerId } },
  );

  const orderContents = useMemo(
    () => rawOrderContents?.items ?? [],
    [rawOrderContents],
  );

  const oddDefaults = useMemo(
    () => rawOrderContents?.orders_delivery_day_defaults ?? null,
    [rawOrderContents],
  );

  const { orderingDeadline, isOrderingClosed } = useOrderingDeadline(
    oddDefaults,
    selectedYear,
    selectedWeek ?? currentWeek,
  );

  const invalidateOrders = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningOrderContentsListQueryKey(orderParams),
    });
    queryClient.invalidateQueries({
      queryKey: getCommissioningOffersListQueryKey(offersParams),
    });
  }, [queryClient, orderParams, offersParams]);

  const isPastWeek = useMemo(() => {
    // Evaluate "now" inside the memo so it can't go stale if the page
    // outlives a week boundary, and so the memo is self-contained: its
    // only inputs are the selection (deps below), with no reliance on the
    // module-level current* snapshot taken once at import time.
    const now = dayjs();
    const nowYear = now.year();
    const nowWeek = now.isoWeek();
    const week = selectedWeek ?? nowWeek;
    return (
      selectedYear < nowYear || (selectedYear === nowYear && week < nowWeek)
    );
  }, [selectedYear, selectedWeek]);

  const isReadOnly = isPastWeek || isOrderingClosed;

  // Map offer ID → order content item (only actual order contents, not unused-offer stubs)
  const orderByOfferId = useMemo(() => {
    const map = new Map<string, CustomerOrderRow>();
    for (const item of orderContents) {
      if (item.offer && item.order_id) map.set(item.offer, item);
    }
    return map;
  }, [orderContents]);

  // Offer-based rows feed the offers table; offer-less order lines (office-added
  // directly, no offer) go to the separate "other articles" table below.
  const offerRows = useMemo(
    () =>
      orderContents.filter(
        (item): item is OrderContentListItem & { offer: string } =>
          !!item.offer,
      ),
    [orderContents],
  );
  const otherArticleRows = useMemo<OtherArticleRow[]>(
    () =>
      orderContents
        .filter((item) => !item.offer && item.order_id)
        .map((item) => ({
          ...item,
          // Real persisted order-content rows always carry an id.
          id: item.id as string,
          order_is_finalized: Boolean(item.order_is_finalized),
        })),
    [orderContents],
  );

  // The order contents response already merges ordered items with unused offers from the backend.
  const tableData = useMemo<CustomerOrderTableRow[]>(() => {
    if (orderContents.length > 0) {
      return offerRows.map((item): CustomerOrderRow => {
        const hasOrder = !!item.order_id;
        return {
          ...item,
          id: item.offer,
          ordered_amount_num: hasOrder ? Number(item.ordered_amount) : null,
          order_content_id: hasOrder ? item.id : null,
          order_price: hasOrder ? Number(item.price_per_unit) : null,
          order_is_finalized: hasOrder ? item.order_is_finalized : false,
        };
      });
    }
    return offers
      .filter((offer) => offer.is_finalized === true)
      .map(
        (offer): OfferRow => ({
          ...offer,
          // Orval marks the server-assigned id readonly-optional; fetched
          // offers always carry one.
          id: offer.id as string,
          ordered_amount_num: null,
          order_content_id: null,
          order_price: null,
          order_is_finalized: false,
        }),
      );
  }, [orderContents, offerRows, offers]);

  const usedTiers = getSetting("used_tiers_for_offers") as number[] | undefined;
  // Single-tier mode when the tenant hasn't configured tiers — only
  // ``price_1`` is ever picked, no quantity-based escalation.
  const finalTiers = usedTiers && usedTiers.length > 0 ? usedTiers : [1];

  const {
    orderAmounts,
    submitting,
    handleAmountChange,
    handleOrder,
    handleUpdateOrder,
  } = useCustomerOrderMutations({
    resellerId,
    selectedYear,
    selectedWeek: selectedWeek ?? currentWeek,
    selectedDay,
    finalTiers,
    invalidateOrders,
    orderByOfferId,
  });

  const columns = useCustomerOrderColumns({
    tableData,
    finalTiers,
    orderAmounts,
    submitting,
    isReadOnly,
    onAmountChange: handleAmountChange,
    onOrder: handleOrder,
    onUpdate: handleUpdateOrder,
  });

  const otherArticleColumns = useOtherArticleColumns();

  const totalOrderSum = useMemo(() => {
    return orderContents.reduce((sum, item) => {
      const amount = Number(item.amount) || 0;
      const price = Number(item.price_per_unit) || 0;
      return sum + amount * price;
    }, 0);
  }, [orderContents]);

  // Order-level info for the summary header (outside the cards): once anything
  // is ordered every row for this reseller/week/day shares one Order, so the
  // first row with an ``order_id`` carries the order number + locked state.
  // ``isLocked`` reflects a finalized order OR an existing delivery note.
  const orderInfo = useMemo(() => {
    const withOrder = orderContents.find((item) => item.order_id);
    if (!withOrder) return null;
    return {
      orderNumber: withOrder.order_number,
      orderNumberPrefix: withOrder.order_number_prefix,
      isLocked:
        withOrder.order_is_finalized || !!withOrder.delivery_note_id,
    };
  }, [orderContents]);

  if (!resellerId) {
    return (
      <div style={{ padding: "48px", textAlign: "center" }}>
        <h1>{t("customer.no_reseller_linked")}</h1>
        <Text type="secondary">{t("customer.contact_admin")}</Text>
      </div>
    );
  }

  return (
    <div style={{ padding: "24px", maxWidth: "1200px", margin: "0 auto" }}>
      <CustomerOrderHeader reseller={reseller} logoUrl={displayLogoUrl} />

      <div style={{ marginBottom: "24px" }}>
        <WeekSelector
          selectedYear={selectedYear}
          setSelectedYear={setSelectedYear}
          selectedWeek={selectedWeek}
          setSelectedWeek={setSelectedWeek}
        />
        <DaySelector
          selectedYear={selectedYear}
          selectedWeek={selectedWeek ?? currentWeek}
          selectedDay={selectedDay}
          setSelectedDay={(v) => v !== null && setSelectedDay(v)}
          days={
            orderDayNumbers.length > 0 ? orderDayNumbers : [0, 1, 2, 3, 4, 5]
          }
          suffix={t("commissioning.delivery_day")}
        />
      </div>

      {/* Order-level summary OUTSIDE the offer card: always rendered (with a
          dash placeholder) so the layout doesn't shift once an order exists.
          The total spans both the offers and the other-articles table. */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 16,
          marginBottom: 16,
        }}
      >
        <Text type="secondary">
          {t("resellers.order_number")}:{" "}
          <Text strong>
            {orderInfo?.orderNumber
              ? orderInfo.orderNumberPrefix
                ? `${orderInfo.orderNumberPrefix}-${orderInfo.orderNumber}`
                : orderInfo.orderNumber
              : "—"}
          </Text>
        </Text>
        {orderInfo?.isLocked && <Tag color="blue">{t("customer.finalized")}</Tag>}
        <Text type="secondary" style={{ marginLeft: "auto" }}>
          {t("customer.total")}:{" "}
          <Text strong>
            {totalOrderSum > 0
              ? `${format(totalOrderSum, 2)} ${currencySymbol}`
              : "—"}
          </Text>
        </Text>
      </div>

      <Row gutter={[24, 24]}>
        <Col xs={24}>
          <Card
            title={
              <>
                {t("customer.available_offers")}
                <Text
                  type="secondary"
                  style={{ marginLeft: 12, fontWeight: "normal", fontSize: 14 }}
                >
                  {t("customer.week")} {selectedWeek} / {selectedYear}
                </Text>
                {orderingDeadline && (
                  <Tag
                    color={isOrderingClosed ? "red" : "green"}
                    style={{ marginLeft: 8 }}
                  >
                    {t("customer.order_deadline")}:{" "}
                    {formatDateTime(orderingDeadline, `dddd, ${dateFormat}`)}
                  </Tag>
                )}
                {isPastWeek && (
                  <Tag color="default" style={{ marginLeft: 8 }}>
                    {t("customer.finalized")}
                  </Tag>
                )}
              </>
            }
          >
            <Text
              type="secondary"
              style={{ marginLeft: 10, fontWeight: "normal", fontSize: 11 }}
            >
              {t("customer.prices_are_netto")}
            </Text>
            <Table
              dataSource={tableData}
              columns={columns}
              rowKey="id"
              pagination={false}
              size="small"
              className="custom-forecast-table compact-table"
              locale={{ emptyText: t("customer.no_offers") }}
            />
          </Card>
        </Col>
      </Row>

      {/* Offer-less order lines (office-added directly) — only when present, so
          the table is invisible otherwise. Own columns: amount + unit, per-unit
          price, rabatt, line total. */}
      {otherArticleRows.length > 0 && (
        <Row gutter={[24, 24]} style={{ marginTop: 24 }}>
          <Col xs={24}>
            <Card title={t("customer.other_articles")}>
              <Table
                dataSource={otherArticleRows}
                columns={otherArticleColumns}
                rowKey="id"
                pagination={false}
                size="small"
                className="custom-forecast-table compact-table"
              />
            </Card>
          </Col>
        </Row>
      )}

      <CustomerDocumentsCard orderContents={orderContents} />
    </div>
  );
}
