import {
  CalendarOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  DownOutlined,
  UpOutlined,
  WalletOutlined,
} from "@ant-design/icons";
import { Button, Card, Divider, Space, Tag, Timeline, Typography } from "antd";
import dayjs from "dayjs";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { usePaymentsChargeSchedulesList } from "@shared/api/generated/payments-—-charge-schedule/payments-—-charge-schedule";
import type { ChargeSchedule } from "@shared/api/generated/models";
import { useCurrency, useDateFormat } from "@hooks/index";
import { CHARGE_STATUS_COLOR as STATUS_COLOR } from "@shared/utils/chargeStatusColors";
import { unwrapList } from "@shared/utils";
import SepaSetupModal from "@features/members/modals/SepaSetupModal";

const { Text } = Typography;

const PAGE_SIZE = 5;

interface PaymentLineItem {
  label: string;
  amount: number;
  status: string;
}

interface PaymentGroup {
  date: dayjs.Dayjs;
  /** due_date is in the past (drives the past/future timeline split). */
  isPast: boolean;
  /** every charge due that date is settled (status === PAID) — the real
   *  ledger state, not a date heuristic. */
  isPaid: boolean;
  items: PaymentLineItem[];
  /** payable total (WAIVED excluded), precomputed once. */
  total: number;
  /** index of the recap window this group falls in (future groups only). */
  windowIndex?: number;
}

/** A recap of what a member pays across one billing cycle (e.g. a month).
 *  Only built when EVERY subscription shares the same non-weekly cycle. */
interface Recap {
  /** monthly → label the window with the month name, not a date range. */
  isMonthly: boolean;
  /** Inclusive calendar range of window ``i``. */
  windowRange: (i: number) => { start: dayjs.Dayjs; end: dayjs.Dayjs };
  /** windowIndex → summed payable total of the FUTURE groups in it. */
  windowTotals: Map<number, number>;
  /** windowIndex → index (within futureGroups) of its LAST group, so the
   *  subtotal renders right after that group is fully loaded. */
  lastIdxByWindow: Map<number, number>;
  /** the window of the next upcoming charge — carries the "next payment" tag. */
  nextBatchWindowIndex: number | undefined;
}

type CanonCycle =
  | "weekly"
  | "biweekly"
  | "monthly"
  | "quarterly"
  | "semiannual"
  | "annual";

// Classify a billing-period length (in days) into a canonical cycle. The ledger
// carries period_start/period_end per charge, so the cycle is inferred without
// a backend field. Missing dates → weekly (legacy/period-less data).
function cycleOf(days: number): CanonCycle {
  if (days <= 8) return "weekly";
  if (days <= 20) return "biweekly";
  if (days <= 45) return "monthly";
  if (days <= 135) return "quarterly";
  if (days <= 270) return "semiannual";
  return "annual";
}

// Months per recap window; 0 = day-stepped (biweekly).
const CYCLE_MONTHS: Record<CanonCycle, number> = {
  weekly: 0,
  biweekly: 0,
  monthly: 1,
  quarterly: 3,
  semiannual: 6,
  annual: 12,
};

// The recap subtotal only appears when EVERY charge shares the same non-weekly
// cycle: mixed cycles keep the plain per-charge timeline (a weekly+monthly mash
// is confusing), and pure-weekly needs no batching (each week is a payment).
function sharedRecapCycle(rows: ChargeSchedule[]): CanonCycle | null {
  const cycles = new Set<CanonCycle>();
  for (const c of rows) {
    const days =
      c.period_start && c.period_end
        ? dayjs(c.period_end).diff(dayjs(c.period_start), "day")
        : 0;
    cycles.add(cycleOf(days));
  }
  if (cycles.size !== 1) return null;
  const only = [...cycles][0];
  return only === "weekly" ? null : only;
}

interface PaymentsCardProps {
  /** Scopes the charge-schedule query + the "Set up SEPA" action to a member.
   *  Optional so legacy call sites still type-check; without it the card shows
   *  no charges (it has no member to read the ledger for). */
  memberId?: string;
}

