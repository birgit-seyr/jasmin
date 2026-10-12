import { useVegetableSizeOptions } from "@hooks/index";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import {
  MobileCard,
  MobileCardContent,
  MobileCardNote,
  MobileCardTitle,
} from "./primitives";
import { recordText } from "./recordText";
import { getSizeLabelOrEmpty } from "@features/commissioning/utils/sizeLabel";
import "./WashingMobileCard.css";

interface WashingMobileCardProps {
  record: TableRecord;
  /** Opens the row's edit dialog; absent where the row can't be edited. */
  onEdit?: (record: TableRecord) => void;
}

export function WashingMobileCard({
  record,
  onEdit,
}: WashingMobileCardProps) {
  const { getVegetableSizeLabel } = useVegetableSizeOptions();
  const articleName = recordText(record, "share_article_name");
  const sizeLabel = getSizeLabelOrEmpty(record.size as string, getVegetableSizeLabel);
  const washAmountText = recordText(record, "computed_total_wash_amount_text");
  const noteText = recordText(record, "note");

  return (
    <MobileCard onClick={onEdit && (() => onEdit(record))}>
      <MobileCardContent>
        <MobileCardTitle name={articleName} sizeLabel={sizeLabel} />
        {washAmountText && (
          <div className="washing-card-amount">
            {washAmountText}
          </div>
        )}
        <MobileCardNote note={noteText} />
      </MobileCardContent>
    </MobileCard>
  );
}
