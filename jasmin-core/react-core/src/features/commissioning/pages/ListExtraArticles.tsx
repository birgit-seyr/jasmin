import { DownloadOutlined } from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
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
import { ExportCsv, ExportCsvPricesShareArticle, ShareArticleExtraPriceModal } from '@features/commissioning/modals';
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
import { useInvalidateAfterTableMutation, useTenant, useUnitOptions } from '@hooks/index';
import { useIsActiveColumn } from '@features/commissioning/hooks';
import { isFieldDisabled } from "@shared/utils";

export default function ListExtraArticles() {
  const { isOffice } = useRoles();
  const permissions = useMemo(
    () => permissionsWithDeletable(isOffice),
    [isOffice],
  );
  const [hideInactive, setHideInactive] = useState(true);
  const [modalVisible, setModalVisible] = useState(false);
  const [selectedShareArticleId, setSelectedShareArticleId] = useState<
    string | null
  >(null);
  const [selectedShareArticleName, setSelectedShareArticleName] = useState("");
  const [csvModalVisible, setCsvModalVisible] = useState(false);
  const [priceExportVisible, setPriceExportVisible] = useState(false);
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { getSetting } = useTenant();

  const uploadAllowed =
    (getSetting("allow_upload_for_data_lists", false) as boolean) === true;

  const { unitOptions } = useUnitOptions();
  const isActiveColumn = useIsActiveColumn();

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

  /**
   * "Extra articles" are now ``ShareArticle`` rows with ``is_extra=True``.
   * The list is scoped to extras only; create/update force ``is_extra=true``
   * so rows added from this page never accidentally end up in the regular
   * share-article list.
   */
  // No ``list``: this page owns the data via ``useCommissioningShareArticlesList``
  // with ``listParams = { is_extra: true }`` (passed as ``initialData``).
  // Supplying ``list`` would make EditableTable double-fetch the same endpoint
  // (it auto-fetches when ``showSearchBar`` + ``apiFunctions.list`` are both
  // set). Mutations refresh via the ``onSaveSuccess``/``onDeleteSuccess``
  // invalidation.
  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<ShareArticle & TableRecord>({
        create: (payload) =>
          commissioningShareArticlesCreate({
            ...payload,
            is_extra: true,
          }),
        update: (id, payload) =>
          commissioningShareArticlesPartialUpdate(id, payload),
        delete: (id) => commissioningShareArticlesDestroy(id),
      }),
    [],
  );

  const customEdit = useCallback(
    (
      record: TableRecord,
      form: { setFieldsValue: (values: Record<string, unknown>) => void },
    ) => {
      if (record.key === -1) {
        const defaultValues = {
          is_active: true,
        };
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
      is_extra: true,
      default_movement_unit: "PCS",
    };
  }, []);

  const listParams = useMemo<CommissioningShareArticlesListParams>(
    () => ({ is_extra: true }),
    [],
  );

  const { data: rawData, isLoading } =
    useCommissioningShareArticlesList(listParams);
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
      queryKey: getCommissioningShareArticlesListQueryKey(),
    });
  }, [queryClient]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

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

  // Memoize so ``columns`` keeps a STABLE reference across renders. A fresh
  // array each render cascades through EditableTable's transformDataFROMapi →
  // setDataWithTransform → the initialData-sync effect, which then refires on
  // every parent re-render (e.g. opening the price modal) and re-applies the
  // not-refetched cache — reverting a just-saved row edit (e.g. article_number).
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
      render: (value: string) => {
        const unitOption = unitOptions.find(
          (option: { value: string; label: string }) => option.value === value,
        );
        return unitOption ? unitOption.label : value;
      },
      // Extras are constrained server-side to PCS only — keep the column
      // visible (so the value is shown), but never editable.
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

      <HideInactiveSwitch value={hideInactive} onChange={setHideInactive} />

      <EditableTable
        columns={columns}
        apiFunctions={apiFunctions}
        focusIndex="name"
        initialData={filteredData}
        loading={isLoading}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        customEdit={customEdit}
        customSave={customSave}
        permissions={permissions}
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
          onUploadSuccess={invalidateData}
        />
      )}

      <ExportCsv
        open={csvModalVisible}
        onClose={() => setCsvModalVisible(false)}
        columns={columns}
        data={filteredData}
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
        onSave={invalidateData}
      />
    </div>
  );
}
