/**
 * CSV utilities shared by the CSV export modals.
 *
 * The dialect (delimiter, decimal separator, date format) is selected by a
 * tenant-level preset stored on ``Tenant.csv_format``:
 *
 *   - ``"de"`` (default): ``;`` delimiter, ``,`` decimal, ``dd.mm.yyyy`` dates
 *   - ``"en"``:           ``,`` delimiter, ``.`` decimal, ``yyyy-mm-dd`` dates
 */

import { downloadBlob } from "./downloadBlob";

export type CsvPreset = "de" | "en";

export interface CsvDialect {
  delimiter: string;
  decimalSeparator: string;
  dateFormat: "dd.mm.yyyy" | "yyyy-mm-dd";
}

const PRESETS: Record<CsvPreset, CsvDialect> = {
  de: { delimiter: ";", decimalSeparator: ",", dateFormat: "dd.mm.yyyy" },
  en: { delimiter: ",", decimalSeparator: ".", dateFormat: "yyyy-mm-dd" },
};

export function resolveCsvDialect(preset?: string | null): CsvDialect {
  const key = (preset ?? "de").toLowerCase() as CsvPreset;
  return PRESETS[key] ?? PRESETS.de;
}

function formatDate(value: Date, format: CsvDialect["dateFormat"]): string {
  const dd = String(value.getDate()).padStart(2, "0");
  const mm = String(value.getMonth() + 1).padStart(2, "0");
  const yyyy = String(value.getFullYear());
  return format === "dd.mm.yyyy" ? `${dd}.${mm}.${yyyy}` : `${yyyy}-${mm}-${dd}`;
}

/**
 * A cell whose value is a decimal amount. The API sends money and other
 * decimals as strings ("2.50"), which can't be told apart from text such as an
 * article number "1.10", so a column marks its values with this to have them
 * written with the dialect's decimal separator.
 */
class CsvDecimalCell {
  constructor(readonly value: unknown) {}
}

export function csvDecimal(value: unknown): CsvDecimalCell {
  return new CsvDecimalCell(value);
}

// The canonical form the API sends a decimal in: digits with an optional
// point, no grouping, no exponent.
const DECIMAL_STRING = /^-?\d+(\.\d+)?$/;

function withDecimalSeparator(text: string, dialect: CsvDialect): string {
  return dialect.decimalSeparator === "."
    ? text
    : text.replace(".", dialect.decimalSeparator);
}

/**
 * The value a cell is written from: a marked decimal that is a number or a
 * canonical decimal string stays marked; anything else in a marked cell is
 * written as the plain value it is, so text keeps its formula guard.
 */
function unwrapCell(raw: unknown): unknown {
  if (!(raw instanceof CsvDecimalCell)) return raw;
  const { value } = raw;
  if (typeof value === "number") return value;
  if (typeof value === "string" && DECIMAL_STRING.test(value)) return raw;
  return value;
}

/**
 * Convert a value to its dialect-specific string representation.
 * Numbers and marked decimals get the dialect decimal separator, Dates the
 * dialect date format.
 */
function formatCsvValue(raw: unknown, dialect: CsvDialect): string {
  const cell = unwrapCell(raw);
  if (cell === null || cell === undefined) return "";
  if (cell instanceof CsvDecimalCell) {
    return withDecimalSeparator(String(cell.value), dialect);
  }
  if (cell instanceof Date) return formatDate(cell, dialect.dateFormat);
  if (typeof cell === "number") return withDecimalSeparator(String(cell), dialect);
  return String(cell);
}

// CSV formula-injection trigger chars (OWASP): a spreadsheet treats a cell
// starting with one of these as a formula. Mirrors the backend
// apps/shared/csv_safety.py::_DANGEROUS_LEAD.
const CSV_FORMULA_LEAD = /^[=+\-@\t\r]/;

/**
 * Escape a single cell value for the given dialect.
 */
function escapeCsvValue(
  raw: unknown,
  dialect: CsvDialect = PRESETS.de,
): string {
  const cell = unwrapCell(raw);
  let str = formatCsvValue(cell, dialect);
  // Formula-injection neutralization: prefix a genuine TEXT cell that starts
  // with a formula trigger with a ``'`` so Excel/Sheets treat it as text.
  // Only string inputs — a numeric -5, a marked decimal or a Date must not be
  // prefixed (matches csv_safety.py, which guards on ``isinstance(value, str)``).
  if (typeof cell === "string" && CSV_FORMULA_LEAD.test(str)) {
    str = `'${str}`;
  }
  if (str.includes(dialect.delimiter) || str.includes('"') || str.includes("\n")) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

/**
 * Build a complete CSV string from headers and rows. Headers are normalized
 * by collapsing newlines into spaces. Rows are arrays of unknown values.
 */
export function buildCsvString(
  headers: string[],
  rows: unknown[][],
  dialect: CsvDialect = PRESETS.de,
): string {
  const cleanHeaders = headers.map((h) => h.replace(/[\n\r]+/g, " ").trim());
  const lines = [cleanHeaders.map((h) => escapeCsvValue(h, dialect)).join(dialect.delimiter)];
  for (const row of rows) {
    lines.push(row.map((v) => escapeCsvValue(v, dialect)).join(dialect.delimiter));
  }
  return lines.join("\n");
}

/**
 * Trigger a browser download for the given CSV content. A UTF-8 BOM is prepended
 * automatically so Excel detects the encoding correctly.
 */
export function downloadCsvBlob(
  content: BlobPart,
  filename: string,
): void {
  const bom = "\uFEFF";
  const parts: BlobPart[] =
    typeof content === "string" ? [bom + content] : [bom, content];
  const blob = new Blob(parts, { type: "text/csv;charset=utf-8;" });
  downloadBlob(blob, filename.endsWith(".csv") ? filename : `${filename}.csv`);
}

// Test-only access to the internal cell helpers (not part of the public CSV
// API — production code builds CSVs via ``buildCsvString`` / ``downloadCsvBlob``).
export const __csvInternalsForTests = { formatCsvValue, escapeCsvValue };
