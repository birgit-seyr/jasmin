import type { FormInstance } from "antd";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";

/**
 * Shared `customEdit` seed for the reseller content tables (InvoiceModal +
 * DeliveryNoteModal). A brand-new row (`key === -1`) is pre-filled with the
 * default size / unit and the tenant's default article tax rate, so the
 * `OrderableItem` NOT NULL `tax_rate` constraint is satisfied even before a
 * share article is picked (the on-change handler overrides the rate with the
 * picked article's own when one is selected).
 *
 * The Invoice and DeliveryNote documents stay distinct — this only shares the
 * byte-for-byte identical new-line seed, not the documents themselves.
 */
export function makeContentCustomEdit(defaultTaxRateArticles: number) {
  return (record: TableRecord, form: FormInstance): TableRecord => {
    if (record.key === -1) {
      const defaultValues = {
        size: "M",
        unit: "KG",
        tax_rate: defaultTaxRateArticles,
      };
      form.setFieldsValue(defaultValues);
      return { ...record, ...defaultValues } as TableRecord;
    }
    return record;
  };
}

/**
 * Shared `customSave` that stamps the parent-document FK onto every content
 * row before it is persisted (the two documents differ only in the FK field
 * name — `invoice` / `delivery_note`, `invoice_id` / `delivery_note_id`).
 */
export function makeFkCustomSave(fkField: string, fkValue: unknown) {
  return (transformedData: Record<string, unknown>): Record<string, unknown> => ({
    ...transformedData,
    [fkField]: fkValue,
  });
}
