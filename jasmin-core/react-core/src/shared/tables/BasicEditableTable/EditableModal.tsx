import { useEffect } from "react";
import type { KeyboardEvent, ReactElement, ReactNode } from "react";
import type { Dayjs } from "dayjs";
import { Modal, Form } from "antd";
import FormInput from "./FormInput";
import { useTranslation } from "react-i18next";
import { useNumberFormat } from "@hooks/useNumberFormat";
import type { EditableModalProps, EditableColumnConfig, TableRecord } from "./types";
import { buildLiveRecord } from "./buildLiveRecord";
import { getEditableFormItemProps } from "./formItemProps";

interface ProcessedColumn<T extends TableRecord = TableRecord>
  extends EditableColumnConfig<T> {
  type?: "section-header";
  parentTitle?: ReactNode;
}

const EditableModal = <T extends TableRecord = TableRecord>({
  visible,
  onCancel,
  onSave,
  record,
  columns,
  loading,
  customEdit,
}: EditableModalProps<T>) => {
  const [form] = Form.useForm();
  const { t } = useTranslation();
  const { separators } = useNumberFormat();
  const formValues = Form.useWatch([], form);

  useEffect(() => {
    if (visible && record) {
      form.resetFields();

      let values: Record<string, unknown> = { ...record };

      columns.forEach((column) => {
        const value = record[column.dataIndex as keyof T];

        if (column.foreignKey) {
          const { valueField } = column.foreignKey;
          const idValue =
            (record as Record<string, unknown>)[`${column.dataIndex}_id`] ??
            (record as Record<string, unknown>)[valueField];
          if (idValue !== undefined) {
            values[column.dataIndex] = idValue;
          }
        }

        if (column.inputType === "date" && value && column.render) {
          const renderedValue = column.render(value, record as T, 0);

          if (
            renderedValue &&
            typeof renderedValue === "object" &&
            (renderedValue as ReactElement).props
          ) {
            values[column.dataIndex] = (renderedValue as ReactElement<{children?: ReactNode}>).props.children;
          } else if (renderedValue && typeof renderedValue === "string") {
            values[column.dataIndex] = renderedValue;
          }
        }
      });

      if (customEdit) {
        values = customEdit(values as T, form) as Record<string, unknown>;
      }

      form.setFieldsValue(values);
    }
  }, [visible, record, columns, customEdit, form]);

  useEffect(() => {
    if (visible) {
      const firstEditableColumn = columns.find(
        (col) =>
          col.inputType &&
          !col.hideInModal &&
          !col.readOnly &&
          col.dataIndex !== "actions",
      );

      if (firstEditableColumn) {
        setTimeout(() => {
          const focusElement = form.getFieldInstance(
            firstEditableColumn.dataIndex,
          );
          if (focusElement?.focus) {
            focusElement.focus();
          }
        }, 100);
      }
    }
  }, [visible, columns, form]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();

      const disabledFields: Record<string, unknown> = {};
      const mergedRecord = buildLiveRecord(record, values, columns) as T;
      columns.forEach((column) => {
        if (column.readOnly || column.excludeFromSave) return;

        const isDisabled = record
          ? typeof column.disabled === "function"
            ? column.disabled(mergedRecord)
            : column.disabled
          : false;

        if (isDisabled && record) {
          if (column.foreignKey) {
            const { valueField } = column.foreignKey;
            disabledFields[column.dataIndex] =
              (record as Record<string, unknown>)[`${column.dataIndex}_id`] ??
              (record as Record<string, unknown>)[valueField];
          } else {
            disabledFields[column.dataIndex] = (record as Record<string, unknown>)[column.dataIndex];
          }
        }
      });

      const completeValues = {
        ...values,
        ...disabledFields,
      };

      await onSave(completeValues);
    } catch (error) {
      console.error("Modal save validation failed:", error);
    }
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSave();
    }
  };

  const renderFormInput = (column: EditableColumnConfig<T>) => {
    const mergedRecord = buildLiveRecord(
      record,
      formValues,
      columns,
    ) as T;
    const isDisabled =
      record &&
      (typeof column.disabled === "function"
        ? column.disabled(mergedRecord)
        : column.disabled);

    const wrappedOnFieldChange = column.onFieldChange
      ? (value: unknown, rec: Record<string, unknown>, f: typeof form) => {
          return column.onFieldChange!(value, rec as T, f, column.dataIndex);
        }
      : undefined;

    return (
      <FormInput
        inputType={column.inputType}
        required={column.required}
        options={
          typeof column.options === "function"
            ? column.options({ ...(record ?? {}), ...formValues } as T)
            : column.options
        }
        title={column.title}
        suffix={column.suffix}
        isModal={true}
        onFieldChange={wrappedOnFieldChange}
        record={record ?? undefined}
        form={form}
        onKeyDown={handleKeyDown}
        disabled={!!isDisabled}
        // Forward the same column props the inline cell editor honours, so the
        // modal mirrors it: the date restriction (valid_from → Mondays only,
        // valid_until → Sundays only, else the backend TimeBoundMixin rejects),
        // the input adornment, and any per-column styling.
        // Curry the live (form-merged) record in so record-aware pickers —
        // the cross-field ``valid_until > valid_from`` floor, ``validUntilFloor``
        // — work in modal mode too (AntD's ``disabledDate`` only passes the
        // date). Mirrors the inline cell editor.
        disabledDate={
          column.disabledDate
            ? (current: Dayjs) => column.disabledDate!(current, mergedRecord)
            : undefined
        }
        prefix={column.prefix}
        className={column.className}
      />
    );
  };

  const getFormRules = (column: EditableColumnConfig<T>) => {
    const rules = [...(column.rules || [])];
    if (column.required) {
      rules.push({ required: true, message: "Required!" });
    }
    return rules;
  };

  // Shared with the inline cell editor (EditableCell) so the two never drift:
  // boolean valuePropName (checkbox/switch → "checked") + locale-aware decimal
  // IO (display the tenant's decimal char, normalise "," → "." at the form
  // boundary so a typed "6,5" doesn't reach the API and 400).
  const getFormItemProps = (column: EditableColumnConfig<T>) =>
    getEditableFormItemProps(column.inputType, separators);

  const processColumns = (cols: EditableColumnConfig<T>[]): ProcessedColumn<T>[] => {
    const processed: ProcessedColumn<T>[] = [];
    let sectionCounter = 0;

    cols.forEach((col, colIndex) => {
      if (col.children && Array.isArray(col.children)) {
        processed.push({
          type: "section-header",
          title: col.title,
          key: `section-${col.key || col.dataIndex || colIndex}-${sectionCounter++}`,
          dataIndex: "",
          hideInModal: col.hideInModal,
        });

        col.children.forEach((childCol, childIndex) => {
          processed.push({
            ...childCol,
            parentTitle: col.title,
            hideInModal: childCol.hideInModal || col.hideInModal,
            key: childCol.key || `${childCol.dataIndex}-${colIndex}-${childIndex}`,
          });
        });
      } else {
        processed.push({
          ...col,
          key: col.key || col.dataIndex || `col-${colIndex}`,
        });
      }
    });

    return processed;
  };

  return (
    <Modal
      title={
        record?.key === -1
          ? t("table.add_record") || "Add Record"
          : t("table.edit_record") || "Edit Record"
      }
      open={visible}
      onOk={handleSave}
      onCancel={onCancel}
      width="30em"
      okText={t("table.save") || "Save"}
      cancelText={t("table.cancel") || "Cancel"}
      confirmLoading={loading}
    >
      <Form form={form} layout="vertical" onKeyDown={handleKeyDown}>
        {processColumns(columns)
          .filter((column) => {
            if (column.dataIndex === "actions") return false;
            if (column.hideInModal === true) return false;
            if (column.type === "section-header") return true;
            if (column.readOnly === true) return false;
            if (!column.inputType) return false;
            if (column.render && !column.inputType) return false;
            return true;
          })
          .map((column) => {
            if (column.type === "section-header") {
              return (
                <div
                  key={column.key}
                  style={{
                    marginTop: "24px",
                    marginBottom: "12px",
                    paddingBottom: "8px",
                    borderBottom: "1px solid var(--color-border)",
                    fontWeight: "600",
                    fontSize: "14px",
                    color: "var(--color-text-primary)",
                  }}
                >
                  {column.title}
                </div>
              );
            }

            // Booleans (checkbox / switch) render inline with their label.
            if (
              column.inputType === "checkbox" ||
              column.inputType === "switch"
            ) {
              return (
                <div
                  key={column.dataIndex}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "6px",
                    marginBottom: "2px",
                  }}
                >
                  <Form.Item
                    name={column.dataIndex}
                    rules={getFormRules(column)}
                    valuePropName={getFormItemProps(column).valuePropName}
                    style={{ margin: 0 }}
                  >
                    {renderFormInput(column)}
                  </Form.Item>
                  <span style={{ whiteSpace: "nowrap" }}>{column.title}</span>
                </div>
              );
            }

            const formItemProps = getFormItemProps(column);
            return (
              <Form.Item
                key={column.dataIndex}
                name={column.dataIndex}
                label={column.title}
                rules={getFormRules(column)}
                valuePropName={formItemProps.valuePropName}
                getValueFromEvent={formItemProps.getValueFromEvent}
                getValueProps={formItemProps.getValueProps}
              >
                {renderFormInput(column)}
              </Form.Item>
            );
          })}
      </Form>
    </Modal>
  );
};

export default EditableModal;
