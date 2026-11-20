import { Alert, Button, Spin } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useMemo, useState, type Key } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  useCommissioningCommissioningListsResellersList,
  useCommissioningDaysWithOrdersRetrieve,
  useCommissioningLabelTemplatesList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningCommissioningListsResellersListParams,
  CommissioningDaysWithOrdersRetrieveParams,
  CommissioningListResellersEntry,
} from "@shared/api/generated/models";
import { useLabelFarm } from "@features/commissioning/hooks";
import { LabelsPDFGenerator } from "@features/commissioning/pdfs";
import {
  labelAmounts,
  layoutOf,
  withLabelCount,
  type LabelData,
} from "@features/commissioning/utils/labelLayout";
import { openingDeliveryDay } from "@features/commissioning/utils/openingDeliveryDay";
import { orderLineArticleLabel } from "@features/commissioning/utils/orderLineLabel";
import { getSizeLabelOrEmpty } from "@features/commissioning/utils/sizeLabel";
import {
  useDateFormat,
  useUnitOptions,
  useVegetableSizeOptions,
  useYearWeekState,
} from "@hooks/index";
import { useRoles } from "@shared/auth";
import { DaySelector, WeekSelector } from "@shared/selectors";
import { ReadOnlyReportTable } from "@shared/tables";
import { ExplainerText, MobileStack, PastWarningMessage } from "@shared/ui";
import NumberInput from "@shared/ui/NumberInput";
import {
  dateForWeekDayNumber,
  formatDayLabel,
  formatWeekLabel,
  generatePdfFilename,
} from "@shared/utils";

type Reseller = CommissioningListResellersEntry;
type OrderLine = Reseller["order"]["contents"][number];

/** One order line of the day and the amounts of its labels, one per
 *  packing unit. */
interface LabelRow {
  key: string;
  reseller: Reseller;
  line: OrderLine;
  amounts: number[];
}

/** The choices made for one delivery day: which lines print, and how many
 *  labels a line gets where the computed number was changed. */
interface DayChoices {
  day: string;
  selected: string[];
  counts: Record<string, number>;
}

