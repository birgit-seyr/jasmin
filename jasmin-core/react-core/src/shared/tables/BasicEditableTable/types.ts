import type { FormInstance } from "antd";
import type { Dayjs } from "dayjs";
import type { CSSProperties, FocusEvent, KeyboardEvent, ReactNode, Key } from "react";

// ─── Input Types ────────────────────────────────────────────────────────────
export type InputType =
  | "text"
  | "select"
  | "checkbox"
  | "switch"
  | "date"
  | "datepicker"
  | "time"
  | "number"
  | "integer"
  | "positive_integer"
  | "negative_integer"
  | "positive_decimal2"
  | "negative_decimal2"
  | "positive_decimal3"
  | "negative_decimal3"
  | "decimal1"
  | "decimal2"
  | "decimal3"
  | "percentage"
  | "kw"
  | "optional";

// ─── Select Option ──────────────────────────────────────────────────────────
export interface SelectOption {
  label: string;
  value: string | number;
  // Greyed-out / non-selectable option (forwarded to AntD Select). Used e.g.
  // for full delivery-station-days in the capacity-aware pickers.
  disabled?: boolean;
}

// ─── Foreign Key ────────────────────────────────────────────────────────────
export interface ForeignKeyConfig {
  valueField: string;
  displayField: string;
}

// ─── Column Definition ──────────────────────────────────────────────────────
export interface EditableColumnConfig<T extends Record<string, unknown> = Record<string, unknown>> {
  title: ReactNode;
  dataIndex: string;
  key?: string;
  inputType?: InputType;
  required?: boolean;
  editable?: boolean;
  readOnly?: boolean;
  hideInModal?: boolean;
  excludeFromSave?: boolean;
  hidden?: boolean;
  width?: string | number;
  minWidth?: string | number;
  maxWidth?: string | number;
  align?: "left" | "center" | "right";
  fixed?: boolean | "left" | "right";
  sorter?: boolean | ((a: T, b: T) => number);
  /**
   * Opt in to an automatic sorter inferred from `inputType`
   * (string for text/select, number for numeric inputs, boolean for
   * checkbox/switch, date for date inputs). Ignored when an explicit
   * `sorter` is provided.
   */
  sortable?: boolean;
  options?: SelectOption[] | ((record: T) => SelectOption[]);
  foreignKey?: ForeignKeyConfig;
  disabled?: boolean | ((record: T) => boolean);
  suffix?: string;
  prefix?: string;
  className?: string;
  // ``record`` is the LIVE row (current form values merged) while editing, so
  // a date constraint can depend on a sibling field the user just picked
  // (e.g. valid_from bounded by the selected variation's own valid_from).
  disabledDate?: (current: Dayjs, record?: T) => boolean;
  onFieldChange?: (
    value: unknown,
    record: T,
    form: FormInstance,
    dataIndex: string,
  ) => Record<string, unknown> | undefined;
  render?: (value: unknown, record: T, index: number) => ReactNode;
  rules?: Array<Record<string, unknown>>;
  style?: CSSProperties;
  showSorterTooltip?: boolean;
  /**
   * Initial (uncontrolled) sort direction, forwarded to the AntD column.
   * Only takes effect when the column also defines a `sorter`.
   */
  defaultSortOrder?: "ascend" | "descend";
  onCell?: (record: T, index?: number) => Record<string, unknown>;
  children?: EditableColumnConfig<T>[];
  /** Optional per-column PDF export config consumed by `utils/pdfUtils.jsx`. */
  pdf?: EditableColumnPdfConfig;
}

/** Per-column PDF export config used by list-PDF generators. */
export interface EditableColumnPdfConfig {
  /** When true, include the column in the PDF output. */
  include?: boolean;
  /** Column width as percent string (e.g. "24%") or number. */
  width?: string | number;
  align?: "left" | "center" | "right";
  /** Header label rendered in the PDF (may differ from on-screen title). */
  title?: ReactNode;
  /** Field on the row to read for the PDF cell value. Defaults to dataIndex. */
  dataKey?: string;
  /** Optional override styles for the header cell. */
  headerStyle?: CSSProperties;
  /** Render an empty bordered "tick box" cell (printable ✓/done square). */
  tickBox?: boolean;
}

