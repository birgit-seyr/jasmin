import { useTranslation } from "react-i18next";
import { useVegetableSizeOptions, useUnitOptions } from "@hooks/index";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import {
  MOBILE_CARD_PLACEHOLDER,
  MobileCard,
  MobileCardContent,
  MobileCardMetric,
  MobileCardMetricsRow,
  MobileCardNote,
  MobileCardTitle,
  getSizeLabelOrEmpty,
} from "./primitives";

interface PackingListBulkMobileCardProps {
  record: TableRecord;
}

export function PackingListBulkMobileCard({
  record,
}: PackingListBulkMobileCardProps) {
  const { t } = useTranslation();
  const { getVegetableSizeLabel } = useVegetableSizeOptions();
  const { getUnitLabel } = useUnitOptions();

  const articleName = (record.share_article_name as string) || "";
  const sizeLabel = getSizeLabelOrEmpty(record.size as string, getVegetableSizeLabel);
  const unitLabel = getUnitLabel(record.unit as string);
  const totalAmount = record.total_amount as number | string | null | undefined;
  const noteText = (record.note as string) || "";

  return (
    <MobileCard>
      <MobileCardContent>
        <MobileCardTitle name={articleName} sizeLabel={sizeLabel} />
        <MobileCardMetricsRow>
          <MobileCardMetric
            label={t("commissioning.total_amount")}
            value={totalAmount ?? MOBILE_CARD_PLACEHOLDER}
            unit={unitLabel}
          />
        </MobileCardMetricsRow>
        <MobileCardNote note={noteText} />
      </MobileCardContent>
    </MobileCard>
  );
}
