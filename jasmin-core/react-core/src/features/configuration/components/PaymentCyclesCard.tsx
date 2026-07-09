import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { Card, Checkbox, Col, Row, Spin } from "antd";
import {
  commissioningPaymentCyclesPartialUpdate,
  getCommissioningPaymentCyclesListQueryKey,
  useCommissioningPaymentCyclesList,
} from "@shared/api/generated/commissioning/commissioning";
import type { PaymentCycle as PaymentCycleType } from "@shared/api/generated/models";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import { paymentCycleLabel } from "@shared/utils/cycleLabels";

const PAYMENT_CYCLE_OPTIONS = [
  "WEEKLY",
  "BIWEEKLY",
  "MONTHLY",
  "QUARTERLY",
  "SEMI_ANNUALLY",
  "ANNUALLY",
] as const;

/**
 * Office toggles for which payment cycles are offered to members. Each checkbox
 * flips the cycle's ``is_active`` via PATCH. Lives in Configuration → Payments.
 */
export default function PaymentCyclesCard() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const { data: rawCycles, isLoading: loading } =
    useCommissioningPaymentCyclesList();
  const cycles = rawCycles ?? [];

  const handleToggle = useCallback(
    async (cycle: PaymentCycleType) => {
      const newActive = !cycle.is_active;
      try {
        await commissioningPaymentCyclesPartialUpdate(String(cycle.id), {
          is_active: newActive,
        } as unknown as PaymentCycleType);
        queryClient.invalidateQueries({
          queryKey: getCommissioningPaymentCyclesListQueryKey(),
        });
      } catch (error) {
        console.error("Failed to update payment cycle:", error);
        notify.error(
          getErrorMessage(error, t("configuration.payment_cycle_toggle_error")),
        );
      }
    },
    [queryClient, t],
  );

  return (
    <Card
      title={t("configuration.payment_cycles")}
      className="settings-card-header page-narrow"
      styles={{ body: { padding: "16px" } }}
    >
      {loading ? (
        <Spin size="small" />
      ) : (
        <Row gutter={[16, 8]}>
          {PAYMENT_CYCLE_OPTIONS.map((option) => {
            const cycle = cycles.find((c) => c.choice === option);
            if (!cycle) return null;
            return (
              <Col key={option}>
                <Checkbox
                  checked={cycle.is_active}
                  onChange={() => handleToggle(cycle)}
                >
                  {paymentCycleLabel(t, option)}
                </Checkbox>
              </Col>
            );
          })}
        </Row>
      )}
    </Card>
  );
}
