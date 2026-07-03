import { DownloadOutlined } from "@ant-design/icons";
import { Button, Flex } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningCratesCreate,
  commissioningCratesDestroy,
  commissioningCratesPartialUpdate,
  useCommissioningCratesList,
} from "@shared/api/generated/commissioning/commissioning";
import type { Crate } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { CratePriceModal, ExportCsv, ExportCsvPricesCrate } from '@features/commissioning/modals';
import {
  EditableTable,
  permissionsWithDeletable,
  wrapApiFunctions,
} from "@shared/tables";
import type {
  ApiFunctions,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { ExplainerText, HideInactiveSwitch } from "@shared/ui";
import { useInvalidateAfterTableMutation, useNoteColumn } from '@hooks/index';
import { useIsActiveColumn, useShareArticlePriceColumn } from '@features/commissioning/hooks';
export default function ListCrates() {
  const { canEdit } = useRoles();
  const permissions = useMemo(
    () => permissionsWithDeletable(canEdit),
    [canEdit],
  );
  const [hideInactive, setHideInactive] = useState(true);
  const [modalVisible, setModalVisible] = useState(false);
  const [selectedCrateId, setSelectedCrateId] = useState<string | null>(null);
  const [selectedCrateName, setSelectedCrateName] = useState("");
  const [csvModalVisible, setCsvModalVisible] = useState(false);
  const [priceExportVisible, setPriceExportVisible] = useState(false);
  const { t } = useTranslation();
  const { noteColumn } = useNoteColumn();
  const isActiveColumn = useIsActiveColumn();

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

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<Crate & TableRecord>({
        create: (payload) => commissioningCratesCreate(payload),
        update: (id, payload) => commissioningCratesPartialUpdate(id, payload),
        delete: (id) => commissioningCratesDestroy(id),
      }),
    [],
  );

  // React Query handles the initial load + caching. Saves do NOT
  // refetch (EditableTable's local state is authoritative — see
  // ``useInvalidateAfterTableMutation``); deletes do, so the row
  // disappears from any downstream cached view.
  const { data: cratesData, refetch, isLoading } = useCommissioningCratesList();
  const data = useMemo<TableRecord[]>(
    () => (cratesData ?? []) as unknown as TableRecord[],
    [cratesData],
  );

  // Memoize the (optionally inactive-filtered) rows so ``initialData`` keeps a
  // STABLE reference across renders. With a fresh array each render (an inline
  // ``data.filter(...)``), EditableTable's initialData-sync effect refires on
  // every unrelated re-render — e.g. opening the price modal — and re-applies
  // the cached list (which an update deliberately does NOT refetch), reverting
  // a just-saved row edit until a hard refresh.
  const visibleData = useMemo<TableRecord[]>(
    () => (hideInactive ? data.filter((r) => r.is_active) : data),
    [data, hideInactive],
  );

  const invalidateData = useCallback(() => {
    void refetch();
  }, [refetch]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

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

  const customSave = useCallback((transformedData: Record<string, unknown>) => {
    return {
      ...transformedData,
      valid_from: dayjs().format("YYYY-MM-DD"),
    };
  }, []);

  // Memoize so ``columns`` keeps a STABLE reference across renders. A fresh
  // array each render cascades through EditableTable's transformDataFROMapi →
  // setDataWithTransform → the initialData-sync effect, which then refires on
  // every parent re-render (e.g. opening the price modal) and re-applies the
  // not-refetched cache — reverting a just-saved row edit. (ListShareArticles
  // avoids this via the memoized useShareArticleListColumns hook.)
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

      <HideInactiveSwitch value={hideInactive} onChange={setHideInactive} />

      <EditableTable
        columns={columns}
        apiFunctions={apiFunctions}
        focusIndex="number"
        initialData={visibleData}
        loading={isLoading}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        customSave={customSave}
        customEdit={customEdit}
        uniqueCheck={["name"]}
        uniqueCheckMessage={t("validation.unique.name")}
        permissions={permissions}
      />
      <ExplainerText title={t("common.info")}>
        {t("explainers.list_crates")}
      </ExplainerText>

      <ExportCsv
        open={csvModalVisible}
        onClose={() => setCsvModalVisible(false)}
        columns={columns}
        data={data}
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
        onSave={() => {
          void refetch();
        }}
      />
    </div>
  );
}
