import {
  DownloadOutlined,
  EditOutlined,
  EuroCircleOutlined,
  InfoCircleOutlined,
} from "@ant-design/icons";
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
  type CrudResource,
  permissionsWithDeletable,
  useCrudListPage,
} from "@shared/tables";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import {
  DownloadCsvTemplateButton,
  ExplainerText,
  HideInactiveSwitch,
} from "@shared/ui";
import { useRoles } from "@shared/auth";
import { useContactColumns, useTenant } from "@hooks/index";
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

type DeliveryStationRow = DeliveryStation & TableRecord;

const deliveryStationsResource: CrudResource<DeliveryStationRow> = {
  useList: useCommissioningDeliveryStationsList,
  create: commissioningDeliveryStationsCreate,
  update: commissioningDeliveryStationsPartialUpdate,
  delete: commissioningDeliveryStationsDestroy,
  getListQueryKey: getCommissioningDeliveryStationsListQueryKey,
};

export default function ListDeliveryStations() {
  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const { getSetting } = useTenant();
  const isActiveColumn = useIsActiveColumn();
  const permissions = useMemo(
    () => permissionsWithDeletable(isOffice),
    [isOffice],
  );
  const uploadAllowed =
    (getSetting("allow_upload_for_data_lists", false) as boolean) === true;

  const [csvModalVisible, setCsvModalVisible] = useState(false);
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

  const list = useCrudListPage<DeliveryStationRow>({
    resource: deliveryStationsResource,
    permissions,
  });

  const contactColumns = useContactColumns({
    translationPrefix: "delivery_stations",
    overrides: {
      address: { inputType: "text", required: true, disabled: isFieldDisabled },
      zipCode: { inputType: "text", required: true, disabled: isFieldDisabled },
      city: { inputType: "text", required: true, disabled: isFieldDisabled },
    },
  });

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

  const shareDeliveryDays = useMemo(
    () => [...(currentlyActiveDeliveryDays || []), ...(futureDeliveryDays || [])],
    [currentlyActiveDeliveryDays, futureDeliveryDays],
  );

  const distinctShareDeliveryDays = useMemo(() => {
    const dayNumberMap = new Map<number, ShareDeliveryDay>();
    (shareDeliveryDays as ShareDeliveryDay[]).forEach((day) => {
      const existing = dayNumberMap.get(day.day_number);
      if (!existing) {
        dayNumberMap.set(day.day_number, day);
      } else {
        const currentHasNoValidUntil = !day.valid_until;
        const existingHasNoValidUntil = !existing.valid_until;
        if (currentHasNoValidUntil && !existingHasNoValidUntil) {
          dayNumberMap.set(day.day_number, day);
        }
      }
    });
    return Array.from(dayNumberMap.values());
  }, [shareDeliveryDays]);

  // Strip the per-delivery-day helper columns from the save payload — they're
  // display-only and not fields on the DeliveryStation model.
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

  const columns: any[] = useMemo(
    () => [
      isActiveColumn,
      {
        title: <>{t("delivery_stations.is_also_reseller")}</>,
        dataIndex: "is_also_reseller",
        key: "is_also_reseller",
        inputType: "checkbox",
        required: false,
        sortable: true,
        // Disable unticking when the linked reseller has dependants and can't
        // be deleted.
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
        required: true,
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
        render: (_: unknown, record: TableRecord) => (
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
              style={{ minWidth: "auto", padding: "0 4px" }}
            />
          </div>
        ),
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
          // Office-only, and only for persisted rows (the "add new" draft row
          // has key === -1 and no id yet).
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
    ],
    [t, isActiveColumn, contactColumns, isOffice],
  );

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

      <HideInactiveSwitch
        value={list.hideInactive}
        onChange={list.setHideInactive}
      />

      <EditableTable
        columns={columns}
        apiFunctions={list.apiFunctions}
        initialData={list.filteredData}
        loading={list.isLoading}
        onSaveSuccess={list.onSaveSuccess}
        onDeleteSuccess={list.onDeleteSuccess}
        customSave={customSave}
        customEdit={list.customEdit}
        permissions={list.permissions}
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
          list.invalidate();
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
        data={list.data}
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
          onUploadSuccess={list.invalidate}
        />
      )}
    </div>
  );
}
