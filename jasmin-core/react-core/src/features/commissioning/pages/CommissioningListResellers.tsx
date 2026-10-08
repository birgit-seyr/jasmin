import { Alert, Button, Card, Spin, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  useCommissioningCommissioningListsResellersList,
  useCommissioningDaysWithOrdersRetrieve,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningCommissioningListsResellersListParams,
  CommissioningDaysWithOrdersRetrieveParams,
  CommissioningListResellersEntry,
} from "@shared/api/generated/models";
import { PastWarningMessage } from "@shared/ui";
import { ResellerOrderMobileCards } from "@features/commissioning/components/mobileCards";
import { CommissioningListResellersPDFGenerator } from "@features/commissioning/pdfs";
import { orderLineArticleLabel } from "@features/commissioning/utils/orderLineLabel";
import { DaySelector, WeekSelector } from "@shared/selectors";
import { ExplainerText, MobileStack } from "@shared/ui";
import {
  useIsMobile,
  useNoteColumn,
  useNumberFormat,
  useVegetableSizeOptions,
  useUnitOptions,
  useYearWeekState,
} from "@hooks/index";
import {
  formatDayLabel,
  formatWeekLabel,
  generatePdfFilename,
  getDayName,
  nextIsoWeek,
} from "@shared/utils";

/**
 * The delivery day the page opens on: today from Monday to Thursday, and next
 * week's Monday from Friday on, when this week's deliveries are packed.
 */
function openingDeliveryDay(): { year: number; week: number; day: number } {
  const today = dayjs();
  const year = today.isoWeekYear();
  const week = today.isoWeek();
  const weekday = today.isoWeekday();
  if (weekday < 5) return { year, week, day: weekday - 1 };
  return { ...nextIsoWeek(year, week), day: 0 };
}

// Derived straight from the generated client — the ``commissioning_lists_resellers``
// endpoint is fully serializer-typed, so there's no parallel interface to keep
// in sync (a hand-written one silently drifts).
type Reseller = CommissioningListResellersEntry;
type OrderContent = Reseller["order"]["contents"][number];

