import { useQueryClient } from "@tanstack/react-query";
import {  Button, Card, Popconfirm, Space, Table, Tag } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  getPaymentsChargeSchedulesListQueryKey,
  paymentsChargeSchedulesRegenerateCreate,
  usePaymentsChargeSchedulesList,
} from "@shared/api/generated/payments-—-charge-schedule/payments-—-charge-schedule";
import type {
  ChargeSchedule,
  PaymentsChargeSchedulesListParams,
} from "@shared/api/generated/models";
import {
  MemberSelector,
  MonthSelector,
  YearSelector,
} from "@shared/selectors";
import { ExplainerText } from "@shared/ui";
import { useCurrency, useDateFormat } from "@hooks/index";
import { notify } from "@shared/utils";
import {
  CHARGE_STATUS_COLOR as STATUS_COLOR,
  CHARGE_STATUS_ORDER as STATUS_ORDER,
} from "@shared/utils/chargeStatusColors";

interface ChargeRow extends ChargeSchedule {
  member_name?: string;
  member_number?: number;
  subscription_label?: string;
}

interface MemberGroup {
  memberId: string;
  memberLabel: string;
  rows: ChargeRow[];
  total: number;
}

interface DisplayRow {
  key: string;
  type: "charge" | "subtotal";
  charge?: ChargeRow;
  memberLabel?: string;
  memberRowSpan?: number;
  subtotal?: number;
  rowCount?: number;
}

