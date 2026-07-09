import { Card, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  useCommissioningCommissioningListsList,
  useCommissioningDaysWithOrdersRetrieve,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningCommissioningListsListParams,
  CommissioningDaysWithOrdersRetrieveParams,
  CommissioningListEntry,
} from "@shared/api/generated/models";
import { PastWarningMessage } from "@shared/ui";
import { CommissioningListResellersPDFGenerator } from "@features/commissioning/pdfs";
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
} from "@shared/utils";

const currentDay = dayjs().isoWeekday();

// Derived straight from the generated client — the ``commissioning_lists``
// endpoint is fully serializer-typed, so there's no parallel interface to keep
// in sync (a hand-written one silently drifts: e.g. ``amount`` is ``number``
// here, and ``unit`` is nullable, both of which the old interface got wrong).
type Reseller = CommissioningListEntry;
type OrderContent = Reseller["order"]["contents"][number];

export default function CommissioningListResellers() {
  const { t } = useTranslation();

  const { selectedYear, setSelectedYear, selectedWeek, setSelectedWeek } =
    useYearWeekState();
  const [selectedDay, setSelectedDay] = useState<number | null>(
    currentDay === 5 || currentDay === 6 ? 0 : currentDay - 1,
  );

  const { getUnitLabel } = useUnitOptions();
  const { getVegetableSizeLabel } = useVegetableSizeOptions();
  const { format } = useNumberFormat();
  const isMobile = useIsMobile();

  const listParams = useMemo<CommissioningCommissioningListsListParams>(
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

  const { data: resellersData, isLoading: loadingResellers } =
    useCommissioningCommissioningListsList(listParams, {
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

  const resellers = resellersData ?? [];
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
        render: (_, record) => (
          <>
            {record.share_article_name} {record.sort}
            {record.size && record.size !== "M" && (
              <>, {getVegetableSizeLabel(record.size)}</>
            )}
          </>
        ),
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
        {resellers.length === 0 && !loadingResellers ? (
          <PastWarningMessage>
            <div style={{ textAlign: "center", padding: "0em" }}>
              {t("commissioning.no_orders_title")}
            </div>
          </PastWarningMessage>
        ) : (
          resellers
            .filter((reseller) => reseller.order?.contents?.length ?? 0 > 0)
            .map((reseller) => (
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
                    {reseller.order?.note && (
                      <span className="reseller-card-header-note">
                        — {reseller.order.note}
                      </span>
                    )}
                  </div>
                }
              >
                {isMobile ? (
                  <div
                    className="flex-col gap-8"
                    style={{
                      marginTop: -8,
                    }}
                  >
                    {(reseller.order?.contents ?? []).map((item) => {
                      const amount = Number(item.amount);
                      const amountPerPu = Number(item.amount_per_pu);
                      const puCount =
                        !isNaN(amount) && !isNaN(amountPerPu) && amountPerPu > 0
                          ? format(amount / amountPerPu, 1)
                          : null;
                      const formattedAmount = !isNaN(amount)
                        ? format(amount, 1)
                        : "-";
                      const unitLabel = getUnitLabel(item.unit);
                      const sizeLabel =
                        item.size && item.size !== "M"
                          ? getVegetableSizeLabel(item.size)
                          : "";

                      return (
                        <div
                          key={item.share_article_id}
                          className="mobile-card-item"
                          style={{ cursor: "default" }}
                        >
                          <div className="mobile-card-content flex-min">
                            <div className="mobile-card-title">
                              {item.share_article_name}
                              {sizeLabel && (
                                <span className="text-hint">{sizeLabel}</span>
                              )}
                            </div>
                            <div
                              style={{ display: "flex", gap: 24, marginTop: 6 }}
                            >
                              <div>
                                <div className="text-muted-xs">
                                  {t("commissioning.amount")}
                                </div>
                                <div className="flex-baseline">
                                  <span
                                    style={{
                                      fontWeight: 600,
                                      fontSize: "1.2em",
                                    }}
                                  >
                                    {formattedAmount}
                                  </span>
                                  {unitLabel && (
                                    <span className="text-secondary">
                                      {unitLabel}
                                    </span>
                                  )}
                                </div>
                              </div>
                              {puCount && (
                                <div>
                                  <div className="text-muted-xs">
                                    {t("commissioning.pu")}
                                  </div>
                                  <div className="flex-baseline">
                                    <span
                                      style={{
                                        fontWeight: 500,
                                        fontSize: "1.2em",
                                      }}
                                    >
                                      {puCount}
                                    </span>
                                    <span className="text-secondary">
                                      ({format(Number(item.amount_per_pu), 2)}{" "}
                                      {unitLabel}/{t("commissioning.pu")})
                                    </span>
                                  </div>
                                </div>
                              )}
                            </div>
                            {item.note && (
                              <div className="text-meta">{item.note}</div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <Table
                    className="custom-jasmin-table"
                    columns={columns}
                    dataSource={reseller.order?.contents}
                    rowKey="share_article_id"
                    loading={loadingResellers}
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
