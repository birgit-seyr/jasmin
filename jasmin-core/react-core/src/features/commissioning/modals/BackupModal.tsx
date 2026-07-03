import { Modal } from "antd";
import ModalCloseFooter from "@shared/modals/ModalCloseFooter";
import dayjs from "dayjs";
import type { Key, ReactNode } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { commissioningHarvestSharePlanningBackupUpdate } from "@shared/api/generated/commissioning/commissioning";
import type { HarvestSharePlanningBackupRequest } from "@shared/api/generated/models/harvestSharePlanningBackupRequest";
import type { ShareTypeEnum } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { useNumberFormat, useSizeOptions, useUnitOptions } from '@hooks/index';
import { useShareArticles, useShareDeliveryDays, useShareTypeVariations } from '@features/commissioning/hooks';
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
}

export default function BackupModal({
  visible,
  onClose,
  data,
  year,
  delivery_week,
  shareOption,
  onSave,
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

  const shareDeliveryDaysFilters = useMemo(() => {
    if (!year || !delivery_week) return null;

    return {
      active_at_date: dayjs()
        .year(year)
        .isoWeek(delivery_week)
        .isoWeekday(6)
        .format("YYYY-MM-DD"),
      get_delivery_stations: false,
      need_info_on_tours: false,
    };
  }, [year, delivery_week]);

  const shareTypeVariationFilters = useMemo(() => {
    if (!year || !delivery_week || !shareOption) return null;

    return {
      physical: true,
      active_at_date: dayjs()
        .year(year)
        .isoWeek(delivery_week)
        .isoWeekday(6)
        .format("YYYY-MM-DD"),
      // shareOption is always a valid ShareOptions value here (guarded above);
      // the list param is now the generated enum, so narrow the string prop.
      share_option: shareOption as ShareTypeEnum,
    };
  }, [year, delivery_week, shareOption]);

  const { shareDeliveryDays } = useShareDeliveryDays(
    shareDeliveryDaysFilters ?? undefined,
  );
  const { shareTypeVariations } = useShareTypeVariations(
    shareTypeVariationFilters ?? null,
  );

  useEffect(() => {
    if (visible && data && shareDeliveryDays && shareTypeVariations) {
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
          const backupKey = `backup_day_${deliveryDay.id}_variation_${variation.id}`;
          row[backupKey] = data[backupKey] || 0;
        });
      });

      setBackupData([row]);
    }
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

    const dayVariationColumns: EditableColumnConfig<TableRecord>[] =
      shareDeliveryDays.map(
        (deliveryDay): EditableColumnConfig<TableRecord> => ({
          title: deliveryDay.label as ReactNode,
          dataIndex: `backup_day_${deliveryDay.id}`,
          key: `backup_day_${deliveryDay.id}`,
          align: "center",
          children: shareTypeVariations.map(
            (
              variation: ShareTypeVariationOption,
            ): EditableColumnConfig<TableRecord> => ({
              title: (variation.size || variation.label) as ReactNode,
              dataIndex: `backup_day_${deliveryDay.id}_variation_${variation.id}`,
              key: `backup_day_${deliveryDay.id}_variation_${variation.id}`,
              inputType: "positive_decimal2",
              align: "center",
              width: "6em",
              render: (value: unknown) => {
                const numValue = Number(value);
                if (isNaN(numValue) || numValue === 0) return "";
                return data?.unit === "KG"
                  ? format(numValue, 2)
                  : format(numValue, 1);
              },
            }),
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
  ]);

  const customSave = useCallback((transformedData: Record<string, unknown>) => {
    const payload: Record<string, unknown> = {};

    Object.keys(transformedData).forEach((key) => {
      if (key.startsWith("backup_day_")) {
        // Strip "backup_" prefix so the backend gets "day_{id}_variation_{id}"
        const strippedKey = key.replace("backup_", "");
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
      width={1200}
      footer={[
        <ModalCloseFooter key="close" onClose={onClose} />,
      ]}
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
