type Row = Record<string, unknown>;

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
