import type { DocumentationSummaryRecord } from "@features/commissioning/hooks/useDocumentationSummaryPage";

// Server ids are alphanumeric, so none can start with this prefix.
const NEXT_WEEK_ONLY_ID_PREFIX = "next_week_only:";

/**
 * Whether a table key names a row of an article only next week needs. Such a
 * row has no entry in the selected week yet, so its save creates one. The
 * table keeps the key after that save brings back the new entry's id, until
 * the refetch replaces the row, so the decision goes by key, never by id.
 */
export const isNextWeekOnlyRowKey = (key: unknown): boolean =>
  typeof key === "string" && key.startsWith(NEXT_WEEK_ONLY_ID_PREFIX);

const articleLine = (row: DocumentationSummaryRecord) =>
  `${row.share_article}_${row.unit}_${row.size}`;

const hasAmounts = (row: DocumentationSummaryRecord) =>
  !!(
    row.theoretical_purchase_amount ||
    row.additional_theoretical_purchase_amount ||
    row.purchase_amount
  );

/**
 * A row for an article line only next week needs, built from next week's row.
 * It keeps next week's PU, stock and seller, but takes an id of its own and
 * this week's amounts and note, which are empty, so a save cannot reach next
 * week's entry.
 */
function nextWeekOnlyRow(
  line: string,
  nextWeekRow: DocumentationSummaryRecord,
  nextWeekTheoretical: number,
): DocumentationSummaryRecord {
  return {
    ...nextWeekRow,
    id: `${NEXT_WEEK_ONLY_ID_PREFIX}${line}`,
    theoretical_id: null,
    additional_id: null,
    theoretical_purchase_amount: 0,
    additional_theoretical_purchase_amount: 0,
    purchase_amount: null,
    note: "",
    next_week_theoretical: nextWeekTheoretical,
  };
}

/**
 * The purchase list's rows: the selected week's rows with an amount, each
 * with next week's theoretical amount of its line, then a row for every other
 * line next week needs. Such a line shows the selected week's own row when
 * the week has one without amounts, so its save updates that entry; only a
 * line the week lacks gets a next-week-only row. `nextWeekRows` is undefined
 * when next week isn't included. Every row is a new object, so the query's
 * cached rows stay as the server sent them.
 */
export function mergePurchaseListRows(
  currentWeekRows: DocumentationSummaryRecord[] | undefined,
  nextWeekRows: DocumentationSummaryRecord[] | undefined,
): DocumentationSummaryRecord[] {
  const currentRows = currentWeekRows ?? [];
  const listedRows = currentRows.filter(hasAmounts);
  if (!nextWeekRows) {
    return listedRows.map((row) => ({ ...row, next_week_theoretical: 0 }));
  }

  const nextWeekByLine = new Map<string, DocumentationSummaryRecord>();
  for (const row of nextWeekRows) nextWeekByLine.set(articleLine(row), row);

  const rows: DocumentationSummaryRecord[] = listedRows.map((row) => ({
    ...row,
    next_week_theoretical:
      nextWeekByLine.get(articleLine(row))?.theoretical_purchase_amount ?? 0,
  }));
  const listedLines = new Set(listedRows.map(articleLine));
  for (const [line, nextWeekRow] of nextWeekByLine) {
    const nextWeekTheoretical = nextWeekRow.theoretical_purchase_amount ?? 0;
    if (!nextWeekTheoretical || listedLines.has(line)) continue;
    const currentWeekRow = currentRows.find((row) => articleLine(row) === line);
    rows.push(
      currentWeekRow
        ? { ...currentWeekRow, next_week_theoretical: nextWeekTheoretical }
        : nextWeekOnlyRow(line, nextWeekRow, nextWeekTheoretical),
    );
  }
  return rows;
}
