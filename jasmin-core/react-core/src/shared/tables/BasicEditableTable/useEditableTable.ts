import { Form } from "antd";
import dayjs from "dayjs";
import { toApiDate } from "@shared/utils/apiDate";
import type { Key } from "react";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { useDateFormat } from "@hooks/configuration/useDateFormat";
import axiosService from "@shared/services/api";
import { getErrorMessage } from "@shared/utils/apiError";
import { buildLiveRecord } from "./buildLiveRecord";
import type {
  EditableColumnConfig,
  SelectOption,
  TableRecord,
  UseEditableTableOptions,
  UseEditableTableReturn,
} from "./types";

// SelectOptions built by FK call sites often carry the full backend entity
// alongside `label`/`value` (e.g. the raw id under `valueField` or the display
// text under `displayField`). One documented intersection cast here keeps
// those dynamic-field reads in a single place instead of scattering
// `as unknown as Record<string, unknown>` at every lookup.
const readOptionField = (option: SelectOption, field: string): unknown =>
  (option as SelectOption & Record<string, unknown>)[field];

export const useEditableTable = <T extends TableRecord = TableRecord>({
  apiEndpoints = {},
  apiFunctions,
  onDataChange,
  focusIndex,
  columns = [],
  customSave,
  customEdit,
  customDelete,
  customUpdate,
  deleteContext = null,
  uniqueCheck = null,
  uniqueCheckMessage = null,
  autoHandleDates = true,
  onSaveSuccess = null,
  onDeleteSuccess = null,
}: UseEditableTableOptions<T>): UseEditableTableReturn<T> => {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [editingKey, setEditingKey] = useState<Key | "">("");
  const [data, setData] = useState<T[]>([]);
  const [loading, setLoading] = useState(false);
  // IDs created during this mount. Pinned to the top across refetches so a
  // freshly-saved row stays visible (otherwise an alphabetical sort can push
  // it onto a later page right after save).
  const [recentlyAddedIds, setRecentlyAddedIds] = useState<string[]>([]);
  const [recentlyDeletedIds, setRecentlyDeletedIds] = useState<string[]>([]);
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});
  // Single human-readable message shown as a banner above the table after a
  // failed save (unique-check rejection or backend validation error). The
  // per-cell red border still comes from `formErrors`; this is the "what
  // actually happened" text the user reads to fix the row.
  const [saveErrorMessage, setSaveErrorMessage] = useState<string | null>(null);
  const [clickedDataIndex, setClickedDataIndex] = useState<string | undefined>(focusIndex);

  const { dateFormat } = useDateFormat();

  const getDateFields = useCallback((cols: EditableColumnConfig<T>[]): string[] => {
    const dateFields: string[] = [];

    const processColumns = (columns: EditableColumnConfig<T>[]) => {
      columns.forEach((column) => {
        if (column.inputType === "date" || column.inputType === "datepicker") {
          dateFields.push(column.dataIndex);
        }
        if (column.children) {
          processColumns(column.children);
        }
      });
    };

    processColumns(cols);
    return dateFields;
  }, []);

  const convertDateToISO = useCallback(
    (dateValue: unknown): unknown => {
      if (!dateValue || !dateFormat) return dateValue;

      if (dayjs.isDayjs(dateValue)) {
        return toApiDate(dateValue);
      }

      if (typeof dateValue === "string") {
        const trimmed = dateValue.trim();
        let parsed = dayjs(trimmed, dateFormat, true);

        if (!parsed.isValid()) {
          const commonFormats = [
            "DD.MM.YYYY", "D.M.YYYY", "DD.M.YYYY", "D.MM.YYYY",
            "YYYY-MM-DD", "MM/DD/YYYY", "DD/MM/YYYY",
          ];

          for (const format of commonFormats) {
            parsed = dayjs(trimmed, format, true);
            if (parsed.isValid()) break;
          }
        }

        return parsed.isValid() ? toApiDate(parsed) : dateValue;
      }

      return dateValue;
    },
    [dateFormat],
  );

  const convertISOToDisplayFormat = useCallback(
    (isoDateValue: unknown): unknown => {
      if (!isoDateValue || !dateFormat) return isoDateValue;

      if (dayjs.isDayjs(isoDateValue)) {
        return isoDateValue.format(dateFormat);
      }

      if (typeof isoDateValue === "string") {
        const parsed = dayjs(isoDateValue, "YYYY-MM-DD", true);
        return parsed.isValid() ? parsed.format(dateFormat) : isoDateValue;
      }

      return isoDateValue;
    },
    [dateFormat],
  );

  const createUrl = apiEndpoints?.create;
  const getUpdateUrl = useCallback((id: Key) => `${apiEndpoints?.update}${id}/`, [apiEndpoints?.update]);
  const getDeleteUrl = useCallback((id: Key) => `${apiEndpoints?.delete}${id}/`, [apiEndpoints?.delete]);

  const transformDataFORapi = useCallback(
    (formData: Record<string, unknown>): Record<string, unknown> => {
      const transformedData = { ...formData };

      columns.forEach((column) => {
        if (column.readOnly || column.excludeFromSave) {
          delete transformedData[column.dataIndex];
          return;
        }

        if (column.foreignKey && formData[column.dataIndex] !== undefined) {
          const { valueField } = column.foreignKey;
          const formValue = formData[column.dataIndex];

          // ``null`` is a valid "clear me" intent (e.g. picking the
          // ``{ value: null, label: "-" }`` placeholder in a select that
          // allows no selection). Pass it through to the FK column so the
          // backend sets the relation to NULL. The old short-circuit on
          // ``formValue !== null`` left the FK untouched, which is why
          // clearing a previously-set crate never actually cleared it.
          transformedData[valueField] = formValue;

          if (column.dataIndex !== valueField) {
            delete transformedData[column.dataIndex];
          }
        }

        if (column.inputType === "checkbox" && formData[column.dataIndex] !== undefined) {
          transformedData[column.dataIndex] = Boolean(formData[column.dataIndex]);
        }
      });

      return transformedData;
    },
    [columns],
  );

  const transformDataFROMapi = useCallback(
    (apiData: unknown[]): T[] => {
      if (!Array.isArray(apiData)) return [];

      return apiData.map((record) => {
        const transformedRecord = { ...(record as Record<string, unknown>) };

        columns.forEach((column) => {
          if (column.foreignKey) {
            const { valueField, displayField } = column.foreignKey;
            const idValue = (record as Record<string, unknown>)[valueField];

            if (idValue !== undefined) {
              const resolvedOptions: SelectOption[] =
                typeof column.options === "function"
                  ? column.options(record as T)
                  : column.options ?? [];

              const matchingOption = resolvedOptions?.find(
                (option) =>
                  option.value === idValue ||
                  readOptionField(option, valueField) === idValue,
              );

              if (matchingOption) {
                transformedRecord[column.dataIndex] =
                  matchingOption.label ??
                  readOptionField(matchingOption, displayField);
                transformedRecord[valueField] = idValue;
                transformedRecord[`${column.dataIndex}_id`] = idValue;
              }
            }
          }
          if (
            column.inputType === "checkbox" &&
            (record as Record<string, unknown>)[column.dataIndex] !== undefined
          ) {
            transformedRecord[column.dataIndex] = Boolean(
              (record as Record<string, unknown>)[column.dataIndex],
            );
          }
        });

        return transformedRecord as T;
      });
    },
    [columns],
  );

  const isEditing = useCallback(
    (record: T): boolean => {
      return record.key === editingKey;
    },
    [editingKey],
  );

  const edit = useCallback(
    async (record: T) => {
      if (record.key === editingKey) return;

      form.resetFields();

      let formValues: Record<string, unknown> = { ...record };

      // Set of inputTypes that represent whole numbers — the backend's
      // Decimal serializer may have padded the value with trailing zeros
      // ("8" stored as Decimal("8.00") and returned as the string "8.00"),
      // which looks wrong in an integer-typed cell. Normalize once on
      // edit-entry to a clean integer string. Decimal-typed columns are
      // intentionally left alone — "8.00" in a price field is correct.
      const integerInputTypes = new Set([
        "integer",
        "positive_integer",
        "negative_integer",
      ]);

      columns.forEach((column) => {
        if (column.foreignKey) {
          const { valueField } = column.foreignKey;
          const idValue =
            (record as Record<string, unknown>)[`${column.dataIndex}_id`] ??
            (record as Record<string, unknown>)[valueField];

          if (idValue !== undefined) {
            formValues[column.dataIndex] = idValue;
          }
        }
        if (column.inputType === "checkbox") {
          formValues[column.dataIndex] = Boolean(
            (record as Record<string, unknown>)[column.dataIndex],
          );
        }
        if (column.inputType && integerInputTypes.has(column.inputType)) {
          const raw = formValues[column.dataIndex];
          if (raw !== null && raw !== undefined && raw !== "") {
            const n = Number(raw);
            if (Number.isFinite(n)) {
              formValues[column.dataIndex] = String(Math.trunc(n));
            }
          }
        }
      });

      if (autoHandleDates) {
        const dateFields = getDateFields(columns);
        dateFields.forEach((field) => {
          if (formValues[field]) {
            formValues[field] = convertISOToDisplayFormat(formValues[field]);
          }
        });
      }

      if (customEdit) {
        formValues = customEdit(formValues as T, form) as Record<string, unknown>;
      }

      form.setFieldsValue(formValues);
      setFormErrors({});
      setSaveErrorMessage(null);
      setEditingKey(record.key);
    },
    [editingKey, form, columns, autoHandleDates, getDateFields, convertISOToDisplayFormat, customEdit],
  );

  const cancel = useCallback(() => {
    setEditingKey("");
    setData((currentData) => currentData.filter((item) => item.key !== -1));
    setFormErrors({});
    setSaveErrorMessage(null);
  }, []);

  const save = useCallback(
    async (key: Key, formValues?: Record<string, unknown>) => {
      if (!key) return;

      try {
        // ``validateFields()`` only returns REGISTERED fields (those with a
        // mounted ``<Form.Item>``). When a column is ``hidden`` in inline
        // mode, Ant Table skips the cell entirely → no Form.Item → the
        // value sits in the form store (put there by ``customEdit`` via
        // ``setFieldsValue``) but is dropped from the validation result.
        // ``getFieldsValue(true)`` exposes the full store; merging it
        // under ``row`` lets validated values still win where they overlap
        // but rescues unregistered fields like ``size: "M"`` on planning
        // pages where the size column is hidden via tenant settings.
        let row: Record<string, unknown>;
        if (formValues) {
          row = formValues;
        } else {
          const validated = await form.validateFields();
          row = { ...form.getFieldsValue(true), ...validated };
        }

        const currentRecord = data.find((record) => record.key === key);

        if (!currentRecord) {
          throw new Error(`No record found with key: ${key}`);
        }

        const disabledFields: Record<string, unknown> = {};
        const mergedRecord = buildLiveRecord(currentRecord, row, columns) as T;

        columns.forEach((column) => {
          if (column.readOnly || column.excludeFromSave) return;

          let isDisabled = false;

          if (typeof column.disabled === "function") {
            isDisabled = column.disabled(mergedRecord);
          } else if (column.disabled === true) {
            isDisabled = true;
          }

          if (isDisabled) {
            if (column.foreignKey) {
              const { valueField } = column.foreignKey;
              // Only the canonical FK locations are valid as an id source.
              // The third fallback (``currentRecord[dataIndex]``) used to
              // be here but ``dataIndex`` carries the DISPLAY label string
              // (rewritten by ``transformDataFROMapi`` to the matching
              // option's label for select rendering). Using it as an FK
              // id pushed e.g. ``"-"`` (the label of the null-option) into
              // the save payload, which the backend then rejected as
              // "Ungültiger pk".
              const valueFieldId = (currentRecord as Record<string, unknown>)[
                valueField
              ];
              const altId = (currentRecord as Record<string, unknown>)[
                `${column.dataIndex}_id`
              ];
              const idValue =
                valueFieldId !== undefined ? valueFieldId : altId ?? null;
              disabledFields[column.dataIndex] = idValue;
            } else {
              disabledFields[column.dataIndex] = (currentRecord as Record<string, unknown>)[
                column.dataIndex
              ];
            }
          }
        });

        const completeRow: Record<string, unknown> = {
          ...row,
          ...disabledFields,
        };

        const processedRow = { ...completeRow };

        if (autoHandleDates) {
          const dateFields = getDateFields(columns);
          dateFields.forEach((field) => {
            if (processedRow[field]) {
              processedRow[field] = convertDateToISO(processedRow[field]);
            }
          });
        }

        let transformedRow = transformDataFORapi(processedRow);

        if (customSave) {
          try {
            const result = customSave(transformedRow, currentRecord);
            if (result === null) return;
            // ``customSave`` may signal that the row should be DELETED rather
            // than saved — e.g. clearing an order's amount removes the
            // OrderContent entirely (offers with no order are placeholder
            // stubs, not null-amount rows). Route through the same delete
            // path as the per-row delete control.
            if (result.__deleteOnSave === true) {
              if (key !== -1 && apiFunctions?.delete) {
                await apiFunctions.delete(String(key));
                const remaining = data.filter((item) => item.key !== key);
                setData(remaining);
                setEditingKey("");
                setFormErrors({});
                setSaveErrorMessage(null);
                if (onDataChange) onDataChange(remaining);
                if (onDeleteSuccess) onDeleteSuccess(key);
              } else {
                // New/placeholder draft — nothing persisted yet; just drop it.
                setEditingKey("");
                setFormErrors({});
              }
              return;
            }
            transformedRow = result;
          } catch (customSaveError) {
            setSaveErrorMessage((customSaveError as Error).message);
            return;
          }
        }

        // Uniqueness validation
        if (uniqueCheck) {
          const fieldsToCheck = Array.isArray(uniqueCheck) ? uniqueCheck : [uniqueCheck];
          const errors: Record<string, string> = {};

          if (fieldsToCheck.length > 1) {
            const duplicateExists = data.some((record) => {
              if (record.key === key || record.key === -1) return false;
              return fieldsToCheck.every(
                (fieldName) =>
                  (record as Record<string, unknown>)[fieldName] ===
                  transformedRow[fieldName],
              );
            });

            if (duplicateExists) {
              const fieldNames = fieldsToCheck.join(" + ");
              const msg =
                uniqueCheckMessage || `This combination of ${fieldNames} already exists.`;
              errors[fieldsToCheck[0]] = msg;
            }
          } else {
            const fieldName = fieldsToCheck[0];
            const valueToCheck = transformedRow[fieldName];

            if (valueToCheck !== undefined && valueToCheck !== null && valueToCheck !== "") {
              const duplicateExists = data.some(
                (record) =>
                  record.key !== key &&
                  record.key !== -1 &&
                  (record as Record<string, unknown>)[fieldName] === valueToCheck,
              );

              if (duplicateExists) {
                const msg =
                  uniqueCheckMessage ||
                  `This ${fieldName} already exists. Please choose a different value.`;
                errors[fieldName] = msg;
              }
            }
          }

          if (Object.keys(errors).length > 0) {
            // Both: mark the offending field with a red border via formErrors
            // AND surface the message in the banner above the table. Toast is
            // gone — the banner stays until the user fixes the row.
            setFormErrors(errors);
            setSaveErrorMessage(Object.values(errors)[0]);
            return;
          }
        }

        // API call
        let savedRecord: unknown;

        if (customUpdate) {
          savedRecord = await customUpdate(key, transformedRow);
        } else if (key === -1) {
          if (apiFunctions?.create) {
            const response = await apiFunctions.create(transformedRow);
            savedRecord =
              (response?.data as Record<string, unknown>)?.grouped_data ?? response?.data;
          } else {
            if (!createUrl) throw new Error("Create URL not configured");
            const response = await axiosService.post(createUrl, transformedRow);
            savedRecord =
              (response?.data as Record<string, unknown>)?.grouped_data ?? response?.data;
          }
        } else {
          if (apiFunctions?.update) {
            const response = await apiFunctions.update(String(key), transformedRow);
            savedRecord =
              (response?.data as Record<string, unknown>)?.grouped_data ?? response?.data;
          } else {
            const updateUrl = getUpdateUrl(key);
            if (!apiEndpoints?.update) throw new Error("Update URL not configured");
            const response = await axiosService.patch(updateUrl, transformedRow);
            savedRecord =
              (response?.data as Record<string, unknown>)?.grouped_data ?? response?.data;
          }
        }

        if (!savedRecord) {
          throw new Error("No data returned from server");
        }

        setEditingKey("");
        setFormErrors({});
        setSaveErrorMessage(null);

        if (key === -1) {
          const newRecord = { ...transformDataFROMapi([savedRecord])[0], key: (savedRecord as T).id };
          const newDataWithRecord = [newRecord, ...data.filter((item) => item.key !== -1)];
          setData(newDataWithRecord);
          const newId = (savedRecord as T).id;
          if (typeof newId === "string" && newId) {
            setRecentlyAddedIds((prev) =>
              prev.includes(newId) ? prev : [newId, ...prev],
            );
          }
          if (onDataChange) {
            onDataChange(newDataWithRecord);
          }
          if (onSaveSuccess) {
            onSaveSuccess(savedRecord as T, "create");
          }
        } else {
          // Merge the server response OVER the existing row rather than
          // replacing it. Partial-update endpoints (e.g. set-invoice-note
          // returns only ``{note}``) would otherwise blank every other column.
          // For a full response this is equivalent to a replace (each returned
          // field overwrites the old value); for a partial one the untouched
          // columns survive.
          const updatedRecord = {
            ...currentRecord,
            ...transformDataFROMapi([savedRecord])[0],
            key,
          };
          const newData = data.map((item) => (item.key === key ? updatedRecord : item));
          setData(newData);
          if (onDataChange) {
            onDataChange(newData);
          }
          if (onSaveSuccess) {
            onSaveSuccess(savedRecord as T, "update");
          }
        }
      } catch (error) {
        console.error("Save operation failed:", error);

        // Per-field red borders: extract field → message from any of the
        // shapes the backend speaks. DRF defaults emit top-level
        // `{field: ["msg"]}`; the canonical Jasmin handler emits
        // `{message, details: {field: ["msg"]}}` (the top-level `message`
        // is just the first one and lacks the field name).
        const axiosError = error as {
          response?: { data?: Record<string, unknown> };
        };
        const data = axiosError.response?.data;
        const fieldErrors: Record<string, string> = {};

        const collectFieldMessages = (
          source: Record<string, unknown>,
          skip: Set<string>,
          arraysOnly = false,
        ) => {
          for (const [k, v] of Object.entries(source)) {
            if (skip.has(k)) continue;
            if (Array.isArray(v) && typeof v[0] === "string") {
              fieldErrors[k] = v[0];
            } else if (!arraysOnly && typeof v === "string") {
              fieldErrors[k] = v;
            }
          }
        };

        if (data && typeof data === "object") {
          // DRF top-level field shape
          collectFieldMessages(
            data,
            new Set(["code", "message", "details", "request_id", "field"]),
          );
          // Canonical Jasmin `details` map. Only ARRAY values are per-field
          // error lists (the `{field: ["msg"]}` shape). Scalar entries are
          // interpolation context for the coded message (e.g. over_capacity's
          // `station_day_id`, `year`, `week`) — collecting those would wrongly
          // tag a real form field and prepend its name to the banner.
          const details = data.details;
          if (details && typeof details === "object") {
            collectFieldMessages(
              details as Record<string, unknown>,
              new Set(),
              true,
            );
          }
        }
        setFormErrors(fieldErrors);

        // Banner: prepend the offending field names so the user can see
        // *which* fields are broken, not just the (often generic) message.
        // Field names use the matching column title when available, falling
        // back to the raw schema name.
        const baseMessage = getErrorMessage(
          error,
          t("table.save_failed_generic"),
        );
        const fields = Object.keys(fieldErrors);
        if (fields.length > 0) {
          const labels = fields.map((name) => {
            const col = columns.find((c) => c.dataIndex === name);
            return typeof col?.title === "string" ? col.title : name;
          });
          setSaveErrorMessage(`${labels.join(", ")}: ${baseMessage}`);
        } else {
          setSaveErrorMessage(baseMessage);
        }
      }
    },
    [
      form,
      createUrl,
      getUpdateUrl,
      transformDataFORapi,
      transformDataFROMapi,
      customSave,
      customUpdate,
      autoHandleDates,
      getDateFields,
      convertDateToISO,
      data,
      uniqueCheck,
      uniqueCheckMessage,
      columns,
      onDataChange,
      onSaveSuccess,
      onDeleteSuccess,
      apiEndpoints?.update,
      apiFunctions,
      t,
    ],
  );

  const add = useCallback(async (): Promise<T | undefined> => {
    const addRecord = data.findIndex((item) => item.key === -1);
    if (addRecord > -1) return data[addRecord];

    await save(editingKey);

    const newEntry = { key: -1 } as T;
    const newData = [newEntry, ...data];
    form.resetFields();
    setFormErrors({});
    setData(newData);
    edit(newEntry);

    return newEntry;
  }, [data, form, save, editingKey, edit]);

  const deleteRecord = useCallback(
    async (key: Key) => {
      if (!key) return;

      try {
        const record = data.find((item) => item.key === key);

        if (!record) {
          throw new Error(`Record with key ${key} not found in data`);
        }

        if (apiFunctions?.delete) {
          if (customDelete) {
            const deleteParams = customDelete(record);
            await apiFunctions.delete(String(key), deleteParams ?? undefined);
          } else {
            await apiFunctions.delete(String(key));
          }
        } else if (customDelete) {
          const deleteParams = customDelete(record);
          const deleteUrl = getDeleteUrl(key);

          if (deleteParams) {
            await axiosService.delete(deleteUrl, { data: deleteParams });
          } else {
            await axiosService.delete(deleteUrl);
          }
        } else {
          let deleteUrl = getDeleteUrl(key);

          if (deleteContext) {
            const separator = deleteUrl.includes("?") ? "&" : "?";
            if (typeof deleteContext === "object") {
              const params = new URLSearchParams();
              const ctx = deleteContext as Record<string, string>;
              if (ctx.selectedYear) params.append("year", ctx.selectedYear);
              if (ctx.selectedWeek) params.append("delivery_week", ctx.selectedWeek);
              if (ctx.selectedDay) params.append("delivery_day", ctx.selectedDay);
              deleteUrl = `${deleteUrl}${separator}${params.toString()}`;
            } else {
              deleteUrl = `${deleteUrl}${separator}delete_context=${deleteContext}`;
            }
          }
          await axiosService.delete(deleteUrl);
        }

        const newData = data.filter((item) => item.key !== key);
        setData(newData);
        // Remember the deleted id so the initialData-sync effect filters it out
        // of a stale refetch that raced ahead of the backend delete — otherwise
        // the row briefly reappears (flicker) before the next refetch settles.
        const deletedId = record.id;
        if (typeof deletedId === "string" && deletedId) {
          setRecentlyDeletedIds((prev) =>
            prev.includes(deletedId) ? prev : [deletedId, ...prev],
          );
        }
        if (onDataChange) {
          onDataChange(newData);
        }
        if (onDeleteSuccess) {
          onDeleteSuccess(key);
        }
      } catch (error) {
        console.error("Delete operation failed:", error);
        throw error;
      }
    },
    [data, getDeleteUrl, onDataChange, deleteContext, customDelete, onDeleteSuccess, apiFunctions],
  );

  const setDataWithTransform = useCallback(
    (newData: T[] | ((prev: T[]) => T[])) => {
      if (typeof newData === "function") {
        setData((currentData) => {
          const result = newData(currentData);
          return Array.isArray(result) ? transformDataFROMapi(result) : result;
        });
      } else {
        setData(Array.isArray(newData) ? transformDataFROMapi(newData) : newData);
      }
    },
    [transformDataFROMapi],
  );

  return {
    form,
    data,
    setDataWithTransform,
    loading,
    setLoading,
    editingKey,
    formErrors,
    saveErrorMessage,
    setSaveErrorMessage,
    clickedDataIndex,
    setClickedDataIndex,
    isEditing,
    edit,
    cancel,
    save,
    add,
    deleteRecord,
    recentlyAddedIds,
    recentlyDeletedIds,
  };
};
