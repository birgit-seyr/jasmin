import { useTranslation } from "react-i18next";
import { useVegetableSizeOptions, useUnitOptions } from "@hooks/index";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import {
  MOBILE_CARD_PLACEHOLDER,
  MobileCard,
  MobileCardContent,
  MobileCardNote,
  MobileCardTags,
  MobileCardTitle,
  getSizeLabelOrEmpty,
} from "./primitives";

interface DocumentationCurrentStockMobileCardProps {
  record: TableRecord;
  onEdit: (record: TableRecord) => void;
}

export function DocumentationCurrentStockMobileCard({
  record,
  onEdit,
}: DocumentationCurrentStockMobileCardProps) {
  const { t } = useTranslation();
  const { getVegetableSizeLabel } = useVegetableSizeOptions();
  const { getUnitLabel } = useUnitOptions();

  const articleName = (record.share_article_name as string) || "";
  const sizeLabel = getSizeLabelOrEmpty(record.size as string, getVegetableSizeLabel);
  const unitLabel = getUnitLabel(record.unit as string);
  const expectedStock = record.theoretical_current_stock as
    | number
    | string
    | null
    | undefined;
  const actualStock = record.amount as number | null | undefined;
  const noteText = (record.note as string) || "";
  const isFinalized = !!record.is_finalized;

  const tags: string[] = [];
  if (record.for_shares) tags.push(t("commissioning.for_shares"));
  if (record.for_resellers) tags.push(t("commissioning.for_resellers"));

  const showActualUnit = !(expectedStock != null && expectedStock !== 0);

  return (
    <MobileCard onClick={() => onEdit(record)} finalized={isFinalized}>
      <MobileCardContent>
        <MobileCardTitle
          name={articleName}
          sizeLabel={sizeLabel}
          finalized={isFinalized}
        />
        <div style={{ display: "flex", gap: 24, marginTop: 6 }}>
          <div>
            <div className="text-muted-xs">{t("commissioning.expected")}</div>
            <div className="flex-baseline">
              <span style={{ fontWeight: 500, fontSize: "1.2em" }}>
                {expectedStock ?? MOBILE_CARD_PLACEHOLDER}
              </span>
              {unitLabel && <span className="text-secondary">{unitLabel}</span>}
            </div>
          </div>
          <div>
            <div className="text-muted-xs">{t("commissioning.actual")}</div>
            <div className="flex-baseline">
              <span
                style={{
                  fontWeight: 600,
                  fontSize: "1.2em",
                  color:
                    actualStock != null && actualStock > 0
                      ? "var(--color-success-text)"
                      : "var(--color-text-muted)",
                }}
              >
                {actualStock ?? MOBILE_CARD_PLACEHOLDER}
              </span>
              {unitLabel && showActualUnit && (
                <span className="text-secondary">{unitLabel}</span>
              )}
            </div>
          </div>
        </div>
        <MobileCardNote note={noteText} />
        <MobileCardTags tags={tags} />
      </MobileCardContent>
    </MobileCard>
  );
}
