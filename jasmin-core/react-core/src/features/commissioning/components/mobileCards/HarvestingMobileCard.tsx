import { CheckOutlined } from "@ant-design/icons";
import { Button } from "antd";
import { useTranslation } from "react-i18next";
import { useVegetableSizeOptions } from "@hooks/index";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import {
  MobileCard,
  MobileCardContent,
  MobileCardNote,
  MobileCardTitle,
} from "./primitives";
import { recordText } from "./recordText";
import { getSizeLabelOrEmpty } from "./sizeLabel";
import "./HarvestingMobileCard.css";

interface HarvestingMobileCardProps {
  record: TableRecord;
  /** Opens the row's edit dialog; absent where the row can't be edited. */
  onEdit?: (record: TableRecord) => void;
  onConfirmHarvest: (record: TableRecord) => void;
  /** Whether to show the plot-name header above this card (computed by the
   *  parent: true when this row starts a new plot group). */
  showPlotHeader: boolean;
  /** True if the user has already confirmed this harvest in the current
   *  session (or it has a saved harvest_amount > 0). */
  isConfirmed: boolean;
  isPast: boolean;
}

interface AmountRowProps {
  label: string;
  unitText: string;
  puText: string;
  /** className for row coloring (e.g. "text-share-content"). */
  colorClassName?: string;
  bold?: boolean;
  showBorderTop?: boolean;
}

function AmountRow({
  label,
  unitText,
  puText,
  colorClassName,
  bold,
  showBorderTop,
}: AmountRowProps) {
  const classes = [
    colorClassName,
    bold ? "is-bold" : null,
    showBorderTop ? "has-border-top" : null,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <tr className={classes || undefined}>
      <td>{label}</td>
      <td className="cell-numeric">{unitText}</td>
      <td className="cell-numeric">{puText}</td>
    </tr>
  );
}

export function HarvestingMobileCard({
  record,
  onEdit,
  onConfirmHarvest,
  showPlotHeader,
  isConfirmed,
  isPast,
}: HarvestingMobileCardProps) {
  const { t } = useTranslation();
  const { getVegetableSizeLabel } = useVegetableSizeOptions();

  const articleName = recordText(record, "share_article_name");
  const sizeLabel = getSizeLabelOrEmpty(record.size as string, getVegetableSizeLabel);
  const perPuText = recordText(record, "computed_amount_per_pu_text");
  const noteText = recordText(record, "computed_note_line");
  const plotName = recordText(record, "forecast_plot_name");
  const bedNumber = record.forecast_bed_number as number | null | undefined;

  const shareUnit = recordText(
    record,
    "computed_total_amount_text_share_content",
  );
  const sharePu = recordText(record, "computed_amount_pu_text_share_content");
  const orderUnit = recordText(
    record,
    "computed_total_amount_text_order_content",
  );
  const orderPu = recordText(record, "computed_amount_pu_text_order_content");
  const totalUnit = recordText(record, "computed_total_amount_text");
  const totalPu = recordText(record, "computed_amount_pu_text");

  const hasShare = !!(shareUnit || sharePu);
  const hasOrder = !!(orderUnit || orderPu);
  const hasTotal = !!(totalUnit || totalPu);
  const hasAnyAmount = hasShare || hasOrder || hasTotal;

  return (
    <>
      {showPlotHeader && plotName && (
        <div className="harvest-plot-header">{plotName}</div>
      )}
      <MobileCard onClick={onEdit && (() => onEdit(record))}>
        {bedNumber != null && (
          <div className="harvest-bed-number">
            {t("commissioning.bed_number")}: {bedNumber}
          </div>
        )}
        <MobileCardContent>
          <MobileCardTitle name={articleName} sizeLabel={sizeLabel} />
          {perPuText && (
            <div className="harvest-per-pu-hint">{perPuText}</div>
          )}
          {hasAnyAmount && (
            <table className="harvest-amounts-table">
              <tbody>
                {hasShare && (
                  <AmountRow
                    label={`${t("commissioning.title_share_content")}:`}
                    unitText={shareUnit}
                    puText={sharePu}
                    colorClassName="text-share-content"
                  />
                )}
                {hasOrder && (
                  <AmountRow
                    label={`${t("commissioning.title_order_content")}:`}
                    unitText={orderUnit}
                    puText={orderPu}
                    colorClassName="text-order-content"
                  />
                )}
                {hasTotal && (
                  <AmountRow
                    label="Σ"
                    unitText={totalUnit}
                    puText={totalPu}
                    bold
                    showBorderTop
                  />
                )}
              </tbody>
            </table>
          )}
          <MobileCardNote note={noteText} />
        </MobileCardContent>

        {!isPast && (
          // Wrapper only stops the card's click/keydown (edit) from firing when
          // the action button inside is activated — it is not itself a control.
          // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- propagation boundary around interactive children
          <div
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
            className="harvest-confirm-action"
          >
            <Button
              shape="circle"
              size="large"
              onClick={() => onConfirmHarvest(record)}
              className={
                isConfirmed
                  ? "harvest-confirm-button is-confirmed"
                  : "harvest-confirm-button"
              }
              icon={<CheckOutlined />}
              title={t("commissioning.actual_harvest")}
              aria-label={t("commissioning.actual_harvest")}
            />
          </div>
        )}
      </MobileCard>
    </>
  );
}
