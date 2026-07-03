import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";

const DEFAULT_COUNTRIES = [
  { value: "DE", label: "DE" },
  { value: "AT", label: "AT" },
  { value: "IT", label: "IT" },
  { value: "FR", label: "FR" },
];

/**
 * Reusable contact-related columns for tables (address, name, email, etc.)
 *
 * @param {Object} options
 * @param {string} options.translationPrefix - e.g. "members" or "resellers"
 * @param {Object} options.overrides - per-column overrides keyed by column name
 * @param {Array} options.countries - country options for the country select column
 */
interface ContactColumnOptions {
  translationPrefix?: string;
  overrides?: Record<string, Partial<EditableColumnConfig<TableRecord>>>;
  countries?: { value: string; label: string }[];
}

export const useContactColumns = (options: ContactColumnOptions = {}) => {
  const { t } = useTranslation();

  const {
    translationPrefix = "members",
    overrides = {},
    countries = DEFAULT_COUNTRIES,
  } = options;

  // Callers often pass a fresh object literal each render (e.g. Members.tsx
  // does `{ overrides: { firstName: {...} } }`), which would invalidate
  // this memo every render if `overrides` were a direct dep. The overrides
  // shape is plain data (no functions), so a JSON key is a stable proxy.
  const overridesKey = useMemo(() => JSON.stringify(overrides), [overrides]);

  const columns = useMemo(() => {
    const applyOverrides = (
      key: string,
      base: EditableColumnConfig<TableRecord>,
    ): EditableColumnConfig<TableRecord> => ({
      ...base,
      ...(overrides[key] || {}),
    });

    return {
      companyName: applyOverrides("companyName", {
        title: <>{t(`${translationPrefix}.company_name`)}</>,
        dataIndex: "company_name",
        key: "company_name",
        inputType: "text",
        required: false,
        width: "16em",
        align: "left",
        sortable: true,
      }),

      firstName: applyOverrides("firstName", {
        title: <>{t(`${translationPrefix}.first_name`)}</>,
        dataIndex: "first_name",
        key: "first_name",
        inputType: "text",
        required: false,
        width: "14em",
        align: "left",
        sortable: true,
      }),

      lastName: applyOverrides("lastName", {
        title: <>{t(`${translationPrefix}.last_name`)}</>,
        dataIndex: "last_name",
        key: "last_name",
        inputType: "text",
        required: false,
        width: "14em",
        align: "left",
        sortable: true,
      }),

      email: applyOverrides("email", {
        title: <>{t(`${translationPrefix}.email`)}</>,
        dataIndex: "email",
        key: "email",
        inputType: "text",
        required: false,
        width: "22em",
        align: "left",
      }),

      address: applyOverrides("address", {
        title: <>{t(`${translationPrefix}.address`)}</>,
        dataIndex: "address",
        key: "address",
        inputType: "text",
        required: false,
        width: "16em",
        align: "left",
      }),

      zipCode: applyOverrides("zipCode", {
        title: <>{t(`${translationPrefix}.zip_code`)}</>,
        dataIndex: "zip_code",
        key: "zip_code",
        inputType: "text",
        required: false,
        width: "6em",
        align: "center",
      }),

      city: applyOverrides("city", {
        title: <>{t(`${translationPrefix}.city`)}</>,
        dataIndex: "city",
        key: "city",
        inputType: "text",
        required: false,
        width: "14em",
        align: "left",
        sortable: true,
      }),

      country: applyOverrides("country", {
        title: <>{t(`${translationPrefix}.country`)}</>,
        dataIndex: "country",
        key: "country",
        inputType: "select",
        required: false,
        width: "5em",
        align: "left",
        options: countries,
      }),

      phone: applyOverrides("phone", {
        title: <>{t(`${translationPrefix}.phone`)}</>,
        dataIndex: "phone",
        key: "phone",
        inputType: "text",
        required: false,
        width: "14em",
        align: "left",
      }),
      phone2: applyOverrides("phone2", {
        title: <>{t(`${translationPrefix}.phone2`)}</>,
        dataIndex: "phone2",
        key: "phone2",
        inputType: "text",
        required: false,
        width: "14em",
        align: "left",
      }),
    };
    // `overrides` is intentionally NOT in the dep array — `overridesKey`
    // tracks its content, and putting both would defeat the stabilization.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [t, translationPrefix, overridesKey, countries]);

  return columns;
};
