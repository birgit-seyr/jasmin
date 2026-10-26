import { useMemo } from "react";
import { useCommissioningConsentDocumentsList } from "@shared/api/generated/commissioning/commissioning";
import { todayApiDate } from "@shared/utils/apiDate";
import type {
  CommissioningConsentDocumentsListKind,
  ConsentDocument,
} from "@shared/api/generated/models";

/**
 * The ``ConsentDocument`` of a kind in force today, from the PUBLIC
 * ``consent_documents`` endpoint (AllowAny). Returns ``undefined`` when the
 * tenant has none in force for that kind — callers then don't require that
 * consent. A version published ahead of its start date isn't in force yet:
 * the server only accepts a consent to one that is. Prefers the open-ended
 * version, else the newest listed.
 *
 * Lives in ``shared/`` so both the public registration steps and the
 * (commissioning-context) NewSubscriptionModal can use it — the abos feature
 * must not import from the auth feature.
 */
export function useCurrentConsentDoc(kind: CommissioningConsentDocumentsListKind) {
  const { data, isLoading } = useCommissioningConsentDocumentsList({ kind });
  const doc: ConsentDocument | undefined = useMemo(() => {
    const today = todayApiDate();
    const inForce = (data ?? []).filter(
      (d) =>
        d.valid_from <= today && (!d.valid_until || d.valid_until >= today),
    );
    return inForce.find((d) => !d.valid_until) ?? inForce.at(0);
  }, [data]);
  return { doc, isLoading };
}
