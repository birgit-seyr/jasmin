import { CaretRightOutlined, CheckCircleOutlined } from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Card, Collapse, Flex, Tag } from "antd";
import dayjs from "dayjs";
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
import { getDateRangeStatus, isFieldDisabled, notify } from "@shared/utils";

// Single source of truth for the share-option codes is the generated
// ``ShareTypeEnum`` (mirrors the backend ShareType.share_option choices) —
// keep the on-screen accordion order matching the enum declaration order.
const SHARE_OPTIONS = Object.values(ShareTypeEnum);

type ShareOption = ShareTypeEnum;

type ShareTypeRecord = ShareType & TableRecord;

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
    (saveData: Record<string, unknown>) => {
      // Client-side joker floor: once a share type is in use
      // (``can_be_deleted === false``) its joker / donation-joker counts may
      // only be RAISED, never lowered — members already have the current count
      // allocated. Mirror the backend rejection BEFORE the request (like the
      // station-day capacity floor) so the office sees it while the row is
      // still in edit mode.
      const original = saveData.id
        ? data.find((row) => String(row.id) === String(saveData.id))
        : undefined;
      if (original?.can_be_deleted === false) {
        for (const field of [
          "amount_of_jokers",
          "amount_of_donation_jokers",
        ] as const) {
          const next = saveData[field];
          if (next == null || next === "") continue;
          if (Number(next) < Number(original[field] ?? 0)) {
            const message = t(
              "validation.amount_cannot_be_reduced_while_in_use",
            );
            notify.validationError(message);
            // Throwing aborts the save; EditableTable keeps the row in edit
            // mode so the office can pick a valid value.
            throw new Error(message);
          }
        }
      }
      return {
        ...saveData,
        share_option: shareOption,
      };
    },
    [shareOption, data, t],
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

export default function ConfigurationShareTypeVariations() {
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

  const { validFromColumn, validUntilColumn } = useTimeBoundColumns({
    // A share type can't end before its latest variation, and can't be closed
    // at all while a variation is open-ended (backend stranding guard).
    validUntilFloor: (record) => ({
      minDate: record.variations_valid_until_max
        ? dayjs(record.variations_valid_until_max as string)
        : null,
      blockAll: Boolean(record.has_open_ended_variation),
    }),
  });

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
              {t("commissioning.short_name")}
              <ToolTipIcon title={t("tooltip.short_name_share_type")} />
            </>
          ),
          dataIndex: "short_name",
          key: "short_name",
          inputType: "text",
          required: true,
          align: "left",
          width: "6em",
        },
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
          width: "10em",
        },
        {
          title: t("commissioning.delivery_cycle"),
          dataIndex: "delivery_cycle",
          key: "delivery_cycle",
          inputType: "select",
          align: "center",
          required: true,
          width: "10em",
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
          width: "8em",
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
          width: "3em",
          align: "center",
          // Always editable; the "may only increase while in use" floor is
          // enforced in ``customSave`` (mirrors the capacity floor).
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
          width: "3em",
          // Always editable; the "may only increase while in use" floor is
          // enforced in ``customSave`` (mirrors the capacity floor).
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
          width: "12em",
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

  return (
    <div>
      <h1>{t("configuration.share_type_variations")}</h1>
      <div style={{ marginTop: "4em" }}></div>
      {/* Share Option Sections — wrapped in a titled Card so the light-blue
          ``settings-card-header`` bar matches the visual rhythm of the other
          config cards. Full width on purpose: the embedded ShareType tables
          need the room. */}

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

      <ShareTypeVariationModal
        visible={shareTypeVariationModal.visible}
        share_type={shareTypeVariationModal.shareType}
        share_type_name={shareTypeVariationModal.shareTypeName}
        onClose={closeShareTypeVariationModal}
        onSave={handleSaveShareTypeVariations}
      />
    </div>
  );
}
