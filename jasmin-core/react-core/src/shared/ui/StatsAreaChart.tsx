import { theme } from "antd";
import type { ReactNode } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import EmptyHint from "./EmptyHint";

export interface StatsAreaSeries {
  /** Data-row key holding this series' value. */
  id: string;
  /** Legend / tooltip name (already translated). */
  label: string;
  /** Stroke + gradient-fill colour. */
  color: string;
}

interface StatsAreaChartProps {
  /** Rows keyed by `xKey` + each series id. */
  data: Array<Record<string, string | number>>;
  series: StatsAreaSeries[];
  /** X-axis category key (default "label"). */
  xKey?: string;
  height?: number;
  /** Shown when there is no non-zero data. */
  emptyText: ReactNode;
  /** Force the legend; defaults to showing it only for ≥ 2 series. */
  showLegend?: boolean;
}

/**
 * Shared monthly area chart for the member + subscription dashboards: one
 * gradient-filled area per series (`0.28 → 0.02` opacity), recessive
 * token-coloured grid/axes, a crosshair tooltip, and a legend for ≥ 2 series.
 * Members pass a single series; abos pass one per share-type variation.
 */
export default function StatsAreaChart({
  data,
  series,
  xKey = "label",
  height = 300,
  emptyText,
  showLegend,
}: StatsAreaChartProps) {
  const { token } = theme.useToken();

  const hasData =
    series.length > 0 &&
    data.some((d) => series.some((s) => Number(d[s.id] ?? 0) !== 0));

  if (!hasData) {
    return <EmptyHint style={{ padding: "2em 0" }}>{emptyText}</EmptyHint>;
  }

  const axisTick = { fill: token.colorTextSecondary, fontSize: 12 };
  const gridStroke = token.colorBorderSecondary;
  const tooltipStyle = {
    background: token.colorBgElevated,
    border: `1px solid ${token.colorBorderSecondary}`,
    borderRadius: token.borderRadius,
    boxShadow: token.boxShadowSecondary,
  } as const;
  const tooltipText = { color: token.colorText };
  const withLegend = showLegend ?? series.length > 1;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
        <defs>
          {series.map((s) => (
            <linearGradient
              key={s.id}
              id={`sac-${s.id}`}
              x1="0"
              y1="0"
              x2="0"
              y2="1"
            >
              <stop offset="0%" stopColor={s.color} stopOpacity={0.28} />
              <stop offset="100%" stopColor={s.color} stopOpacity={0.02} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid
          strokeDasharray="3 3"
          stroke={gridStroke}
          vertical={false}
        />
        <XAxis
          dataKey={xKey}
          tick={axisTick}
          axisLine={{ stroke: gridStroke }}
          tickLine={false}
          minTickGap={16}
        />
        <YAxis
          tick={axisTick}
          axisLine={false}
          tickLine={false}
          width={40}
          allowDecimals={false}
        />
        <Tooltip
          contentStyle={tooltipStyle}
          labelStyle={tooltipText}
          itemStyle={tooltipText}
        />
        {withLegend && <Legend />}
        {series.map((s) => (
          <Area
            key={s.id}
            type="monotone"
            dataKey={s.id}
            name={s.label}
            stroke={s.color}
            strokeWidth={2}
            fill={`url(#sac-${s.id})`}
            dot={false}
            activeDot={{ r: 4 }}
          />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  );
}
