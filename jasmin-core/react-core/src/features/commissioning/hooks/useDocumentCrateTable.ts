import { useCallback, useMemo, useState } from "react";
import type { CrateItemSummary } from "@shared/api/generated/models/crateItemSummary";
import { sameCellValue } from "@shared/tables/BasicEditableTable/duplicateErrors";
import { RowSaveRefused } from "@shared/tables/BasicEditableTable/RowSaveRefused";
import type {
  ApiFunctions,
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { useCratesColumns } from "./columns/useCratesColumns";

/**
 * Refuses a new crate line of a crate type that `rows` already list, with
 * `message` on the crate type: the office changes that type's line instead.
 * Saved lines may share a crate type, each billing it at its own price,
 * discount or VAT rate, so only a new row is checked.
 */
export function refuseRepeatedCrateType(
  rows: readonly Record<string, unknown>[],
  data: Record<string, unknown>,
  record: TableRecord,
  message: string,
): void {
  const crateType = data.crate_type;
  if (record.key !== -1 || crateType == null || crateType === "") return;
  if (rows.some((row) => sameCellValue(row.crate_type, crateType))) {
    throw new RowSaveRefused(message, { crate_type_name: message });
  }
}

interface DocumentCrateTableOptions {
  /** The document's crate lines, as its retrieve lists them. */
  crateItems: readonly CrateItemSummary[] | undefined;
  /** The field that names the document in a crate line's write body. */
  documentField: "delivery_note_id" | "invoice_id";
  documentId: string | null;
  canWrite: boolean;
  apiFunctions: ApiFunctions;
  /** Reads the document again. */
  refetchDocument: () => void;
  /** Why a new line of a crate type the document lists is refused. */
  repeatedTypeMessage: string;
  withoutPrice?: boolean;
}

/**
 * The `EditableTable` props of a delivery note's or an invoice's crate table.
 *
 * A document has a crate line per crate type, price, discount and VAT rate,
 * so one type can have several lines, each with an id of its own. A new line
 * takes a crate type the document doesn't list yet, and the picker offers no
 * other. A saved line can merge with another line of its type, so every save
 * and delete reads the document again. `rows` are the lines the table holds,
 * its edits included, for totals worked out from them.
 *
 * The table remembers the lines saved and deleted on it by id for as long as
 * it is mounted, so the caller keys it by the document: another document
 * gets a table of its own.
 */
export function useDocumentCrateTable({
  crateItems,
  documentField,
  documentId,
  canWrite,
  apiFunctions,
  refetchDocument,
  repeatedTypeMessage,
  withoutPrice,
}: DocumentCrateTableOptions) {
  const { cratesColumns, crates: crateOptions } = useCratesColumns({
    without_price: withoutPrice,
  });
  const lines = useMemo<(CrateItemSummary & TableRecord)[]>(
    () => (crateItems ?? []).map((item) => ({ ...item, key: item.id })),
    [crateItems],
  );

  // The table reports its rows after each save and delete; they stand until
  // the document is read again.
  const [reported, setReported] = useState<{
    from: TableRecord[];
    rows: TableRecord[];
  } | null>(null);
  const rows = reported?.from === lines ? reported.rows : lines;
  const onDataChange = useCallback(
    (tableRows: TableRecord[]) => setReported({ from: lines, rows: tableRows }),
    [lines],
  );

  const unlistedCrateTypes = useMemo(() => {
    const listed = new Set(rows.map((row) => row.crate_type));
    return crateOptions.filter((option) => !listed.has(option.value));
  }, [crateOptions, rows]);

  const columns = useMemo(
    () =>
      cratesColumns.map((column) =>
        column.key === "crate_type_name"
          ? { ...column, options: unlistedCrateTypes }
          : column,
      ) as EditableColumnConfig[],
    [cratesColumns, unlistedCrateTypes],
  );

  const permissions = useMemo(
    () => ({
      canAdd: canWrite && unlistedCrateTypes.length > 0,
      canEdit: canWrite,
      canDelete: canWrite,
    }),
    [canWrite, unlistedCrateTypes],
  );

  const customSave = useCallback(
    (data: Record<string, unknown>, record: TableRecord) => {
      refuseRepeatedCrateType(rows, data, record, repeatedTypeMessage);
      return { ...data, [documentField]: documentId };
    },
    [rows, repeatedTypeMessage, documentField, documentId],
  );

  const customDelete = useCallback(
    (record: TableRecord) => ({
      crate_type: record.crate_type,
      [documentField]: documentId,
    }),
    [documentField, documentId],
  );

  return {
    rows,
    tableProps: {
      columns,
      apiFunctions,
      initialData: lines,
      permissions,
      customSave,
      customDelete,
      onDataChange,
      onSaveSuccess: refetchDocument,
      onDeleteSuccess: refetchDocument,
    },
  };
}
