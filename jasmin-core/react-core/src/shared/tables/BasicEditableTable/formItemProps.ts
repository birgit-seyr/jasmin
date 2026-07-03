import type { ChangeEvent } from "react";
import type { InputType } from "./types";

export interface DecimalSeparators {
  decimalChar: string;
}

/**
 * The ``Form.Item`` props that make an editable field behave IDENTICALLY in the
 * inline cell editor (``EditableCell``) and the modal row editor
 * (``EditableModal``, used when inline editing is off). Keeping this in ONE
 * place stops the two editors drifting — e.g. the modal silently dropping the
 * "," → "." normalisation and POSTing an unparseable "6,5" that 400s, or
 * mis-binding a boolean ``switch`` to ``value`` instead of ``checked``.
 *
 * Locale-aware decimal IO: when the tenant's ``number_locale`` uses something
 * other than "." (e.g. "," in de-DE), the stored form value stays canonical
 * ("." separator, parseable as a JS number) while the input displays the
 * localised form — so the wire payload and tax/price math stay numeric while
 * the UI shows "5,12".
 */
export function getEditableFormItemProps(
  inputType: InputType | undefined,
  separators: DecimalSeparators,
): {
  valuePropName: string;
  getValueFromEvent?: (e: ChangeEvent<HTMLInputElement> | unknown) => unknown;
  getValueProps?: (value: unknown) => { value: unknown };
} {
  const valuePropName =
    inputType === "checkbox" || inputType === "switch" ? "checked" : "value";

  const isDecimalLikeInput =
    typeof inputType === "string" &&
    (inputType.includes("decimal") || inputType === "percentage");

  const decimalChar = separators.decimalChar;
  const needsLocaleTranslation = isDecimalLikeInput && decimalChar !== ".";

  // Always normalise "," → "." at the form boundary for decimal inputs,
  // regardless of locale. The FormInput keydown handler accepts both
  // separators, so a user on an en-US tenant who types "6,5" out of habit
  // would otherwise send "6,5" to the API and trigger a 400.
  const getValueFromEvent = isDecimalLikeInput
    ? (e: ChangeEvent<HTMLInputElement> | unknown) => {
        const raw =
          typeof e === "object" && e !== null && "target" in e
            ? (e as ChangeEvent<HTMLInputElement>).target.value
            : (e as string);
        if (typeof raw !== "string") return raw;
        return raw.replaceAll(",", ".");
      }
    : undefined;

  const getValueProps = needsLocaleTranslation
    ? (value: unknown) => ({
        value:
          value === null || value === undefined || value === ""
            ? value
            : String(value).replace(".", decimalChar),
      })
    : undefined;

  return { valuePropName, getValueFromEvent, getValueProps };
}
