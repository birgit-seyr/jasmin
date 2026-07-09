import { useVegetableSizeOptions } from "@hooks/index";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import {
  MobileCard,
  MobileCardContent,
  MobileCardNote,
  MobileCardTitle,
  getSizeLabelOrEmpty,
} from "./primitives";

interface WashingMobileCardProps {
  record: TableRecord;
  onEdit: (record: TableRecord) => void;
}

export function WashingMobileCard({
  record,
  onEdit,
}: WashingMobileCardProps) {
  const { getVegetableSizeLabel } = useVegetableSizeOptions();
  const articleName = (record.share_article_name as string) || "";
  const sizeLabel = getSizeLabelOrEmpty(record.size as string, getVegetableSizeLabel);
  const washAmountText =
    (record.computed_total_wash_amount_text as string) || "";
  const noteText = (record.note as string) || "";

  return (
    <MobileCard onClick={() => onEdit(record)}>
      <MobileCardContent>
        <MobileCardTitle name={articleName} sizeLabel={sizeLabel} />
        {washAmountText && (
          <div style={{ fontSize: "0.9em", marginTop: 2, fontWeight: 600 }}>
            {washAmountText}
          </div>
        )}
        <MobileCardNote note={noteText} />
      </MobileCardContent>
    </MobileCard>
  );
}
