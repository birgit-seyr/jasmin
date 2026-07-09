import {
  useAmountUnitSizeColumns,
  useShareArticleColumn,
} from "@features/commissioning/hooks";
import { ShareArticleSelector } from "@features/commissioning/selectors";
import { useCommissioningDocumentationOverviewList } from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningDocumentationOverviewListParams,
  CommissioningDocumentationOverviewListSource,
} from "@shared/api/generated/models";
import { DaySelector, WeekSelector } from "@shared/selectors";
import { EmptyHint, ExplainerText } from "@shared/ui";
import { Select, Table } from "antd";
import dayjs from "dayjs";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

const currentYear = dayjs().year();
const currentWeek = dayjs().isoWeek();

export default function DocumentationOverview() {
  const [selectedYear, setSelectedYear] = useState(currentYear);
  const [selectedWeek, setSelectedWeek] = useState<number | null>(currentWeek);
  const [selectedDay, setSelectedDay] = useState<number | null>(null);
  const [selectedShareArticle, setSelectedShareArticle] = useState<
    string | null
  >(null);
  const [selectedSource, setSelectedSource] =
    useState<CommissioningDocumentationOverviewListSource>("HARVEST");

  const { shareArticleColumn } = useShareArticleColumn();
  const { amountUnitSizeColumns } = useAmountUnitSizeColumns({
    showAmount: true,
  });

  const { t } = useTranslation();

  const params: CommissioningDocumentationOverviewListParams = {
    year: selectedYear,
    delivery_week: selectedWeek ?? undefined,
    share_article: selectedShareArticle ?? "",
    source: selectedSource,
    ...(selectedDay != null ? { delivery_day: String(selectedDay) } : {}),
  };

  const { data: rawData, isLoading: loading } =
    useCommissioningDocumentationOverviewList(params, {
      query: { enabled: !!selectedShareArticle },
    });

  const data = useMemo(() => rawData ?? [], [rawData]);

  const columns: any[] = [shareArticleColumn, ...amountUnitSizeColumns];

  const sourceOptions = [
    { value: "HARVEST", label: t("commissioning.harvest_select") },
    {
      value: "PURCHASE",
      label: t("commissioning.purchase_select"),
    },
    { value: "WASTE", label: t("commissioning.waste_select") },
  ];

  return (
    <div>
      <h1>{t("commissioning.documentation_overview")}</h1>

      <WeekSelector
        selectedYear={selectedYear}
        setSelectedYear={setSelectedYear}
        selectedWeek={selectedWeek}
        setSelectedWeek={setSelectedWeek}
        include_null_option={true}
      />
      <DaySelector
        selectedDay={selectedDay}
        setSelectedDay={setSelectedDay}
        selectedWeek={selectedWeek ?? currentWeek}
        selectedYear={selectedYear}
        days={[0, 1, 2, 3, 4, 5, 6]}
        include_null_option={true}
      />
      <div style={{ marginTop: "1em", marginBottom: "1em" }}>
        <ShareArticleSelector
          selectedShareArticle={selectedShareArticle}
          setSelectedShareArticle={setSelectedShareArticle}
          preserveSelection={true}
        />
      </div>
      <div style={{ marginTop: "1em", marginBottom: "1em" }}>
        <Select
          value={selectedSource}
          style={{ width: "12em" }}
          size="small"
          onChange={(val) =>
            setSelectedSource(
              val as CommissioningDocumentationOverviewListSource,
            )
          }
          options={sourceOptions}
          className="bold-select"
        />
      </div>
      <Table
        columns={columns}
        dataSource={data}
        pagination={false}
        loading={loading}
        size="small"
        className="custom-jasmin-table w-max"
        rowKey="id"
        locale={{ emptyText: <EmptyHint>{t("table.no_data")}</EmptyHint> }}
      />

      <ExplainerText title={t("common.info")}>
        {t("explainers.documentation_overview")}
      </ExplainerText>
    </div>
  );
}