// ─── API Endpoints ──────────────────────────────────────────────────────────
export interface ApiEndpoints {
  list?: string;
  create?: string;
  update?: string;
  delete?: string;
}

// ─── API Functions (generated client alternative) ───────────────────────────
/**
 * The adapted endpoint set EditableTable consumes. Kept deliberately LOOSE
 * (envelopes of `unknown`): the table feeds raw form values in and a few call
 * sites build this object directly from Orval responses that lack the
 * table-only `key` field, so a typed envelope here would reject them for no
 * benefit. The typed, cast-eliminating surface lives on
 * {@link wrapApiFunctions} / `RawApiFunctions` (call-site facing) and on the
 * already-generic `EditableColumnConfig<T>` + `initialData: T[]`.
 */
export interface ApiFunctions {
  list?: (params?: Record<string, string>) => Promise<{ data: unknown }>;
  create?: (data: Record<string, unknown>) => Promise<{ data: unknown }>;
  update?: (id: string, data: Record<string, unknown>) => Promise<{ data: unknown }>;
  delete?: (id: string, data?: Record<string, unknown>) => Promise<unknown>;
}

// ─── Permissions ────────────────────────────────────────────────────────────
export interface TablePermissions<T extends Record<string, unknown> = Record<string, unknown>> {
  canAdd?: boolean;
  canEdit?: boolean;
  canDelete?: boolean;
  canDeleteRecord?: boolean | ((record: T) => boolean);
  canEditRecord?: boolean | ((record: T) => boolean);
}

// ─── Summary Row ────────────────────────────────────────────────────────────
export interface SummaryRow {
  label: string;
  subLabel?: string;
  columns: string[];
  data: Record<string, number | string>;
  subData?: Record<string, number | string>;
  subSuffix?: string;
  suffix?: string;
  summaryLabelColSpan?: number;
  style?: CSSProperties & {
    backgroundColor?: string;
    fontWeight?: string;
    borderTop?: string;
    borderBottom?: string;
    fontSize?: string;
    color?: string;
  };
}

// ─── Row Selection ──────────────────────────────────────────────────────────
export interface RowSelectionConfig<T extends Record<string, unknown> = Record<string, unknown>> {
  type?: "checkbox" | "radio";
  onSelect?: (record: T, selected: boolean, selectedRows: T[]) => void;
  onSelectAll?: (selected: boolean, selectedRows: T[], changeRows: T[]) => void;
  getCheckboxProps?: (record: T) => Record<string, unknown>;
  [key: string]: unknown;
}

// ─── Table Record ───────────────────────────────────────────────────────────
export interface TableRecord extends Record<string, unknown> {
  key: Key;
  id?: string | number;
}

// ─── customSave Result ──────────────────────────────────────────────────────
/**
 * Return shape of {@link EditableTableProps.customSave}. A plain object is the
 * (possibly rewritten) payload to persist; `null` aborts the save silently.
 * Setting the `__deleteOnSave` sentinel routes the row through the DELETE path
 * instead of saving — e.g. clearing an order's amount removes the OrderContent
 * row entirely rather than persisting a null-amount row.
 */
export interface CustomSaveResult extends Record<string, unknown> {
  __deleteOnSave?: boolean;
}

