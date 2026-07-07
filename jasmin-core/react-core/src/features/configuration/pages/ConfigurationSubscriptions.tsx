import { CaretRightOutlined, CheckCircleOutlined } from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Card, Col, Collapse, Flex, Row, Tag } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningShareTypesCreate,
  commissioningShareTypesDestroy,
  commissioningShareTypesPartialUpdate,
  getCommissioningShareTypesListQueryKey,
  useCommissioningShareTypesList,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  ActiveShareOptions,
  CommissioningShareTypesListParams,
  ShareType,
} from "@shared/api/generated/models";
import { ShareTypeEnum } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { ShareTypeVariationModal } from "@features/commissioning/modals";
import {
  EditableTable,
  permissionsWithDeletable,
  wrapApiFunctions,
} from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { DateRangeStatusLegend, ToolTipIcon } from "@shared/ui";
import {
  useActiveShareOptions,
  useActiveStatusColumn,
  useInvalidateAfterTableMutation,
  useShareTypeVariationSizeOptions,
  useTimeBoundColumns,
} from "@hooks/index";
import { getDateRangeStatus, isFieldDisabled } from "@shared/utils";
import { SettingsCategory } from "@features/configuration/components/SettingsRenderer";
import SettingsPage from "@features/configuration/components/SettingsPage";

// Single source of truth for the share-option codes is the generated
// ``ShareTypeEnum`` (mirrors the backend ShareType.share_option choices) —
// keep the on-screen accordion order matching the enum declaration order.
const SHARE_OPTIONS = Object.values(ShareTypeEnum);

type ShareOption = ShareTypeEnum;

type ShareTypeRecord = ShareType & TableRecord;

const EXCLUSIVE_SETTINGS: Record<string, string> = {
  subscriptions_end_at_end_of_season: "subscriptions_end_after_one_year",
  subscriptions_end_after_one_year: "subscriptions_end_at_end_of_season",
};

interface ShareTypeTableProps {
  shareOption: ShareOption;
  columns: EditableColumnConfig<TableRecord>[];
  onActiveStatusChange?: (shareOption: ShareOption, hasActive: boolean) => void;
}

function ShareTypeTable({
  shareOption,
  columns,
  onActiveStatusChange,
}: ShareTypeTableProps) {
  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const queryClient = useQueryClient();

  // ``permissionsWithDeletable`` gates the delete button on ``can_be_deleted``
  // (false when the ShareType has share-type variations — the PROTECT FK from
  // ShareTypeVariation). ``gatedByPermission`` alone always showed delete.
  const permissions = useMemo(
    () => permissionsWithDeletable(isOffice),
    [isOffice],
  );

  const listParams = useMemo<CommissioningShareTypesListParams>(
    () => ({ share_option: shareOption }),
    [shareOption],
  );

  const { data: rawData, isLoading } =
    useCommissioningShareTypesList(listParams);
  // Directional cast at the orval boundary: rows gain the table-only
  // ``key`` field.
  const data = useMemo(() => (rawData ?? []) as ShareTypeRecord[], [rawData]);

  useEffect(() => {
    const hasActive = data.some(
      (item) =>
        getDateRangeStatus(item.valid_from, item.valid_until) === "active",
    );
    onActiveStatusChange?.(shareOption, hasActive);
  }, [data, shareOption, onActiveStatusChange]);

  const apiFunctions: ApiFunctions = useMemo(
    () =>
      wrapApiFunctions<ShareTypeRecord>({
        create: (data) => commissioningShareTypesCreate(data),
        update: (id, data) => commissioningShareTypesPartialUpdate(id, data),
        delete: (id) => commissioningShareTypesDestroy(id),
      }),
    [],
  );

  const handleDataChange = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningShareTypesListQueryKey(listParams),
    });
  }, [queryClient, listParams]);

  const { onSaveSuccess: trackAddedRow, onDeleteSuccess } =
    useInvalidateAfterTableMutation(handleDataChange);

  // Reload the WHOLE table on save (not just the optimistic add): creating a
  // ShareType auto-closes the open predecessor in the same share_option (sets
  // its ``valid_until`` via TimeBoundMixin succession), so a create mutates
  // ANOTHER row that the optimistic insert never reflects. Mirrors the
  // child-relations carve-out in ``useInvalidateAfterTableMutation``'s
  // docstring — still call the hook's handler for the ``recentlyAddedIds`` pin.
  const onSaveSuccess = useCallback(
    (record: TableRecord, action: "create" | "update") => {
      trackAddedRow(record, action);
      handleDataChange();
    },
    [trackAddedRow, handleDataChange],
  );

  const customSave = useCallback(
    (saveData: Record<string, unknown>) => ({
      ...saveData,
      share_option: shareOption,
    }),
    [shareOption],
  );

  // HARVEST_SHARE and HARVEST_SHARE_FRUIT are the primary harvest shares — they
  // can never be an "additional" share type (an add-on like eggs/bread), so lock
  // that checkbox in those two tables (for existing AND new rows). Every other
  // share_option keeps the normal row-status gate (``isFieldDisabled``).
  const effectiveColumns = useMemo(() => {
    const lockAdditional =
      shareOption === ShareTypeEnum.HARVEST_SHARE ||
      shareOption === ShareTypeEnum.HARVEST_SHARE_FRUIT;
    if (!lockAdditional) return columns;
    return columns.map((col) =>
      col.key === "is_additional_share_type" ? { ...col, disabled: true } : col,
    );
  }, [columns, shareOption]);

  return (
    <>
      <EditableTable
        columns={effectiveColumns}
        apiFunctions={apiFunctions}
        initialData={data}
        loading={isLoading}
        onSaveSuccess={onSaveSuccess}
        onDeleteSuccess={onDeleteSuccess}
        permissions={permissions}
        uniqueCheck={["name"]}
        uniqueCheckMessage={t("validation.unique.name")}
        customSave={customSave}
        forceInlineMode={true}
      />
      <DateRangeStatusLegend />
    </>
  );
}

