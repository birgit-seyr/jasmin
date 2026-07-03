import { useRef, useEffect, useMemo } from "react";
import type { KeyboardEvent } from "react";
import { Form } from "antd";
import type { InputRef } from "antd";
import type { Dayjs } from "dayjs";
import FormInput from "./FormInput";
import { useTranslation } from "react-i18next";
import type { EditableCellProps, EditableColumnConfig, TableRecord, SelectOption } from "./types";
import { buildLiveRecord } from "./buildLiveRecord";
import { getEditableFormItemProps } from "./formItemProps";
import { useNumberFormat } from "@hooks/useNumberFormat";

// Hook-free helper, shared by both the display and the editing cell. Walks the
// (possibly nested) column tree to find the config for a given dataIndex.
const findColumnConfig = <T extends TableRecord>(
  cols: EditableColumnConfig<T>[],
  idx: string,
): EditableColumnConfig<T> | null => {
  for (const col of cols) {
    if (col.dataIndex === idx) {
      return col;
    }
    if (col.children) {
      const childConfig = findColumnConfig(col.children, idx);
      if (childConfig) {
        return childConfig;
      }
    }
  }
  return null;
};

const isUnsavedRowKey = (record: TableRecord | undefined): boolean =>
  // A not-yet-saved row (the new-row placeholder, or any row without an id)
  // gets a marker class so action buttons / links inside its cells are
  // disabled (see tables.css) — they would otherwise fire against a missing
  // record id and "give nonsense".
  !!record &&
  record.key !== "summary-row" &&
  (record.key === -1 || !record.id);

// ─── Display cell (rows NOT being edited) ────────────────────────────────────
// Renders the prebuilt `children` Ant Table computed from the saved record. It
// deliberately does NOT call Form.useWatch: a non-editing cell never needs live
// form values, and subscribing every cell to the shared form makes the whole
// table re-render on every keystroke (the EditableCell `useWatch([])` storm).
// `reactiveDisabled` is evaluated against the row's own `record` — the only
// correct source for a row that isn't in the edit form.
const DisplayCell = <T extends TableRecord = TableRecord>({
  dataIndex,
  record,
  children,
  onCellClick,
  columns = [],
  disabled = false,
  // Destructured out so the custom props never leak onto the <td> via restProps.
  editing: _editing,
  title: _title,
  index: _index,
  inputType: _inputType,
  required: _required,
  options: _options,
  formErrors: _formErrors,
  form: _form,
  shouldFocus: _shouldFocus,
  save: _save,
  ...restProps
}: EditableCellProps<T>) => {
  const columnConfig = findColumnConfig(columns, dataIndex);

  const reactiveDisabled =
    typeof columnConfig?.disabled === "function"
      ? !!columnConfig.disabled(record)
      : false;
  const effectiveDisabled = disabled || reactiveDisabled;
  const isReadOnly = !!columnConfig?.readOnly;

  // `readOnly` implies the "locked" visual — gray bg + not-allowed cursor.
  const showLockedStyle = effectiveDisabled || isReadOnly;
  const isUnsavedRow = isUnsavedRowKey(record);

  return (
    <td
      {...restProps}
      className={
        [
          (restProps as { className?: string }).className,
          isUnsavedRow && "editable-cell-unsaved",
        ]
          .filter(Boolean)
          .join(" ") || undefined
      }
      onClick={() =>
        !effectiveDisabled && onCellClick && onCellClick(record, dataIndex)
      }
      style={{
        ...restProps.style,
        backgroundColor: showLockedStyle ? "var(--color-bg-subtle)" : undefined,
        cursor: showLockedStyle ? "not-allowed" : undefined,
      }}
    >
      {children}
    </td>
  );
};

