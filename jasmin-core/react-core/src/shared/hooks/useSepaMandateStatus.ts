import { useCallback, useMemo } from "react";
import { useRoles } from "@shared/auth";
import { usePaymentsBillingProfilesMandateStatusList } from "@shared/api/generated/payments/payments";
import type { SepaMandateStatus } from "@shared/api/generated/models";

/**
 * Per-member SEPA mandate status for overview tables (the Abos SEPA column).
 *
 * One office-only fetch of the lightweight ``mandate_status`` endpoint (no
 * bank identifiers, so no IBAN decryption / SEC-1 bulk-read audit line),
 * mapped by member id for O(1) row lookup. Gated on the office role — a
 * member must not see every member's mandate status, and the endpoint 403s
 * them anyway, so we don't even fire the request.
 */
export function useSepaMandateStatus(enabled = true) {
  const { isOffice } = useRoles();
  const { data, isLoading } = usePaymentsBillingProfilesMandateStatusList({
    query: { enabled: enabled && isOffice },
  });

  const byMember = useMemo(() => {
    const map = new Map<string, SepaMandateStatus>();
    for (const row of data ?? []) map.set(row.member, row);
    return map;
  }, [data]);

  const getMandateForMember = useCallback(
    (memberId?: string | null): SepaMandateStatus | undefined =>
      memberId ? byMember.get(memberId) : undefined,
    [byMember],
  );

  return { getMandateForMember, isLoading };
}
