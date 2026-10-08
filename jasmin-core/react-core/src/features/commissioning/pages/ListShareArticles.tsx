import { DownloadOutlined } from "@ant-design/icons";
import { Button, Flex, Radio } from "antd";
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
  ExportCsvAllArticles,
  ExportCsvPricesShareArticle,
  ShareArticlePriceModal,
} from "@features/commissioning/modals";
import {
  EditableTable,
  type CrudResource,
  permissionsWithDeletable,
  useCrudListPage,
} from "@shared/tables";
import type { TableRecord } from "@shared/tables/BasicEditableTable/types";
import { ExplainerText, HideInactiveSwitch } from "@shared/ui";
import { CsvImportButton } from "@shared/modals";
import {
  useActiveShareOptions,
  useNumberFormat,
  useOrganicGate,
  useTenant,
  useUnitOptions,
} from "@hooks/index";
import {
  useCrates,
  useIsActiveColumn,
  useShareArticleListColumns,
  useShareArticlePriceColumn,
  useShareOptions,
} from "@features/commissioning/hooks";
import { getShareOptionLabel, syncPurchasedName } from "@shared/utils";

// Pure row predicates — a row is harvest-only or purchase-only based on
// ``is_purchased``. Module-level so they're stable references.
const isHarvestDisabled = (record: TableRecord) => record.is_purchased === true;
const isPurchaseDisabled = (record: TableRecord) =>
  record.is_purchased === false;

const SHARE_ARTICLE_LIST_PARAMS: CommissioningShareArticlesListParams = {
  is_data_list: true,
};

// Typed on TableRecord (not ShareArticle & TableRecord): this page's columns +
// customEdit are TableRecord-typed, so keeping the whole page on TableRecord
// avoids a generic clash. The create/update casts sit here (one place).
const shareArticlesResource: CrudResource<TableRecord> = {
  useList: useCommissioningShareArticlesList,
  create: (payload) =>
    commissioningShareArticlesCreate(payload as unknown as ShareArticle),
  update: (id, payload) =>
    commissioningShareArticlesPartialUpdate(
      id,
      payload as unknown as ShareArticle,
    ),
  delete: commissioningShareArticlesDestroy,
  getListQueryKey: getCommissioningShareArticlesListQueryKey,
};

