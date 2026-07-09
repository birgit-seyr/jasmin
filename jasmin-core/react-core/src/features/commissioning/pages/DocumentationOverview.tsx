import {
  useAmountUnitSizeColumns,
  useShareArticleColumn,
} from "@features/commissioning/hooks";
import { ShareArticleSelector } from "@features/commissioning/selectors";
import { useCommissioningDocumentationOverviewList } from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningDocumentationOverviewListParams,
  CommissioningDocumentationOverviewListSource,
  DocumentationAggregationItem,
} from "@shared/api/generated/models";
import { DaySelector, WeekSelector } from "@shared/selectors";
import { EditableTable, READ_ONLY_PERMISSION } from "@shared/tables";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { ExplainerText } from "@shared/ui";
import { Select } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { currentWeek, useYearWeekState } from "@hooks/index";

// The aggregation rows carry no server id (grouped by article/size/unit), so a
// stable synthetic key is minted per row for the table.
type DocumentationRow = DocumentationAggregationItem & TableRecord;

export default function DocumentationOverview() {
  const { selectedYear, setSelectedYear, selectedWeek, setSelectedWeek } =
    useYearWeekState();
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

  const { data: rawData, isFetching } =
    useCommissioningDocumentationOverviewList(params, {
      query: { enabled: !!selectedShareArticle },
    });

  const data = useMemo<DocumentationRow[]>(
    () =>
      (rawData ?? []).map((item, index) => ({
        ...item,
        id: String(index),
        key: String(index),
      })),
    [rawData],
  );

  const columns: EditableColumnConfig<TableRecord>[] = [
    shareArticleColumn,
    ...amountUnitSizeColumns,
  ];

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
      <EditableTable
        columns={columns}
        initialData={data}
        loading={isFetching}
        permissions={READ_ONLY_PERMISSION}
        pagination={false}
        className="custom-jasmin-table w-max"
      />

      <ExplainerText title={t("common.info")}>
        {t("explainers.documentation_overview")}
      </ExplainerText>
    </div>
  );
}