interface ShareTypeVariationModalState {
  visible: boolean;
  shareType: string | null;
  shareTypeName: string;
}

export default function ConfigurationSubscriptions() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const {
    activeShareOptions: fetchedActiveShareOptions,
    loading: loadingActiveStatus,
  } = useActiveShareOptions();
  // ``activeShareOptions`` has a single owner: this local state. It is SEEDED
  // once from the query (the backend's computed active status), after which the
  // per-option ``ShareTypeTable`` children are the sole writers via
  // ``handleActiveStatusChange``. The ref guard stops a background refetch of
  // ``fetchedActiveShareOptions`` from clobbering those live child-driven
  // toggles (the old two-write-path race).
  const [activeShareOptions, setActiveShareOptions] = useState<
    Partial<Record<keyof ActiveShareOptions, boolean>>
  >({});
  const activeStatusSeededRef = useRef(false);

  useEffect(() => {
    if (loadingActiveStatus || activeStatusSeededRef.current) return;
    setActiveShareOptions(fetchedActiveShareOptions);
    activeStatusSeededRef.current = true;
  }, [fetchedActiveShareOptions, loadingActiveStatus]);

  const { getShareTypeVariationSizeLabel } = useShareTypeVariationSizeOptions();

  const handleActiveStatusChange = useCallback(
    (shareOption: ShareOption, hasActive: boolean) => {
      setActiveShareOptions((prev) => ({
        ...prev,
        [shareOption]: hasActive,
      }));
    },
    [],
  );

  const { validFromColumn, validUntilColumn } = useTimeBoundColumns();

  const getShareOptionLabel = useCallback(
    (value: string) => t(`commissioning.share_option.${value}`),
    [t],
  );

  const [shareTypeVariationModal, setShareTypeVariationModal] =
    useState<ShareTypeVariationModalState>({
      visible: false,
      shareType: null,
      shareTypeName: "",
    });

  const openShareTypeVariationModal = useCallback(
    (shareTypeId: string, shareTypeName: string) => {
      setShareTypeVariationModal({
        visible: true,
        shareType: shareTypeId,
        shareTypeName,
      });
    },
    [],
  );

  const closeShareTypeVariationModal = useCallback(() => {
    setShareTypeVariationModal({
      visible: false,
      shareType: null,
      shareTypeName: "",
    });
    // Reload the share-types table(s) on close — editing a share type's
    // variations in the modal can change what the parent table derives (e.g.
    // the "active sizes" / sizes-in-use column). The base key prefix-matches
    // every per-share_option ShareTypeTable list query.
    queryClient.invalidateQueries({
      queryKey: getCommissioningShareTypesListQueryKey(),
    });
  }, [queryClient]);

  const handleSaveShareTypeVariations = useCallback(() => {
    closeShareTypeVariationModal();
  }, [closeShareTypeVariationModal]);

  const activeStatusColumn = useActiveStatusColumn({
    defaultSortOrder: "descend",
  });

  const shareTypeColumns = useMemo(
    () =>
      [
        activeStatusColumn,
        validFromColumn,
        validUntilColumn,
        {
          title: (
            <>
              {t("commissioning.name")}
              <ToolTipIcon title={t("tooltip.name_share_type")} />
            </>
          ),
          dataIndex: "name",
          key: "name",
          inputType: "text",
          required: true,
          align: "left",
          width: "12em",
        },
        {
          title: t("commissioning.delivery_cycle"),
          dataIndex: "delivery_cycle",
          key: "delivery_cycle",
          inputType: "select",
          align: "center",
          required: true,
          width: "14em",
          disabled: isFieldDisabled,
          options: [
            { label: t("commissioning.weekly"), value: "WEEKLY" },
            { label: t("commissioning.odd_weeks"), value: "ODD_WEEKS" },
            { label: t("commissioning.even_weeks"), value: "EVEN_WEEKS" },
            {
              label: t("commissioning.all_three_weeks"),
              value: "ALL_THREE_WEEKS",
            },
            {
              label: t("commissioning.all_four_weeks"),
              value: "ALL_FOUR_WEEKS",
            },
          ],
          render: (value: string) => {
            const option: Record<string, string> = {
              WEEKLY: t("commissioning.weekly"),
              ODD_WEEKS: t("commissioning.odd_weeks"),
              EVEN_WEEKS: t("commissioning.even_weeks"),
              ALL_THREE_WEEKS: t("commissioning.all_three_weeks"),
              ALL_FOUR_WEEKS: t("commissioning.all_four_weeks"),
            };
            return option[value] || value;
          },
        },
        {
          title: (
            <div style={{ fontSize: "0.85em" }}>
              {t("commissioning.share_type_variation_sizes_in_use")}
            </div>
          ),
          dataIndex: "share_type_variation_sizes_in_use",
          key: "share_type_variation_sizes_in_use",
          inputType: "text",
          disabled: true,
          width: "12em",
          readOnly: true,
          align: "left",
          render: (value: string) => (
            <>{getShareTypeVariationSizeLabel(value)}</>
          ),
        },
        {
          title: (
            <div className="checkbox-column-title">
              {t("commissioning.amount_of_jokers")}
            </div>
          ),
          dataIndex: "amount_of_jokers",
          key: "amount_of_jokers",
          inputType: "integer",
          width: "4em",
          align: "center",
          disabled: isFieldDisabled,
          render: (_: unknown, record: TableRecord) =>
            record.amount_of_jokers == 0 ? "-" : record.amount_of_jokers,
        },
        {
          title: (
            <div className="checkbox-column-title">
              {t("commissioning.amount_of_donation_jokers")}
            </div>
          ),
          dataIndex: "amount_of_donation_jokers",
          key: "amount_of_donation_jokers",
          inputType: "integer",
          align: "center",
          width: "4em",
          disabled: isFieldDisabled,
          render: (_: unknown, record: TableRecord) =>
            record.amount_of_donation_jokers == 0
              ? "-"
              : record.amount_of_donation_jokers,
        },
        {
          title: (
            <>
              {t("commissioning.is_additional_share_type")}{" "}
              <ToolTipIcon title={t("tooltip.is_additional_share_type")} />
            </>
          ),
          dataIndex: "is_additional_share_type",
          key: "is_additional_share_type",
          inputType: "checkbox",
          align: "center",
          disabled: isFieldDisabled,
        },
        {
          title: (
            <>
              {t("commissioning.needs_complex_planning")}{" "}
              <ToolTipIcon title={t("tooltip.needs_complex_planning")} />
            </>
          ),
          dataIndex: "needs_complex_planning",
          key: "needs_complex_planning",
          inputType: "checkbox",
          align: "center",
        },
        {
          title: "",
          dataIndex: "variations_action",
          key: "variations_action",
          disabled: true,
          readOnly: true,
          width: "16em",
          render: (_: unknown, record: TableRecord) => (
            <Button
              type="primary"
              size="small"
              onClick={() =>
                openShareTypeVariationModal(
                  String(record.id),
                  String(
                    record.name ||
                      record.description ||
                      record.valid_from ||
                      "",
                  ),
                )
              }
            >
              {t("commissioning.configure_variations")}
            </Button>
          ),
        },
      ] as EditableColumnConfig<TableRecord>[],
    [
      openShareTypeVariationModal,
      activeStatusColumn,
      validFromColumn,
      validUntilColumn,
      getShareTypeVariationSizeLabel,
      t,
    ],
  );

  const shareOptionCollapseItems = useMemo(
    () =>
      SHARE_OPTIONS.map((option) => {
        const isActive = activeShareOptions[option];
        return {
          key: option,
          label: (
            <Flex align="center" gap={10}>
              <span style={{ fontWeight: 500 }}>
                {getShareOptionLabel(option)}
              </span>
              {isActive && (
                <Tag
                  icon={<CheckCircleOutlined />}
                  color="success"
                  style={{ borderRadius: 12, margin: 0 }}
                >
                  {t("configuration.active")}
                </Tag>
              )}
            </Flex>
          ),
          children: (
            <ShareTypeTable
              shareOption={option}
              columns={shareTypeColumns}
              onActiveStatusChange={handleActiveStatusChange}
            />
          ),
          style: {
            borderLeft: isActive
              ? "3px solid var(--color-success)"
              : "3px solid transparent",
            background: isActive
              ? "linear-gradient(90deg, rgba(82,196,26,0.03) 0%, transparent 40%)"
              : undefined,
            transition: "border-color 0.3s, background 0.3s",
          },
        };
      }),
    [
      activeShareOptions,
      getShareOptionLabel,
      t,
      shareTypeColumns,
      handleActiveStatusChange,
    ],
  );

  // The trial-share card moved to ConfigurationSubscriptions when the
  // underlying field was renamed to ``allows_trial_subscriptions``
  // (migration 0018) — the name was misleading because it gates trial
  // *subscriptions*, not Share/CoopShare equity.
  const settingsConfig = useMemo<SettingsCategory[]>(
    () => [
      {
        category: "subscriptions",
        title: t("settings.commissioning.subscriptions.title"),
        settings: [
          {
            key: "subscriptions_end_at_end_of_season",
            label: t("settings.commissioning.end_at_season_end"),
            type: "checkbox",
            defaultValue: false,
          },
          {
            key: "season_start_week",
            label: t("settings.commissioning.season_start_week"),
            // Stored as ISO calendar week so the same value drives
            // every year's ``valid_until`` derivation in Abos.tsx
            // (Monday of that week → -1 day → preceding Sunday).
            type: "number",
            min: 1,
            max: 53,
            visibleIf: (getValue) =>
              Boolean(getValue("subscriptions_end_at_end_of_season", true)),
          },
          {
            key: "subscriptions_end_after_one_year",
            label: t("settings.commissioning.end_after_year"),
            type: "checkbox",
            defaultValue: false,
          },
          {
            key: "subscriptions_are_auto_renewed",
            label: t("settings.commissioning.auto_renewed"),
            type: "checkbox",
            defaultValue: false,
          },
          {
            key: "min_weeks_to_cancel_before_ending",
            label: t("settings.commissioning.min_weeks_cancel"),
            description: t(
              "settings.commissioning.min_weeks_cancel_description",
            ),
            type: "number",
            defaultValue: 6,
            min: 0,
            max: 52,
            visibleIf: (getValue) =>
              Boolean(getValue("subscriptions_are_auto_renewed", true)),
          },
          {
            // Tenant-wide gate for the on-off (per-delivery opt-in)
            // mechanism. When True, ``ShareTypeVariationModal``
            // exposes two columns (``requires_optin``,
            // ``optin_deadline_days_before_delivery``) and the
            // backend accepts ``requires_optin=True`` writes. When
            // False, the columns disappear and the backend rejects
            // any save that would flip ``requires_optin=True``.
            // Existing on-off variations stay configured but their
            // toggles are inert until the flag flips back on.
            key: "allows_share_type_variation_optin",
            label: t(
              "settings.commissioning.allows_share_type_variation_optin",
            ),
            description: t(
              "settings.commissioning.allows_share_type_variation_optin_desc",
            ),
            type: "checkbox",
            defaultValue: false,
          },
        ],
      },
      {
        category: "trial_subscriptions",
        title: t("settings.subscriptions.trial.title"),
        description: t("settings.subscriptions.trial.description"),
        settings: [
          {
            key: "allows_trial_subscriptions",
            label: t("settings.subscriptions.allows_trial_subscriptions"),

            type: "checkbox",
            defaultValue: true,
          },
          {
            key: "allowed_trial_subscription_duration",
            label: t(
              "settings.subscriptions.allowed_trial_subscription_duration",
            ),
            description: t(
              "settings.subscriptions.allowed_trial_subscription_duration_desc",
            ),
            type: "number",
            defaultValue: 4,
            min: 1,
            max: 52,
            visibleIf: (getValue) =>
              Boolean(getValue("allows_trial_subscriptions", true)),
          },
          {
            key: "allows_trial_subscriptions_for_trial_members",
            label: t(
              "settings.subscriptions.allows_trial_subscriptions_for_trial_members",
            ),
            description: t(
              "settings.subscriptions.allows_trial_subscriptions_for_trial_members_desc",
            ),
            type: "checkbox",
            defaultValue: true,
            visibleIf: (getValue) =>
              Boolean(getValue("allows_trial_subscriptions", true)),
          },
          {
            key: "info_sentence_about_trial_subscriptions",
            label: t(
              "settings.subscriptions.info_sentence_about_trial_subscriptions",
            ),
            description: t(
              "settings.subscriptions.info_sentence_about_trial_subscriptions_desc",
            ),
            type: "input",
            defaultValue: "",
            visibleIf: (getValue) =>
              Boolean(getValue("allows_trial_subscriptions", true)),
          },
          {
            key: "uses_jokers_for_trial_subscriptions",
            label: t(
              "settings.subscriptions.uses_jokers_for_trial_subscriptions",
            ),
            description: t(
              "settings.subscriptions.uses_jokers_for_trial_subscriptions_desc",
            ),
            type: "checkbox",
            defaultValue: false,
            visibleIf: (getValue) =>
              Boolean(getValue("allows_trial_subscriptions", true)),
          },
        ],
      },
    ],
    [t],
  );

  return (
    <>
      <SettingsPage
        settingsConfig={settingsConfig}
        onBeforeSettingChange={(key, value, setSetting) => {
          const opposite = EXCLUSIVE_SETTINGS[key];
          if (opposite && value === true) {
            setSetting(opposite, false);
          }
        }}
        extraBefore={({ renderSetting }) => (
          <>
            {/* Share Option Sections — wrapped in a titled Card so the
                light-blue ``settings-card-header`` bar matches the
                visual rhythm of the other cards on this page. Full
                width on purpose: the embedded ShareType tables need
                the room; the other settings cards below stay at the
                ``page-narrow`` 800px cap. */}
            <Card
              title={t("settings.subscriptions.share_types.title")}
              className="settings-card-header"
              styles={{ body: { padding: "16px" } }}
            >
              <Collapse
                accordion={false}
                expandIcon={({ isActive }) => (
                  <CaretRightOutlined
                    rotate={isActive ? 90 : 0}
                    style={{ fontSize: 14 }}
                  />
                )}
                items={shareOptionCollapseItems}
                className="w-full"
              />
            </Card>

            {/* Display Settings */}
            <Card
              className="settings-card-header page-narrow"
              styles={{ body: { padding: "16px" } }}
            >
              <Row gutter={[12, 12]}>
                <Col span={24}>
                  <div style={{ padding: "4px 0" }}>
                    {renderSetting({
                      key: "show_seller_name_of_share_article_in_share_for_member_on_page",
                      label: t(
                        "settings.commissioning.show_seller_name_in_share",
                      ),
                      type: "checkbox",
                      defaultValue: true,
                    })}
                  </div>
                </Col>
              </Row>
            </Card>
          </>
        )}
      />

      <ShareTypeVariationModal
        visible={shareTypeVariationModal.visible}
        share_type={shareTypeVariationModal.shareType}
        share_type_name={shareTypeVariationModal.shareTypeName}
        onClose={closeShareTypeVariationModal}
        onSave={handleSaveShareTypeVariations}
      />
    </>
  );
}
