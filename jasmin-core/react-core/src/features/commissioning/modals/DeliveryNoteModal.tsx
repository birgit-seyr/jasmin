import { useQueryClient } from "@tanstack/react-query";
import type { FormInstance } from "antd";
import { Modal } from "antd";
import ModalCloseFooter from "@shared/modals/ModalCloseFooter";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningCrateContentsDeliveryNoteCreate,
  commissioningCrateContentsDeliveryNoteDestroy,
  commissioningCrateContentsDeliveryNotePartialUpdate,
  commissioningDeliveryNoteContentsCreate,
  commissioningDeliveryNoteContentsDestroy,
  commissioningDeliveryNoteContentsPartialUpdate,
  getCommissioningDeliveryNotesRetrieveQueryKey,
  useCommissioningDeliveryNotesRetrieve,
} from "@shared/api/generated/commissioning/commissioning";
import type { CommissioningCrateContentsDeliveryNoteDestroyParams } from "@shared/api/generated/models/commissioningCrateContentsDeliveryNoteDestroyParams";
import type { CrateDeliveryNoteContent } from "@shared/api/generated/models/crateDeliveryNoteContent";
import type { CrateDeliveryNoteContentWriteRequest } from "@shared/api/generated/models/crateDeliveryNoteContentWriteRequest";
import type { DeliveryNoteResellerContent } from "@shared/api/generated/models/deliveryNoteResellerContent";
import { useRoles } from "@shared/auth";
import { useDateFormat, useDefaultTaxRates, useNoteColumn, useNumberFormat } from '@hooks/index';
import { formatAmountForUnit } from "@shared/utils";
import { makeContentCustomEdit, makeFkCustomSave } from "./contentTableHelpers";
import { useAmountUnitSizeColumns, useCratesColumns, useShareArticleColumn } from '@features/commissioning/hooks';
import { FinalizedNotice } from '@features/commissioning/components';
import { EditableTable, gatedByPermission, wrapApiFunctions } from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { DiffCell } from "@shared/ui";

type DeliveryNoteContentRecord = DeliveryNoteResellerContent & TableRecord;
type CrateContentRecord = CrateDeliveryNoteContent & TableRecord;

interface DeliveryNoteModalProps {
  visible: boolean;
  onClose: () => void;
  deliveryNoteId: string | null;
}