// ─── EditableTable Props ────────────────────────────────────────────────────
export interface EditableTableProps<T extends TableRecord = TableRecord> {
  columns: EditableColumnConfig<T>[];
  apiEndpoints?: ApiEndpoints;
  apiFunctions?: ApiFunctions;
  // Accepts any plain-object shape so call sites can pass their Orval-generated
  // *ListParams types directly without an `as unknown as Record<string,
  // string | number>` cast. Falsy / non-primitive values are filtered when
  // the table builds its internal query string.
  baseParams?: Record<string, unknown>;
  initialData?: T[];
  /**
   * External data-fetch loading flag, shown as the grid's spinner overlay
   * (OR-ed with the table's own save/delete loading). When the parent owns
   * the data (passes `initialData` from its own query instead of letting the
   * table auto-fetch via `showSearchBar` + `apiFunctions.list`), pass the
   * query's loading state here.
   *
   * Pass `isFetching` for filter-driven tables (a spinner on every
   * week/year/filter change, even when the new key is cached) or `isLoading`
   * for plain lists (a spinner only on the genuine first load). This is the
   * single supported way to drive the overlay — `loading` is no longer
   * forwarded to the inner AntD Table via prop spread.
   */
  loading?: boolean;
  onDataChange?: (data: T[]) => void;
  permissions?: TablePermissions<T>;
  showActions?: boolean;
  size?: "small" | "middle" | "large";
  customSave?: ((data: Record<string, unknown>, record: T) => CustomSaveResult | null) | null;
  customEdit?: ((record: T, form: FormInstance) => T) | null;
  customDelete?: ((record: T) => Record<string, unknown> | null) | null;
  customUpdate?: ((key: Key, data: Record<string, unknown>) => Promise<T>) | null;
  focusIndex?: string;
  rowSelection?: RowSelectionConfig<T> | null;
  onSelectedRowsChange?: ((keys: Key[], rows: T[]) => void) | null;
  selectedRowKeys?: Key[];
  summaryRows?: SummaryRow[];
  summaryLabelColumnIndex?: number;
  summaryPosition?: "top" | "bottom";
  pagination?: boolean;
  showSearchBar?: boolean;
  deleteContext?: Record<string, unknown> | string | null;
  forceInlineMode?: boolean;
  uniqueCheck?: string | string[] | null;
  uniqueCheckMessage?: string | null;
  onSaveSuccess?: ((record: T, type: "create" | "update") => void) | null;
  onDeleteSuccess?: ((key: Key) => void) | null;
  renderMobileCard?: (record: T, onEdit: (record: T) => void) => ReactNode;
  /**
   * If true, pressing "+" on the keyboard triggers the same logic as the add button.
   * Ignored while focus is inside an input, textarea, contenteditable element, or while a modal is open.
   */
  keyboardAddShortcut?: boolean;
  /**
   * If true (default), automatically computes `scroll.x` from the column widths
   * via `calculateTableScrollWidth`. Set to false to disable, or pass an
   * explicit `scroll.x` to override.
   */
  autoScrollX?: boolean;
  /**
   * If true (default), rows created during this mount are pinned to the top of
   * the table across refetches so a freshly-saved row stays visible instead of
   * sliding to an alphabetically-distant page. Set to false on tables where
   * server order is meaningful (e.g. manually sorted, position-based).
   */
  pinNewRowsToTop?: boolean;
  className?: string;
  scroll?: { x?: string | number; y?: string | number };
  /**
   * AntD ``Table`` pass-through props, forwarded via the internal prop spread.
   * Declared EXPLICITLY (rather than relying on a `[key: string]: unknown`
   * index signature) so prop typos are caught at the call site. These three —
   * `rowClassName`, `style`, `bordered` — are the only pass-throughs any call
   * site actually uses; add more here deliberately if a new one is needed.
   */
  rowClassName?: string | ((record: T, index: number) => string);
  style?: CSSProperties;
  bordered?: boolean;
}

// ─── useEditableTable Options ───────────────────────────────────────────────
export interface UseEditableTableOptions<T extends TableRecord = TableRecord> {
  apiEndpoints?: ApiEndpoints;
  apiFunctions?: ApiFunctions;
  onDataChange?: (data: T[]) => void;
  focusIndex?: string;
  columns?: EditableColumnConfig<T>[];
  customSave?: EditableTableProps<T>["customSave"];
  customEdit?: EditableTableProps<T>["customEdit"];
  customDelete?: EditableTableProps<T>["customDelete"];
  customUpdate?: EditableTableProps<T>["customUpdate"];
  deleteContext?: Record<string, unknown> | string | null;
  uniqueCheck?: string | string[] | null;
  uniqueCheckMessage?: string | null;
  autoHandleDates?: boolean;
  onSaveSuccess?: EditableTableProps<T>["onSaveSuccess"];
  onDeleteSuccess?: EditableTableProps<T>["onDeleteSuccess"];
}

