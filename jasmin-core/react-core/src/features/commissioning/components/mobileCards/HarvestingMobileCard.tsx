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
  getSizeLabelOrEmpty,
  stopPropagation,
} from "./primitives";
import "./HarvestingMobileCard.css";

interface HarvestingMobileCardProps {
  record: TableRecord;
  onEdit: (record: TableRecord) => void;
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

  const articleName = (record.share_article_name as string) || "";
  const sizeLabel = getSizeLabelOrEmpty(record.size as string, getVegetableSizeLabel);
  const perPuText = (record.computed_amount_per_pu_text as string) || "";
  const noteText = (record.computed_note_line as string) || "";
  const plotName = (record.forecast_plot_name as string) || "";
  const bedNumber = record.forecast_bed_number as number | null | undefined;

  const shareUnit =
    (record.computed_total_amount_text_share_content as string) || "";
  const sharePu = (record.computed_amount_pu_text_share_content as string) || "";
  const orderUnit =
    (record.computed_total_amount_text_order_content as string) || "";
  const orderPu = (record.computed_amount_pu_text_order_content as string) || "";
  const totalUnit = (record.computed_total_amount_text as string) || "";
  const totalPu = (record.computed_amount_pu_text as string) || "";

  const hasShare = !!(shareUnit || sharePu);
  const hasOrder = !!(orderUnit || orderPu);
  const hasTotal = !!(totalUnit || totalPu);
  const hasAnyAmount = hasShare || hasOrder || hasTotal;

  return (
    <>
      {showPlotHeader && plotName && (
        <div className="harvest-plot-header">{plotName}</div>
      )}
      <MobileCard onClick={() => onEdit(record)}>
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
            onClick={stopPropagation}
            onKeyDown={(e) => e.stopPropagation()}
            style={{
              display: "flex",
              alignItems: "center",
              marginLeft: 8,
              flexShrink: 0,
            }}
          >
            <Button
              shape="circle"
              size="large"
              onClick={() => onConfirmHarvest(record)}
              style={{
                width: 48,
                height: 48,
                backgroundColor: isConfirmed
                  ? "var(--color-success-bg)"
                  : "#fce4ec",
                borderColor: isConfirmed ? "#81c784" : "#ef9a9a",
                color: isConfirmed ? "var(--color-share-content)" : "#c62828",
                fontSize: 20,
              }}
              icon={<CheckOutlined />}
              title={t("commissioning.actual_harvest")}
            />
          </div>
        )}
      </MobileCard>
    </>
  );
}
