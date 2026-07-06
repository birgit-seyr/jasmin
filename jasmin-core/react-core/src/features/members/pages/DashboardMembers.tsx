import { Card, DatePicker, Spin, Typography } from "antd";
import dayjs from "dayjs";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useCommissioningMemberGrowthStatisticsList } from "@shared/api/generated/commissioning/commissioning";
import { StatsAreaChart, type StatsAreaSeries } from "@shared/ui";
import {
  useDateFormat,
  useDateRangePresets,
  useFiscalYearRangeState,
} from "@hooks/index";

const { RangePicker } = DatePicker;
const { Text } = Typography;

export default function DashboardMembers() {
  const { t } = useTranslation();
  const { dateFormat } = useDateFormat();
  const presets = useDateRangePresets();

  // Default window: the tenant's current fiscal year (1st of
  // ``fiscal_year_start_month`` → one year).
  const [range, setRange] = useFiscalYearRangeState();

  const { data: growth, isLoading: growthLoading } =
    useCommissioningMemberGrowthStatisticsList({ period: "month" });

  const growthSeries = useMemo(() => {
    const raw = (growth ?? [])
      .map((row) => ({
        ms: dayjs(row.period).startOf("month").valueOf(),
        total: row.total_members,
      }))
      .sort((a, b) => a.ms - b.ms);

    // Continuous monthly buckets across the window, ALWAYS spanning at least
    // one year (12 months) ending at the range end. total_members is cumulative,
    // so months without a data point carry the previous total forward.
    const end = (range ? range[1] : dayjs()).startOf("month");
    const selStart = (range ? range[0] : dayjs().subtract(1, "year")).startOf(
      "month",
    );
    const minStart = end.subtract(11, "month");
    let cursor = selStart.isBefore(minStart) ? selStart : minStart;

    const byMonth = new Map(raw.map((r) => [r.ms, r.total]));
    // Baseline: the last known cumulative total at or before the window start.
    let running = 0;
    for (const r of raw) {
      if (r.ms <= cursor.valueOf()) running = r.total;
      else break;
    }

    const out: Array<Record<string, string | number>> = [];
    while (!cursor.isAfter(end)) {
      const hit = byMonth.get(cursor.valueOf());
      if (hit !== undefined) running = hit;
      out.push({ label: cursor.format("MMM 'YY"), members: running });
      cursor = cursor.add(1, "month");
    }
    return out;
  }, [growth, range]);

  const series: StatsAreaSeries[] = [
    {
      id: "members",
      label: t("statistics.series_members"),
      color: "var(--color-success)",
    },
  ];

  return (
    <div>
      <Spin spinning={growthLoading}>
        <h1>{t("statistics.members_title")}</h1>
        <RangePicker
          value={range}
          onChange={(v) => setRange(v && v[0] && v[1] ? [v[0], v[1]] : null)}
          presets={presets}
          format={dateFormat}
          allowClear={false}
        />
        <Card
          className="dark-green-border"
          title={t("statistics.chart_members_over_time")}
          style={{ marginTop: "1em" }}
        >
          <StatsAreaChart
            data={growthSeries}
            series={series}
            emptyText={t("statistics.no_member_data")}
          />
        </Card>
      </Spin>
    </div>
  );
}
