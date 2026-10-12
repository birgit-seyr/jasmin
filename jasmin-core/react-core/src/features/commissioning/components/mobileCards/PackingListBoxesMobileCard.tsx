import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useUnitOptions, useVegetableSizeOptions } from "@hooks/index";
import type { PackingBoxesMatrixColumn } from "@shared/api/generated/models";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import {
  MobileCard,
  MobileCardContent,
  MobileCardMetric,
  MobileCardMetricsRow,
  MobileCardNote,
  MobileCardTitle,
} from "./primitives";
import { recordText } from "./recordText";
import { getSizeLabelOrEmpty } from "@features/commissioning/utils/sizeLabel";

/** The packing list's box-combination columns, grouped by share type. */
type CombinationGroups = EditableColumnConfig<TableRecord>[];

/** The combinations of the grouped columns in the table's order, each named
 *  by its share type and its combination as the table heads them — a box
 *  without a base share by its combination alone, which says so already. */
function combinationsOf(
  groups: CombinationGroups,
  columns: PackingBoxesMatrixColumn[],
): { key: string; label: ReactNode }[] {
  const withoutBase = new Set(
    columns.filter((column) => !column.base_variation_id).map((column) => column.key),
  );
  return groups.flatMap((group) =>
    (group.children ?? []).map((combination) => ({
      key: combination.dataIndex,
      label: withoutBase.has(combination.dataIndex) ? (
        combination.title
      ) : (
        <>
          {group.title} {combination.title}
        </>
      ),
    })),
  );
}

interface PackingListBoxesMobileCardProps {
  record: TableRecord;
  groups: CombinationGroups;
  columns: PackingBoxesMatrixColumn[];
  /** An amount's text, as the table's cell shows it. */
  amountText: (value: unknown, record: TableRecord) => string;
}

/** An article on the phone: how much of it goes into each kind of box. */
export function PackingListBoxesMobileCard({
  record,
  groups,
  columns,
  amountText,
}: PackingListBoxesMobileCardProps) {
  const { getVegetableSizeLabel } = useVegetableSizeOptions();
  const { getUnitLabel } = useUnitOptions();

  const unitLabel = getUnitLabel(record.unit as string);
  const amounts = combinationsOf(groups, columns)
    .map((combination) => ({
      ...combination,
      text: amountText(record[combination.key], record),
    }))
    .filter((combination) => combination.text !== "");

  return (
    <MobileCard>
      <MobileCardContent>
        <MobileCardTitle
          name={recordText(record, "share_article_name")}
          sizeLabel={getSizeLabelOrEmpty(
            record.size as string,
            getVegetableSizeLabel,
          )}
        />
        <MobileCardMetricsRow gap={16}>
          {amounts.map(({ key, label, text }) => (
            <MobileCardMetric
              key={key}
              label={label}
              value={text}
              unit={unitLabel}
            />
          ))}
        </MobileCardMetricsRow>
        <MobileCardNote note={recordText(record, "note")} />
      </MobileCardContent>
    </MobileCard>
  );
}

interface PackingListBoxesCountCardProps {
  groups: CombinationGroups;
  columns: PackingBoxesMatrixColumn[];
}

/** The phone's version of the table's box-count row. */
export function PackingListBoxesCountCard({
  groups,
  columns,
}: PackingListBoxesCountCardProps) {
  const { t } = useTranslation();
  const counts = new Map(columns.map((column) => [column.key, column.count]));
  return (
    <MobileCard>
      <MobileCardContent>
        <MobileCardTitle name={t("commissioning.box_count")} />
        <MobileCardMetricsRow gap={16}>
          {combinationsOf(groups, columns).map(({ key, label }) => (
            <MobileCardMetric
              key={key}
              label={label}
              value={String(counts.get(key) ?? 0)}
            />
          ))}
        </MobileCardMetricsRow>
      </MobileCardContent>
    </MobileCard>
  );
}
