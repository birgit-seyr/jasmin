import type { TablePaginationConfig } from "antd";
import { DatePicker, Divider, Switch, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  useCommissioningStorageLoggingList,
  useCommissioningTheoreticalCleanAmountsList,
  useCommissioningTheoreticalHarvestsList,
  useCommissioningTheoreticalPurchaseAmountsList,
  useCommissioningTheoreticalWashAmountsList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningStorageLoggingListParams,
  StorageLoggingEntry,
  TheoreticalCleanAmount,
  TheoreticalHarvest,
  TheoreticalPurchase,
  TheoreticalWashAmount,
} from "@shared/api/generated/models";
import { YearSelector } from '@shared/selectors';
import { ShareArticleSelector, StorageSelector } from '@features/commissioning/selectors';
import { ExplainerText } from "@shared/ui";
import { useDateFormat, useNumberFormat } from '@hooks/index';
import { useAmountUnitSizeColumns } from '@features/commissioning/hooks';

const { RangePicker } = DatePicker;
const currentYear = dayjs().year();

/** One row of the internal-workflow table — whichever theoretical model the
 *  selected source tab queried. */
type WorkflowEntry =
  | TheoreticalHarvest
  | TheoreticalCleanAmount
  | TheoreticalWashAmount
  | TheoreticalPurchase;