export default function ListShareArticles() {
  const { t } = useTranslation();
  const { getSetting } = useTenant();
  const { canEdit, isOffice: canManagePrices } = useRoles();
  const { enabled: organicGateEnabled } = useOrganicGate();
  const { format } = useNumberFormat();
  const { unitOptions } = useUnitOptions();
  const { crates } = useCrates();
  const { shareOptions } = useShareOptions();
  const { activeShareOptions } = useActiveShareOptions();

  const [modalVisible, setModalVisible] = useState(false);
  const [selectedShareArticleId, setSelectedShareArticleId] = useState<
    string | null
  >(null);
  const [selectedShareArticleName, setSelectedShareArticleName] = useState("");
  const [activeFilter, setActiveFilter] = useState("all");
  const [csvModalVisible, setCsvModalVisible] = useState(false);
  const [priceExportVisible, setPriceExportVisible] = useState(false);
  const [allArticlesExportVisible, setAllArticlesExportVisible] =
    useState(false);

  const permissions = useMemo(
    () => permissionsWithDeletable(canEdit),
    [canEdit],
  );

  const list = useCrudListPage<TableRecord>({
    resource: shareArticlesResource,
    permissions,
    listParams: SHARE_ARTICLE_LIST_PARAMS,
  });

  const has_markets = getSetting("has_markets", true) as boolean;
  const sells_to_resellers = getSetting("sells_to_resellers", true) as boolean;
  const number_packing_stations = getSetting(
    "number_packing_stations",
    1,
  ) as number;
  const uploadAllowed =
    (getSetting("allow_upload_for_data_lists", false) as boolean) === true;
  const packing_mode = getSetting("packing_mode", "BOXES") as
    | "BOXES"
    | "BULK"
    | "MIXED";
  const packingBulk = packing_mode === "BULK" || packing_mode === "MIXED";
  const defaultPercentageBulk = getSetting(
    "percentage_added_to_bulk_packing_list",
  ) as number;

  const handleOpenModal = useCallback(
    (record: Record<string, unknown>) => {
      setSelectedShareArticleId(String(record.id ?? ""));
      setSelectedShareArticleName(record.name as string);
      setModalVisible(true);
    },
    [],
  );

  const handleCloseModal = useCallback(() => {
    setModalVisible(false);
    setSelectedShareArticleId(null);
    setSelectedShareArticleName("");
  }, []);

  const priceColumn = useShareArticlePriceColumn(handleOpenModal);
  // The prices are the office's to manage, so only the office gets the button.
  const priceModalColumn = canManagePrices ? priceColumn : null;

  // The irrelevant side of the harvest/purchase split renders an empty cell
  // (disabled → grey background is the only cue; no "—" placeholder leaks into
  // the save payload).
  const renderHarvestNumber = useCallback(
    (decimals: number) => (value: number, record: TableRecord) =>
      isHarvestDisabled(record)
        ? null
        : value
          ? format(Number(value), decimals)
          : null,
    [format],
  );
  const renderPurchaseNumber = useCallback(
    (decimals: number) => (value: number, record: TableRecord) =>
      isPurchaseDisabled(record)
        ? null
        : value
          ? format(Number(value), decimals)
          : null,
    [format],
  );

  const visibleShareOptions = useMemo(
    () =>
      shareOptions.filter(
        (opt) =>
          (activeShareOptions as unknown as Record<string, boolean>)[
            opt.value
          ] === true,
      ),
    [shareOptions, activeShareOptions],
  );

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => {
      const share_option_list = shareOptions
        .map((opt: { value: string }) => opt.value.toLowerCase())
        .filter((key: string) => transformedData[key])
        .map((key: string) => key.toUpperCase());

      const synced = syncPurchasedName(
        (transformedData.name as string) || "",
        !!transformedData.is_purchased,
        t,
      );

      return {
        ...transformedData,
        name: synced.name,
        is_purchased: synced.is_purchased,
        share_option_list,
      };
    },
    [shareOptions, t],
  );

  const customEdit = useCallback(
    (
      record: TableRecord,
      form: { setFieldsValue: (values: Record<string, unknown>) => void },
    ) => {
      if (record.key === -1) {
        // customSave turns every ticked per-option flag into share_option_list,
        // so a new article ticks only an option whose column the office sees:
        // the filtered one, or else the vegetable share (the common case)
        // when the farm runs it.
        const preselectedShareOption =
          activeFilter !== "all"
            ? activeFilter
            : visibleShareOptions.some((opt) => opt.value === "HARVEST_SHARE")
              ? "harvest_share"
              : null;
        const defaultValues: Record<string, unknown> = {
          is_active: true,
          ...(preselectedShareOption && { [preselectedShareOption]: true }),
          percentage_added_to_bulk_packing_list: defaultPercentageBulk,
          is_sold_to_resellers: true,
          // For a certified-organic tenant, new articles are overwhelmingly
          // Bio — preselect that.
          ...(organicGateEnabled && { organic_status: "organic" }),
        };
        form.setFieldsValue(defaultValues);
        return { ...record, ...defaultValues };
      }
      return record;
    },
    [activeFilter, visibleShareOptions, defaultPercentageBulk, organicGateEnabled],
  );

  // Layer the share-option radio filter on top of the hook's hide-inactive
  // filter (`list.filteredData` already dropped inactive rows).
  const filteredData = useMemo(
    () =>
      activeFilter !== "all"
        ? list.filteredData.filter(
            (record) => record[activeFilter as keyof typeof record],
          )
        : list.filteredData,
    [list.filteredData, activeFilter],
  );

  // Stable options object so `useIsActiveColumn`'s internal memo holds.
  const isActiveColumnOptions = useMemo(() => ({ fixed: true }), []);
  const isActiveColumn = useIsActiveColumn(isActiveColumnOptions);

  const columns = useShareArticleListColumns({
    isActiveColumn,
    priceModalColumn,
    unitOptions,
    crates,
    visibleShareOptions,
    activeFilter,
    sells_to_resellers,
    has_markets,
    number_packing_stations,
    packingBulk,
    renderHarvestNumber,
    renderPurchaseNumber,
  });

  return (
    <div>
      <div className="flex-between">
        <div>
          <h1 className="mb-0">
            {t("commissioning.share_articles")}
          </h1>
          <h5>{t("commissioning.share_articles_description")}</h5>
        </div>
        <Flex vertical gap={8} align="flex-end">
          <Flex gap={8}>
            {canManagePrices && (
              <Button
                className="download-button"
                icon={<DownloadOutlined />}
                onClick={() => setPriceExportVisible(true)}
              >
                {t("commissioning.export_prices")}
              </Button>
            )}
            {canManagePrices && (
              <Button
                className="download-button"
                icon={<DownloadOutlined />}
                onClick={() => setCsvModalVisible(true)}
              >
                {t("commissioning.share_article_list_csv_export")}
              </Button>
            )}
          </Flex>
          {canManagePrices && (
            <Button
              className="download-button"
              icon={<DownloadOutlined />}
              onClick={() => setAllArticlesExportVisible(true)}
            >
              {t("commissioning.export_all_articles_combined")}
            </Button>
          )}
        </Flex>
      </div>

      <div className="flex-center-y gap-16 mb-16">
        <Radio.Group
          value={activeFilter}
          onChange={(e) => setActiveFilter(e.target.value)}
          optionType="button"
          buttonStyle="solid"
        >
          <Radio.Button value="all">{t("common.all")}</Radio.Button>
          {visibleShareOptions.map((opt: { value: string; label: string }) => (
            <Radio.Button key={opt.value} value={opt.value.toLowerCase()}>
              {getShareOptionLabel(opt.value, t)}
            </Radio.Button>
          ))}
        </Radio.Group>
      </div>
      <Flex align="center" gap={8}>
        <HideInactiveSwitch
          value={list.hideInactive}
          onChange={list.setHideInactive}
        />
      </Flex>

      <EditableTable
        columns={columns}
        apiFunctions={list.apiFunctions}
        uniqueCheck={["name", "default_movement_unit", "is_purchased"]}
        uniqueCheckMessage={t("validation.unique.list_share_articles")}
        focusIndex="name"
        initialData={filteredData}
        uniqueCheckRows={list.data}
        loading={list.isLoading}
        onSaveSuccess={list.onSaveSuccess}
        onDeleteSuccess={list.onDeleteSuccess}
        customSave={customSave}
        customEdit={customEdit}
        permissions={list.permissions}
        pagination={true}
        showSearchBar={true}
        keyboardAddShortcut={true}
      />
      <ExplainerText title={t("common.info")}>
        {t("explainers.list_share_articles")}
      </ExplainerText>

      <CsvImportButton
        uploadAllowed={uploadAllowed}
        columns={columns}
        filename={t("commissioning.share_articles_template.csv")}
        modelName="share_article"
        onUploadSuccess={list.invalidate}
      />
      <ExportCsv
        open={csvModalVisible}
        onClose={() => setCsvModalVisible(false)}
        columns={
          columns as unknown as Parameters<typeof ExportCsv>[0]["columns"]
        }
        data={filteredData}
        filename={t("commissioning.share_articles")}
      />

      <ExportCsvPricesShareArticle
        open={priceExportVisible}
        onClose={() => setPriceExportVisible(false)}
      />

      <ExportCsvAllArticles
        open={allArticlesExportVisible}
        onClose={() => setAllArticlesExportVisible(false)}
      />

      <ShareArticlePriceModal
        visible={modalVisible}
        onClose={handleCloseModal}
        share_article={selectedShareArticleId}
        share_article_name={selectedShareArticleName}
        onSave={list.invalidate}
      />
    </div>
  );
}
