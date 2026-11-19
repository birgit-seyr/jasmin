import { useQueryClient } from "@tanstack/react-query";
import { Modal, Typography } from "antd";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
  type DeliveryStationOption,
  useDeliveryStations,
} from "@features/commissioning/hooks/useDeliveryStations";
import {
  commissioningDeliveryStationsPartialUpdate,
  getCommissioningDeliveryStationsListQueryKey,
} from "@shared/api/generated/commissioning/commissioning";
import type { PatchedDeliveryStationRequest } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import ModalCloseFooter from "@shared/modals/ModalCloseFooter";
import {
  EditableTable,
  gatedByPermissionOnlyEdit,
  wrapApiFunctions,
} from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";

const { Paragraph } = Typography;

type StationRecord = DeliveryStationOption & TableRecord;

interface StationBulkPercentagesModalProps {
  open: boolean;
  onClose: () => void;
}

/**
 * Each active delivery station's surcharge on its loose packing list, added to
 * every article's own. Only the surcharge is edited here, and only it is sent:
 * the row also holds the rest of the station, which its own list keeps, or a
 * host that syncs the stations in.
 */
export default function StationBulkPercentagesModal({
  open,
  onClose,
}: StationBulkPercentagesModalProps) {
  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const queryClient = useQueryClient();

  const { deliveryStations, loading } = useDeliveryStations({}, { enabled: open });
  const stations = deliveryStations as StationRecord[];

  const permissions = useMemo(
    () => gatedByPermissionOnlyEdit(isOffice),
    [isOffice],
  );

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<PatchedDeliveryStationRequest & TableRecord>({
        update: (id, station) =>
          commissioningDeliveryStationsPartialUpdate(id, station),
      }),
    [],
  );

  const onlyTheSurcharge = useCallback(
    (row: Record<string, unknown>) => ({
      percentage_added_to_bulk_packing_list:
        row.percentage_added_to_bulk_packing_list,
    }),
    [],
  );

  // Every list of stations shows the saved surcharge, this one included.
  const reloadStations = useCallback(() => {
    void queryClient.invalidateQueries({
      queryKey: getCommissioningDeliveryStationsListQueryKey(),
    });
  }, [queryClient]);

  const columns = useMemo<EditableColumnConfig<StationRecord>[]>(
    () => [
      {
        title: t("commissioning.delivery_station"),
        dataIndex: "label",
        key: "label",
        readOnly: true,
        disabled: true,
      },
      {
        title: t("settings.commissioning.station_bulk_percentages.column"),
        dataIndex: "percentage_added_to_bulk_packing_list",
        key: "percentage_added_to_bulk_packing_list",
        inputType: "positive_integer",
        required: false,
        width: "9em",
        align: "center",
        render: (value) => (value == null ? "" : `${String(value)} %`),
      },
    ],
    [t],
  );

  return (
    <Modal
      title={t("settings.commissioning.station_bulk_percentages.title")}
      open={open}
      onCancel={onClose}
      width={600}
      destroyOnHidden
      footer={[<ModalCloseFooter key="close" onClose={onClose} />]}
    >
      <Paragraph type="secondary">
        {t("settings.commissioning.station_bulk_percentages.description")}
      </Paragraph>
      <EditableTable<StationRecord>
        columns={columns}
        apiFunctions={apiFunctions}
        initialData={stations}
        loading={loading}
        permissions={permissions}
        customSave={onlyTheSurcharge}
        onSaveSuccess={reloadStations}
        forceInlineMode={true}
      />
    </Modal>
  );
}
