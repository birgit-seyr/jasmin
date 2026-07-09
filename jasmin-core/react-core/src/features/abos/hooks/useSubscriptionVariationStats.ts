import dayjs, { type Dayjs } from "dayjs";
import { useMemo } from "react";
import { buildMonthAxis } from "@shared/utils";
import { useShareTypeVariationSizeOptions } from "@hooks/index";

/**
 * Okabe–Ito colourblind-safe categorical palette, in a fixed order. Assigned to
 * share-type variations by catalogue order (never cycled until exhausted) so a
 * variation keeps its colour across the stats strips and the dashboard graph.
 * A CSA runs a handful of variations, well within these eight steps.
 */
export const VARIATION_PALETTE = [
  "#0072B2", // blue
  "#CC79A7", // reddish purple
  "#E69F00", // orange
  "#009E73", // green
  "#D55E00", // vermillion
  "#56B4E9", // sky blue
  "#999999", // grey
  "#000000", // black
];

export interface VariationInfo {
  id: string;
  label: string;
  color: string;
}

/**
 * Deterministic, id-based order for palette assignment. Numeric-aware (so
 * "2" sorts before "10"), lexicographic fallback for non-numeric ids. Keyed on
 * the stable variation id — NOT the incoming array order — so a variation keeps
 * its colour regardless of which query (and thus which ordering) a page fetched
 * the catalogue through.
 */
function compareVariationId(a: string, b: string): number {
  const na = Number(a);
  const nb = Number(b);
  if (Number.isFinite(na) && Number.isFinite(nb) && na !== nb) return na - nb;
  return a < b ? -1 : a > b ? 1 : 0;
}

interface SubRow {
  // Optional to match the loose read-view row types (AboRecord / generated
  // Subscription) — a row without a variation is skipped in the per-variation
  // breakdown but still counts toward the status total.
  share_type_variation?: string;
  share_type_variation_string?: string | null;
  quantity?: number;
  valid_from?: string | null;
  valid_until?: string | null;
  on_waiting_list?: boolean | null;
  admin_confirmed?: boolean | null;
  cancelled_at?: string | null;
}

interface VariationOption {
  id?: string;
  share_type_name?: string | null;
  size?: string | null;
}

/** Per-status, per-variation summed quantity (a subscription can be >1 share). */
export interface StatusSummary {
  total: number;
  byVariation: Map<string, number>;
}

/**
 * Shared subscription aggregation for the abos list + dashboard: stable
 * per-variation metadata (label + colour) and today's per-status quantities,
 * summed per variation.
 */
export function useSubscriptionVariationStats(
  subscriptions: SubRow[] | undefined,
  variations: VariationOption[] | undefined,
) {
  const { getShareTypeVariationSizeLabel } = useShareTypeVariationSizeOptions();

  // Ordered variation metadata taken from the CATALOGUE (not the subscriptions)
  // so ordering + colour stay stable regardless of which subs exist. The
  // backend ``share_type_variation_string`` bakes in the raw size enum ("FULL")
  // and can't be localized client-side, hence rebuilding the label here.
  const variationInfo = useMemo(() => {
    const map = new Map<string, VariationInfo>();
    // Assign palette colours by the stable id order (not the array order), so
    // the abos stats strip and the dashboard graph agree on every variation's
    // colour even though each page fetches the catalogue through a different
    // query.
    const ordered = [...(variations ?? [])]
      .filter((v): v is VariationOption & { id: string } => !!v.id)
      .sort((a, b) => compareVariationId(a.id, b.id));
    ordered.forEach((v, i) => {
      const label =
        [v.share_type_name, getShareTypeVariationSizeLabel(v.size ?? "")]
          .filter(Boolean)
          .join(" · ") || v.id;
      map.set(v.id, {
        id: v.id,
        label,
        color: VARIATION_PALETTE[i % VARIATION_PALETTE.length],
      });
    });
    return map;
  }, [variations, getShareTypeVariationSizeLabel]);

  const snapshot = useMemo(() => {
    const rows = subscriptions ?? [];
    const today = dayjs();
    const eligible = (s: SubRow) =>
      s.admin_confirmed === true && !s.cancelled_at && !s.on_waiting_list;
    const isActive = (s: SubRow) =>
      eligible(s) &&
      (!s.valid_from || !dayjs(s.valid_from).isAfter(today, "day")) &&
      (!s.valid_until || !dayjs(s.valid_until).isBefore(today, "day"));
    const isFuture = (s: SubRow) =>
      eligible(s) && !!s.valid_from && dayjs(s.valid_from).isAfter(today, "day");
    const isWaiting = (s: SubRow) => !!s.on_waiting_list && !s.cancelled_at;

    const summarize = (subs: SubRow[]): StatusSummary => {
      const byVariation = new Map<string, number>();
      let total = 0;
      for (const s of subs) {
        const q = s.quantity || 0;
        total += q;
        const id = s.share_type_variation;
        if (id) byVariation.set(id, (byVariation.get(id) ?? 0) + q);
      }
      return { total, byVariation };
    };

    return {
      active: summarize(rows.filter(isActive)),
      future: summarize(rows.filter(isFuture)),
      waiting: summarize(rows.filter(isWaiting)),
    };
  }, [subscriptions]);

  return { variationInfo, snapshot };
}

/**
 * Monthly active subscription QUANTITY per variation across the window — one
 * data key per variation, for the dashboard's multi-line chart. Always spans at
 * least 12 months (zero-filled) so the graph never looks sparse. A variation
 * only gets a series if it was active at some point in the window.
 */
export function buildMonthlyActiveByVariation(
  subscriptions: SubRow[] | undefined,
  variationInfo: Map<string, VariationInfo>,
  range: [Dayjs, Dayjs] | null,
) {
  const rows = subscriptions ?? [];
  const { months, labelOf } = buildMonthAxis(range);

  // Eligible = confirmed, not cancelled, not waiting, and actually started.
  const eligible = rows.filter(
    (s) =>
      s.admin_confirmed === true &&
      !s.cancelled_at &&
      !s.on_waiting_list &&
      !!s.valid_from,
  );

  const data: Array<Record<string, number | string>> = [];
  const usedVarIds = new Set<string>();
  for (const cursor of months) {
    const monthStart = cursor.startOf("month");
    const monthEnd = cursor.endOf("month");
    const point: Record<string, number | string> = {
      label: labelOf(cursor),
    };
    for (const s of eligible) {
      const id = s.share_type_variation;
      if (!id) continue;
      if (dayjs(s.valid_from as string).isAfter(monthEnd)) continue; // not yet
      if (s.valid_until && dayjs(s.valid_until).isBefore(monthStart)) continue; // ended
      point[id] = ((point[id] as number) ?? 0) + (s.quantity || 0);
      usedVarIds.add(id);
    }
    data.push(point);
  }

  const series = [...variationInfo.values()].filter((v) => usedVarIds.has(v.id));
  return { data, series };
}
