import { DownloadOutlined } from "@ant-design/icons";
import { Button, Flex } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningCratesCreate,
  commissioningCratesDestroy,
  commissioningCratesPartialUpdate,
  getCommissioningCratesListQueryKey,
  useCommissioningCratesList,
} from "@shared/api/generated/commissioning/commissioning";
import type { Crate } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import {
  CratePriceModal,
  ExportCsv,
  ExportCsvPricesCrate,
} from "@features/commissioning/modals";
import {
  EditableTable,
  type CrudResource,
  permissionsWithDeletable,
  useCrudListPage,
} from "@shared/tables";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import { ExplainerText, HideInactiveSwitch } from "@shared/ui";
import { useDateFormat, useNoteColumn } from "@hooks/index";
import {
  useIsActiveColumn,
  useShareArticlePriceColumn,
} from "@features/commissioning/hooks";

type CrateRow = Crate & TableRecord;

const cratesResource: CrudResource<CrateRow> = {
  useList: useCommissioningCratesList,
  create: commissioningCratesCreate,
  update: commissioningCratesPartialUpdate,
  delete: commissioningCratesDestroy,
  getListQueryKey: getCommissioningCratesListQueryKey,
};

export default function ListCrates() {
  const { t } = useTranslation();
  const { canEdit } = useRoles();
  const { formatDateForAPI } = useDateFormat();
  const { noteColumn } = useNoteColumn();
  const isActiveColumn = useIsActiveColumn();
  const permissions = useMemo(
    () => permissionsWithDeletable(canEdit),
    [canEdit],
  );

  const [modalVisible, setModalVisible] = useState(false);
  const [selectedCrateId, setSelectedCrateId] = useState<string | null>(null);
  const [selectedCrateName, setSelectedCrateName] = useState("");
  const [csvModalVisible, setCsvModalVisible] = useState(false);
  const [priceExportVisible, setPriceExportVisible] = useState(false);

  // Everything below the columns/modals is the shared CRUD boilerplate.
  const list = useCrudListPage<CrateRow>({ resource: cratesResource, permissions });

  const handleOpenModal = useCallback((record: Record<string, unknown>) => {
    setSelectedCrateId(record.id as string);
    setSelectedCrateName(record.name as string);
    setModalVisible(true);
  }, []);

  const handleCloseModal = useCallback(() => {
    setModalVisible(false);
    setSelectedCrateId(null);
    setSelectedCrateName("");
  }, []);

  const priceModalColumn = useShareArticlePriceColumn(handleOpenModal);

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => ({
      ...transformedData,
      valid_from: formatDateForAPI(dayjs()),
    }),
    [formatDateForAPI],
  );

  const columns = useMemo<any[]>(
    () => [
      isActiveColumn,
      {
        title: "#",
        dataIndex: "number",
        key: "number",
        inputType: "positive_integer",
        required: false,
        width: "4em",
        align: "center",
      },
      {
        title: <>{t("resellers.name")}</>,
        dataIndex: "name",
        key: "name",
        inputType: "text",
        required: false,
        width: "12em",
        align: "left",
        sortable: true,
      },
      {
        title: <>{t("resellers.short_name")}</>,
        dataIndex: "short_name",
        key: "short_name",
        inputType: "text",
        required: true,
        width: "10em",
        align: "left",
      },
      priceModalColumn,
      {
        ...noteColumn,
        title: <>{t("resellers.note")}</>,
        inputType: "text",
        width: undefined,
        align: "left",
      },
    ],
    [isActiveColumn, t, priceModalColumn, noteColumn],
  );

  return (
    <div>
      <div className="flex-between">
        <h1>{t("commissioning.list_crates")}</h1>
        <Flex gap={8}>
          <Button
            className="download-button"
            icon={<DownloadOutlined />}
            onClick={() => setPriceExportVisible(true)}
          >
            {t("commissioning.export_prices")}
          </Button>
          <Button
            className="download-button"
            icon={<DownloadOutlined />}
            onClick={() => setCsvModalVisible(true)}
          >
            {t("commissioning.csv_export_crates")}
          </Button>
        </Flex>
      </div>

      <HideInactiveSwitch
        value={list.hideInactive}
        onChange={list.setHideInactive}
      />

      <EditableTable
        columns={columns}
        apiFunctions={list.apiFunctions}
        focusIndex="number"
        initialData={list.filteredData}
        loading={list.isLoading}
        onSaveSuccess={list.onSaveSuccess}
        onDeleteSuccess={list.onDeleteSuccess}
        customSave={customSave}
        customEdit={list.customEdit}
        uniqueCheck={["name"]}
        uniqueCheckMessage={t("validation.unique.name")}
        permissions={list.permissions}
      />
      <ExplainerText title={t("common.info")}>
        {t("explainers.list_crates")}
      </ExplainerText>

      <ExportCsv
        open={csvModalVisible}
        onClose={() => setCsvModalVisible(false)}
        columns={columns}
        data={list.data}
        filename={t("commissioning.list_crates")}
      />

      <ExportCsvPricesCrate
        open={priceExportVisible}
        onClose={() => setPriceExportVisible(false)}
      />

      <CratePriceModal
        visible={modalVisible}
        onClose={handleCloseModal}
        crate={selectedCrateId}
        crate_name={selectedCrateName}
        onSave={list.invalidate}
      />
    </div>
  );
}
