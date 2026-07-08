import { DownloadOutlined } from "@ant-design/icons";
import { Button, Flex } from "antd";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningShareArticlesCreate,
  commissioningShareArticlesDestroy,
  commissioningShareArticlesPartialUpdate,
  getCommissioningShareArticlesListQueryKey,
  useCommissioningShareArticlesList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningShareArticlesListParams,
  ShareArticle,
} from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import {
  ExportCsv,
  ExportCsvPricesShareArticle,
  ShareArticleExtraPriceModal,
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
import { useTenant, useUnitOptions } from "@hooks/index";
import { useIsActiveColumn } from "@features/commissioning/hooks";
import { isFieldDisabled } from "@shared/utils";

type ShareArticleRow = ShareArticle & TableRecord;

// Extra articles are ShareArticles with is_extra=true; the list is scoped to
// extras and create forces the flag so rows added here never land in the
// regular share-article list.
const EXTRA_LIST_PARAMS: CommissioningShareArticlesListParams = {
  is_extra: true,
};

const extraArticlesResource: CrudResource<ShareArticleRow> = {
  useList: useCommissioningShareArticlesList,
  create: (payload) =>
    commissioningShareArticlesCreate({ ...payload, is_extra: true }),
  update: commissioningShareArticlesPartialUpdate,
  delete: commissioningShareArticlesDestroy,
  getListQueryKey: getCommissioningShareArticlesListQueryKey,
};

export default function ListExtraArticles() {
  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const { getSetting } = useTenant();
  const { unitOptions } = useUnitOptions();
  const isActiveColumn = useIsActiveColumn();
  const permissions = useMemo(
    () => permissionsWithDeletable(isOffice),
    [isOffice],
  );
  const uploadAllowed =
    (getSetting("allow_upload_for_data_lists", false) as boolean) === true;

  const [modalVisible, setModalVisible] = useState(false);
  const [selectedShareArticleId, setSelectedShareArticleId] = useState<
    string | null
  >(null);
  const [selectedShareArticleName, setSelectedShareArticleName] = useState("");
  const [csvModalVisible, setCsvModalVisible] = useState(false);
  const [priceExportVisible, setPriceExportVisible] = useState(false);

  const list = useCrudListPage<ShareArticleRow>({
    resource: extraArticlesResource,
    permissions,
    listParams: EXTRA_LIST_PARAMS,
  });

  const handleOpenModal = useCallback((record: Record<string, unknown>) => {
    setSelectedShareArticleId(String(record.id ?? ""));
    setSelectedShareArticleName(record.name as string);
    setModalVisible(true);
  }, []);

  const handleCloseModal = useCallback(() => {
    setModalVisible(false);
    setSelectedShareArticleId(null);
    setSelectedShareArticleName("");
  }, []);

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => ({
      ...transformedData,
      is_extra: true,
      default_movement_unit: "PCS",
    }),
    [],
  );

  const priceModalColumn = useMemo(
    () => ({
      title: "",
      dataIndex: "actions",
      key: "actions",
      width: "6em",
      align: "center",
      readOnly: true,
      disabled: true,
      render: (_: unknown, record: Record<string, unknown>) => (
        <Button
          type="primary"
          size="small"
          onClick={() => handleOpenModal(record)}
          disabled={record.key === -1 || !record.id}
          title={t("commissioning.manage_prices")}
        >
          {t("commissioning.prices")}
        </Button>
      ),
    }),
    [handleOpenModal, t],
  );

  const columns = useMemo<any[]>(
    () => [
      isActiveColumn,
      {
        title: <>{t("commissioning.article_number")}</>,
        dataIndex: "article_number",
        key: "article_number",
        inputType: "text",
        required: false,
        width: "6em",
        align: "left",
        fixed: true,
        sortable: true,
      },
      {
        title: <>{t("commissioning.name")}</>,
        dataIndex: "name",
        key: "name",
        inputType: "text",
        required: true,
        width: "20em",
        align: "left",
        sortable: true,
        disabled: isFieldDisabled,
      },
      priceModalColumn,
      {
        title: <>{t("commissioning.default_movement_unit")}</>,
        dataIndex: "default_movement_unit",
        key: "default_movement_unit",
        inputType: "select",
        required: false,
        disabled: true,
        readOnly: true,
        options: unitOptions,
        // Extras are constrained server-side to PCS only — keep the column
        // visible (so the value is shown), but never editable.
        render: (value: string) => {
          const unitOption = unitOptions.find(
            (option: { value: string; label: string }) =>
              option.value === value,
          );
          return unitOption ? unitOption.label : value;
        },
      },
      {
        title: <>{t("commissioning.description")}</>,
        dataIndex: "description",
        key: "description",
        inputType: "text",
        required: false,
      },
    ],
    [isActiveColumn, t, priceModalColumn, unitOptions],
  );

  return (
    <div>
      <div className="flex-between">
        <div>
          <h1 style={{ marginBottom: 0 }}>
            {t("commissioning.extra_articles")}
          </h1>
          <h5>{t("commissioning.extra_articles_description")}</h5>
        </div>
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
            {t("commissioning.csv_export_extra_articles")}
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
        focusIndex="name"
        initialData={list.filteredData}
        loading={list.isLoading}
        onSaveSuccess={list.onSaveSuccess}
        onDeleteSuccess={list.onDeleteSuccess}
        customEdit={list.customEdit}
        customSave={customSave}
        permissions={list.permissions}
        pagination={true}
        showSearchBar={true}
      />
      <ExplainerText title={t("common.info")}>
        {t("explainers.list_extra_articles")}
      </ExplainerText>

      {uploadAllowed && (
        <DownloadCsvTemplateButton
          columns={columns}
          filename={t("commissioning.extra_articles_template.csv")}
          modelName="share_article"
          onUploadSuccess={list.invalidate}
        />
      )}

      <ExportCsv
        open={csvModalVisible}
        onClose={() => setCsvModalVisible(false)}
        columns={columns}
        data={list.filteredData}
        filename={t("commissioning.extra_articles")}
      />

      <ExportCsvPricesShareArticle
        open={priceExportVisible}
        onClose={() => setPriceExportVisible(false)}
      />

      <ShareArticleExtraPriceModal
        visible={modalVisible}
        onClose={handleCloseModal}
        share_article={selectedShareArticleId}
        share_article_name={selectedShareArticleName}
        onSave={list.invalidate}
      />
    </div>
  );
}