export default function LabelsResellers() {
  const { t } = useTranslation();
  const { isAdmin } = useRoles();

  const [openingDay] = useState(openingDeliveryDay);
  const { selectedYear, setSelectedYear, selectedWeek, setSelectedWeek } =
    useYearWeekState({
      initialYear: openingDay.year,
      initialWeek: openingDay.week,
    });
  const [selectedDay, setSelectedDay] = useState<number | null>(openingDay.day);

  const { getUnitLabel } = useUnitOptions();
  const { getVegetableSizeLabel } = useVegetableSizeOptions();
  const { formatDate } = useDateFormat();
  const { farm, logoUrl, bioLogoUrl, amountText } = useLabelFarm();

  const listParams = useMemo<CommissioningCommissioningListsResellersListParams>(
    () => ({
      year: selectedYear,
      delivery_week: selectedWeek,
      day_number: selectedDay!,
    }),
    [selectedYear, selectedWeek, selectedDay],
  );
  const daysParams = useMemo<CommissioningDaysWithOrdersRetrieveParams>(
    () => ({ year: selectedYear, delivery_week: selectedWeek }),
    [selectedYear, selectedWeek],
  );

  const {
    data: resellersData,
    isLoading: loadingOrders,
    isError: ordersFailed,
    refetch: refetchOrders,
  } = useCommissioningCommissioningListsResellersList(listParams, {
    query: { enabled: selectedWeek != null && selectedDay != null },
  });
  const { data: daysData } = useCommissioningDaysWithOrdersRetrieve(daysParams, {
    query: { enabled: selectedWeek != null },
  });
  const {
    data: templates,
    isLoading: loadingTemplate,
    isError: templateFailed,
  } = useCommissioningLabelTemplatesList();
  const layout = useMemo(
    () => (templates?.[0] ? layoutOf(templates[0]) : null),
    [templates],
  );

  const rows = useMemo<LabelRow[]>(
    () =>
      (resellersData ?? []).flatMap((reseller) =>
        reseller.order.contents.map((line) => ({
          key: line.id,
          reseller,
          line,
          amounts: labelAmounts(Number(line.amount), Number(line.amount_per_pu)),
        })),
      ),
    [resellersData],
  );

  // Kept per delivery day: another day starts with nothing chosen.
  const day = `${selectedYear}-${selectedWeek}-${selectedDay}`;
  const [choices, setChoices] = useState<DayChoices>({
    day,
    selected: [],
    counts: {},
  });
  const current = choices.day === day ? choices : { day, selected: [], counts: {} };
  const countOf = useCallback(
    (row: LabelRow) => current.counts[row.key] ?? null,
    [current.counts],
  );
  // A cleared count goes back to one label per packing unit.
  const setCount = (row: LabelRow, count: number | null) => {
    const counts = Object.fromEntries(
      Object.entries(current.counts).filter(([key]) => key !== row.key),
    );
    setChoices({
      ...current,
      counts: count === null ? counts : { ...counts, [row.key]: count },
    });
  };
  const setSelected = (keys: Key[]) =>
    setChoices({ ...current, selected: keys.map(String) });
  // A line ticked before the list reloaded without it is no longer chosen.
  const selected = useMemo(
    () => current.selected.filter((key) => rows.some((row) => row.key === key)),
    [current.selected, rows],
  );

  const [startPosition, setStartPosition] = useState(1);

  const deliveryDate =
    selectedDay !== null
      ? (formatDate(dateForWeekDayNumber(selectedYear, selectedWeek, selectedDay)) ??
        "")
      : "";

  const labels = useMemo<LabelData[]>(() => {
    const printed = selected.length
      ? rows.filter((row) => selected.includes(row.key))
      : rows;
    return printed.flatMap((row) => {
      const { reseller, line } = row;
      const amounts = withLabelCount(
        row.amounts,
        countOf(row),
        Number(line.amount_per_pu),
      );
      return amounts.map((amount) => ({
        resellerName: reseller.name,
        resellerAddress: reseller.address,
        resellerCity: `${reseller.zip_code} ${reseller.city}`.trim(),
        article: line.share_article_name,
        isOrganic: line.organic_status === "organic",
        isCertified:
          line.organic_status === "organic" ||
          line.organic_status === "in_conversion",
        sort: line.sort ?? "",
        size: getSizeLabelOrEmpty(line.size, getVegetableSizeLabel),
        amountPerPu: amountText(amount, getUnitLabel(line.unit)),
        deliveryDate,
        orderNumber: reseller.order.number ?? "",
      }));
    });
  }, [
    rows,
    selected,
    countOf,
    getVegetableSizeLabel,
    getUnitLabel,
    amountText,
    deliveryDate,
  ]);

  const columns: ColumnsType<LabelRow> = [
    {
      title: t("commissioning.reseller"),
      key: "reseller",
      align: "left",
      render: (_, row) => row.reseller.name,
    },
    {
      title: t("commissioning.share_article"),
      key: "article",
      align: "left",
      render: (_, row) => orderLineArticleLabel(row.line, getVegetableSizeLabel),
    },
    {
      title: t("commissioning.per_pu"),
      key: "per_pu",
      align: "center",
      render: (_, row) =>
        Number(row.line.amount_per_pu) > 0
          ? amountText(Number(row.line.amount_per_pu), getUnitLabel(row.line.unit))
          : "-",
    },
    {
      title: t("commissioning.labels.count"),
      key: "count",
      align: "center",
      width: "10em",
      render: (_, row) => (
        <NumberInput
          min={0}
          max={999}
          precision={0}
          value={countOf(row) ?? row.amounts.length}
          onChange={(value) => setCount(row, value)}
          aria-label={t("commissioning.labels.count_of", {
            article: row.line.share_article_name,
            reseller: row.reseller.name,
          })}
        />
      ),
    },
  ];

  const filename = generatePdfFilename([
    t("commissioning.labels.page_title"),
    selectedYear,
    formatWeekLabel(selectedWeek, t),
    formatDayLabel(selectedDay, t),
  ]);

  return (
    <div>
      <h1>{t("commissioning.labels.page_title")}</h1>
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
          selectedWeek={selectedWeek}
          selectedYear={selectedYear}
          days={[0, 1, 2, 3, 4, 5, 6]}
          suffix={t("commissioning.delivery_day")}
          usesDaysWithOrders={true}
          daysWithOrders={daysData?.days ?? []}
        />
      </MobileStack>

      {templateFailed ? (
        // A failed load is shown as such, never as a farm without a template.
        <Alert
          type="error"
          showIcon
          className="labels-page__hint"
          message={t("table.load_failed_title")}
          description={t("table.load_failed_hint")}
        />
      ) : !loadingTemplate && layout === null && (
        <Alert
          type="info"
          showIcon
          className="labels-page__hint"
          message={t("commissioning.labels.no_template")}
          action={
            isAdmin ? (
              <Link to="/configuration/labels">
                {t("commissioning.labels.to_editor")}
              </Link>
            ) : undefined
          }
        />
      )}

      <div className="section-divider labels-page__actions">
        <LabelsPDFGenerator
          layout={layout}
          labels={labels}
          farm={farm}
          logoUrl={logoUrl}
          bioLogoUrl={bioLogoUrl}
          startPosition={startPosition}
          filename={filename}
          buttonText={t("download.selected_labels")}
        />
        {layout?.printMode === "sheet" && (
          <label className="labels-page__start">
            {t("commissioning.labels.start_position")}
            <NumberInput
              aria-label={t("commissioning.labels.start_position")}
              min={1}
              max={layout.sheet.columns * layout.sheet.rows}
              precision={0}
              value={startPosition}
              onChange={(value) => setStartPosition(value ?? 1)}
            />
          </label>
        )}
        <span className="text-bold">
          {t("commissioning.sum_labels")}: {labels.length}
        </span>
      </div>

      {loadingOrders ? (
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
      ) : rows.length === 0 ? (
        <PastWarningMessage>
          <div className="text-center p-0">{t("commissioning.no_orders_title")}</div>
        </PastWarningMessage>
      ) : (
        <ReadOnlyReportTable
          className="w-max custom-jasmin-table"
          columns={columns}
          dataSource={rows}
          rowKey="key"
          pagination={false}
          rowSelection={{
            selectedRowKeys: selected,
            onChange: setSelected,
          }}
        />
      )}

      <ExplainerText title={t("common.info")}>
        {t("explainers.labels_resellers")}
      </ExplainerText>
    </div>
  );
}
