import { useTranslation } from "react-i18next";
import { useNumberFormat, useVegetableSizeOptions, useUnitOptions } from "@hooks/index";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import { formatAmountForUnit } from "@shared/utils";
import {
  MOBILE_CARD_PLACEHOLDER,
  MobileCard,
  MobileCardContent,
  MobileCardNote,
  MobileCardTitle,
} from "./primitives";
import { recordText } from "./recordText";
import { getSizeLabelOrEmpty } from "@features/commissioning/utils/sizeLabel";
import "./DocumentationMobileCard.css";

interface DocumentationHarvestMobileCardProps {
  record: TableRecord;
  /** Opens the row's edit dialog; absent where the row can't be edited. */
  onEdit?: (record: TableRecord) => void;
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
  const { format } = useNumberFormat();

  const articleName = recordText(record, "share_article_name");
  const sizeLabel = getSizeLabelOrEmpty(record.size as string, getVegetableSizeLabel);
  const unitLabel = getUnitLabel(record.unit as string);
  const unit = record.unit as string | undefined;
  // A decimal string on the wire ("14.500").
  const actualAmount = record.harvest_amount as string | number | null | undefined;
  const noteText = recordText(record, "note");
  const isFinalized = !!record.is_finalized;

  const theoreticalAmount = !isLongTermStorage
    ? ((record.theoretical_harvest_amount as number) || 0) +
      ((record.additional_theoretical_harvest_amount as number) || 0)
    : 0;

  const showActualUnit = !(!isLongTermStorage && theoreticalAmount > 0);

  return (
    <MobileCard onClick={onEdit && (() => onEdit(record))} finalized={isFinalized}>
      <MobileCardContent>
        <MobileCardTitle
          name={articleName}
          sizeLabel={sizeLabel}
          finalized={isFinalized}
        />
        <div className="documentation-card-figures">
          {!isLongTermStorage && (
            <div>
              <div className="text-muted-xs">{t("commissioning.expected")}</div>
              <div className="flex-baseline">
                <span className="documentation-card-amount">
                  {theoreticalAmount > 0
                    ? formatAmountForUnit(theoreticalAmount, unit, format)
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
                className={`documentation-card-amount is-actual${
                  actualAmount != null && Number(actualAmount) > 0 ? " has-amount" : ""
                }`}
              >
                {actualAmount == null || actualAmount === ""
                  ? MOBILE_CARD_PLACEHOLDER
                  : formatAmountForUnit(Number(actualAmount), unit, format)}
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