export default function ChargesAbos() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { formatDate } = useDateFormat();
  const { formatCurrency, currencySymbol } = useCurrency();

  const [selectedMember, setSelectedMember] = useState<string | null>(null);
  const [selectedYear, setSelectedYear] = useState<number>(dayjs().year());
  const [selectedMonth, setSelectedMonth] = useState<number | "all">(
    dayjs().month() + 1,
  );
  const [selectedStatus, setSelectedStatus] = useState<string | null>(null);
  const [regenerating, setRegenerating] = useState(false);

  // Status is filtered CLIENT-side (see ``filteredRows``) — NOT sent to the API —
  // so a single load carries every status and the per-status totals below stay
  // visible all at once instead of collapsing to the one the server filtered to.
  const params = useMemo<PaymentsChargeSchedulesListParams>(() => {
    const p: PaymentsChargeSchedulesListParams = { year: selectedYear };
    if (selectedMonth !== "all") p.month = selectedMonth;
    if (selectedMember) p.member = selectedMember;
    return p;
  }, [selectedYear, selectedMonth, selectedMember]);

  // UI-3: filter-driven table — use isFetching (not isLoading) so revisiting a
  // previously-loaded year/month (cached, staleTime:0) still shows the spinner
  // while it refetches.
  const { data, isFetching, refetch } = usePaymentsChargeSchedulesList(params);
  const rows = useMemo<ChargeRow[]>(() => (data ?? []) as ChargeRow[], [data]);

  // Per-status totals (amount + count) across the whole loaded set.
  const statusTotals = useMemo(() => {
    const map = new Map<string, { total: number; count: number }>();
    for (const r of rows) {
      const st = r.status ?? "?";
      const agg = map.get(st) ?? { total: 0, count: 0 };
      agg.total += Number.parseFloat(r.expected_amount ?? "0");
      agg.count += 1;
      map.set(st, agg);
    }
    return [...map.entries()].sort(
      (a, b) => STATUS_ORDER.indexOf(a[0]) - STATUS_ORDER.indexOf(b[0]),
    );
  }, [rows]);

  const filteredRows = useMemo(
    () =>
      selectedStatus ? rows.filter((r) => r.status === selectedStatus) : rows,
    [rows, selectedStatus],
  );

  // Group by member; within a group sort by due_date.
  const grouped: MemberGroup[] = useMemo(() => {
    const map = new Map<string, MemberGroup>();
    for (const r of filteredRows) {
      const key = r.member ?? "?";
      const num = r.member_number ? `#${r.member_number} ` : "";
      const label = r.member_name ? `${num}${r.member_name}` : key;
      if (!map.has(key)) {
        map.set(key, {
          memberId: key,
          memberLabel: label,
          rows: [],
          total: 0,
        });
      }
      const g = map.get(key)!;
      g.rows.push(r);
      g.total += Number.parseFloat(r.expected_amount ?? "0");
    }
    for (const g of map.values()) {
      g.rows.sort((a, b) => (a.due_date ?? "").localeCompare(b.due_date ?? ""));
    }
    return [...map.values()].sort((a, b) =>
      a.memberLabel.localeCompare(b.memberLabel),
    );
  }, [filteredRows]);

  // Flatten groups → list of charge rows + a subtotal row per group.
  // The first charge of each block carries memberRowSpan so AntD merges
  // the member-name cell visually.
  const displayRows: DisplayRow[] = useMemo(() => {
    const out: DisplayRow[] = [];
    for (const g of grouped) {
      g.rows.forEach((charge, idx) => {
        out.push({
          key: charge.id ?? `${g.memberId}-${idx}`,
          type: "charge",
          charge,
          memberLabel: idx === 0 ? g.memberLabel : "",
          memberRowSpan: idx === 0 ? g.rows.length + 1 : 0, // +1 for subtotal
        });
      });
      out.push({
        key: `subtotal-${g.memberId}`,
        type: "subtotal",
        memberLabel: g.memberLabel,
        subtotal: g.total,
        rowCount: g.rows.length,
      });
    }
    return out;
  }, [grouped]);

  const handleRegenerate = useCallback(async () => {
    setRegenerating(true);
    try {
      const res = await paymentsChargeSchedulesRegenerateCreate();
      const created = Object.values(res?.details ?? {}).reduce(
        (a: number, b) => a + Number(b ?? 0),
        0,
      );
      notify.success(
        t("abos.charges_regenerated", {
          subscriptions: res?.regenerated_subscriptions ?? 0,
          rows: created,
        }),
      );
      queryClient.invalidateQueries({
        queryKey: getPaymentsChargeSchedulesListQueryKey(params),
      });
      refetch();
    } catch (err) {
      console.error(err);
      notify.error(t("abos.charges_regenerate_error"));
    } finally {
      setRegenerating(false);
    }
  }, [t, queryClient, params, refetch]);

  const columns = useMemo(
    () => [
      {
        title: t("abos.charges_col_member"),
        key: "memberLabel",
        width: "18em",
        onCell: (r: DisplayRow) => ({ rowSpan: r.memberRowSpan ?? 1 }),
        render: (_v: unknown, r: DisplayRow) =>
          r.memberLabel ? <strong>{r.memberLabel}</strong> : null,
      },
      {
        title: t("abos.charges_col_subscription"),
        key: "subscription_label",
        onCell: (r: DisplayRow) =>
          r.type === "subtotal" ? { colSpan: 4 } : {},
        render: (_v: unknown, r: DisplayRow) => {
          if (r.type === "subtotal") {
            return (
              <span style={{ color: "var(--color-text-muted)" }}>
                {t("abos.charges_subtotal_label", {
                  count: r.rowCount,
                })}
              </span>
            );
          }
          return r.charge?.subscription_label;
        },
      },
      {
        title: t("abos.charges_col_period"),
        key: "period",
        onCell: (r: DisplayRow) =>
          r.type === "subtotal" ? { colSpan: 0 } : {},
        render: (_v: unknown, r: DisplayRow) =>
          r.charge
            ? `${formatDate(r.charge.period_start)} – ${formatDate(r.charge.period_end)}`
            : null,
      },
      {
        title: t("abos.charges_col_due_date"),
        key: "due_date",
        align: "center" as const,
        width: "8em",
        onCell: (r: DisplayRow) =>
          r.type === "subtotal" ? { colSpan: 0 } : {},
        render: (_v: unknown, r: DisplayRow) =>
          r.charge ? formatDate(r.charge.due_date) : null,
      },
      {
        title: t("abos.charges_col_status"),
        key: "status",
        align: "center" as const,
        width: "7em",
        onCell: (r: DisplayRow) =>
          r.type === "subtotal" ? { colSpan: 0 } : {},
        render: (_v: unknown, r: DisplayRow) =>
          r.charge?.status ? (
            <Tag
              color={STATUS_COLOR[r.charge.status] ?? "default"}
              style={{ cursor: "pointer" }}
              onClick={(e) => {
                e.stopPropagation();
                setSelectedStatus((s) =>
                  s === r.charge?.status ? null : (r.charge?.status ?? null),
                );
              }}
            >
              {t(`abos.charge_status.${r.charge.status}`)}
            </Tag>
          ) : null,
      },
      {
        title: t("abos.charges_col_amount"),
        key: "expected_amount",
        align: "right" as const,
        width: "9em",
        render: (_v: unknown, r: DisplayRow) => {
          if (r.type === "subtotal") {
            return <strong>{formatCurrency(r.subtotal ?? 0)}</strong>;
          }
          return formatCurrency(
            Number.parseFloat(r.charge?.expected_amount ?? "0"),
          );
        },
      },
    ],
    [t, formatDate, formatCurrency],
  );

  return (
    <div>
      <h1>{t("abos.charges")}</h1>

      <YearSelector
        selectedYear={selectedYear}
        setSelectedYear={setSelectedYear}
      />
      <MonthSelector
        selectedMonth={selectedMonth}
        setSelectedMonth={setSelectedMonth}
        selectedYear={selectedYear}
        include_all_option
      />
      <MemberSelector
        selectedMember={selectedMember}
        setSelectedMember={setSelectedMember}
        include_null_option
      />
      <div style={{ marginBottom: "2em", marginTop: "2em" }}>
        <Button
          type="primary"
          loading={regenerating}
          onClick={handleRegenerate}
        >
          {t("abos.charges_regenerate")}
        </Button>
      </div>

      {statusTotals.length > 0 && (
        <div style={{ marginBottom: "1.5em" }}>
          <span style={{ color: "var(--color-text-muted)", marginRight: 8 }}>
            {t("abos.charges_status_totals")}
          </span>
          <Space wrap>
            {statusTotals.map(([st, agg]) => (
              <Tag
                key={st}
                color={STATUS_COLOR[st] ?? "default"}
                style={{
                  cursor: "pointer",
                  fontWeight: selectedStatus === st ? 700 : 400,
                }}
                onClick={() => setSelectedStatus((s) => (s === st ? null : st))}
              >
                {t(`abos.charge_status.${st}`)}: {formatCurrency(agg.total)} (
                {agg.count})
              </Tag>
            ))}
          </Space>
        </div>
      )}

      <Table<DisplayRow>
        rowKey="key"
        loading={isFetching}
        dataSource={displayRows}
        columns={columns}
        size="small"
        pagination={{ pageSize: 100, showSizeChanger: true }}
        rowClassName={(r) =>
          r.type === "subtotal" ? "charges-subtotal-row" : ""
        }
      />

      <ExplainerText title={t("common.info")}>
        {t("explainers.charges_overview", {
          currency: currencySymbol,
        })}
      </ExplainerText>
    </div>
  );
}