export default function CommissioningListResellers() {
  const { t } = useTranslation();

  // Read once when the page opens, so the first request already asks for the
  // opening day's week.
  const [openingDay] = useState(openingDeliveryDay);
  const { selectedYear, setSelectedYear, selectedWeek, setSelectedWeek } =
    useYearWeekState({
      initialYear: openingDay.year,
      initialWeek: openingDay.week,
    });
  const [selectedDay, setSelectedDay] = useState<number | null>(
    openingDay.day,
  );

  const { getUnitLabel } = useUnitOptions();
  const { getVegetableSizeLabel } = useVegetableSizeOptions();
  const { format } = useNumberFormat();
  const isMobile = useIsMobile();

  const listParams = useMemo<CommissioningCommissioningListsResellersListParams>(
    () => ({
      year: selectedYear,
      delivery_week: selectedWeek!,
      day_number: selectedDay!,
    }),
    [selectedYear, selectedWeek, selectedDay],
  );

  const daysParams = useMemo<CommissioningDaysWithOrdersRetrieveParams>(
    () => ({
      year: selectedYear,
      delivery_week: selectedWeek!,
    }),
    [selectedYear, selectedWeek],
  );

  const {
    data: resellersData,
    isLoading: loadingResellers,
    isError: ordersFailed,
    refetch: refetchOrders,
  } = useCommissioningCommissioningListsResellersList(listParams, {
      query: {
        enabled: selectedWeek != null && selectedDay != null,
      },
    });

  const { data: daysData } = useCommissioningDaysWithOrdersRetrieve(
    daysParams,
    {
      query: {
        enabled: selectedWeek != null,
      },
    },
  );

  // Only the resellers with something to pack get a card and a page.
  const resellers = useMemo(
    () =>
      (resellersData ?? []).filter(
        (reseller) => reseller.order.contents.length > 0,
      ),
    [resellersData],
  );
  const daysWithOrders = daysData?.days ?? [];

  const { noteColumn } = useNoteColumn();

  const columns: ColumnsType<OrderContent> = useMemo(
    () => [
      {
        title: t("commissioning.amount"),
        dataIndex: "amount_pu",
        key: "amount_pu",
        width: "12em",
        render: (_, record) => {
          const amount = Number(record.amount);
          const amountPerPu = Number(record.amount_per_pu);

          if (isNaN(amount) || isNaN(amountPerPu) || amountPerPu === 0) {
            return "-";
          }

          const puCount = format(amount / amountPerPu, 1);
          const formattedAmount = format(amount, 1);

          return (
            <>
              {puCount} {t("commissioning.pu")}{" "}
              <span className="text-bold">
                ({formattedAmount} {getUnitLabel(record.unit)})
              </span>
            </>
          );
        },
      },
      {
        title: t("commissioning.share_article"),
        dataIndex: "share_article_name",
        key: "share_article_name",
        width: "18em",
        align: "left",
        render: (_, record) =>
          orderLineArticleLabel(record, getVegetableSizeLabel),
      },
      {
        title: t("commissioning.per_pu"),
        dataIndex: "share_article_amount_per_pu",
        key: "share_article_amount_per_pu",
        width: "10em",
        align: "center",
        render: (_, record) => (
          <>
            ({format(Number(record.amount_per_pu), 2)}{" "}
            {getUnitLabel(record.unit)}/{t("commissioning.pu")})
          </>
        ),
      },
      noteColumn as ColumnsType<OrderContent>[number],
    ],
    [t, getUnitLabel, getVegetableSizeLabel, noteColumn, format],
  );

  const generateFilename = useMemo(() => {
    return generatePdfFilename([
      t("commissioning.commissioning_list_reseller"),
      selectedYear,
      formatWeekLabel(selectedWeek, t),
      formatDayLabel(selectedDay, t),
    ]);
  }, [selectedYear, selectedWeek, selectedDay, t]);

  return (
    <div>
      <h1>{t("commissioning.commissioning_list_reseller")}</h1>
      <MobileStack>
        <WeekSelector
          selectedYear={selectedYear}
          setSelectedYear={setSelectedYear}
          selectedWeek={selectedWeek}
          setSelectedWeek={setSelectedWeek}
        />
        <DaySelector
          selectedDay={selectedDay}
          setSelectedDay={setSelectedDay}
          selectedWeek={selectedWeek!}
          selectedYear={selectedYear}
          days={[0, 1, 2, 3, 4, 5, 6]}
          suffix={t("commissioning.delivery_day")}
          usesDaysWithOrders={true}
          daysWithOrders={daysWithOrders}
        />
      </MobileStack>
      {!isMobile && (
        <div className="section-divider">
          <CommissioningListResellersPDFGenerator
            data={resellers.length > 0 ? resellers : null}
            year={selectedYear}
            week={selectedWeek!}
            dayName={getDayName(selectedDay, t)}
            filename={generateFilename}
            buttonText={t("download.commissioning_list")}
            t={t}
          />
        </div>
      )}
      <div
        style={{ marginTop: isMobile ? "1em" : "4em", marginBottom: "2em" }}
      ></div>
      <div>
        {loadingResellers ? (
          <div className="flex-center">
            <Spin />
          </div>
        ) : ordersFailed ? (
          // A failed load is shown as such, never as a day without orders.
          <Alert
            type="error"
            showIcon
            message={t("table.load_failed_title")}
            description={t("table.load_failed_hint")}
            action={
              <Button size="small" onClick={() => refetchOrders()}>
                {t("table.retry")}
              </Button>
            }
            className="editable-table-banner"
          />
        ) : resellers.length === 0 ? (
          <PastWarningMessage>
            <div style={{ textAlign: "center", padding: "0em" }}>
              {t("commissioning.no_orders_title")}
            </div>
          </PastWarningMessage>
        ) : (
          resellers.map((reseller) => (
            <Card
              key={reseller.id}
              style={{ width: "60%", marginBottom: 16 }}
              // Trim Ant Design's Card chrome on both slots so the
              // pink reseller-card-header chip starts at the same
              // left edge as the table below it. Without this, the
              // header sits inside .ant-card-head's default 24px
              // horizontal padding while the body is at 8px — they
              // look misaligned.
              styles={{
                body: { padding: 8 },
                header: { padding: 8 },
              }}
              title={
                <div className="reseller-card-header">
                  <span>{reseller.name}</span>
                  {reseller.order.note && (
                    <span className="reseller-card-header-note">
                      — {reseller.order.note}
                    </span>
                  )}
                </div>
              }
            >
              {isMobile ? (
                <ResellerOrderMobileCards lines={reseller.order.contents} />
              ) : (
                <Table
                  className="custom-jasmin-table"
                  columns={columns}
                  dataSource={reseller.order.contents}
                  rowKey="id"
                  pagination={false}
                  size="small"
                  locale={{
                    emptyText: (
                      <div style={{ height: "4em" }}>
                        {t("common.no_orders_available")}
                      </div>
                    ),
                  }}
                />
              )}
            </Card>
          ))
        )}
      </div>
      {!isMobile && (
        <ExplainerText title={t("common.info")}>
          {t("explainers.commissioning_lists")}
        </ExplainerText>
      )}
    </div>
  );
}
