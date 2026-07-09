import { useTranslation } from "react-i18next";
import { useVegetableSizeOptions, useUnitOptions } from "@hooks/index";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import {
  MOBILE_CARD_PLACEHOLDER,
  MobileCard,
  MobileCardContent,
  MobileCardNote,
  MobileCardTitle,
  getSizeLabelOrEmpty,
} from "./primitives";

interface DocumentationHarvestMobileCardProps {
  record: TableRecord;
  onEdit: (record: TableRecord) => void;
  isLongTermStorage: boolean;
}

export function DocumentationHarvestMobileCard({
  record,
  onEdit,
  isLongTermStorage,
}: DocumentationHarvestMobileCardProps) {
  const { t } = useTranslation();
  const { getVegetableSizeLabel } = useVegetableSizeOptions();
  const { getUnitLabel } = useUnitOptions();

  const articleName = (record.share_article_name as string) || "";
  const sizeLabel = getSizeLabelOrEmpty(record.size as string, getVegetableSizeLabel);
  const unitLabel = getUnitLabel(record.unit as string);
  const actualAmount = record.harvest_amount as number | null | undefined;
  const noteText = (record.note as string) || "";
  const isFinalized = !!record.is_finalized;

  const theoreticalAmount = !isLongTermStorage
    ? ((record.theoretical_harvest_amount as number) || 0) +
      ((record.additional_theoretical_harvest_amount as number) || 0)
    : 0;

  const showActualUnit = !(!isLongTermStorage && theoreticalAmount > 0);

  return (
    <MobileCard onClick={() => onEdit(record)} finalized={isFinalized}>
      <MobileCardContent>
        <MobileCardTitle
          name={articleName}
          sizeLabel={sizeLabel}
          finalized={isFinalized}
        />
        <div style={{ display: "flex", gap: 24, marginTop: 6 }}>
          {!isLongTermStorage && (
            <div>
              <div className="text-muted-xs">{t("commissioning.expected")}</div>
              <div className="flex-baseline">
                <span style={{ fontWeight: 500, fontSize: "1.2em" }}>
                  {theoreticalAmount > 0
                    ? theoreticalAmount
                    : MOBILE_CARD_PLACEHOLDER}
                </span>
                {unitLabel && <span className="text-secondary">{unitLabel}</span>}
              </div>
            </div>
          )}
          <div>
            <div className="text-muted-xs">{t("commissioning.actual")}</div>
            <div className="flex-baseline">
              <span
                style={{
                  fontWeight: 600,
                  fontSize: "1.2em",
                  color:
                    actualAmount != null && (actualAmount as number) > 0
                      ? "var(--color-success-text)"
                      : "var(--color-text-muted)",
                }}
              >
                {actualAmount ?? MOBILE_CARD_PLACEHOLDER}
              </span>
              {unitLabel && showActualUnit && (
                <span className="text-secondary">{unitLabel}</span>
              )}
            </div>
          </div>
        </div>
        <MobileCardNote note={noteText} />
      </MobileCardContent>
    </MobileCard>
  );
}
