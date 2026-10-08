import { useTranslation } from "react-i18next";
import type { CommissioningListResellersOrderContent } from "@shared/api/generated/models";
import { useNumberFormat, useUnitOptions, useVegetableSizeOptions } from "@hooks/index";
import { orderLineArticleLabel } from "../../utils/orderLineLabel";
import {
  MobileCard,
  MobileCardContent,
  MobileCardMetric,
  MobileCardMetricsRow,
  MobileCardNote,
  MobileCardTitle,
} from "./primitives";
import "./ResellerOrderMobileCards.css";

type OrderLine = CommissioningListResellersOrderContent;

/** The lines of a reseller's order on the phone, one card each, under the
 *  reseller's card heading. */
export function ResellerOrderMobileCards({ lines }: { lines: OrderLine[] }) {
  return (
    <div className="flex-col gap-8 reseller-order-mobile-cards">
      {lines.map((line) => (
        <ResellerOrderLineMobileCard key={line.id} line={line} />
      ))}
    </div>
  );
}

/** One line of a reseller's order: the article, the amount to pack and how
 *  many PUs it fills. */
function ResellerOrderLineMobileCard({ line }: { line: OrderLine }) {
  const { t } = useTranslation();
  const { format } = useNumberFormat();
  const { getUnitLabel } = useUnitOptions();
  const { getVegetableSizeLabel } = useVegetableSizeOptions();

  const amount = Number(line.amount);
  const amountPerPu = Number(line.amount_per_pu);
  const puCount =
    !isNaN(amount) && !isNaN(amountPerPu) && amountPerPu > 0
      ? format(amount / amountPerPu, 1)
      : null;
  const unitLabel = getUnitLabel(line.unit);

  return (
    <MobileCard>
      <MobileCardContent>
        <MobileCardTitle name={orderLineArticleLabel(line, getVegetableSizeLabel)} />
        <MobileCardMetricsRow>
          <MobileCardMetric
            label={t("commissioning.amount")}
            value={!isNaN(amount) ? format(amount, 1) : "-"}
            unit={unitLabel}
          />
          {puCount && (
            <MobileCardMetric
              label={t("commissioning.pu")}
              value={puCount}
              unit={`(${format(amountPerPu, 2)} ${unitLabel}/${t("commissioning.pu")})`}
              emphasis="secondary"
            />
          )}
        </MobileCardMetricsRow>
        <MobileCardNote note={line.note} />
      </MobileCardContent>
    </MobileCard>
  );
}