const PaymentsCard = ({ memberId }: PaymentsCardProps) => {
  const { t } = useTranslation();
  const { formatCurrency } = useCurrency();
  const { formatDate } = useDateFormat();
  const [futureCount, setFutureCount] = useState(PAGE_SIZE);
  const [pastCount, setPastCount] = useState(0);
  const [sepaModalOpen, setSepaModalOpen] = useState(false);

  // SOURCE OF TRUTH: the backend ChargeSchedule ledger (same data ChargesAbos
  // shows). ``expected_amount`` already accounts for jokers / opt-outs / the
  // billing strategy — the previous client-side
  // ``price_per_delivery * quantity * deliveriesPerCycle`` recompute diverged
  // from it, which is exactly the bug this card had.
  const { data: chargesData } = usePaymentsChargeSchedulesList(
    { member: memberId },
    { query: { enabled: !!memberId } },
  );

  const { pastGroups, futureGroups, recap } = useMemo(() => {
    const rows = unwrapList<ChargeSchedule>(chargesData);
    if (!rows.length) return { pastGroups: [], futureGroups: [], recap: null };

    const today = dayjs();
    const byDate = new Map<string, PaymentGroup>();
    for (const charge of rows) {
      if (!charge.due_date) continue;
      let group = byDate.get(charge.due_date);
      if (!group) {
        group = {
          date: dayjs(charge.due_date),
          isPast: dayjs(charge.due_date).isBefore(today, "day"),
          isPaid: true,
          items: [],
          total: 0,
        };
        byDate.set(charge.due_date, group);
      }
      group.items.push({
        label: charge.subscription_label ?? "",
        amount: Number.parseFloat(charge.expected_amount ?? "0"),
        status: charge.status ?? "PLANNED",
      });
      if (charge.status !== "PAID") group.isPaid = false;
    }

    const groups = Array.from(byDate.values()).sort((a, b) =>
      a.date.diff(b.date),
    );
    for (const group of groups) {
      // WAIVED charges are forgiven — shown but no longer money owed.
      group.total = group.items.reduce(
        (sum, item) => sum + (item.status === "WAIVED" ? 0 : item.amount),
        0,
      );
    }

    const past: PaymentGroup[] = [];
    const future: PaymentGroup[] = [];
    for (const group of groups) (group.isPast ? past : future).push(group);

    // Recap: only when all subs share one non-weekly cycle AND there is future.
    const recapCycle = future.length ? sharedRecapCycle(rows) : null;
    let recap: Recap | null = null;
    if (recapCycle) {
      const months = CYCLE_MONTHS[recapCycle];
      const first = future[0].date;
      const anchor = months > 0 ? first.startOf("month") : first.startOf("day");
      const windowIndexFor = (d: dayjs.Dayjs) =>
        months > 0
          ? Math.floor(d.diff(anchor, "month") / months)
          : Math.floor(d.diff(anchor, "day") / 14);
      const windowRange = (i: number) =>
        months > 0
          ? {
              start: anchor.add(i * months, "month"),
              end: anchor.add((i + 1) * months, "month").subtract(1, "day"),
            }
          : {
              start: anchor.add(i * 14, "day"),
              end: anchor.add((i + 1) * 14, "day").subtract(1, "day"),
            };

      const windowTotals = new Map<number, number>();
      const lastIdxByWindow = new Map<number, number>();
      future.forEach((group, index) => {
        const wi = windowIndexFor(group.date);
        group.windowIndex = wi;
        windowTotals.set(wi, (windowTotals.get(wi) ?? 0) + group.total);
        lastIdxByWindow.set(wi, index);
      });
      recap = {
        isMonthly: recapCycle === "monthly",
        windowRange,
        windowTotals,
        lastIdxByWindow,
        nextBatchWindowIndex: future[0]?.windowIndex,
      };
    }

    return { pastGroups: past, futureGroups: future, recap };
  }, [chargesData]);

  const visiblePast = useMemo(
    () =>
      pastCount > 0
        ? pastGroups.slice(Math.max(0, pastGroups.length - pastCount))
        : [],
    [pastGroups, pastCount],
  );
  const visibleFuture = useMemo(
    () => futureGroups.slice(0, futureCount),
    [futureGroups, futureCount],
  );
  const hasMorePast = pastCount < pastGroups.length;
  const hasMoreFuture = futureCount < futureGroups.length;

  const timelineItems = useMemo(() => {
    const renderGroup = (
      group: PaymentGroup,
      isNext: boolean,
      key: string,
      showTotal: boolean,
    ) => ({
      key,
      color: isNext ? "green" : group.isPast ? "gray" : "blue",
      dot: isNext ? (
        <CalendarOutlined />
      ) : group.isPast ? (
        <CheckCircleOutlined />
      ) : (
        <ClockCircleOutlined />
      ),
      children: (
        <div>
          <Space>
            <Text strong>{formatDate(group.date)}</Text>
            {isNext && <Tag color="green">{t("members.next_payment")}</Tag>}
            {group.isPaid && <Tag color="default">{t("members.paid")}</Tag>}
          </Space>
          {group.items.map((item, i) => (
            <div
              key={`${item.label}-${i}`}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "baseline",
                gap: 8,
              }}
            >
              <Space size={6}>
                <Text type="secondary">{item.label}</Text>

                {t(`abos.charge_status.${item.status}`)}
              </Space>
              <Text
                type={group.items.length > 1 ? "secondary" : undefined}
                strong
                delete={item.status === "WAIVED"}
                style={{ whiteSpace: "nowrap", marginLeft: "8px" }}
              >
                {formatCurrency(item.amount)}
              </Text>
            </div>
          ))}
          {showTotal && group.items.length > 1 && (
            <>
              <Divider style={{ margin: "4px 0" }} />
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <Text strong>{t("members.total")}</Text>
                <Text
                  strong
                  style={{ whiteSpace: "nowrap", marginLeft: "8px" }}
                >
                  {formatCurrency(group.total)}
                </Text>
              </div>
            </>
          )}
        </div>
      ),
    });

    const renderBatchSubtotal = (windowIndex: number, isNextBatch: boolean) => {
      const range = recap!.windowRange(windowIndex);
      const label = recap!.isMonthly
        ? range.start.format("MMMM YYYY")
        : `${formatDate(range.start)} – ${formatDate(range.end)}`;
      return {
        key: `batch-${windowIndex}`,
        color: isNextBatch ? "green" : "gray",
        dot: <WalletOutlined />,
        children: (
          <div className="payment-batch-subtotal">
            <Space size={6} wrap>
              <Text strong>{t("members.batch_total")}</Text>
              <Text type="secondary">{label}</Text>
              {isNextBatch && (
                <Tag color="green">{t("members.next_payment")}</Tag>
              )}
            </Space>
            <Text strong style={{ whiteSpace: "nowrap", marginLeft: "8px" }}>
              {formatCurrency(recap!.windowTotals.get(windowIndex) ?? 0)}
            </Text>
          </div>
        ),
      };
    };

    const items: ReturnType<typeof renderGroup>[] = [];
    // Past groups: unchanged — never "next", keep their own totals.
    visiblePast.forEach((group, idx) =>
      items.push(renderGroup(group, false, `past-${idx}`, true)),
    );
    // Future groups: with a recap the "next payment" emphasis + the per-cycle
    // total move onto the batch subtotal (so the per-group total isn't a
    // redundant second line); without one it's the plain per-week timeline.
    visibleFuture.forEach((group, futureIndex) => {
      const isNext = !recap && futureIndex === 0;
      items.push(renderGroup(group, isNext, `future-${futureIndex}`, !recap));
      if (
        recap &&
        group.windowIndex !== undefined &&
        recap.lastIdxByWindow.get(group.windowIndex) === futureIndex
      ) {
        items.push(
          renderBatchSubtotal(
            group.windowIndex,
            group.windowIndex === recap.nextBatchWindowIndex,
          ),
        );
      }
    });
    return items;
  }, [visiblePast, visibleFuture, recap, t, formatCurrency, formatDate]);

  return (
    <Card
      title={t("members.payments")}
      className="member-card member-card--top-spaced blue-border member-card--blue-title"
      extra={
        memberId ? (
          <Button size="small" onClick={() => setSepaModalOpen(true)}>
            {t("sepa.setup_action")}
          </Button>
        ) : null
      }
    >
      {memberId && (
        <SepaSetupModal
          open={sepaModalOpen}
          memberId={memberId}
          onClose={() => setSepaModalOpen(false)}
        />
      )}
      {timelineItems.length > 0 ? (
        <>
          {hasMorePast && (
            <div style={{ textAlign: "center", marginBottom: 8 }}>
              <Button
                type="link"
                icon={<UpOutlined />}
                onClick={() => setPastCount((c) => c + PAGE_SIZE)}
              >
                {t("common.load_more")}
              </Button>
            </div>
          )}
          <Timeline items={timelineItems} />
          {hasMoreFuture && (
            <div className="text-center">
              <Button
                type="link"
                icon={<DownOutlined />}
                onClick={() => setFutureCount((c) => c + PAGE_SIZE)}
              >
                {t("common.load_more")}
              </Button>
            </div>
          )}
        </>
      ) : (
        <Text type="secondary">{t("members.no_payments")}</Text>
      )}
    </Card>
  );
};

export default PaymentsCard;
