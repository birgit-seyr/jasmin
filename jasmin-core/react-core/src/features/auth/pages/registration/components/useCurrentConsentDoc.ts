import { useMemo } from "react";
import { useCommissioningConsentDocumentsList } from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningConsentDocumentsListKind,
  ConsentDocument,
} from "@shared/api/generated/models";

/**
 * The current (active) ``ConsentDocument`` for a kind, from the PUBLIC
 * ``consent_documents`` endpoint (AllowAny). Returns ``undefined`` when the
 * tenant hasn't published a document for that kind — callers then don't
 * require that consent. Prefers the open-ended version, else the newest listed.
 */
export function useCurrentConsentDoc(kind: CommissioningConsentDocumentsListKind) {
  const { data, isLoading } = useCommissioningConsentDocumentsList({ kind });
  const doc: ConsentDocument | undefined = useMemo(() => {
    const list: ConsentDocument[] = data ?? [];
    return list.find((d) => !d.valid_until) ?? list[0];
  }, [data]);
  return { doc, isLoading };
}
