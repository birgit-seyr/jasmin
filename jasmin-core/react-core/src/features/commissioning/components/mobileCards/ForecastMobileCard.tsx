import { useTranslation } from "react-i18next";
import { useVegetableSizeOptions, useUnitOptions } from "@hooks/index";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import {
  MobileCard,
  MobileCardContent,
  MobileCardNote,
  MobileCardTags,
  MobileCardTitle,
  getSizeLabelOrEmpty,
} from "./primitives";

interface ForecastMobileCardProps {
  record: TableRecord;
  onEdit: (record: TableRecord) => void;
}

export function ForecastMobileCard({
  record,
  onEdit,
}: ForecastMobileCardProps) {
  const { t } = useTranslation();
  const { getVegetableSizeLabel } = useVegetableSizeOptions();
  const { getUnitLabel } = useUnitOptions();

  const articleName = (record.share_article_name as string) || "";
  const sizeLabel = getSizeLabelOrEmpty(record.size as string, getVegetableSizeLabel);
  const amount = record.amount as number | null | undefined;
  const unitLabel = getUnitLabel(record.unit as string);
  const plotName = (record.plot_name as string) || "";
  const bedNumber = record.bed_number as number | null | undefined;
  const noteText = (record.note as string) || "";
  const isFinalized = !!record.is_finalized;

  const tags: string[] = [];
  if (record.for_all_harvest_shares) tags.push(t("commissioning.for_shares"));
  if (record.for_all_harvest_shares_fruit)
    tags.push(t("commissioning.for_fruit_shares"));
  if (record.for_all_resellers) tags.push(t("commissioning.for_resellers"));
  if (record.for_all_markets) tags.push(t("commissioning.for_all_markets"));

  const rightSlot =
    amount != null && amount > 0 ? (
      <span style={{ fontWeight: 600 }}>
        {amount} {unitLabel}
      </span>
    ) : null;

  return (
    <MobileCard onClick={() => onEdit(record)} finalized={isFinalized}>
      <MobileCardContent>
        <MobileCardTitle
          name={articleName}
          sizeLabel={sizeLabel}
          finalized={isFinalized}
          rightSlot={rightSlot}
        />
        {(plotName || bedNumber != null) && (
          <div className="text-meta">
            {plotName && (
              <>
                {t("commissioning.plot")}: {plotName}
              </>
            )}
            {plotName && bedNumber != null && ", "}
            {bedNumber != null && (
              <>
                {t("commissioning.bed_number")}: {bedNumber}
              </>
            )}
          </div>
        )}
        {noteText && (
          <MobileCardNote note={noteText} />
        )}
        <MobileCardTags tags={tags} />
      </MobileCardContent>
    </MobileCard>
  );
}
