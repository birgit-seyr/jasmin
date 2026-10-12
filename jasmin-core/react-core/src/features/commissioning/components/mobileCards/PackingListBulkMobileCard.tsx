import { useTranslation } from "react-i18next";
import { useNumberFormat, useVegetableSizeOptions, useUnitOptions } from "@hooks/index";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import { formatAmountForUnit } from "@shared/utils";
import {
  MOBILE_CARD_PLACEHOLDER,
  MobileCard,
  MobileCardContent,
  MobileCardMetric,
  MobileCardMetricsRow,
  MobileCardNote,
  MobileCardTitle,
} from "./primitives";
import { recordText } from "./recordText";
import { getSizeLabelOrEmpty } from "@features/commissioning/utils/sizeLabel";

interface PackingListBulkMobileCardProps {
  record: TableRecord;
}

export function PackingListBulkMobileCard({
  record,
}: PackingListBulkMobileCardProps) {
  const { t } = useTranslation();
  const { getVegetableSizeLabel } = useVegetableSizeOptions();
  const { getUnitLabel } = useUnitOptions();
  const { format } = useNumberFormat();

  const articleName = recordText(record, "share_article_name");
  const sizeLabel = getSizeLabelOrEmpty(record.size as string, getVegetableSizeLabel);
  const unitLabel = getUnitLabel(record.unit as string);
  const totalAmount = record.total_amount as number | string | null | undefined;
  const totalAmountText =
    totalAmount == null || totalAmount === ""
      ? MOBILE_CARD_PLACEHOLDER
      : formatAmountForUnit(Number(totalAmount), record.unit as string, format);
  const noteText = recordText(record, "note");

  return (
    <MobileCard>
      <MobileCardContent>
        <MobileCardTitle name={articleName} sizeLabel={sizeLabel} />
        <MobileCardMetricsRow>
          <MobileCardMetric
            label={t("commissioning.total_amount")}
            value={totalAmountText}
            unit={unitLabel}
          />
        </MobileCardMetricsRow>
        <MobileCardNote note={noteText} />
      </MobileCardContent>
    </MobileCard>
  );
}
