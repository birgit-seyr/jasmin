import { useTranslation } from "react-i18next";
import { useNumberFormat, useVegetableSizeOptions, useUnitOptions } from "@hooks/index";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import {
  MOBILE_CARD_PLACEHOLDER,
  MobileCard,
  MobileCardContent,
  MobileCardNote,
  MobileCardTags,
  MobileCardTitle,
} from "./primitives";
import { recordText } from "./recordText";
import { getSizeLabelOrEmpty } from "@features/commissioning/utils/sizeLabel";
import "./DocumentationMobileCard.css";

interface DocumentationCurrentStockMobileCardProps {
  record: TableRecord;
  /** Opens the row's edit dialog; absent where the row can't be edited. */
  onEdit?: (record: TableRecord) => void;
}

export function DocumentationCurrentStockMobileCard({
  record,
  onEdit,
}: DocumentationCurrentStockMobileCardProps) {
  const { t } = useTranslation();
  const { getVegetableSizeLabel } = useVegetableSizeOptions();
  const { getUnitLabel } = useUnitOptions();
  const { format } = useNumberFormat();
  // Whole units, as the current-stock table shows them.
  const stockText = (value: number | string | null | undefined) =>
    value == null || value === ""
      ? MOBILE_CARD_PLACEHOLDER
      : format(Number(value), 0);

  const articleName = recordText(record, "share_article_name");
  const sizeLabel = getSizeLabelOrEmpty(record.size as string, getVegetableSizeLabel);
  const unitLabel = getUnitLabel(record.unit as string);
  const expectedStock = record.theoretical_current_stock as
    | number
    | string
    | null
    | undefined;
  const actualStock = record.amount as number | null | undefined;
  const noteText = recordText(record, "note");
  const isFinalized = !!record.is_finalized;

  const tags: string[] = [];
  if (record.for_shares) tags.push(t("commissioning.for_shares"));
  if (record.for_resellers) tags.push(t("commissioning.for_resellers"));

  const showActualUnit = !(expectedStock != null && expectedStock !== 0);

  return (
    <MobileCard onClick={onEdit && (() => onEdit(record))} finalized={isFinalized}>
      <MobileCardContent>
        <MobileCardTitle
          name={articleName}
          sizeLabel={sizeLabel}
          finalized={isFinalized}
        />
        <div className="documentation-card-figures">
          <div>
            <div className="text-muted-xs">{t("commissioning.expected")}</div>
            <div className="flex-baseline">
              <span className="documentation-card-amount">
                {stockText(expectedStock)}
              </span>
              {unitLabel && <span className="text-secondary">{unitLabel}</span>}
            </div>
          </div>
          <div>
            <div className="text-muted-xs">{t("commissioning.actual")}</div>
            <div className="flex-baseline">
              <span
                className={`documentation-card-amount is-actual${
                  actualStock != null && actualStock > 0 ? " has-amount" : ""
                }`}
              >
                {stockText(actualStock)}
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
