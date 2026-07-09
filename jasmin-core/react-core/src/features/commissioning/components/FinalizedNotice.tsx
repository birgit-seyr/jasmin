import type { ConfigType } from "dayjs";
import type { FC } from "react";

import { useTimeFormat } from "@hooks/index";

interface FinalizedNoticeProps {
  /** Already-translated notice text, e.g.
   *  ``t("commissioning.invoice_finalized_notice")``. Ends with a trailing
   *  space so the timestamp reads inline. */
  label: string;
  /** The ``finalized_at`` timestamp; rendered right after the label. */
  at: ConfigType;
}

/**
 * Green "this document is finalized / locked" banner rendered at the top of
 * the DeliveryNote and Invoice modals. Styling lives in the global
 * ``finalized-notice`` CSS class so both modals stay identical.
 */
const FinalizedNotice: FC<FinalizedNoticeProps> = ({ label, at }) => {
  const { formatDateTime } = useTimeFormat();
  return (
    <div className="finalized-notice">
      {label}
      {formatDateTime(at)}
    </div>
  );
};

export default FinalizedNotice;
