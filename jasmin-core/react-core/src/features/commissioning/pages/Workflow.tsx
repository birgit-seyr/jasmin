import type { TablePaginationConfig } from "antd";
import { Table, Tag } from "antd";
import dayjs from "dayjs";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  useCommissioningTheoreticalCleanAmountsList,
  useCommissioningTheoreticalHarvestsList,
  useCommissioningTheoreticalPurchaseAmountsList,
  useCommissioningTheoreticalWashAmountsList,
} from "@shared/api/generated/commissioning/commissioning";
// All four `useCommissioningTheoretical*List` hooks accept structurally the
// same `{ year?: number; share_article?: string }` shape — typing once via
// the harvest variant is fine for all of them.
import type { CommissioningTheoreticalHarvestsListParams } from "@shared/api/generated/models";
import { YearSelector } from '@shared/selectors';
import { ShareArticleSelector } from '@features/commissioning/selectors';
import { ExplainerText } from "@shared/ui";
import { useDateFormat } from '@hooks/index';
import { useAmountUnitSizeColumns, useShareArticleColumn } from '@features/commissioning/hooks';

const currentYear = dayjs().year();

type SourceType = "HARVEST" | "CLEAN" | "WASH" | "PURCHASE";

interface WorkflowRecord {
  id?: string | number;
  day_number?: number;
  year: number;
  delivery_week: number;
  [key: string]: unknown;
}

export default function Workflow() {
  const [selectedYear, setSelectedYear] = useState(currentYear);
  const [selectedShareArticle, setSelectedShareArticle] = useState<
    string | null
  >(null);
  const [selectedSource, setSelectedSource] = useState<SourceType>("HARVEST");

  const { formatDate } = useDateFormat();
  const { shareArticleColumn } = useShareArticleColumn();
  const { amountUnitSizeColumns } = useAmountUnitSizeColumns({
    showAmount: true,
  });

  const { t } = useTranslation();

  const listParams = useMemo<CommissioningTheoreticalHarvestsListParams>(
    () => ({
      year: selectedYear,
      ...(selectedShareArticle
        ? { share_article: selectedShareArticle }
        : {}),
    }),
    [selectedYear, selectedShareArticle],
  );

  const { data: harvestData, isLoading: harvestLoading } =
    useCommissioningTheoreticalHarvestsList(listParams, {
      query: { enabled: selectedSource === "HARVEST" },
    });
  const { data: cleanData, isLoading: cleanLoading } =
    useCommissioningTheoreticalCleanAmountsList(listParams, {
      query: { enabled: selectedSource === "CLEAN" },
    });
  const { data: washData, isLoading: washLoading } =
    useCommissioningTheoreticalWashAmountsList(listParams, {
      query: { enabled: selectedSource === "WASH" },
    });
  const { data: purchaseData, isLoading: purchaseLoading } =
    useCommissioningTheoreticalPurchaseAmountsList(listParams, {
      query: { enabled: selectedSource === "PURCHASE" },
    });

  const data = useMemo(() => {
    switch (selectedSource) {
      case "HARVEST":
        return (harvestData ?? []) as unknown as WorkflowRecord[];
      case "CLEAN":
        return (cleanData ?? []) as unknown as WorkflowRecord[];
      case "WASH":
        return (washData ?? []) as unknown as WorkflowRecord[];
      case "PURCHASE":
        return (purchaseData ?? []) as unknown as WorkflowRecord[];
      default:
        return [];
    }
  }, [selectedSource, harvestData, cleanData, washData, purchaseData]);

  const loading =
    selectedSource === "HARVEST"
      ? harvestLoading
      : selectedSource === "CLEAN"
        ? cleanLoading
        : selectedSource === "WASH"
          ? washLoading
          : purchaseLoading;

  const _getSourceColor = (source: SourceType) => {
    switch (source) {
      case "HARVEST":
        return "green";
      case "CLEAN":
        return "magenta";
      case "WASH":
        return "purple";
      case "PURCHASE":
        return "cyan";
      default:
        return "default";
    }
  };

  const getSourceLabel = (source: SourceType) => {
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

  const columns: any[] = [
    {
      title: t("commissioning.date"),
      dataIndex: "date",
      key: "date",
      width: "12em",
      render: (_: unknown, record: WorkflowRecord) => {
        const day = record.day_number != null ? record.day_number : 1;

        const date = dayjs()
          .year(record.year)
          .isoWeek(record.delivery_week)
          .isoWeekday(day + 1);

        return formatDate(date);
      },
    },
    shareArticleColumn,
    ...amountUnitSizeColumns,
  ];

  const sourceOptions: { value: SourceType; label: string; color: string }[] = [
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

  return (
    <div>
      <h1>{t("commissioning.internal_workflow")}</h1>

      <div style={{ marginBottom: "1em" }}>
        <YearSelector
          selectedYear={selectedYear}
          setSelectedYear={setSelectedYear}
        />
        <div style={{ marginTop: "1em" }}>
          <ShareArticleSelector
            selectedShareArticle={selectedShareArticle}
            setSelectedShareArticle={setSelectedShareArticle}
            include_null_option={true}
            preserveSelection={true}
          />
        </div>
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
            {getSourceLabel(option.value)}
          </Tag>
        ))}
      </div>

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

      <ExplainerText title={t("common.info")}>
        {t("explainers.workflow")}
      </ExplainerText>
    </div>
  );
}
