import { useTranslation } from "react-i18next";
import {
  useVegetableSizeOptions,
  useUnitOptions,
  getShareTypeVariationSizeLabelPure,
} from "@hooks/index";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import { variationColumnKey } from "@features/commissioning/hooks/columns/columnKeys";
import {
  MobileCard,
  MobileCardContent,
  MobileCardNote,
  getSizeLabelOrEmpty,
} from "./primitives";

export interface ShareTypeVariationOption {
  id?: number | string;
  size: string;
}

interface PackingListBoxesMobileCardProps {
  record: TableRecord;
  shareTypeVariations: ShareTypeVariationOption[];
}

export function PackingListBoxesMobileCard({
  record,
  shareTypeVariations,
}: PackingListBoxesMobileCardProps) {
  const { t } = useTranslation();
  const { getVegetableSizeLabel } = useVegetableSizeOptions();
  const { getUnitLabel } = useUnitOptions();

  const articleName = (record.share_article_name as string) || "";
  const sizeLabel = getSizeLabelOrEmpty(record.size as string, getVegetableSizeLabel);
  const unitLabel = getUnitLabel(record.unit as string);
  const noteText = (record.note as string) || "";

  const variations = shareTypeVariations
    .map((v) => ({
      label: getShareTypeVariationSizeLabelPure(v.size, t),
      value: (record as Record<string, unknown>)[variationColumnKey(v.id!)] as
        | number
        | string
        | null
        | undefined,
    }))
    .filter((v) => v.value != null && v.value !== "" && v.value !== 0);

  return (
    <MobileCard>
      <MobileCardContent>
        <div className="mobile-card-title">
          {articleName}
          {sizeLabel && <span className="text-hint">{sizeLabel}</span>}
          {unitLabel && <span className="text-hint">({unitLabel})</span>}
        </div>
        {variations.length > 0 && (
          <div
            style={{
              display: "flex",
              gap: 16,
              marginTop: 6,
              flexWrap: "wrap",
            }}
          >
            {variations.map((v) => (
              <div key={v.label} style={{ minWidth: 40, textAlign: "center" }}>
                <div className="text-muted-xs">{v.label}</div>
                <span style={{ fontWeight: 600, fontSize: "1.1em" }}>
                  {v.value}
                </span>
              </div>
            ))}
          </div>
        )}
        <MobileCardNote note={noteText} />
      </MobileCardContent>
    </MobileCard>
  );
}