// ─── useEditableTable Return ────────────────────────────────────────────────
export interface UseEditableTableReturn<T extends TableRecord = TableRecord> {
  form: FormInstance;
  data: T[];
  setDataWithTransform: (data: T[] | ((prev: T[]) => T[])) => void;
  loading: boolean;
  setLoading: (loading: boolean) => void;
  editingKey: Key | "";
  formErrors: Record<string, string>;
  /** Single human-readable message shown as a banner above the table after a
   * failed save (unique-check rejection or backend validation error). */
  saveErrorMessage: string | null;
  setSaveErrorMessage: (message: string | null) => void;
  clickedDataIndex: string | undefined;
  setClickedDataIndex: (index: string | undefined) => void;
  isEditing: (record: T) => boolean;
  edit: (record: T) => void;
  cancel: () => void;
  save: (key: Key, formValues?: Record<string, unknown>) => Promise<void>;
  add: () => Promise<T | undefined>;
  deleteRecord: (key: Key) => Promise<void>;
  /** IDs created during this mount, newest first. The table pins these to the
   * top across refetches so a freshly-saved row stays visible instead of
   * disappearing into an alphabetically-distant page. */
  recentlyAddedIds: string[];
  /** IDs deleted during this mount. The table filters these out of every
   * refetch so a just-deleted row can't briefly reappear (flicker) when a
   * stale refetch — one that raced ahead of the backend delete — still
   * contains it. IDs are unique nanoids that never recur, so this is harmless
   * once the backend catches up. */
  recentlyDeletedIds: string[];
}

// ─── EditableModal Props ────────────────────────────────────────────────────
export interface EditableModalProps<T extends TableRecord = TableRecord> {
  visible: boolean;
  onCancel: () => void;
  onSave: (values: Record<string, unknown>) => Promise<void>;
  record: T | null;
  columns: EditableColumnConfig<T>[];
  loading: boolean;
  customEdit?: EditableTableProps<T>["customEdit"];
  focusIndex?: string;
  uniqueCheck?: string | string[] | null;
  uniqueCheckMessage?: string | null;
  data?: T[];
}

// ─── EditableCell Props ─────────────────────────────────────────────────────
export interface EditableCellProps<T extends TableRecord = TableRecord> {
  editing: boolean;
  dataIndex: string;
  title: ReactNode;
  record: T;
  index: number;
  children: ReactNode;
  inputType?: InputType;
  required?: boolean;
  options?: SelectOption[] | ((record: T) => SelectOption[]);
  formErrors?: Record<string, string>;
  onCellClick?: (record: T, dataIndex: string) => void;
  columns?: EditableColumnConfig<T>[];
  form?: FormInstance;
  shouldFocus?: boolean;
  disabled?: boolean;
  save?: (key: Key) => void;
  style?: CSSProperties;
}

// ─── FormInput Props ────────────────────────────────────────────────────────
export interface FormInputProps {
  inputType?: InputType;
  options?: SelectOption[];
  /**
   * The column's `required` flag. For selects it is the single source of truth
   * for clearability: any select that is not `required: true` gets a leading
   * blank option auto-prepended so the value can be cleared (see FormInput).
   */
  required?: boolean;
  size?: "small" | "middle" | "large";
  placeholder?: string;
  title?: ReactNode;
  isModal?: boolean;
  onKeyDown?: (e: KeyboardEvent) => void;
  onFieldChange?: (
    value: unknown,
    record: Record<string, unknown>,
    form: FormInstance,
  ) => Record<string, unknown> | undefined;
  record?: Record<string, unknown>;
  form?: FormInstance;
  suffix?: string;
  className?: string;
  disabledDate?: (current: Dayjs) => boolean;
  value?: unknown;
  checked?: boolean;
  onChange?: (value: unknown) => void;
  onFocus?: (e: FocusEvent) => void;
  disabled?: boolean;
  prefix?: string;
  style?: CSSProperties;
  "aria-label"?: string;
  "aria-describedby"?: string;
  "aria-invalid"?: boolean;
}