export default function DeliveryNoteModal({
  visible,
  onClose,
  deliveryNoteId,
}: DeliveryNoteModalProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { isOffice } = useRoles();
  const { format } = useNumberFormat();
  const { formatDate, formatDateWithFallback } = useDateFormat();
  // Fallback tax rate for new lines when the picked ShareArticle
  // doesn't carry an annotated current rate. Matches the InvoiceModal.
  const { articles: defaultTaxRateArticles } = useDefaultTaxRates();

  // ``isFetching`` (not ``isLoading``): drives the EditableTable grid spinner.
  // With the global staleTime:0, reopening a previously-viewed note has
  // ``isLoading === false`` (cached), so only ``isFetching`` surfaces the
  // refresh while the retrieve refetches.
  const { data: deliveryNoteData, isFetching: loading } =
    useCommissioningDeliveryNotesRetrieve(deliveryNoteId!, {
      query: { enabled: visible && !!deliveryNoteId },
    });

  const lineItems = useMemo(
    () => (deliveryNoteData?.line_items ?? []) as DeliveryNoteContentRecord[],
    [deliveryNoteData],
  );
  const lineItemsCrates = useMemo(
    () =>
      (deliveryNoteData?.crate_items ?? []) as unknown as CrateContentRecord[],
    [deliveryNoteData],
  );
  const isFinalized = deliveryNoteData?.is_finalized ?? false;
  const permissions = useMemo(
    () => gatedByPermission(!isFinalized && isOffice),
    [isFinalized, isOffice],
  );

  // Delivery notes include both regular and extra share articles.
  // ``get_price_info=true`` makes the backend annotate each
  // ShareArticle option with its currently-valid ``tax_rate`` (and
  // every other DecimalField on ``ShareArticleNetPrice``) so the
  // share-article-change handler can pick the right tax rate
  // without a second round-trip. ``shareArticles`` exposed below
  // carries those annotations.
  const {
    shareArticleColumn,
    shareArticles,
  } = useShareArticleColumn({
    filters: { include_extra: true, get_price_info: true } as Record<
      string,
      unknown
    >,
    onFieldChange: (...args: unknown[]) => {
      // Auto-fill ``tax_rate`` on share-article pick. Use the
      // article's own current tax_rate (annotated by the backend
      // via ``get_price_info=true``) when present, fall back to
      // the tenant default. The ``OrderableItem`` model requires
      // tax_rate non-null at save time — without this the office
      // would have to remember to set it for every new line.
      const shareArticleValue = args[0] as string | undefined;
      const form = args[2] as FormInstance | undefined;
      if (!form) return {};
      const picked = shareArticles.find(
        (a) => a.value === shareArticleValue,
      ) as (Record<string, unknown> & { tax_rate?: string | number }) | undefined;
      const articleTaxRate =
        picked && picked.tax_rate != null ? Number(picked.tax_rate) : null;
      const resolved =
        articleTaxRate != null && Number.isFinite(articleTaxRate)
          ? articleTaxRate
          : defaultTaxRateArticles;
      form.setFieldsValue({ tax_rate: resolved });
      return { tax_rate: resolved };
    },
  });
  const { noteColumn } = useNoteColumn({ inputType: "optional" });

  const { amountUnitSizeColumns } = useAmountUnitSizeColumns({
    overrides: {
      amount: {
        title: t("commissioning.ordered_amount"),
        width: "6em",
        render: (value: unknown, record: DeliveryNoteContentRecord) => {
          const numValue = Number(value);
          if (isNaN(numValue) || numValue === 0) return "";
          return formatAmountForUnit(numValue, record.unit, format);
        },
      },
    },
  });

  const { cratesColumns: columnsCrates, crates: crateOptions } =
    useCratesColumns({
      without_price: true,
    });

  // Filter out crate-types already used on this delivery note — same
  // pattern as Orders.tsx (useColumnsOrders.filteredColumnsCrates).
  // Without this, the office could pick the same crate type twice and
  // hit the (delivery_note, crate_type) unique constraint at save.
  const filteredColumnsCrates = useMemo(() => {
    const usedCrateTypes = new Set(
      lineItemsCrates.map(
        (item) => (item as Record<string, unknown>).crate_type,
      ),
    );
    const availableOptions = crateOptions.filter(
      (opt) => !usedCrateTypes.has(opt.value as string),
    );
    return columnsCrates.map((col) =>
      col.key === "crate_type_name"
        ? { ...col, options: availableOptions }
        : col,
    );
  }, [columnsCrates, crateOptions, lineItemsCrates]);

  // When no unused crate-types remain, disable the add-row button on
  // the crates table (edit/delete still allowed for existing rows).
  const cratesPermissions = useMemo(() => {
    const usedCrateTypes = new Set(
      lineItemsCrates.map(
        (item) => (item as Record<string, unknown>).crate_type,
      ),
    );
    const hasAvailable = crateOptions.some(
      (opt) => !usedCrateTypes.has(opt.value as string),
    );
    const baseCanWrite = !isFinalized && isOffice;
    return {
      canAdd: baseCanWrite && hasAvailable,
      canEdit: baseCanWrite,
      canDelete: baseCanWrite,
    };
  }, [crateOptions, lineItemsCrates, isFinalized, isOffice]);

  // Invalidate the delivery-note retrieve query after every save AND
  // delete. Mirrors InvoiceModal — the local-state-only pattern of
  // ``useInvalidateAfterTableMutation`` lets stale rows linger when
  // the user deletes everything and re-adds a line (the new row
  // disappears) and occasionally keeps a just-deleted row visible.
  // Round-tripping through the cache is the reliable fix.
  const invalidateDeliveryNote = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningDeliveryNotesRetrieveQueryKey(deliveryNoteId!),
    });
  }, [queryClient, deliveryNoteId]);

  // CREATE invalidates so the delivery-note's tax-breakdown
  // summary + crate-type filter (which depends on used types) get
  // re-derived; UPDATE skips invalidation so an edited row stays
  // where the office put it. DELETE always invalidates so the row
  // vanishes and totals refresh.
  const handleSaveSuccess = useCallback(
    (_record: TableRecord, action: "create" | "update") => {
      if (action === "create") {
        invalidateDeliveryNote();
      }
    },
    [invalidateDeliveryNote],
  );

  const handleDeleteSuccess = useCallback(() => {
    invalidateDeliveryNote();
  }, [invalidateDeliveryNote]);

  const columns = useMemo<EditableColumnConfig<DeliveryNoteContentRecord>[]>(
    () => [
      {
        ...shareArticleColumn,
        disabled: (record) => record.key !== -1,
      },
      {
        title: <>{t("commissioning.sort")}</>,
        dataIndex: "sort",
        key: "sort",
        inputType: "optional",
        required: false,
        width: "8em",
      },
      ...amountUnitSizeColumns.map((col) => {
        // `differField` / `originalField` are runtime-derived keys, so
        // TS can't statically narrow them — index access still needs a
        // cast even with a typed record.
        const differField = `${col.dataIndex}_differs`;
        const originalField = `original_${col.dataIndex}`;

        return {
          ...col,
          render: (value: unknown, record: DeliveryNoteContentRecord) => (
            <DiffCell
              value={
                (col as EditableColumnConfig).render
                  ? (col as EditableColumnConfig).render!(
                      value,
                      record as TableRecord,
                      0,
                    )
                  : (value as string)
              }
              differs={record[differField] as boolean | undefined}
              original={record[originalField]}
            />
          ),
        };
      }),

      noteColumn,
      // ``tax_rate`` is intentionally NOT shown as a column on the
      // delivery note — corrections happen on the InvoiceModal where
      // tax math actually matters. The value is still auto-filled
      // (from the picked share article, or the tenant default) and
      // persisted on the row so the OrderableItem NOT NULL
      // constraint is satisfied.
    ],
    [shareArticleColumn, amountUnitSizeColumns, noteColumn, t],
  );

  const customSave = useMemo(
    () => makeFkCustomSave("delivery_note", deliveryNoteId),
    [deliveryNoteId],
  );

  const customSaveCrates = useMemo(
    () => makeFkCustomSave("delivery_note_id", deliveryNoteData?.id),
    [deliveryNoteData?.id],
  );

  // ``tax_rate`` defaults to the tenant fallback so the model (``OrderableItem``)
  // NOT NULL constraint is satisfied even if the office never picks a
  // share_article (the on-change handler overrides it with the picked article's
  // own tax_rate when one is selected).
  const customEdit = useMemo(
    () => makeContentCustomEdit(defaultTaxRateArticles),
    [defaultTaxRateArticles],
  );

  const customDeleteCrates = useCallback(
    (record: TableRecord) => {
      return {
        crate_type: (record as Record<string, unknown>).crate_type,
        delivery_note_id: deliveryNoteId,
      };
    },
    [deliveryNoteId],
  );

  const apiFunctionsContents = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<DeliveryNoteContentRecord>({
        create: (data) => commissioningDeliveryNoteContentsCreate(data),
        update: (id, data) =>
          commissioningDeliveryNoteContentsPartialUpdate(id, data),
        delete: (id) => commissioningDeliveryNoteContentsDestroy(id),
      }),
    [],
  );

  const apiFunctionsCrates = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<CrateDeliveryNoteContentWriteRequest & TableRecord>({
        create: (data) => commissioningCrateContentsDeliveryNoteCreate(data),
        update: (id, data) =>
          commissioningCrateContentsDeliveryNotePartialUpdate(
            id,
            data as unknown as CrateDeliveryNoteContent,
          ),
        delete: (id, data) =>
          commissioningCrateContentsDeliveryNoteDestroy(
            id,
            data as unknown as CommissioningCrateContentsDeliveryNoteDestroyParams,
          ),
      }),
    [],
  );

  return (
    <Modal
      title={
        deliveryNoteData
          ? `${t("commissioning.delivery_note_details")} ${deliveryNoteData.prefix}-${deliveryNoteData.delivery_note_number}`
          : ""
      }
      open={visible}
      onCancel={onClose}
      width={1200}
      footer={[
        <ModalCloseFooter key="close" onClose={onClose} />,
      ]}
    >
      {deliveryNoteData && (
        <div>
          <div style={{ marginBottom: "1em" }}>
            <p>
              <strong>{t("resellers.reseller")}</strong>{" "}
              {deliveryNoteData.reseller_name}
            </p>
            <p>
              <strong>{t("commissioning.delivery_note_date")}</strong>{" "}
              {formatDate(deliveryNoteData.delivery_note_date)}
            </p>
            <p>
              <strong>{t("commissioning.corresponding_order")}</strong>{" "}
              {deliveryNoteData.order_prefix}-{deliveryNoteData.order_number} (
              {formatDateWithFallback(deliveryNoteData.order_date, "")}
              )
            </p>
          </div>
          {isFinalized && (
            <FinalizedNotice
              label={t("commissioning.delivery_note_finalized_notice")}
              at={deliveryNoteData.finalized_at}
            />
          )}

          <EditableTable
            key={deliveryNoteId!}
            columns={columns as EditableColumnConfig[]}
            apiFunctions={apiFunctionsContents}
            initialData={lineItems}
            onSaveSuccess={handleSaveSuccess}
            onDeleteSuccess={handleDeleteSuccess}
            permissions={permissions}
            loading={loading}
            customSave={customSave}
            customEdit={customEdit}
            uniqueCheck={["share_article", "size", "unit"]}
            uniqueCheckMessage={t(
              "validation.unique.share_article_unit_size_must_be_unique",
            )}
          />
          <div style={{ marginTop: "4em", marginBottom: "-1em" }}>
            <h5>{t("commissioning.crates")}</h5>
          </div>
          <EditableTable
            key="crates"
            columns={filteredColumnsCrates as EditableColumnConfig[]}
            apiFunctions={apiFunctionsCrates}
            initialData={lineItemsCrates}
            onSaveSuccess={handleSaveSuccess}
            onDeleteSuccess={handleDeleteSuccess}
            permissions={cratesPermissions}
            loading={loading}
            customSave={customSaveCrates}
            customDelete={customDeleteCrates}
            uniqueCheck={["crate_type"]}
            uniqueCheckMessage={t("validation.unique.delivery_note_modal_crate")}
          />
        </div>
      )}
    </Modal>
  );
}
