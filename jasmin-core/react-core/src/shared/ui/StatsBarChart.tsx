import { theme } from "antd";
import type { ReactElement, ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Rectangle,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { BarShapeProps } from "recharts";
import EmptyHint from "./EmptyHint";

// Height of the dark-grey stub drawn for a zero-value bar, so an empty period
// stays visible on the baseline instead of leaving a blank gap.
const EMPTY_BAR_STUB_PX = 3;

/** Bar renderer that draws zero-value bars as a short dark-grey stub at the
 *  baseline and everything else as the normal rounded-top bar. */
const makeBarShape =
  (emptyFill: string) =>
  (props: BarShapeProps): ReactElement => {
    const raw = props.value;
    const numeric = Array.isArray(raw) ? raw[1] - raw[0] : raw;
    if (!numeric) {
      const baselineY = props.y ?? 0;
      return (
        <Rectangle
          {...props}
          y={baselineY - EMPTY_BAR_STUB_PX}
          height={EMPTY_BAR_STUB_PX}
          fill={emptyFill}
          radius={0}
        />
      );
    }
    return <Rectangle {...props} radius={[4, 4, 0, 0]} />;
  };

export interface StatsBarSeries {
  /** Data-row key holding this series' value. */
  id: string;
  /** Legend / tooltip name (already translated). */
  label: string;
  /** Bar fill colour. */
  color: string;
}

interface StatsBarChartProps {
  /** Rows keyed by `xKey` + each series id. */
  data: Array<Record<string, string | number>>;
  series: StatsBarSeries[];
  /** X-axis category key (default "label"). */
  xKey?: string;
  height?: number;
  /** Shown when there is no non-zero data. */
  emptyText: ReactNode;
  /** Force the legend; defaults to showing it only for ≥ 2 series. */
  showLegend?: boolean;
  /** Formats bar values for the tooltip (e.g. currency). Raw number by default. */
  valueFormatter?: (value: number) => string;
  /** Draw zero-value bars as a short dark-grey baseline stub instead of nothing,
   *  so empty periods stay visible. Off by default. */
  showEmptyBars?: boolean;
  /** Render the x-axis label of "empty" rows (every series 0) in a lighter grey
   *  than the normal tick colour — e.g. weeks with no spend. */
  muteEmptyLabels?: boolean;
  /** Force every category tick to render (recharts thins them by default). Use
   *  when each label matters (e.g. every ISO week). */
  showAllXLabels?: boolean;
  /** Accessible name for the chart. recharts marks the SVG as a focusable
   *  ``role="application"`` widget; without this it has no name. Also used as
   *  the caption of the visually-hidden data table. */
  ariaLabel?: string;
  /** Header for the category column of the visually-hidden data table
   *  (e.g. "Week"). Defaults to ``xKey``. */
  xHeader?: string;
}

/**
 * Shared discrete bar chart — a sum-per-bucket companion to {@link StatsAreaChart}.
 * Use it for summed, non-continuous quantities (money spent per week, counts per
 * period) where each bar is an independent total, not a point on a trend line.
 * Rounded bar tops, recessive token-coloured grid/axes, a per-bar hover tooltip,
 * and a legend only for ≥ 2 series (a single series is named by the card title).
 */
export default function StatsBarChart({
  data,
  series,
  xKey = "label",
  height = 300,
  emptyText,
  showLegend,
  valueFormatter,
  showEmptyBars = false,
  muteEmptyLabels = false,
  showAllXLabels = false,
  ariaLabel,
  xHeader,
}: StatsBarChartProps) {
  const { token } = theme.useToken();

  const hasData =
    series.length > 0 &&
    data.some((d) => series.some((s) => Number(d[s.id] ?? 0) !== 0));

  if (!hasData) {
    return <EmptyHint style={{ padding: "2em 0" }}>{emptyText}</EmptyHint>;
  }

  const axisTick = { fill: token.colorText, fontSize: 12 };
  const gridStroke = token.colorBorderSecondary;
  const tooltipStyle = {
    background: token.colorBgElevated,
    border: `1px solid ${token.colorBorderSecondary}`,
    borderRadius: token.borderRadius,
    boxShadow: token.boxShadowSecondary,
  } as const;
  const tooltipText = { color: token.colorText };
  const withLegend = showLegend ?? series.length > 1;

  // Empty bars: a dark-grey baseline stub. Empty x-labels: a lighter grey.
  const emptyBarShape = showEmptyBars
    ? makeBarShape(token.colorTextTertiary)
    : undefined;

  // x-values whose every series value is 0 — their axis labels render one step
  // greyer (colorTextSecondary vs the normal colorText) so an empty period
  // (e.g. a delivery-exception week) reads as de-emphasised while STILL meeting
  // the 4.5:1 text-contrast minimum. Null when the feature is off (default tick
  // object).
  const emptyXValues = muteEmptyLabels
    ? new Set(
        data
          .filter((d) => series.every((s) => Number(d[s.id] ?? 0) === 0))
          .map((d) => d[xKey]),
      )
    : null;

  const renderMutedTick = (tickProps: {
    x?: string | number;
    y?: string | number;
    payload?: { value?: string | number };
  }): ReactElement => {
    const value = tickProps.payload?.value;
    const muted = emptyXValues?.has(value as string | number) ?? false;
    return (
      <text
        x={tickProps.x}
        y={tickProps.y}
        dy={12}
        textAnchor="middle"
        fontSize={12}
        fill={muted ? token.colorTextSecondary : token.colorText}
      >
        {value}
      </text>
    );
  };

  return (
    <>
      {/* Visually-hidden text equivalent so the per-bucket figures are
          available to screen readers, not only as visual bars / hover. */}
      <table className="sr-only">
        {ariaLabel ? <caption>{ariaLabel}</caption> : null}
        <thead>
          <tr>
            <th scope="col">{xHeader ?? xKey}</th>
            {series.map((s) => (
              <th key={s.id} scope="col">
                {s.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, index) => (
            <tr key={String(row[xKey] ?? index)}>
              <th scope="row">{String(row[xKey] ?? "")}</th>
              {series.map((s) => {
                const value = Number(row[s.id] ?? 0);
                return (
                  <td key={s.id}>
                    {valueFormatter ? valueFormatter(value) : String(value)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart
          data={data}
          margin={{ top: 8, right: 8, left: -12, bottom: 0 }}
          aria-label={ariaLabel}
        >
          <CartesianGrid
          strokeDasharray="3 3"
          stroke={gridStroke}
          vertical={false}
        />
        <XAxis
          dataKey={xKey}
          tick={emptyXValues ? renderMutedTick : axisTick}
          axisLine={{ stroke: gridStroke }}
          tickLine={false}
          minTickGap={showAllXLabels ? 0 : 8}
          interval={showAllXLabels ? 0 : undefined}
        />
        <YAxis tick={axisTick} axisLine={false} tickLine={false} width={48} />
        <Tooltip
          contentStyle={tooltipStyle}
          labelStyle={tooltipText}
          itemStyle={tooltipText}
          cursor={{ fill: token.colorFillSecondary }}
          formatter={
            valueFormatter ? (value) => valueFormatter(Number(value)) : undefined
          }
        />
        {withLegend && <Legend />}
        {series.map((s) => (
          <Bar
            key={s.id}
            dataKey={s.id}
            name={s.label}
            fill={s.color}
            radius={[4, 4, 0, 0]}
            maxBarSize={48}
            shape={emptyBarShape}
          />
        ))}
        </BarChart>
      </ResponsiveContainer>
    </>
  );
}
