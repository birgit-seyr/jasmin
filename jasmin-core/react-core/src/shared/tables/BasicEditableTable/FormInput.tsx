import { forwardRef } from "react";
import type {
  AriaAttributes,
  ChangeEvent,
  ComponentPropsWithRef,
  FocusEvent,
  KeyboardEvent,
  KeyboardEventHandler,
  MouseEvent as ReactMouseEvent,
  Ref,
} from "react";
import { Input, Select, Checkbox, DatePicker, TimePicker, Switch } from "antd";
import type { GetRef, InputProps, InputRef, SelectProps } from "antd";
import dayjs from "dayjs";
import { useDateFormat, useTimeFormat } from "@hooks/index";
import { toValidDayjs } from "@shared/utils/dayjsParse";
import { withClearOption } from "./selectOptions";
import type { FormInputProps, SelectOption } from "./types";

const FormInput = forwardRef<InputRef, FormInputProps>(
  (
    {
      inputType = "text",
      options = [],
      required,
      size,
      placeholder,
      title: _title,
      isModal = false,
      onKeyDown,
      onFieldChange,
      record,
      form,
      suffix,
      className,
      disabledDate,
      value,
      checked,
      onChange,
      onFocus,
      disabled,
      prefix,
      style,
      "aria-label": ariaLabel,
      "aria-describedby": ariaDescribedBy,
      "aria-invalid": ariaInvalid,
    },
    ref,
  ) => {
    const controlSize = isModal ? undefined : size || "small";
    const controlStyle = isModal ? { width: "100%" } : style;

    // Accessibility attributes shared by every widget. Kept as a spreadable
    // bag because some widget prop types don't declare aria-* explicitly —
    // the underlying rc-components still forward them to the DOM input.
    const ariaProps: AriaAttributes = {
      "aria-label": ariaLabel,
      "aria-describedby": ariaDescribedBy,
      "aria-invalid": ariaInvalid,
    };

    // Shared prop bag for the text-like <Input> branches, typed against the
    // real Input props so field names/types stay checked. `value` arrives as
    // `unknown` (injected by Form.Item), so it gets the one localized cast.
    const inputProps: Partial<ComponentPropsWithRef<typeof Input>> = {
      ref,
      size: controlSize,
      style: controlStyle,
      suffix,
      value: value as InputProps["value"],
      onChange,
      onFocus,
      disabled,
      prefix,
      placeholder,
      ...ariaProps,
    };

    const { timeFormat } = useTimeFormat();
    // Use the shared hook (not raw ``getSetting``): its ``dateFormat`` defaults
    // to the tenant format / "DD.MM.YYYY" and is never null, so the picker's
    // ``format`` / ``placeholder`` don't blank out during the window before the
    // tenant settings have loaded.
    const { dateFormat } = useDateFormat();

    // Select-all on focus for text-like inputs so clicking a cell with a
    // value lets the user overwrite it by typing — the previous flow used
    // a separate `selectOnFocus` flag (hardcoded false everywhere) plus a
    // duplicate handler in EditableCell, which was fragile under
    // re-renders. Centralised here so it's reliable for every consumer.
    const TEXT_LIKE_TYPES = new Set([
      "text",
      "date",
      "number",
      "kw",
      "integer",
      "negative_integer",
      "positive_integer",
      "decimal1",
      "decimal2",
      "decimal3",
      "positive_decimal2",
      "negative_decimal2",
      "positive_decimal3",
      "negative_decimal3",
      "percentage",
    ]);

    // Find the actual <input> from a synthetic event. Ant Design's Input
    // sometimes wraps in <span class="ant-input-affix-wrapper">, so
    // `e.target` may be a child of the input or the wrapper. We resolve to
    // the nearest <input> instead of capturing `e.currentTarget`, which
    // can go stale if Form.useWatch re-renders the cell between the focus
    // event and the deferred select (the cause of the
    // PlanningHarvestShares bug — many-cell forms trigger frequent
    // re-renders, replacing the input node before RAF fires).
    const resolveInput = (
      target: EventTarget | null,
    ): HTMLInputElement | null => {
      if (!(target instanceof HTMLElement)) return null;
      if (target instanceof HTMLInputElement) return target;
      return target.querySelector?.("input") ?? null;
    };

    const selectInput = (input: HTMLInputElement | null) => {
      if (!input) return;
      if (typeof input.select === "function") {
        input.select();
      } else if (
        typeof input.setSelectionRange === "function" &&
        typeof input.value === "string"
      ) {
        input.setSelectionRange(0, input.value.length);
      }
    };

    const handleFocus = (e: FocusEvent<HTMLInputElement>) => {
      if (onFocus) {
        onFocus(e);
      }
      if (TEXT_LIKE_TYPES.has(inputType)) {
        const input = resolveInput(e.target);
        // setTimeout(0) defers past all synchronous re-renders + mouseup
        // cursor placement in the current tick.
        setTimeout(() => selectInput(input), 0);
      }
    };

    // Intercepting on `mousedown` and calling `preventDefault` short-circuits
    // the browser's default click-to-position behaviour entirely — no caret
    // placement, no mouseup interference. We then focus + select manually.
    // This is necessary because Form.useWatch in PlanningHarvestShares
    // re-renders the cell frequently enough that a deferred select via
    // setTimeout can lose the race when the input is already focused.
    const handleMouseDown = (e: ReactMouseEvent<HTMLInputElement>) => {
      if (!TEXT_LIKE_TYPES.has(inputType)) return;
      const input = resolveInput(e.target);
      if (!input) return;
      // Don't fight modifier-clicks (shift-click extends selection, etc.).
      if (e.shiftKey || e.altKey || e.metaKey || e.ctrlKey) return;
      e.preventDefault();
      input.focus();
      selectInput(input);
    };

    const handleSelectChange = (selectValue: unknown) => {
      if (onChange) {
        onChange(selectValue);
      }

      if (onFieldChange && record && form) {
        const updates = onFieldChange(selectValue, record, form);
        if (updates && Object.keys(updates).length > 0) {
          form.setFieldsValue(updates);
        }
      }
    };

    const handleInputChange = (e: ChangeEvent<HTMLInputElement> | unknown) => {
      const inputValue = (e as ChangeEvent<HTMLInputElement>).target
        ? (e as ChangeEvent<HTMLInputElement>).target.value
        : e;

      if (onChange) {
        onChange(e);
      }

      if (onFieldChange && record && form) {
        const updates = onFieldChange(inputValue, record, form);
        if (updates && Object.keys(updates).length > 0) {
          form.setFieldsValue(updates);
        }
      }
    };

    const getNumberConstraints = (type: string) => {
      const constraints: {
        min?: number;
        max?: number;
        precision?: number;
        step?: number;
      } = {};

      if (type.includes("positive")) {
        constraints.min = 0;
      }
      if (type.includes("negative")) {
        constraints.max = 0;
      }
      if (type.includes("percentage")) {
        constraints.min = 0;
        constraints.max = 400;
        constraints.precision = 2;
        constraints.step = 0;
      }
      if (type.includes("decimal2")) {
        constraints.precision = 2;
        constraints.step = 0.01;
      }
      if (type.includes("decimal1")) {
        constraints.precision = 1;
        constraints.step = 0.1;
      }
      if (type.includes("decimal3")) {
        constraints.precision = 3;
        constraints.step = 0.001;
      }
      if (
        type === "integer" ||
        type === "positive_integer" ||
        type === "negative_integer"
      ) {
        constraints.precision = 0;
        constraints.step = 1;
      }

      return constraints;
    };

    const handleNumberKeyDown = (e: KeyboardEvent<HTMLInputElement>, type: string) => {
      const key = e.key;
      const input = e.target as HTMLInputElement;
      const currentValue = input.value;

      // Compute the value the input *would* have after this keystroke is
      // applied (selected text gets replaced). Validating against this
      // instead of `currentValue` is what lets "select-all + type 3" work
      // on a cell that currently shows e.g. "5.50" — otherwise the existing
      // 2-digit decimal part would block the keystroke even though it's
      // about to be deleted by the selection replacement.
      const selStart = input.selectionStart ?? currentValue.length;
      const selEnd = input.selectionEnd ?? currentValue.length;
      const resultingValue =
        currentValue.substring(0, selStart) +
        key +
        currentValue.substring(selEnd);

      const controlKeys = [
        "Backspace", "Delete", "Tab", "Escape", "Enter",
        "Home", "End", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown",
      ];

      if (
        controlKeys.includes(key) ||
        (e.ctrlKey && key === "a") ||
        (e.ctrlKey && key === "c") ||
        (e.ctrlKey && key === "v") ||
        (e.ctrlKey && key === "x")
      ) {
        return;
      }

      if (type.includes("percentage")) {
        if (!/[0-9]/.test(key)) {
          e.preventDefault();
          return;
        }
        const numValue = parseFloat(resultingValue);
        if (!isNaN(numValue) && numValue > 400) {
          e.preventDefault();
        }
        return;
      }

      // ``-`` is allowed at position 0 (and only when not already
       // present) for any type that isn't explicitly "positive". That
       // covers ``negative_*`` (negative-only) AND the plain signed
       // variants (``integer`` / ``decimal2`` / ``decimal1`` /
       // ``decimal3``) where the keydown handler used to silently
       // swallow ``-``. Plain ``decimal2`` is the canonical "signed
       // money" input — see ``priceColumns.tsx`` (Gutschein/Pauschalen
       // Rabatt) and ``InvoiceModal.price_per_unit``.
       const allowMinus =
         !type.includes("positive") &&
         key === "-" &&
         !resultingValue.slice(1).includes("-") &&
         selStart === 0;

      if (type.includes("integer")) {
        if (!/[0-9]/.test(key)) {
          if (!allowMinus) {
            e.preventDefault();
          }
        }
        return;
      }

      if (type.includes("decimal")) {
        // Accept both "." and "," as decimal separator regardless of
        // tenant locale — the EditableCell's Form.Item normalises the
        // stored form value back to "." via `getValueFromEvent`.
        if (!/[0-9.,]/.test(key)) {
          if (!allowMinus) {
            e.preventDefault();
          }
          return;
        }
        // At most one decimal separator (counting "." and "," together).
        const sepCount = (resultingValue.match(/[.,]/g) ?? []).length;
        if (sepCount > 1) {
          e.preventDefault();
          return;
        }
        // Enforce max decimal places on the *resulting* value. Split on
        // either separator so the check works in both locales. Check the
        // most specific suffix first (decimal3 / decimal2 / decimal1).
        const maxDecimals = type.includes("decimal3")
          ? 3
          : type.includes("decimal2")
            ? 2
            : type.includes("decimal1")
              ? 1
              : null;
        if (maxDecimals) {
          const decimalPart = resultingValue.split(/[.,]/)[1];
          if (decimalPart && decimalPart.length > maxDecimals) {
            e.preventDefault();
          }
        }
        return;
      }

      if (type.includes("positive") && key === "-") {
        e.preventDefault();
        return;
      }
    };

    switch (inputType) {
      case "select": {
        // Clearability follows ``required`` (see withClearOption): a
        // non-required select gets a leading blank option so it can be cleared.
        const selectOptions = withClearOption(options, required);
        return (
          <Select
            // The shared forwarded ref is typed for Input (the dominant
            // text-like case); the Select instance only ever gets `.focus()`
            // called through it (EditableCell shouldFocus), so this
            // directional cast is safe.
            ref={ref as unknown as Ref<GetRef<typeof Select>>}
            size={controlSize}
            style={controlStyle}
            disabled={disabled}
            value={value as SelectProps["value"]}
            {...ariaProps}
            showSearch
            options={selectOptions}
            optionFilterProp="children"
            filterOption={(input: string, option?: SelectOption) =>
              (option?.label ?? "").toLowerCase().includes(input.toLowerCase())
            }
            onChange={handleSelectChange}
            onKeyDown={(e: KeyboardEvent) => {
              if (e.key === "Enter") {
                setTimeout(() => {
                  if (onKeyDown) {
                    onKeyDown(e);
                  }
                }, 10);
              }
            }}
          />
        );
      }

      case "date":
        return (
          <Input
            {...inputProps}
            placeholder={dateFormat}
            onKeyDown={onKeyDown as KeyboardEventHandler<HTMLInputElement> | undefined}
            onFocus={handleFocus}
            onMouseDown={handleMouseDown}
            onChange={handleInputChange}
          />
        );

      case "datepicker":
        return (
          <DatePicker
            // See the Select ref note — only `.focus()` is called through it.
            ref={ref as unknown as Ref<GetRef<typeof DatePicker>>}
            size={controlSize}
            style={controlStyle}
            disabled={disabled}
            {...ariaProps}
            format={dateFormat}
            value={toValidDayjs(value, [dateFormat, "YYYY-MM-DD"])}
            disabledDate={disabledDate}
            onChange={(date: dayjs.Dayjs | null) => {
              const formatted = date ? date.format("YYYY-MM-DD") : null;
              if (onChange) {
                onChange(formatted);
              }
              // Fire ``onFieldChange`` so column-level handlers (e.g.
              // ``Abos.handleValidFromChange`` that auto-computes
              // ``valid_until`` from ``valid_from``) actually run on
              // date inputs. Without this the column-level
              // ``onFieldChange`` is dead code for ``inputType:
              // "datepicker"`` — the form value updates but no
              // downstream side-effects fire. Mirrors the numeric
              // case's ``handleInputChange`` pattern.
              if (onFieldChange && record && form) {
                const updates = onFieldChange(formatted, record, form);
                if (updates && typeof updates === "object") {
                  form.setFieldsValue(updates as Record<string, unknown>);
                }
              }
            }}
            onKeyDown={onKeyDown as KeyboardEventHandler | undefined}
            allowClear={false}
          />
        );

      case "time":
        return (
          <TimePicker
            // See the Select ref note — only `.focus()` is called through it.
            ref={ref as unknown as Ref<GetRef<typeof TimePicker>>}
            size={controlSize}
            style={controlStyle}
            disabled={disabled}
            {...ariaProps}
            // ``timeFormat`` drives the picker's *display* only — the
            // wire format stays canonical ``HH:mm:ss`` regardless of
            // the tenant's preference, so backend parsing isn't
            // affected. Incoming values from the backend are still
            // parsed off the ``HH:mm:ss`` / ``HH:mm`` shapes.
            format={timeFormat}
            value={toValidDayjs(value, ["HH:mm:ss", "HH:mm"])}
            onChange={(time: dayjs.Dayjs | null) => {
              if (onChange) {
                onChange(time ? time.format("HH:mm:ss") : null);
              }
            }}
            onKeyDown={onKeyDown as KeyboardEventHandler | undefined}
            allowClear={false}
          />
        );
      case "integer":
      case "positive_integer":
      case "negative_integer":
      case "decimal1":
      case "decimal2":
      case "decimal3":
      case "positive_decimal2":
      case "negative_decimal2":
      case "positive_decimal3":
      case "negative_decimal3":
      case "percentage": {
        const constraints = getNumberConstraints(inputType);
        return (
          <Input
            {...inputProps}
            {...constraints}
            // Numeric inputs need ``handleInputChange`` (not the bare
            // commonProps.onChange) so the column's ``onFieldChange``
            // fires on every keystroke. Without this override, the form
            // field updates but downstream side-effects (e.g. live
            // price-per-unit tier picker on amount-change in Orders /
            // InvoiceModal) silently never run.
            onChange={handleInputChange}
            onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => {
              handleNumberKeyDown(e, inputType);
              if (onKeyDown) onKeyDown(e);
            }}
            onFocus={handleFocus}
            onMouseDown={handleMouseDown}
          />
        );
      }

      case "number":
        return (
          <Input
            {...inputProps}
            onKeyDown={onKeyDown as KeyboardEventHandler<HTMLInputElement> | undefined}
            onFocus={handleFocus}
            onMouseDown={handleMouseDown}
          />
        );

      case "kw":
        return (
          <Input
            {...inputProps}
            onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => {
              const key = e.key;
              const input = e.target as HTMLInputElement;
              const currentValue = input.value;
              const selStart = input.selectionStart ?? currentValue.length;
              const selEnd = input.selectionEnd ?? currentValue.length;
              const resultingValue =
                currentValue.substring(0, selStart) +
                key +
                currentValue.substring(selEnd);

              const controlKeys = [
                "Backspace", "Delete", "Tab", "Escape", "Enter",
                "Home", "End", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown",
              ];

              if (
                controlKeys.includes(key) ||
                (e.ctrlKey && key === "a") ||
                (e.ctrlKey && key === "c") ||
                (e.ctrlKey && key === "v") ||
                (e.ctrlKey && key === "x")
              ) {
                return;
              }

              if (!/[0-9]/.test(key)) {
                e.preventDefault();
                return;
              }

              const numValue = parseInt(resultingValue, 10);
              if (!isNaN(numValue) && numValue > 53) {
                e.preventDefault();
              }

              if (onKeyDown) onKeyDown(e);
            }}
            onChange={(e: ChangeEvent<HTMLInputElement>) => {
              let value = e.target.value;
              value = value.replace(/[^0-9]/g, "");
              const numValue = parseInt(value);

              if (value === "" || (numValue >= 1 && numValue <= 53)) {
                const newEvent = {
                  ...e,
                  target: { ...e.target, value },
                };
                if (onChange) {
                  onChange(newEvent);
                }
              }
            }}
            onFocus={handleFocus}
            onMouseDown={handleMouseDown}
            placeholder="1-53"
          />
        );

      case "checkbox":
        return (
          <Checkbox
            // See the Select ref note — the Checkbox instance exposes
            // `.input`/`.focus()`, which is all EditableCell uses.
            ref={ref as unknown as Ref<GetRef<typeof Checkbox>>}
            style={controlStyle}
            disabled={disabled}
            {...ariaProps}
            checked={checked}
            className={className}
            onChange={(e) => {
              const newValue = e.target.checked;

              if (onChange) {
                onChange(newValue);
              }

              if (onFieldChange && record && form) {
                const updates = onFieldChange(newValue, record, form);
                if (updates && Object.keys(updates).length > 0) {
                  form.setFieldsValue(updates);
                }
              }
            }}
            onKeyDown={
              (onKeyDown as KeyboardEventHandler<HTMLElement> | undefined) ||
              ((e: KeyboardEvent) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                }
              })
            }
          />
        );

      case "switch":
        return (
          <Switch
            size={isModal ? "default" : "small"}
            disabled={disabled as boolean | undefined}
            className={className}
            checked={!!checked}
            aria-label={ariaLabel}
            aria-describedby={ariaDescribedBy}
            aria-invalid={ariaInvalid}
            // AntD Switch.onChange is (checked, event) — the boolean is the
            // first arg, NOT e.target.checked (unlike Checkbox above).
            onChange={(newValue: boolean) => {
              if (onChange) {
                onChange(newValue);
              }
              if (onFieldChange && record && form) {
                const updates = onFieldChange(newValue, record, form);
                if (updates && Object.keys(updates).length > 0) {
                  form.setFieldsValue(updates);
                }
              }
            }}
          />
        );

      default:
        return (
          <Input
            {...inputProps}
            onKeyDown={onKeyDown as KeyboardEventHandler<HTMLInputElement> | undefined}
            onFocus={handleFocus}
            onMouseDown={handleMouseDown}
          />
        );
    }
  },
);

FormInput.displayName = "FormInput";

export default FormInput;