// ─── Editing cell (cells in the row currently being edited) ──────────────────
// Subscribes to the shared form via Form.useWatch so derived display, dynamic
// options and reactive-disabled stay in sync as the user types. Only mounted
// for the handful of cells in the editing row, so the whole-form subscription
// is scoped instead of paid by every cell in the table.
const EditingCell = <T extends TableRecord = TableRecord>({
  editing,
  dataIndex,
  title: _title,
  record,
  index,
  children,
  inputType = "text",
  required = false,
  options = [],
  formErrors = {},
  onCellClick,
  columns = [],
  form,
  shouldFocus = false,
  disabled = false,
  save,
  ...restProps
}: EditableCellProps<T>) => {
  const formValues = Form.useWatch([], form);
  const resolvedOptions: SelectOption[] = useMemo(() => {
    if (typeof options === "function") {
      const liveRecord = { ...record, ...formValues } as T;
      return options(liveRecord);
    }
    return options as SelectOption[];
  }, [options, record, formValues]);

  const inputRef = useRef<InputRef | null>(null);
  const selectEnterCountRef = useRef(0);

  const { t } = useTranslation();
  // Read once at the top so the hook count stays stable across the
  // edit / display branches below (rules-of-hooks).
  const { separators } = useNumberFormat();

  const columnConfig = findColumnConfig(columns, dataIndex);

  const liveRecord = useMemo(
    () => buildLiveRecord(record, formValues, columns) as T,
    [record, formValues, columns],
  );

  const reactiveDisabled = useMemo(() => {
    if (typeof columnConfig?.disabled === "function") {
      return !!columnConfig.disabled(liveRecord);
    }
    return false;
  }, [columnConfig, liveRecord]);

  const effectiveDisabled = disabled || reactiveDisabled;

  useEffect(() => {
    // When the row enters edit mode (programmatic focus, not a click on
    // the input itself), focus AND select synchronously. Deferring the
    // select via setTimeout in FormInput.handleFocus loses the race if the
    // user starts typing immediately — the first keystroke lands before
    // the select macrotask fires, so the existing value isn't overwritten.
    if (editing && inputRef.current && shouldFocus) {
      requestAnimationFrame(() => {
        const input =
          inputRef.current?.input ??
          (inputRef.current as unknown as HTMLInputElement | null);
        if (!input) return;
        input.focus();
        if (
          inputType !== "select" &&
          inputType !== "checkbox" &&
          inputType !== "switch"
        ) {
          input.select?.();
        }
      });
    }
  }, [editing, shouldFocus, inputType]);

  useEffect(() => {
    if (editing) {
      selectEnterCountRef.current = 0;
    }
  }, [editing]);

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();

      if (inputType === "select") {
        selectEnterCountRef.current += 1;
        if (selectEnterCountRef.current >= 2) {
          handleSave();
        }
      } else {
        handleSave();
      }
    }
  };

  const handleSave = () => {
    if (save) {
      save(record.key);
    }
  };

  const isReadOnly = !!columnConfig?.readOnly;

  if (!editing || effectiveDisabled || isReadOnly) {
    // For disabled / read-only cells in a row that IS being edited,
    // re-render through the column's `render` using `liveRecord` (built
    // from current form values via Form.useWatch). That lets derived
    // display cells — running totals, "still free" indicators, computed
    // summaries — update in real time as the user types into sibling
    // cells, instead of staying frozen on the last saved snapshot.
    //
    // ReadOnly cells use the same render-with-liveRecord path so a
    // derived display (e.g. an average of sibling cells) stays in sync
    // with the form, without becoming an input itself.
    let displayChildren = children;
    if (
      editing &&
      (effectiveDisabled || isReadOnly) &&
      columnConfig?.render
    ) {
      const liveValue = (liveRecord as Record<string, unknown>)[dataIndex];
      displayChildren = columnConfig.render(liveValue, liveRecord, index);
    }

    // `readOnly` implies the "locked" visual — gray bg + not-allowed cursor.
    // This is what makes the `readOnly: true` flag self-sufficient: callers
    // don't need to add `disabled: true` just to get the read-only look.
    // Click-to-edit stays gated on `effectiveDisabled` only — a readOnly cell
    // is informational but shouldn't block the row from entering edit mode.
    const showLockedStyle = effectiveDisabled || isReadOnly;
    const isUnsavedRow = isUnsavedRowKey(record);

    return (
      <td
        {...restProps}
        className={
          [
            (restProps as { className?: string }).className,
            isUnsavedRow && "editable-cell-unsaved",
          ]
            .filter(Boolean)
            .join(" ") || undefined
        }
        onClick={() =>
          !effectiveDisabled && onCellClick && onCellClick(record, dataIndex)
        }
        style={{
          ...restProps.style,
          backgroundColor: showLockedStyle ? "var(--color-bg-subtle)" : undefined,
          cursor: showLockedStyle ? "not-allowed" : undefined,
        }}
      >
        {displayChildren}
      </td>
    );
  }

  const getErrorMessage = (): string | undefined => {
    const fieldError = form?.getFieldError(dataIndex)?.[0];
    const customError = formErrors[dataIndex];
    return fieldError || customError;
  };

  // Programmatic accessible name for the inline-edit control: a SR user tabbing
  // into the cell otherwise hears an unlabeled "edit text" with no column
  // context. `column.title` is a ReactNode, so guard to string and fall back to
  // dataIndex.
  const ariaLabel =
    typeof columnConfig?.title === "string" ? columnConfig.title : dataIndex;

  // Expose validation errors to assistive tech without changing the borderless
  // visual: keep AntD's `help=""` (no visible explain node) and instead point
  // the control's `aria-invalid`/`aria-describedby` at an off-screen .sr-only
  // node carrying the message — covers both rules-path errors and the
  // server/unique-check errors in `formErrors` that bypass AntD's validation.
  const errorMessage = getErrorMessage();
  const errorDescriptionId = `editable-cell-error-${dataIndex}`;

  const getInputNode = () => {
    const wrappedOnFieldChange = columnConfig?.onFieldChange
      ? (value: unknown, rec: Record<string, unknown>, f: typeof form) => {
          return columnConfig.onFieldChange!(value, rec as T, f!, dataIndex);
        }
      : undefined;

    return (
      <FormInput
        ref={inputRef}
        inputType={inputType}
        required={required}
        options={resolvedOptions}
        suffix={columnConfig?.suffix}
        prefix={columnConfig?.prefix}
        className={columnConfig?.className}
        disabledDate={
          columnConfig?.disabledDate
            ? (current: Dayjs) =>
                columnConfig.disabledDate!(current, liveRecord)
            : undefined
        }
        isModal={false}
        onFieldChange={wrappedOnFieldChange}
        record={record}
        form={form}
        onKeyDown={handleKeyDown}
        aria-label={ariaLabel}
        aria-invalid={errorMessage ? true : undefined}
        aria-describedby={errorMessage ? errorDescriptionId : undefined}
        style={{
          textAlign: columnConfig?.align || "left",
        }}
      />
    );
  };

  // Shared with the modal row editor (EditableModal) so the two never drift:
  // boolean valuePropName + locale-aware decimal IO (display the tenant's
  // decimal char, normalise "," → "." at the form boundary).
  const { valuePropName, getValueFromEvent, getValueProps } =
    getEditableFormItemProps(inputType, separators);

  return (
    <td
      {...restProps}
      style={{
        ...restProps.style,
        width: columnConfig?.width,
        minWidth: columnConfig?.minWidth,
        maxWidth: columnConfig?.maxWidth,
        textAlign: columnConfig?.align || "left",
      }}
    >
      <Form.Item
        name={dataIndex}
        style={{ margin: 0 }}
        validateStatus={errorMessage ? "error" : "success"}
        valuePropName={valuePropName}
        getValueFromEvent={getValueFromEvent}
        getValueProps={getValueProps}
        hasFeedback={false}
        help=""
        rules={[
          {
            required: required,
            message: t("table.required"),
          },
          ...(columns.find((col) => col.dataIndex === dataIndex)?.rules || []),
        ]}
      >
        {getInputNode()}
      </Form.Item>
      {errorMessage && (
        <span id={errorDescriptionId} className="sr-only" role="alert">
          {errorMessage}
        </span>
      )}
    </td>
  );
};

// AntD wires this as `components.body.cell` for EVERY body cell. Only cells in
// the editing row need the form subscription (Form.useWatch); routing
// non-editing cells through the hook-free DisplayCell keeps a keystroke from
// re-rendering the whole table. The wrapper itself calls no hooks, so the
// conditional render is rules-of-hooks safe.
const EditableCell = <T extends TableRecord = TableRecord>(
  props: EditableCellProps<T>,
) => {
  if (!props.editing) {
    return <DisplayCell {...props} />;
  }
  return <EditingCell {...props} />;
};

export default EditableCell;
