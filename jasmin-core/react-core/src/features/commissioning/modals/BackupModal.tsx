import { Modal } from "antd";
import ModalCloseFooter from "@shared/modals/ModalCloseFooter";
import type { Key, ReactNode } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { commissioningHarvestSharePlanningBackupUpdate } from "@shared/api/generated/commissioning/commissioning";
import type { HarvestSharePlanningBackupRequest } from "@shared/api/generated/models/harvestSharePlanningBackupRequest";
import { useRoles } from "@shared/auth";
import { useNumberFormat, useSizeOptions, useUnitOptions } from "@hooks/index";
import {
  dayVariationKey,
  parseDayVariationKey,
  useShareArticles,
  usePlanningAxes,
  variationColumnKey,
} from "@features/commissioning/hooks";
import { gatedByPermissionOnlyEdit } from "@shared/tables/tablePermissions";
import type { ShareTypeVariationOption } from "@features/commissioning/hooks/useShareTypeVariations";
import { EditableTable, wrapApiFunctions } from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  SelectOption,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";

interface BackupDataRecord extends TableRecord {
  share_article_name?: string;
  unit?: string;
  size?: string;
  [key: string]: unknown;
}

interface BackupModalProps {
  visible: boolean;
  onClose: () => void;
  data: BackupDataRecord | null;
  year: number;
  delivery_week: number;
  shareOption: string;
  onSave?: () => void;
  // Mirror the base planning table's day/variation nesting: true =
  // variation-major (size group, day children), false = day-major.
  showDaysTogether?: boolean;
}

