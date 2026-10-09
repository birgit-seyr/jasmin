/**
 * Small readers for column configs built by the column hooks: find a column
 * (also inside groups), render one of its cells, evaluate its `disabled`.
 */
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";

export type Column = EditableColumnConfig<TableRecord>;

/** A column's identity: its key, or its dataIndex when it carries none. */
export const columnId = (column: Column): string =>
  String(column.key ?? column.dataIndex);

export const columnIds = (columns: Column[]): string[] => columns.map(columnId);

/** Find a column by key or dataIndex, searching group children too. */
export function findColumn(columns: Column[], id: string): Column {
  for (const column of columns) {
    if (column.key === id || column.dataIndex === id) return column;
    if (column.children) {
      try {
        return findColumn(column.children, id);
      } catch {
        // not in this group
      }
    }
  }
  throw new Error(`no column ${id}`);
}

export const hasColumn = (columns: Column[], id: string): boolean => {
  try {
    findColumn(columns, id);
    return true;
  } catch {
    return false;
  }
};

/** Render one cell of a column and return the element holding it. */
export function renderCell(
  column: Column,
  value: unknown,
  record: TableRecord,
): HTMLElement {
  if (!column.render) throw new Error(`${columnId(column)} has no render`);
  const cell = column.render(value, record, 0) as ReactNode;
  return render(<>{cell}</>).container;
}

/** The text a cell shows. */
export const cellText = (
  column: Column,
  value: unknown,
  record: TableRecord,
): string => renderCell(column, value, record).textContent ?? "";

/** A column's `disabled`, evaluated for a row. */
export function isDisabled(column: Column, record: TableRecord): boolean {
  const { disabled } = column;
  return typeof disabled === "function" ? disabled(record) : Boolean(disabled);
}

/** The text of a title node. */
export const titleText = (title: ReactNode): string =>
  render(<>{title}</>).container.textContent ?? "";