export default function LoggingStorage() {
  // Storage Logging State
  const [selectedStorage, setSelectedStorage] = useState<string | null>(null);
  const [selectedShareArticle, setSelectedShareArticle] = useState<
    string | null
  >(null);
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(
    null,
  );

  // Workflow State
  const [selectedYear, setSelectedYear] = useState(currentYear);
  const [selectedWorkflowShareArticle, setSelectedWorkflowShareArticle] =
    useState<string | null>(null);
  const [selectedSource, setSelectedSource] = useState("HARVEST");

  // Hide rows with amount = 0 (default on). One toggle per table — independent.
  const [hideInactiveStorage, setHideInactiveStorage] = useState(true);
  const [hideInactiveWorkflow, setHideInactiveWorkflow] = useState(true);

  const { t } = useTranslation();
  const { dateFormat, formatDate } = useDateFormat();
  const { format } = useNumberFormat();

  const { amountUnitSizeColumns } = useAmountUnitSizeColumns({
    showAmount: false,
    overrides: {
      unit: { width: "5em", align: "center", fixed: false },
      size: { width: "5em", align: "center", fixed: false },
    },
  });

  // Storage Logging via RQ
  const storageLoggingParams: CommissioningStorageLoggingListParams = useMemo(
    () => ({
      storage: selectedStorage ?? "",
      ...(dateRange &&
        dateRange[0] &&
        dateRange[1] && {
          start_date: dateRange[0].format("YYYY-MM-DD"),
          end_date: dateRange[1].format("YYYY-MM-DD"),
        }),
      ...(selectedShareArticle && {
        share_article: selectedShareArticle,
      }),
    }),
    [selectedStorage, dateRange, selectedShareArticle],
  );

  const { data: rawData, isLoading: loading } =
    useCommissioningStorageLoggingList(storageLoggingParams, {
      query: { enabled: !!selectedStorage },
    });
  const data = useMemo(() => {
    const rows: StorageLoggingEntry[] = rawData ?? [];
    if (!hideInactiveStorage) return rows;
    return rows.filter((r) => {
      if (r.amount === null || r.amount === undefined) return true;
      return parseFloat(String(r.amount)) !== 0;
    });
  }, [rawData, hideInactiveStorage]);

  // Workflow via RQ
  const workflowParams = useMemo(
    () => ({
      year: selectedYear,
      ...(selectedWorkflowShareArticle && {
        share_article: selectedWorkflowShareArticle,
      }),
    }),
    [selectedYear, selectedWorkflowShareArticle],
  );

  const { data: harvestData, isLoading: harvestLoading } =
    useCommissioningTheoreticalHarvestsList(workflowParams, {
      query: { enabled: selectedSource === "HARVEST" },
    });
  const { data: cleanData, isLoading: cleanLoading } =
    useCommissioningTheoreticalCleanAmountsList(workflowParams, {
      query: { enabled: selectedSource === "CLEAN" },
    });
  const { data: washData, isLoading: washLoading } =
    useCommissioningTheoreticalWashAmountsList(workflowParams, {
      query: { enabled: selectedSource === "WASH" },
    });
  const { data: purchaseData, isLoading: purchaseLoading } =
    useCommissioningTheoreticalPurchaseAmountsList(workflowParams, {
      query: { enabled: selectedSource === "PURCHASE" },
    });

  // Directional casts at the orval boundary: these endpoints use optional
  // limit/offset pagination — without a ``limit`` param (as here) they return
  // a plain array, not the generated paginated envelope.
  const workflowData = useMemo(() => {
    let rows: WorkflowEntry[];
    switch (selectedSource) {
      case "HARVEST":
        rows = (harvestData ?? []) as unknown as TheoreticalHarvest[];
        break;
      case "CLEAN":
        rows = (cleanData ?? []) as unknown as TheoreticalCleanAmount[];
        break;
      case "WASH":
        rows = (washData ?? []) as unknown as TheoreticalWashAmount[];
        break;
      case "PURCHASE":
        rows = (purchaseData ?? []) as unknown as TheoreticalPurchase[];
        break;
      default:
        rows = [];
    }
    if (hideInactiveWorkflow) {
      rows = rows.filter((r) => {
        if (r.amount === null || r.amount === undefined) return true;
        return parseFloat(String(r.amount)) !== 0;
      });
    }
    return rows;
  }, [
    selectedSource,
    harvestData,
    cleanData,
    washData,
    purchaseData,
    hideInactiveWorkflow,
  ]);

  const workflowLoading =
    selectedSource === "HARVEST"
      ? harvestLoading
      : selectedSource === "CLEAN"
        ? cleanLoading
        : selectedSource === "WASH"
          ? washLoading
          : purchaseLoading;

  const getTypeColor = (type: string) => {
    switch (type) {
      case "STOCK_COUNT":
        return "blue";
      case "HARVEST":
        return "green";
      case "PURCHASE":
        return "cyan";
      case "SHARECONTENT":
        return "red";
      case "ORDERCONTENT":
        return "orange";
      case "WASTE":
        return "volcano";
      case "WASH":
        return "purple";
      case "CLEAN":
        return "magenta";
      default:
        return "default";
    }
  };

  const getTypeLabel = (type: string) => {
    switch (type) {
      case "STOCK_COUNT":
        return t("common.stock_count");
      case "HARVEST":
        return t("common.harvest");
      case "PURCHASE":
        return t("common.purchase");
      case "SHARECONTENT":
        return t("common.share_content");
      case "ORDERCONTENT":
        return t("common.order_content");
      case "WASTE":
        return t("common.waste");
      case "WASH":
        return t("commissioning.washed");
      case "INVENTORY":
        return t("common.inventory");
      case "CLEAN":
        return t("commissioning.cleaned");
      default:
        return type;
    }
  };

  const getWorkflowSourceLabel = (source: string) => {
    switch (source) {
      case "HARVEST":
        return t("commissioning.theoretical_harvests");
      case "CLEAN":
        return t("commissioning.theoretical_clean_amounts");
      case "WASH":
        return t("commissioning.theoretical_wash_amounts");
      case "PURCHASE":
        return t("commissioning.theoretical_purchase_amounts");
      default:
        return source;
    }
  };

  const columns: ColumnsType<StorageLoggingEntry> = [
    {
      title: t("commissioning.date"),
      dataIndex: "date",
      key: "date",
      width: "10em",
      render: (_: unknown, record: StorageLoggingEntry) => {
        if (
          record.year != null &&
          record.delivery_week != null &&
          record.day_number != null
        ) {
          const date = dayjs()
            .year(record.year)
            .isoWeek(record.delivery_week)
            .isoWeekday(record.day_number + 1);
          return formatDate(date);
        }
        return record.date ? formatDate(record.date) : "-";
      },
      sorter: (a: StorageLoggingEntry, b: StorageLoggingEntry) => {
        const dateA =
          a.year != null && a.delivery_week != null && a.day_number != null
            ? dayjs()
                .year(a.year)
                .isoWeek(a.delivery_week)
                .isoWeekday(a.day_number + 1)
            : dayjs(a.date);
        const dateB =
          b.year != null && b.delivery_week != null && b.day_number != null
            ? dayjs()
                .year(b.year)
                .isoWeek(b.delivery_week)
                .isoWeekday(b.day_number + 1)
            : dayjs(b.date);
        return dateA.unix() - dateB.unix();
      },
      defaultSortOrder: "descend",
    },
    {
      title: "",
      dataIndex: "type",
      key: "type",
      width: "9em",
      render: (type: string) => (
        <Tag color={getTypeColor(type)} style={{ fontSize: "9px" }}>
          {getTypeLabel(type)}
        </Tag>
      ),
      filters: [
        { text: t("common.stock_count"), value: "STOCK_COUNT" },
        { text: t("common.harvest"), value: "HARVEST" },
        { text: t("common.purchase"), value: "PURCHASE" },
        { text: t("common.share_content"), value: "SHARECONTENT" },
        { text: t("common.order_content"), value: "ORDERCONTENT" },
        { text: t("common.waste"), value: "WASTE" },
        { text: t("common.washing"), value: "WASH" },
        { text: t("commissioning.cleaned"), value: "CLEAN" },
      ],
      onFilter: (value, record) => record.type === value,
    },
    {
      title: t("commissioning.share_article_name"),
      dataIndex: "share_article_name",
      key: "share_article_name",
      width: "12em",
    },
    {
      title: t("commissioning.amount"),
      dataIndex: "amount",
      key: "amount",
      width: "7em",
      align: "right",
      render: (amount: number | null, record: StorageLoggingEntry) => {
        if (amount === null || amount === undefined) return "-";
        const numAmount = parseFloat(String(amount));
        if (record.type === "STOCK_COUNT") {
          return (
            <span style={{ fontWeight: "bold" }}>{format(numAmount, 2)}</span>
          );
        }
        const isNegative = numAmount < 0;
        return (
          <span className={isNegative ? "text-error" : "text-success"}>
            {numAmount > 0 ? "+" : ""}
            {format(numAmount, 2)}
          </span>
        );
      },
    },
    {
      title: t("commissioning.balance"),
      dataIndex: "running_balance",
      key: "running_balance",
      width: "8em",
      align: "right",
      render: (balance: number | null) => {
        if (balance === null || balance === undefined) return "-";
        const num = parseFloat(String(balance));
        return (
          <span className={num < 0 ? "text-error" : undefined}>
            {format(num, 2)}
          </span>
        );
      },
    },
    // EditableColumnConfig-based unit/size columns reused inside a plain AntD
    // table — structurally compatible cells, widened once at the spread.
    ...(amountUnitSizeColumns as unknown as ColumnsType<StorageLoggingEntry>),
  ];

  const workflowColumns: ColumnsType<WorkflowEntry> = [
    {
      title: t("commissioning.date"),
      dataIndex: "date",
      key: "date",
      width: "12em",
      render: (_: unknown, record: WorkflowEntry) => {
        const day = record.day_number != null ? record.day_number : 1;

        const date = dayjs()
          .year(record.year)
          .isoWeek(record.delivery_week)
          .isoWeekday(day + 1);

        return formatDate(date);
      },
      sorter: (a: WorkflowEntry, b: WorkflowEntry) => {
        const dayA = a.day_number != null ? a.day_number : 1;
        const dayB = b.day_number != null ? b.day_number : 1;
        const dateA = dayjs()
          .year(a.year)
          .isoWeek(a.delivery_week)
          .isoWeekday(dayA + 1);
        const dateB = dayjs()
          .year(b.year)
          .isoWeek(b.delivery_week)
          .isoWeekday(dayB + 1);
        return dateA.unix() - dateB.unix();
      },
      defaultSortOrder: "descend",
    },
    {
      title: "",
      dataIndex: "type",
      key: "type",
      width: "9em",
      render: (_: unknown, record: WorkflowEntry) => {
        // The theoretical models carry no ``type`` field — the tag is only
        // derivable from a linked share/order content. Rows without either
        // link get no tag (previously an empty default Tag).
        const type = record.share_content
          ? "SHARECONTENT"
          : record.order_content
            ? "ORDERCONTENT"
            : null;
        if (!type) return null;
        return (
          <Tag color={getTypeColor(type)} style={{ fontSize: "9px" }}>
            {getTypeLabel(type)}
          </Tag>
        );
      },
    },
    {
      title: t("commissioning.share_article_name"),
      dataIndex: "share_article_name",
      key: "share_article_name",
      width: "12em",
    },
    {
      title: t("commissioning.amount"),
      dataIndex: "amount",
      key: "amount",
      width: "7em",
      align: "right",
      // ``amount`` is a DecimalField — a decimal string on the wire.
      render: (amount: string | null | undefined) => {
        if (amount === null || amount === undefined) return "-";
        return format(parseFloat(amount), 2);
      },
    },
    // EditableColumnConfig-based unit/size columns reused inside a plain AntD
    // table — structurally compatible cells, widened once at the spread.
    ...(amountUnitSizeColumns as unknown as ColumnsType<WorkflowEntry>),
  ];

  const sourceOptions = [
    { value: "HARVEST", label: "HARVEST", color: "green" },
    { value: "CLEAN", label: "CLEAN", color: "magenta" },
    { value: "WASH", label: "WASH", color: "purple" },
    { value: "PURCHASE", label: "PURCHASE", color: "cyan" },
  ];

  const [pageSize, setPageSize] = useState(10);
  const paginationConfig: TablePaginationConfig = {
    pageSize: pageSize,
    showSizeChanger: true,
    pageSizeOptions: ["10", "20", "50", "100", "500"],
    onChange: (_page: number, newPageSize: number) => {
      setPageSize(newPageSize);
    },
    locale: { items_per_page: t("table.items_per_page") },
    position: ["topRight", "bottomRight"],
  };

  const [workflowPageSize, setWorkflowPageSize] = useState(10);
  const workflowPaginationConfig: TablePaginationConfig = {
    pageSize: workflowPageSize,
    showSizeChanger: true,
    pageSizeOptions: ["10", "20", "50", "100", "500"],
    onChange: (_page: number, newPageSize: number) => {
      setWorkflowPageSize(newPageSize);
    },
    locale: { items_per_page: t("table.items_per_page") },
    position: ["topRight", "bottomRight"],
  };

  return (
    <div>
      <h1>{t("commissioning.storage_logging")}</h1>
      <h5>{t("commissioning.storage_logging_explanation")}</h5>

      <div style={{ marginBottom: "1em", marginLeft: "-2em" }}>
        <StorageSelector
          selectedStorage={selectedStorage}
          setSelectedStorage={setSelectedStorage}
        />

        <ShareArticleSelector
          selectedShareArticle={selectedShareArticle}
          setSelectedShareArticle={setSelectedShareArticle}
          include_null_option={true}
        />
        <div style={{ marginTop: "1em", marginLeft: "2em" }}>
          <RangePicker
            value={dateRange}
            onChange={(dates) => {
              if (dates && dates[0] && dates[1]) {
                setDateRange([dates[0], dates[1]]);
              } else {
                setDateRange(null);
              }
            }}
            format={dateFormat}
            size="small"
            placeholder={[t("common.start_date"), t("common.end_date")]}
            style={{
              border: "1px solid #070707ff",
              borderRadius: "4px",
              color: "#070707ff",
            }}
          />
          <span style={{ marginLeft: "1em" }}>
            <Switch
              size="small"
              checked={hideInactiveStorage}
              onChange={setHideInactiveStorage}
            />
            <span style={{ marginLeft: "0.5em" }}>
              {t("commissioning.hide_inactive_rows")}
            </span>
          </span>
        </div>
      </div>

      {selectedStorage && (
        <div className="compact-logging-table">
          <Table
            columns={columns}
            dataSource={data}
            pagination={paginationConfig}
            size="small"
            loading={loading}
            rowKey="id"
            className="w-max"
            locale={{
              emptyText: (
                <div style={{ height: "4em" }}>{t("table.no_data")}</div>
              ),
            }}
          />
        </div>
      )}

      <Divider style={{ margin: "3em 0" }} />

      <h1>{t("commissioning.internal_workflow")}</h1>
      <h5>{t("commissioning.workflow_explanation")}</h5>

      <div style={{ marginBottom: "1em" }}>
        <YearSelector
          selectedYear={selectedYear}
          setSelectedYear={setSelectedYear}
        />

        <ShareArticleSelector
          selectedShareArticle={selectedWorkflowShareArticle}
          setSelectedShareArticle={setSelectedWorkflowShareArticle}
          include_null_option={true}
          preserveSelection={true}
        />
      </div>

      <div style={{ marginBottom: "1em" }}>
        {sourceOptions.map((option) => (
          <Tag
            key={option.value}
            color={selectedSource === option.value ? option.color : "default"}
            style={{
              cursor: "pointer",
              fontSize: "12px",
              padding: "4px 12px",
              marginBottom: "8px",
            }}
            onClick={() => setSelectedSource(option.value)}
          >
            {getWorkflowSourceLabel(option.value)}
          </Tag>
        ))}
        <span style={{ marginLeft: "1em" }}>
          <Switch
            size="small"
            checked={hideInactiveWorkflow}
            onChange={setHideInactiveWorkflow}
          />
          <span style={{ marginLeft: "0.5em" }}>
            {t("commissioning.hide_inactive_rows")}
          </span>
        </span>
      </div>

      <div className="compact-logging-table">
        <Table
          columns={workflowColumns}
          dataSource={workflowData}
          pagination={workflowPaginationConfig}
          size="small"
          loading={workflowLoading}
          rowKey="id"
          className="w-max"
          locale={{
            emptyText: (
              <div style={{ height: "4em" }}>{t("table.no_data")}</div>
            ),
          }}
        />
      </div>

      <ExplainerText title={t("common.info")}>
        {t("explainers.logging_storage")}
        <br />
        <br />
        {t("explainers.workflow")}
      </ExplainerText>
    </div>
  );
}