export default function BackupModal({
  visible,
  onClose,
  data,
  year,
  delivery_week,
  shareOption,
  onSave,
  showDaysTogether = false,
}: BackupModalProps) {
  const [backupData, setBackupData] = useState<BackupDataRecord[] | null>(null);
  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const { format } = useNumberFormat();
  const permissions = useMemo(
    () => gatedByPermissionOnlyEdit(isOffice),
    [isOffice],
  );

  const { unitOptions, getUnitLabel } = useUnitOptions();
  const { sizeOptions, getSizeLabel } = useSizeOptions();

  const { shareArticles } = useShareArticles({
    is_harvest_share_article: true,
    is_active: true,
    is_purchased: false,
  });

  // Single source of truth for the day/variation axes — the same hook the base
  // planning page uses, so the backup grid's day and variation sets can never
  // drift from the base table (requireStations mirrors the base page's
  // get_delivery_stations:true, which drops station-less days). See
  // docs/day-variation-columns-audit.md.
  const { shareDeliveryDays, shareTypeVariations } = usePlanningAxes({
    year,
    week: delivery_week,
    shareOption,
    requireStations: true,
    needTours: false,
  });

  // Build the editable row ONCE per open (keyed on the backup's id), not on
  // every dependency change. `data` is a frozen snapshot from the parent
  // (setSelectedBackupData) that is never refreshed after a save; the
  // share-day / variation queries refetch under the global staleTime=0 (e.g.
  // the save invalidates them), which used to re-run this effect and overwrite
  // the just-saved edit with the stale `data` — so the change only appeared
  // after reopening. Guarding on data.id keeps the in-table (onDataChange)
  // values authoritative until the modal is actually reopened.
  const builtForIdRef = useRef<Key | null>(null);
  useEffect(() => {
    if (!visible) {
      builtForIdRef.current = null; // reset so a reopen rebuilds from fresh data
      return;
    }
    if (!data || !shareDeliveryDays || !shareTypeVariations) return;
    if (builtForIdRef.current === (data.id as Key)) return;
    builtForIdRef.current = data.id as Key;

    const row: BackupDataRecord = {
      id: data.id,
      key: data.id as Key,
      backup_share_article: data.backup_share_article,
      backup_share_article_name: data.backup_share_article_name,
      backup_unit: data.backup_unit,
      backup_size: data.backup_size,
    };

    shareDeliveryDays.forEach((deliveryDay) => {
      shareTypeVariations.forEach((variation) => {
        const backupKey = dayVariationKey({
          dayId: deliveryDay.id!,
          variationId: variation.id!,
          prefix: "backup_",
        });
        row[backupKey] = data[backupKey] || 0;
      });
    });

    setBackupData([row]);
  }, [visible, data, shareDeliveryDays, shareTypeVariations]);

  const handleDataChange = useCallback((newData: TableRecord[]) => {
    setBackupData(newData as BackupDataRecord[]);
  }, []);

  const columns = useMemo(() => {
    if (!shareDeliveryDays || !shareTypeVariations) return [];

    const baseColumns: EditableColumnConfig<TableRecord>[] = [
      {
        title: t("commissioning.vegetable"),
        dataIndex: "backup_share_article_name",
        key: "backup_share_article_name",
        inputType: "select",
        width: "15em",
        options: shareArticles as unknown as SelectOption[],
        foreignKey: {
          valueField: "backup_share_article",
          displayField: "backup_share_article_name",
        },
      },
      {
        title: t("commissioning.unit"),
        dataIndex: "backup_unit",
        key: "backup_unit",
        inputType: "select",
        required: false,
        align: "center",
        fixed: true,
        options: unitOptions,
        render: (value: unknown) => getUnitLabel(value as string),
      },
      {
        title: t("commissioning.size"),
        dataIndex: "backup_size",
        key: "backup_size",
        inputType: "select",
        required: false,
        width: "7em",
        align: "center",
        fixed: true,
        options: sizeOptions,
        render: (value: unknown) => getSizeLabel(value as string),
      },
    ];

    const renderBackupCell = (value: unknown) => {
      const numValue = Number(value);
      if (isNaN(numValue) || numValue === 0) return "";
      return data?.unit === "KG" ? format(numValue, 2) : format(numValue, 1);
    };
    // Match the base table's size label (t("commissioning.<size>")).
    const variationTitle = (variation: ShareTypeVariationOption): ReactNode =>
      variation.size
        ? t(`commissioning.${variation.size}`)
        : ((variation.label ?? "") as ReactNode);

    // Mirror the base planning table's nesting so the backup grid matches it
    // column-for-column. ``showDaysTogether`` = variation-major (size group,
    // day children); otherwise day-major (day group, variation children). The
    // leaf dataIndex is always ``backup_day_<day>_variation_<var>`` — only the
    // grouping changes, so the data binding is identical either way.
    const dayVariationColumns: EditableColumnConfig<TableRecord>[] =
      showDaysTogether
        ? shareTypeVariations.map(
            (
              variation: ShareTypeVariationOption,
            ): EditableColumnConfig<TableRecord> => ({
              title: variationTitle(variation),
              dataIndex: variationColumnKey(variation.id!, "backup_"),
              key: `backup_variation_group_${variation.id}`,
              align: "center",
              children: shareDeliveryDays.map(
                (deliveryDay): EditableColumnConfig<TableRecord> => {
                  const leafKey = dayVariationKey({
                    dayId: deliveryDay.id!,
                    variationId: variation.id!,
                    prefix: "backup_",
                  });
                  return {
                    title: deliveryDay.label as ReactNode,
                    dataIndex: leafKey,
                    key: leafKey,
                    inputType: "positive_decimal2",
                    align: "center",
                    width: "6em",
                    render: renderBackupCell,
                  };
                },
              ),
            }),
          )
        : shareDeliveryDays.map(
            (deliveryDay): EditableColumnConfig<TableRecord> => ({
              title: deliveryDay.label as ReactNode,
              dataIndex: `backup_day_${deliveryDay.id}`,
              key: `backup_day_${deliveryDay.id}`,
              align: "center",
              children: shareTypeVariations.map(
                (
                  variation: ShareTypeVariationOption,
                ): EditableColumnConfig<TableRecord> => {
                  const leafKey = dayVariationKey({
                    dayId: deliveryDay.id!,
                    variationId: variation.id!,
                    prefix: "backup_",
                  });
                  return {
                    title: variationTitle(variation),
                    dataIndex: leafKey,
                    key: leafKey,
                    inputType: "positive_decimal2",
                    align: "center",
                    width: "6em",
                    render: renderBackupCell,
                  };
                },
              ),
            }),
          );

    return [...baseColumns, ...dayVariationColumns];
  }, [
    shareDeliveryDays,
    shareTypeVariations,
    shareArticles,
    unitOptions,
    sizeOptions,
    data,
    t,
    format,
    getUnitLabel,
    getSizeLabel,
    showDaysTogether,
  ]);

  const customSave = useCallback((transformedData: Record<string, unknown>) => {
    const payload: Record<string, unknown> = {};

    Object.keys(transformedData).forEach((key) => {
      const parsed = parseDayVariationKey(key);
      if (parsed?.prefix === "backup_") {
        // Rebuild WITHOUT the "backup_" prefix so the backend gets the plain
        // "day_{id}_variation_{id}" (+ tour/station tier) key it stores under.
        const strippedKey = dayVariationKey({
          dayId: parsed.dayId,
          variationId: parsed.variationId,
          tour: parsed.tour,
          station: parsed.station,
        });
        payload[strippedKey] = transformedData[key] || 0;
      } else if (
        key === "backup_share_article" ||
        key === "backup_unit" ||
        key === "backup_size"
      ) {
        payload[key] = transformedData[key];
      }
    });

    return payload;
  }, []);

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<HarvestSharePlanningBackupRequest & TableRecord>({
        update: (id, payload) =>
          commissioningHarvestSharePlanningBackupUpdate(id, payload),
      }),
    [],
  );

  return (
    <Modal
      title={
        data ? (
          <div>
            <div>
              {t("commissioning.backup_planning")}
              {data.share_article_name || ""} -{" "}
              {getSizeLabel(data.size as string) || ""} (
              {getUnitLabel(data.unit as string) || ""})
            </div>
          </div>
        ) : (
          ""
        )
      }
      open={visible}
      onCancel={onClose}
      width={800}
      destroyOnHidden
      footer={[<ModalCloseFooter key="close" onClose={onClose} />]}
    >
      <p
        style={{
          whiteSpace: "pre-line",
          color: "var(--color-text-secondary)",
          marginBottom: "1em",
        }}
      >
        {t("commissioning.backup_modal_info")}
      </p>
      {data && backupData && shareDeliveryDays && shareTypeVariations ? (
        <div>
          <EditableTable
            key={data.id as string}
            columns={columns}
            apiFunctions={apiFunctions}
            initialData={backupData}
            onDataChange={handleDataChange}
            customSave={customSave}
            onSaveSuccess={onSave}
            permissions={permissions}
            forceInlineMode={true}
          />
        </div>
      ) : (
        <div style={{ textAlign: "center", padding: "2em" }}>
          {t("common.loading")}...
        </div>
      )}
    </Modal>
  );
}
