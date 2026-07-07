import {
  DownloadOutlined,
  EditOutlined,
  EuroCircleOutlined,
  InfoCircleOutlined,
} from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningDeliveryStationsCreate,
  commissioningDeliveryStationsDestroy,
  commissioningDeliveryStationsPartialUpdate,
  getCommissioningDeliveryStationsListQueryKey,
  useCommissioningDeliveryStationsList,
} from "@shared/api/generated/commissioning/commissioning";
import type { DeliveryStation } from "@shared/api/generated/models";
import {
  DeliveryStationDetailModal,
  DeliveryStationFeeModal,
  DeliveryStationInfoModal,
  ExportCsv,
} from "@features/commissioning/modals";
import {
  EditableTable,
  permissionsWithDeletable,
  wrapApiFunctions,
} from "@shared/tables";
import type {
  ApiFunctions,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import {
  ExplainerText,
  HideInactiveSwitch,
  DownloadCsvTemplateButton,
} from "@shared/ui";
import { useRoles } from "@shared/auth";
import {
  useContactColumns,
  useInvalidateAfterTableMutation,
  useTenant,
} from "@hooks/index";
import {
  useIsActiveColumn,
  useShareDeliveryDays,
} from "@features/commissioning/hooks";
import { isFieldDisabled } from "@shared/utils";

interface ShareDeliveryDay {
  id: string;
  day_number: number;
  label: string;
  valid_until?: string | null;
}

export default function ListDeliveryStations() {
  const { isOffice } = useRoles();
  const permissions = useMemo(
    () => permissionsWithDeletable(isOffice),
    [isOffice],
  );
  const [hideInactive, setHideInactive] = useState(true);
  const [csvModalVisible, setCsvModalVisible] = useState(false);
  const queryClient = useQueryClient();
  const { t } = useTranslation();
  const { getSetting } = useTenant();
  const uploadAllowed =
    (getSetting("allow_upload_for_data_lists", false) as boolean) === true;

  const contactColumns = useContactColumns({
    translationPrefix: "delivery_stations",
    overrides: {
      address: {
        inputType: "text",
        required: true,
        disabled: isFieldDisabled,
      },
      zipCode: {
        inputType: "text",
        required: true,
        disabled: isFieldDisabled,
      },
      city: { inputType: "text", required: true, disabled: isFieldDisabled },
    },
  });

  const [
    isDeliveryStationDetailModalOpen,
    setIsDeliveryStationDetailModalOpen,
  ] = useState(false);
  const [
    selectedDeliveryStationDetailData,
    setSelectedDeliveryStationDetailData,
  ] = useState<Record<string, unknown> | null>(null);
  const [infoModalStation, setInfoModalStation] = useState<Record<
    string,
    unknown
  > | null>(null);
  const [feeModalStation, setFeeModalStation] = useState<Record<
    string,
    unknown
  > | null>(null);

  const shareDeliveryDaysParams = useMemo(
    () => ({ active_at_date: dayjs().format("YYYY-MM-DD") }),
    [],
  );
  const futureShareDeliveryDaysParams = useMemo(
    () => ({ active_at_date: dayjs().format("YYYY-MM-DD"), future: true }),
    [],
  );

  const { shareDeliveryDays: currentlyActiveDeliveryDays } =
    useShareDeliveryDays(shareDeliveryDaysParams);

  const { shareDeliveryDays: futureDeliveryDays } = useShareDeliveryDays(
    futureShareDeliveryDaysParams,
  );

  const shareDeliveryDays = useMemo(() => {
    return [
      ...(currentlyActiveDeliveryDays || []),
      ...(futureDeliveryDays || []),
    ];
  }, [currentlyActiveDeliveryDays, futureDeliveryDays]);

  const distinctShareDeliveryDays = useMemo(() => {
    const dayNumberMap = new Map<number, ShareDeliveryDay>();

    (shareDeliveryDays as ShareDeliveryDay[]).forEach((day) => {
      const existing = dayNumberMap.get(day.day_number);

      if (!existing) {
        dayNumberMap.set(day.day_number, day);
      } else {
        const currentHasNoValidUntil =
          !day.valid_until || day.valid_until === null;
        const existingHasNoValidUntil =
          !existing.valid_until || existing.valid_until === null;

        if (currentHasNoValidUntil && !existingHasNoValidUntil) {
          dayNumberMap.set(day.day_number, day);
        }
      }
    });

    return Array.from(dayNumberMap.values());
  }, [shareDeliveryDays]);

  const isActiveColumn = useIsActiveColumn();

  // Page owns the data via ``useCommissioningDeliveryStationsList`` (passed
  // as ``initialData``); no ``list`` in ``apiFunctions`` so the table never
  // double-fetches. Mutations refresh through the invalidation below.
  const { data: rawData, isLoading } = useCommissioningDeliveryStationsList();
  const data = useMemo(
    () => (rawData ?? []) as unknown as TableRecord[],
    [rawData],
  );
  const filteredData = useMemo(
    () => (hideInactive ? data.filter((r) => r.is_active) : data),
    [data, hideInactive],
  );
  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningDeliveryStationsListQueryKey(),
    });
  }, [queryClient]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<DeliveryStation & TableRecord>({
        create: (payload) => commissioningDeliveryStationsCreate(payload),
        update: (id, payload) =>
          commissioningDeliveryStationsPartialUpdate(id, payload),
        delete: (id) => commissioningDeliveryStationsDestroy(id),
      }),
    [],
  );

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => {
      const cleanedData = { ...transformedData };
      distinctShareDeliveryDays.forEach((day) => {
        delete cleanedData[day.id];
      });
      return cleanedData;
    },
    [distinctShareDeliveryDays],
  );

  const customEdit = useCallback(
    (
      record: TableRecord,
      form: { setFieldsValue: (values: Record<string, unknown>) => void },
    ) => {
      if (record.key === -1) {
        const defaultValues = { is_active: true };
        form.setFieldsValue(defaultValues);
        return { ...record, ...defaultValues };
      }
      return record;
    },
    [],
  );

  const columns: any[] = useMemo(() => {
    const staticColumns = [
      isActiveColumn,
      {
        title: <>{t("delivery_stations.is_also_reseller")}</>,
        dataIndex: "is_also_reseller",
        key: "is_also_reseller",
        inputType: "checkbox",
        required: false,
        sortable: true,

        // Disable unticking when the linked reseller has dependants and can't be deleted.
        disabled: (record: TableRecord) =>
          !!(record.is_also_reseller || record.is_also_seller) &&
          record.linked_reseller_can_be_deleted === false,
      },
      {
        title: "#",
        dataIndex: "number",
        key: "number",
        inputType: "text",
        required: false,
        width: "6em",
        align: "left",
        sortable: true,
      },
      {
        title: <>{t("delivery_stations.short_name")}</>,
        dataIndex: "short_name",
        key: "short_name",
        inputType: "text",
        required: false,
        width: "9em",
        align: "center",
        sortable: true,

        disabled: isFieldDisabled,
      },
      {
        title: <>{t("delivery_stations.delivery_days")}</>,
        dataIndex: "action_delivery_days",
        key: "action_delivery_days",
        inputType: "text",
        required: false,
        disabled: true,
        width: "8em",
        render: (_: unknown, record: TableRecord) => {
          return (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "4px",
                width: "100%",
              }}
            >
              <Button
                size="small"
                type="text"
                className="long-squared-button"
                icon={<EditOutlined />}
                aria-label={t("table.edit")}
                onClick={(e) => {
                  e.stopPropagation();
                  setIsDeliveryStationDetailModalOpen(true);
                  setSelectedDeliveryStationDetailData(record);
                }}
                style={{
                  minWidth: "auto",
                  padding: "0 4px",
                }}
              />
            </div>
          );
        },
      },
      {
        title: <>{t("delivery_stations.infos")}</>,
        dataIndex: "action_station_settings",
        key: "action_station_settings",
        inputType: "text",
        required: false,
        disabled: true,
        width: "7em",
        render: (_: unknown, record: TableRecord) => {
          // Office-only, and only for persisted rows (the "add new" draft
          // row has key === -1 and no id yet).
          if (!isOffice || record.key === -1 || !record.id) return null;
          return (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "4px",
                width: "100%",
              }}
            >
              <Button
                size="small"
                type="text"
                icon={<InfoCircleOutlined />}
                title={t("delivery_stations.member_info_title")}
                onClick={(e) => {
                  e.stopPropagation();
                  setInfoModalStation(record);
                }}
                style={{ minWidth: "auto", padding: "0 4px" }}
              />
              <Button
                size="small"
                type="text"
                icon={<EuroCircleOutlined />}
                title={t("delivery_stations.fee_title")}
                onClick={(e) => {
                  e.stopPropagation();
                  setFeeModalStation(record);
                }}
                style={{ minWidth: "auto", padding: "0 4px" }}
              />
            </div>
          );
        },
      },
      contactColumns.companyName,
      contactColumns.firstName,
      contactColumns.lastName,
      contactColumns.address,
      contactColumns.zipCode,
      contactColumns.city,
      contactColumns.email,
      contactColumns.phone,
    ];

    return staticColumns;
  }, [t, isActiveColumn, contactColumns, isOffice]);

  return (
    <div>
      <div className="flex-between">
        <h1>{t("delivery_stations.list_delivery_stations")}</h1>
        <Button
          className="download-button"
          icon={<DownloadOutlined />}
          onClick={() => setCsvModalVisible(true)}
        >
          {t("commissioning.csv_export_delivery_stations")}
        </Button>
      </div>

      <HideInactiveSwitch value={hideInactive} onChange={setHideInactive} />

      <EditableTable
        columns={columns}
        apiFunctions={apiFunctions}
        initialData={filteredData}
        loading={isLoading}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        customSave={customSave}
        customEdit={customEdit}
        permissions={permissions}
        uniqueCheck={["number"]}
        uniqueCheckMessage={t("validation.unique.number")}
        pagination={true}
        showSearchBar={true}
      />

      <DeliveryStationDetailModal
        visible={isDeliveryStationDetailModalOpen}
        onClose={() => {
          setIsDeliveryStationDetailModalOpen(false);
          setSelectedDeliveryStationDetailData(null);
        }}
        deliveryStation={selectedDeliveryStationDetailData as never}
        onSave={() => {
          invalidateData();
          setIsDeliveryStationDetailModalOpen(false);
          setSelectedDeliveryStationDetailData(null);
        }}
      />
      <DeliveryStationInfoModal
        open={!!infoModalStation}
        deliveryStation={infoModalStation as never}
        onClose={() => setInfoModalStation(null)}
        onSaved={() => setInfoModalStation(null)}
      />
      <DeliveryStationFeeModal
        open={!!feeModalStation}
        deliveryStation={feeModalStation as never}
        onClose={() => setFeeModalStation(null)}
        onSaved={() => setFeeModalStation(null)}
      />
      <ExportCsv
        open={csvModalVisible}
        onClose={() => setCsvModalVisible(false)}
        columns={columns}
        data={data}
        filename={t("delivery_stations.list_delivery_stations")}
      />

      <ExplainerText title={t("common.info")}>
        {t("explainers.list_delivery_stations")}
      </ExplainerText>
      {uploadAllowed && (
        <DownloadCsvTemplateButton
          columns={columns}
          filename={t("commissioning.delivery_stations_template.csv")}
          modelName="delivery_station"
          onUploadSuccess={invalidateData}
        />
      )}
    </div>
  );
}
