type Row = Record<string, unknown>;

/**
 * The structural subset of a column definition that width calculation reads.
 * `EditableColumnConfig` satisfies this shape, so callers can pass their
 * column arrays directly without casting.
 */
export interface ScrollColumn {
  hidden?: boolean;
  children?: ScrollColumn[];
  width?: string | number;
  inputType?: string;
  sorter?: unknown;
  dataIndex?: string;
}

/**
 * Calculate total scroll width for table columns including nested children.
 * @param rawColumns - Array of column definitions
 * @param additionalWidth - Additional width to add (default: 5)
 * @returns Total width in em units
 */
export const calculateTableScrollWidth = (
  rawColumns: readonly ScrollColumn[],
  additionalWidth = 5,
): string => {
  const calculateColumnWidth = (column: ScrollColumn): number => {
    if (column.hidden) {
      return 0;
    }

    // If column has children, calculate the sum of children widths
    if (column.children && column.children.length > 0) {
      return column.children.reduce((sum, child) => {
        return sum + calculateColumnWidth(child);
      }, 0);
    }

    // If column has explicit width
    if (
      column.width &&
      typeof column.width === "string" &&
      column.width.endsWith("em")
    ) {
      return parseFloat(column.width);
    }

    // Add width for checkbox columns that don't have width specified
    if (column.inputType === "checkbox" && !column.width) {
      // If checkbox has a sorter: 4em, otherwise: 2.5em
      return column.sorter ? 4 : 2.5;
    }

    // Add width for text columns that don't have width specified
    if (column.inputType === "text" && !column.width) {
      return 4;
    }

    // Add width for columns ending with "unit"
    if (column.dataIndex && column.dataIndex.endsWith("unit")) {
      return 6;
    }

    // Default width for other input types
    switch (column.inputType) {
      case "date":
        return 10;
      case "number":
        return 5;
      case "positive-decimal2":
        return 6;
      case "select":
        return 12;
      case "textarea":
        return 20;
      default:
        return 8; // Default width
    }
  };

  const totalWidth = rawColumns.reduce((sum, column) => {
    return sum + calculateColumnWidth(column);
  }, 0);

  return `${totalWidth + additionalWidth}em`;
};

export const createStringSorter =
  (field: string) =>
  (a: Row, b: Row): number =>
    String(a[field] ?? "").localeCompare(String(b[field] ?? ""));

export const createNumberSorter =
  (field: string) =>
  (a: Row, b: Row): number =>
    ((a[field] as number) || 0) - ((b[field] as number) || 0);

export const createBooleanSorter =
  (field: string, trueFirst = true) =>
  (a: Row, b: Row): number => {
    const aValue = !!a[field];
    const bValue = !!b[field];
    if (aValue === bValue) return 0;
    return trueFirst ? (aValue ? -1 : 1) : aValue ? 1 : -1;
  };

export const createDateSorter =
  (field: string, nullsLast = true) =>
  (a: Row, b: Row): number => {
    const aValue = a[field];
    const bValue = b[field];

    if (!aValue && !bValue) return 0;
    if (!aValue) return nullsLast ? 1 : -1;
    if (!bValue) return nullsLast ? -1 : 1;

    const aDate = new Date(aValue as string);
    const bDate = new Date(bValue as string);
    return aDate.getTime() - bDate.getTime();
  };
