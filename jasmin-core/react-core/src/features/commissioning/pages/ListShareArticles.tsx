import { DownloadOutlined } from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
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
import { ExportCsv, ExportCsvAllArticles, ExportCsvPricesShareArticle, ShareArticlePriceModal } from '@features/commissioning/modals';
import {
  EditableTable,
  gatedByPermission,
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
import { useActiveShareOptions, useInvalidateAfterTableMutation, useNumberFormat, useOrganicGate, useTenant, useUnitOptions } from '@hooks/index';
import { useCrates, useIsActiveColumn, useShareArticleListColumns, useShareArticlePriceColumn, useShareOptions } from '@features/commissioning/hooks';
import { syncPurchasedName } from "@shared/utils";

// Pure row predicates — a row is harvest-only or purchase-only based on
// ``is_purchased``. Module-level so they're stable references the column
// ``useMemo`` can depend on indirectly without being invalidated each render.
const isHarvestDisabled = (record: TableRecord) =>
  record.is_purchased === true;
const isPurchaseDisabled = (record: TableRecord) =>
  record.is_purchased === false;

export default function ListShareArticles() {
  const [modalVisible, setModalVisible] = useState(false);
  const [selectedShareArticleId, setSelectedShareArticleId] = useState<
    string | null
  >(null);
  const [selectedShareArticleName, setSelectedShareArticleName] = useState("");
  const [activeFilter, setActiveFilter] = useState("all");
  const [hideInactive, setHideInactive] = useState(true);
  const [csvModalVisible, setCsvModalVisible] = useState(false);
  const [priceExportVisible, setPriceExportVisible] = useState(false);
  const [allArticlesExportVisible, setAllArticlesExportVisible] =
    useState(false);
  const queryClient = useQueryClient();

  // Permissions — derived from current user's roles.
  const { canEdit, isOffice: canManagePrices } = useRoles();
  const permissions = useMemo(
    () => ({
      ...gatedByPermission(canEdit),
      canDeleteRecord: (record: TableRecord) => {
        if (!canEdit) return false;
        if (record.key === -1 || !record.id) return true;
        return record.can_be_deleted !== false;
      },
    }),
    [canEdit],
  );

  const handleOpenModal = useCallback(
    (record: Record<string, unknown>) => {
      if (!canManagePrices) return;
      setSelectedShareArticleId(String(record.id ?? ""));
      setSelectedShareArticleName(record.name as string);
      setModalVisible(true);
    },
    [canManagePrices],
  );

  const handleCloseModal = useCallback(() => {
    setModalVisible(false);
    setSelectedShareArticleId(null);
    setSelectedShareArticleName("");
  }, []);

  const priceModalColumn = useShareArticlePriceColumn(handleOpenModal);

  const { t } = useTranslation();
  const { getSetting } = useTenant();
  const { enabled: organicGateEnabled } = useOrganicGate();
  const { format } = useNumberFormat();

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
  // The bulk-percentage column only applies when a bulk packing list
  // actually exists — i.e. BULK or MIXED modes.
  const packingBulk = packing_mode === "BULK" || packing_mode === "MIXED";
  const defaultPercentageBulk = getSetting(
    "percentage_added_to_bulk_packing_list",
  ) as number;

  const { unitOptions } = useUnitOptions();
  const { crates } = useCrates();
  const { shareOptions } = useShareOptions();
  const { activeShareOptions } = useActiveShareOptions();

  // Predicates + render wrappers for the harvest/purchase column split.
  // A row's ``is_purchased`` flag drives which side of the article's
  // logistics applies: purchased articles don't have a harvest path
  // (no kg/piece/bunch/crate from the farm), and farmed articles don't
  // have a purchase path. The cells on the irrelevant side are disabled
  // for editing AND show an empty cell — the grey background painted
  // by EditableCell for disabled cells is the only visual cue, no "—"
  // or other placeholder string (which used to leak into the save
  // payload as a FK value).
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

  // No ``list``: this page owns the data via ``useCommissioningShareArticlesList``
  // with ``listParams = { is_data_list: true }`` (passed as ``initialData``).
  // Supplying ``list`` would make EditableTable double-fetch the same endpoint
  // (it auto-fetches when ``showSearchBar`` + ``apiFunctions.list`` are both
  // set). Mutations refresh via the ``onSaveSuccess``/``onDeleteSuccess``
  // invalidation.
  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<ShareArticle & TableRecord>({
        create: (payload) => commissioningShareArticlesCreate(payload),
        update: (id, payload) =>
          commissioningShareArticlesPartialUpdate(id, payload),
        delete: (id) => commissioningShareArticlesDestroy(id),
      }),
    [],
  );

  const listParams = useMemo<CommissioningShareArticlesListParams>(
    () => ({ is_data_list: true }),
    [],
  );

  const { data: rawData, isLoading } =
    useCommissioningShareArticlesList(listParams);
  const data = useMemo(
    () => (rawData ?? []) as unknown as TableRecord[],
    [rawData],
  );

  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningShareArticlesListQueryKey(),
    });
  }, [queryClient]);
  const { onSaveSuccess, onDeleteSuccess } =
    useInvalidateAfterTableMutation(invalidateData);

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => {
      const share_option_list = shareOptions
        .map((opt: { value: string }) => opt.value.toLowerCase())
        .filter((key: string) => transformedData[key])
        .map((key: string) => key.toUpperCase());

      let modifiedName = (transformedData.name as string) || "";
      let modifiedIsPurchased = transformedData.is_purchased;

      const synced = syncPurchasedName(modifiedName, !!modifiedIsPurchased, t);
      modifiedName = synced.name;
      modifiedIsPurchased = synced.is_purchased;

      return {
        ...transformedData,
        name: modifiedName,
        is_purchased: modifiedIsPurchased,
        share_option_list: share_option_list,
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
        const defaultValues: Record<string, unknown> = {
          is_active: true,
          // New articles default to the harvest-share option — the common
          // case. ``customSave`` maps these per-option booleans into
          // ``share_option_list``. Office can untick / add other options.
          harvest_share: true,
          percentage_added_to_bulk_packing_list: defaultPercentageBulk,
          is_sold_to_resellers: true,
          // For a certified-organic tenant, new articles are
          // overwhelmingly Bio — preselect that. Office can flip the
          // dropdown to Umstellung / Konventionell on the rare bought-
          // in items. When the tenant isn't certified, the column is
          // hidden anyway, but we keep the default off so a future
          // certification doesn't auto-claim Bio on legacy rows.
          ...(organicGateEnabled && { organic_status: "organic" }),
          ...(activeFilter !== "all" && { [activeFilter]: true }),
        };
        form.setFieldsValue(defaultValues);
        return { ...record, ...defaultValues };
      }
      return record;
    },
    [activeFilter, defaultPercentageBulk, organicGateEnabled],
  );

  const filteredData = useMemo(() => {
    let result = data;
    if (hideInactive) {
      result = result.filter((record) => record.is_active);
    }
    if (activeFilter !== "all") {
      result = result.filter(
        (record) => record[activeFilter as keyof typeof record],
      );
    }
    return result;
  }, [data, activeFilter, hideInactive]);

  // Stable options object so ``useIsActiveColumn``'s internal memo (keyed on
  // its options arg) holds — a fresh ``{ fixed: true }`` literal each render
  // would return a new column ref and bust the columns useMemo below.
  const isActiveColumnOptions = useMemo(() => ({ fixed: true }), []);
  const isActiveColumn = useIsActiveColumn(isActiveColumnOptions);

  const columns = useShareArticleListColumns({
    isActiveColumn,
    priceModalColumn,
    unitOptions,
    crates,
    organicGateEnabled,
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
          <h1 style={{ marginBottom: 0 }}>
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

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 16,
          marginBottom: 16,
        }}
      >
        <Radio.Group
          value={activeFilter}
          onChange={(e) => setActiveFilter(e.target.value)}
          optionType="button"
          buttonStyle="solid"
        >
          <Radio.Button value="all">{t("common.all")}</Radio.Button>
          {visibleShareOptions.map((opt: { value: string; label: string }) => (
            <Radio.Button key={opt.value} value={opt.value.toLowerCase()}>
              {t(`commissioning.share_option.${opt.value}`, opt.label)}
            </Radio.Button>
          ))}
        </Radio.Group>
      </div>
      <Flex align="center" gap={8}>
        <HideInactiveSwitch value={hideInactive} onChange={setHideInactive} />
      </Flex>

      <EditableTable
        columns={columns}
        apiFunctions={apiFunctions}
        uniqueCheck={["name", "default_movement_unit", "is_purchased"]}
        uniqueCheckMessage={t("validation.unique.list_share_articles")}
        focusIndex="name"
        initialData={filteredData}
        loading={isLoading}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        customSave={customSave}
        customEdit={customEdit}
        permissions={permissions}
        pagination={true}
        showSearchBar={true}
      />
      <ExplainerText title={t("common.info")}>
        {t("explainers.list_share_articles")}
      </ExplainerText>

      {uploadAllowed && (
        <DownloadCsvTemplateButton
          columns={columns}
          filename={t("commissioning.share_articles_template.csv")}
          modelName="share_article"
          onUploadSuccess={invalidateData}
        />
      )}
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
        onSave={invalidateData}
      />
    </div>
  );
}
