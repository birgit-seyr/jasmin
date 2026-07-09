import {
  CalendarOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  DownOutlined,
  UpOutlined,
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

  const { pastGroups, futureGroups } = useMemo(() => {
    const rows = unwrapList<ChargeSchedule>(chargesData);
    if (!rows.length) return { pastGroups: [], futureGroups: [] };

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
    const past: PaymentGroup[] = [];
    const future: PaymentGroup[] = [];
    for (const group of groups) (group.isPast ? past : future).push(group);
    return { pastGroups: past, futureGroups: future };
  }, [chargesData]);

  // Memoize so the array identity is stable across renders — `timelineItems`
  // depends on `visibleGroups` and would otherwise rebuild every render.
  const visibleGroups = useMemo(() => {
    const visiblePast =
      pastCount > 0
        ? pastGroups.slice(Math.max(0, pastGroups.length - pastCount))
        : [];
    const visibleFuture = futureGroups.slice(0, futureCount);
    return [...visiblePast, ...visibleFuture];
  }, [pastGroups, pastCount, futureGroups, futureCount]);
  const hasMorePast = pastCount < pastGroups.length;
  const hasMoreFuture = futureCount < futureGroups.length;

  const timelineItems = useMemo(() => {
    return visibleGroups.map((group, index) => {
      const isNext =
        !group.isPast && (index === 0 || visibleGroups[index - 1]?.isPast);
      // WAIVED charges are forgiven — they keep their original amount in the
      // ledger but are no longer money owed, so exclude them from the total.
      const total = group.items.reduce(
        (sum, item) => sum + (item.status === "WAIVED" ? 0 : item.amount),
        0,
      );

      return {
        key: `${group.date.format("YYYY-MM-DD")}-${index}`,
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
                  <Tag
                    color={STATUS_COLOR[item.status] ?? "default"}
                    style={{ margin: 0 }}
                  >
                    {t(`abos.charge_status.${item.status}`)}
                  </Tag>
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
            {group.items.length > 1 && (
              <>
                <Divider style={{ margin: "4px 0" }} />
                <div
                  style={{ display: "flex", justifyContent: "space-between" }}
                >
                  <Text strong>{t("members.total")}</Text>
                  <Text
                    strong
                    style={{ whiteSpace: "nowrap", marginLeft: "8px" }}
                  >
                    {formatCurrency(total)}
                  </Text>
                </div>
              </>
            )}
          </div>
        ),
      };
    });
  }, [visibleGroups, t, formatCurrency, formatDate]);

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
