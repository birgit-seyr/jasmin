import {
  DeleteOutlined,
  EditOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { useCrates } from "@features/commissioning/hooks";
import ShareTypeVariationPriceModal from "@features/commissioning/modals/prices/ShareTypeVariationPriceModal";
import {
  useActiveStatusColumn,
  useNumberFormat,
  useShareTypeVariationSizeOptions,
  useTenant,
  useTimeBoundColumns,
} from "@hooks/index";
import BubbleChartIcon from "@mui/icons-material/BubbleChart";
import {
  commissioningShareTypeVariationsCreate,
  commissioningShareTypeVariationsDestroy,
  commissioningShareTypeVariationsPartialUpdate,
  getCommissioningShareTypeVariationsListQueryKey,
  getCommissioningShareTypesRetrieveQueryOptions,
  useCommissioningShareTypeVariationsList,
} from "@shared/api/generated/commissioning/commissioning";
import type { CommissioningShareTypeVariationsListParams } from "@shared/api/generated/models/commissioningShareTypeVariationsListParams";
import type { ShareTypeVariation } from "@shared/api/generated/models/shareTypeVariation";
import { useRoles } from "@shared/auth";
import ModalCloseFooter from "@shared/modals/ModalCloseFooter";
import RichTextEditorModal from "@shared/modals/RichTextEditorModal";
import {
  EditableTable,
  gatedByPermission,
  wrapApiFunctions,
} from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import {
  DateRangeStatusLegend,
  PictureUploadField,
  ToolTipIcon,
  usePictureUpload,
} from "@shared/ui";
import { isFieldDisabled, notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Modal, Space, Spin } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import VirtualComponentModal from "./VirtualComponentModal";

interface ShareTypeVariationRecord extends TableRecord {
  size?: string;
  variation_type?: string;
  average_weight?: string | number;
  description?: string;
  used_crate?: string;
  used_crate_name?: string;
  can_be_deleted?: boolean;
  picture?: string | null;
  [key: string]: unknown;
}

interface ShareTypeVariationModalProps {
  visible: boolean;
  onClose: () => void;
  share_type: string | null;
  share_type_name: string;
  onSave?: () => void;
}

export default function ShareTypeVariationModal({
  visible,
  onClose,
  share_type,
  share_type_name,
  onSave: _onSave,
}: ShareTypeVariationModalProps) {
  const [selectedShareTypeVariation, setSelectedShareTypeVariation] =
    useState<ShareTypeVariationRecord | null>(null);
  const [priceModalVisible, setPriceModalVisible] = useState(false);
  const [descriptionModalVisible, setDescriptionModalVisible] = useState(false);
  const [selectedDescriptionRecord, setSelectedDescriptionRecord] =
    useState<ShareTypeVariationRecord | null>(null);
  const [virtualComponentModalVisible, setVirtualComponentModalVisible] =
    useState(false);
  const [selectedVirtualComponentRecord, setSelectedVirtualComponentRecord] =
    useState<ShareTypeVariationRecord | null>(null);
  const [pictureModalVisible, setPictureModalVisible] = useState(false);
  const [selectedPictureRecord, setSelectedPictureRecord] =
    useState<ShareTypeVariationRecord | null>(null);

  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const { format } = useNumberFormat();
  const { getSetting } = useTenant();
  const packing_mode = getSetting("packing_mode", "BOXES") as
    | "BOXES"
    | "BULK"
    | "MIXED";
  // Tenant-wide gate for on-off (per-delivery opt-in) variations.
  // When False, the three opt-in configuration columns are hidden;
  // backend also refuses to persist ``requires_optin=True`` in that
  // state (see ``ShareTypeVariation.clean``).
  const allows_share_type_variation_optin = getSetting(
    "allows_share_type_variation_optin",
    false,
  ) as boolean;
  const allows_trial_subscriptions = getSetting(
    "allows_trial_subscriptions",
    false,
  ) as boolean;
  // Jokers (per-share-type opt-OUT) and per-delivery opt-IN are mutually
  // exclusive (backend enforces this in ShareType/ShareTypeVariation.clean).
  // When this share type has any jokers configured, hide the opt-in columns
  // entirely — even if the tenant setting would otherwise allow them.
  const { data: parentShareType } = useQuery({
    ...getCommissioningShareTypesRetrieveQueryOptions(share_type ?? ""),
    enabled: visible && !!share_type,
  });
  const shareTypeHasJokers =
    (parentShareType?.amount_of_jokers ?? 0) > 0 ||
    (parentShareType?.amount_of_donation_jokers ?? 0) > 0;
  const showOptinColumns =
    allows_share_type_variation_optin && !shareTypeHasJokers;
  const permissions = useMemo(
    () => ({
      ...gatedByPermission(isOffice),
      canDeleteRecord: (record: TableRecord) => {
        if (record.key === -1 || !record.id) return true;
        return isOffice && record.can_be_deleted !== false;
      },
    }),
    [isOffice],
  );
  const queryClient = useQueryClient();

  const { crates } = useCrates();
  const { shareTypeVariationSizeOptions, getShareTypeVariationSizeLabel } =
    useShareTypeVariationSizeOptions();

  // future → active → past (blue-green-grey), consistent with the other
  // status-column tables.
  const activeStatusColumn = useActiveStatusColumn({
    defaultSortOrder: "descend",
  });
  const { validFromColumn, validUntilColumn } = useTimeBoundColumns({
    width: "8em",
    // A variation can't end before its latest subscription, and can't be closed
    // at all while a subscription is open-ended (backend stranding guard).
    validUntilFloor: (record) => ({
      minDate: record.subscriptions_valid_until_max
        ? dayjs(record.subscriptions_valid_until_max as string)
        : null,
      blockAll: Boolean(record.has_open_ended_subscription),
    }),
  });

  const listParams = useMemo<CommissioningShareTypeVariationsListParams>(
    () => (share_type ? { share_type } : {}),
    [share_type],
  );

  // Outer gate uses ``loading`` (isLoading → first-load spinner only); the
  // table's ``loading`` uses ``isFetching`` so a revisit (cached under the
  // global staleTime:0) shows a grid refresh spinner instead of silently
  // swapping stale rows for fresh ones.
  const {
    data: rawData,
    isLoading: loading,
    isFetching,
  } = useCommissioningShareTypeVariationsList(listParams, {
    query: { enabled: visible && !!share_type },
  });

  const data = useMemo(
    () => (rawData ?? []) as unknown as ShareTypeVariationRecord[],
    [rawData],
  );

  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCommissioningShareTypeVariationsListQueryKey(listParams),
    });
  }, [queryClient, listParams]);

  // CREATE invalidates so the newly-added variation pulls in its
  // pricing relations (``ShareTypeVariationGrossPrice`` lives on a
  // separate query) — without this, the office has to close +
  // reopen the modal to see the price columns populate. UPDATE
  // skips invalidation so an edited row stays where the office
  // put it (no spring). DELETE always invalidates so the row
  // vanishes. ``EditableTable``'s internal ``recentlyAddedIds`` pin
  // keeps the just-added row at the top across the create refetch.
  const handleSaveSuccess = useCallback(
    (_record: TableRecord, action: "create" | "update") => {
      if (action === "create") {
        invalidateData();
      }
    },
    [invalidateData],
  );

  const handleDeleteSuccess = useCallback(() => {
    invalidateData();
  }, [invalidateData]);

  const handleOpenPriceModal = useCallback(
    (record: ShareTypeVariationRecord) => {
      setSelectedShareTypeVariation(record);
      setPriceModalVisible(true);
    },
    [],
  );

  const handleClosePriceModal = useCallback(() => {
    setPriceModalVisible(false);
    setSelectedShareTypeVariation(null);
  }, []);

  const handleOpenDescriptionModal = useCallback(
    (record: ShareTypeVariationRecord) => {
      setSelectedDescriptionRecord(record);
      setDescriptionModalVisible(true);
    },
    [],
  );

  const handleCloseDescriptionModal = useCallback(() => {
    setDescriptionModalVisible(false);
    setSelectedDescriptionRecord(null);
  }, []);

  const handleSaveDescription = useCallback(
    async (htmlContent: string) => {
      if (!selectedDescriptionRecord?.id) return;

      try {
        await commissioningShareTypeVariationsPartialUpdate(
          String(selectedDescriptionRecord.id),
          { description: htmlContent } as unknown as ShareTypeVariation,
        );
        notify.success(t("common.saved_successfully"));
        invalidateData();
      } catch (error) {
        notify.error(getErrorMessage(error, t("common.error_saving")));
      }
    },
    [selectedDescriptionRecord, t, invalidateData],
  );

  const handleOpenVirtualComponentModal = useCallback(
    (record: ShareTypeVariationRecord) => {
      setSelectedVirtualComponentRecord(record);
      setVirtualComponentModalVisible(true);
    },
    [],
  );

  const handleCloseVirtualComponentModal = useCallback(() => {
    setVirtualComponentModalVisible(false);
    setSelectedVirtualComponentRecord(null);
  }, []);

  const handleSaveVirtualComponents = useCallback(() => {
    invalidateData();
  }, [invalidateData]);

  const handleOpenPictureModal = useCallback(
    (record: ShareTypeVariationRecord) => {
      setSelectedPictureRecord(record);
      setPictureModalVisible(true);
    },
    [],
  );

  const handleClosePictureModal = useCallback(() => {
    setPictureModalVisible(false);
    setSelectedPictureRecord(null);
  }, []);

  // Multipart escape hatch: the generated PATCH only sends JSON, so the shared
  // hook posts the FormData directly to the same endpoint (upload persists
  // immediately) and clears via a null JSON PATCH. Same pattern as
  // ConfigurationApp / ConfigurationGeneral. Closes the picture sub-modal on
  // success — the refreshed list carries the new/cleared thumbnail.
  const {
    uploading: uploadingPicture,
    uploadPicture,
    deletePicture,
  } = usePictureUpload({
    endpoint: `/api/commissioning/share_type_variations/${selectedPictureRecord?.id ?? ""}/`,
    invalidate: invalidateData,
    successMessage: t("common.saved_successfully"),
    errorMessage: t("common.error_saving"),
    onUploaded: handleClosePictureModal,
    onDeleted: handleClosePictureModal,
  });

  const columns = useMemo<EditableColumnConfig<TableRecord>[]>(
    () =>
      [
        activeStatusColumn,
        validFromColumn,
        validUntilColumn,
        {
          title: t("commissioning.size"),
          dataIndex: "size",
          key: "size",
          inputType: "select",
          options: shareTypeVariationSizeOptions,
          required: true,
          disabled: isFieldDisabled,
          align: "center",
          width: "7em",
          render: (value: unknown) =>
            value ? (
              <strong>{getShareTypeVariationSizeLabel(value as string)}</strong>
            ) : (
              ""
            ),
        },
        {
          title: (
            <div className="text-xs">
              {t("commissioning.sort_order")}
              <ToolTipIcon title={t("tooltip.sort_order")} />
            </div>
          ),
          dataIndex: "sort_order",
          key: "sort_order",
          inputType: "positive_integer",
          required: false,
          width: "5em",
          align: "center",
        },
        {
          title: (
            <div className="text-xs">
              {t("commissioning.variation_type")}
              <ToolTipIcon title={t("tooltip.variation_type")} />
            </div>
          ),
          dataIndex: "variation_type",
          key: "variation_type",
          width: "6em",
          readOnly: true,
          disabled: true,
          align: "center",
          render: (_: unknown, record: ShareTypeVariationRecord) => (
            <Space>
              {record.key !== -1 && record.id && (
                <Button
                  type="link"
                  size="small"
                  icon={
                    <BubbleChartIcon
                      style={{
                        color:
                          record.variation_type === "virtual"
                            ? "green"
                            : "var(--color-text-primary)",
                      }}
                    />
                  }
                  onClick={() => handleOpenVirtualComponentModal(record)}
                  title={t("commissioning.configure_virtual_components")}
                />
              )}
            </Space>
          ),
        },
        {
          title: t("commissioning.average_weight"),
          dataIndex: "average_weight",
          key: "average_weight",
          inputType: "positive_decimal2",
          width: "7em",
          suffix: "kg",
          align: "center",
          render: (text: unknown) =>
            text ? `${format(parseFloat(text as string), 2)} kg` : text,
        },
        {
          title: (
            <>
              {t("commissioning.capacity")}
              <ToolTipIcon
                title={t("tooltip.capacity_share_type_variations")}
              />
            </>
          ),
          dataIndex: "capacity",
          key: "capacity",
          inputType: "positive_integer",
          width: "7em",
          align: "center",
        },
        {
          title: t("commissioning.description"),
          dataIndex: "description",
          key: "description",
          width: "9em",
          align: "center",
          readOnly: true,
          disabled: true,
          render: (_: unknown, record: ShareTypeVariationRecord) => {
            if (record.key === -1 || !record.id) {
              return <span className="text-muted">-</span>;
            }

            return (
              <Space>
                <Button
                  type="link"
                  size="small"
                  icon={<EditOutlined />}
                  onClick={() => handleOpenDescriptionModal(record)}
                  aria-label={t("commissioning.edit_description")}
                />
              </Space>
            );
          },
        },
        {
          title: t("commissioning.picture"),
          dataIndex: "picture",
          key: "picture",
          width: "5em",
          align: "center",
          readOnly: true,
          disabled: true,
          render: (_: unknown, record: ShareTypeVariationRecord) => {
            if (record.key === -1 || !record.id) {
              return <span className="text-muted">-</span>;
            }
            return (
              <Button
                type="link"
                size="small"
                aria-label={t("commissioning.view_picture")}
                onClick={() => handleOpenPictureModal(record)}
              >
                {record.picture ? (
                  <img
                    src={record.picture}
                    alt=""
                    style={{
                      width: 28,
                      height: 28,
                      objectFit: "cover",
                      borderRadius: 4,
                    }}
                  />
                ) : (
                  <UploadOutlined />
                )}
              </Button>
            );
          },
        },
        {
          title: <>{t("commissioning.used_crate")}</>,
          dataIndex: "used_crate_name",
          key: "used_crate_name",
          inputType: "select",
          options: crates,
          required: false,
          width: "10em",
          foreignKey: {
            valueField: "used_crate",
            displayField: "used_crate_name",
          },
        },
        ...(allows_trial_subscriptions
          ? [
              {
                title: (
                  <div className="text-xs">
                    {t("commissioning.allowed_for_trial_subscription")}
                    <ToolTipIcon
                      title={t("tooltip.allowed_for_trial_subscription")}
                    />
                  </div>
                ),
                dataIndex: "allowed_for_trial_subscription",
                key: "allowed_for_trial_subscription",
                inputType: "checkbox",
                required: false,
                width: "6em",
                align: "center" as const,
              },
            ]
          : []),
        ...(packing_mode === "MIXED"
          ? [
              {
                title: (
                  <div className="text-xs">
                    {t("commissioning.is_packed_bulk")}
                    <ToolTipIcon title={t("tooltip.is_packed_bulk")} />
                  </div>
                ),
                dataIndex: "is_packed_bulk",
                key: "is_packed_bulk",
                inputType: "checkbox",
                required: false,
                width: "6em",
                align: "center" as const,
              },
            ]
          : []),
        // ---- On-off (per-delivery opt-in) columns ------------------
        // Hidden when the tenant hasn't enabled the feature OR this share type
        // has jokers (jokers and opt-in are mutually exclusive). Backend
        // mirrors both with a ``ValidationError`` on ``ShareTypeVariation.clean()``
        // so admin saves can't bypass.
        ...(showOptinColumns
          ? [
              {
                title: (
                  <div className="text-xs">
                    {t("commissioning.requires_optin")}
                    <ToolTipIcon title={t("tooltip.requires_optin")} />
                  </div>
                ),
                dataIndex: "requires_optin",
                key: "requires_optin",
                inputType: "checkbox",
                required: false,
                width: "6em",
                align: "center" as const,
              },
              {
                title: (
                  <div className="text-xs">
                    {t("commissioning.optin_deadline_days_before_delivery")}
                    <ToolTipIcon
                      title={t("tooltip.optin_deadline_days_before_delivery")}
                    />
                  </div>
                ),
                dataIndex: "optin_deadline_days_before_delivery",
                key: "optin_deadline_days_before_delivery",
                inputType: "positive_integer",
                required: false,
                width: "7em",
                align: "center" as const,
                render: (_: unknown, record: ShareTypeVariationRecord) => (
                  <>
                    {record.requires_optin == false
                      ? "-"
                      : record.optin_deadline_days_before_delivery}
                  </>
                ),
              },
            ]
          : []),
        {
          title: "",
          dataIndex: "action",
          key: "action",
          inputType: "select",
          required: false,
          disabled: true,
          readOnly: true,
          render: (_: unknown, record: ShareTypeVariationRecord) => (
            <>
              {record.key !== -1 && (
                <Button
                  type="primary"
                  size="small"
                  onClick={() => handleOpenPriceModal(record)}
                >
                  {t("commissioning.configure_prices")}
                </Button>
              )}
            </>
          ),
        },
      ] as EditableColumnConfig[],
    [
      t,
      crates,
      shareTypeVariationSizeOptions,
      getShareTypeVariationSizeLabel,
      activeStatusColumn,
      format,
      handleOpenDescriptionModal,
      handleOpenPictureModal,
      handleOpenPriceModal,
      handleOpenVirtualComponentModal,
      validFromColumn,
      validUntilColumn,
      packing_mode,
      showOptinColumns,
      allows_trial_subscriptions,
    ],
  );

  const customSave = useCallback(
    (transformedData: Record<string, unknown>) => {
      // Sort-order uniqueness — the table's built-in ``uniqueCheck``
      // prop only supports one rule (currently ``size``). Enforce
      // sort-order uniqueness here so the office can't ship two rows
      // with the same "3". The backend's variation querysets order by
      // ``sort_order`` first (see
      // ``ShareDeliveryService.get_weekly_variation_count_matrix`` +
      // ``ShareTypeVariationViewSet.get_queryset``); duplicates would leave
      // tiebreakers up to ``id`` and confuse the office.
      const sortOrder = transformedData.sort_order;
      const editingId = transformedData.id;
      if (sortOrder != null && sortOrder !== "") {
        const duplicate = (data as Array<Record<string, unknown>>).some(
          (row) =>
            row.id != null &&
            row.id !== editingId &&
            row.sort_order === sortOrder,
        );
        if (duplicate) {
          const msg = t("validation.unique.sort_order");
          notify.error(msg);
          // Throwing aborts the save; ``EditableTable`` keeps the row
          // in edit mode so the office can pick a different value.
          throw new Error(msg);
        }
      }
      return {
        ...transformedData,
        share_type,
      };
    },
    [share_type, data, t],
  );

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<ShareTypeVariation & TableRecord>({
        create: (data) => commissioningShareTypeVariationsCreate(data),
        update: (id, data) =>
          commissioningShareTypeVariationsPartialUpdate(id, data),
        delete: (id) => commissioningShareTypeVariationsDestroy(id),
      }),
    [],
  );

  return (
    <>
      <Modal
        title={
          <div>
            {t("commissioning.variations")} {share_type_name}
          </div>
        }
        open={visible}
        onCancel={onClose}
        width={1400}
        // Unmount the table on close so reopening for a DIFFERENT share type
        // starts fresh — no carry-over of the previous variation rows, draft,
        // or recentlyAddedIds pins.
        destroyOnHidden
        footer={[<ModalCloseFooter key="close" onClose={onClose} />]}
      >
        {loading ? (
          <div className="loading-placeholder">
            <Spin size="large" />
          </div>
        ) : (
          <>
            <EditableTable
              columns={columns}
              apiFunctions={apiFunctions}
              initialData={data}
              loading={isFetching}
              // Invalidate on save AND delete. ``onDataChange`` is
              // deliberately NOT wired — it would fire on every
              // local-state change (each keystroke during edit) and
              // produce a refetch storm. The save-success path is
              // the right level of granularity.
              onSaveSuccess={handleSaveSuccess}
              onDeleteSuccess={handleDeleteSuccess}
              permissions={permissions}
              uniqueCheck={["size"]}
              uniqueCheckMessage={t("validation.unique.size")}
              customSave={customSave}
              forceInlineMode={true}
            />
            <DateRangeStatusLegend />
          </>
        )}
      </Modal>

      <ShareTypeVariationPriceModal
        visible={priceModalVisible}
        onClose={handleClosePriceModal}
        share_type_variation={
          (selectedShareTypeVariation?.id as string) ?? null
        }
        share_type_variation_name={
          selectedShareTypeVariation
            ? `${getShareTypeVariationSizeLabel(selectedShareTypeVariation.size ?? "")} `
            : ""
        }
        onSave={undefined}
      />
      <RichTextEditorModal
        // Fresh key per opened record so the editor remounts and
        // useState(value) picks up the description — without it, ReactQuill
        // mounts empty and only fills on the second open.
        key={selectedDescriptionRecord?.id ?? "desc"}
        visible={descriptionModalVisible}
        zIndex={1100}
        onClose={handleCloseDescriptionModal}
        value={selectedDescriptionRecord?.description || ""}
        onSave={handleSaveDescription}
        placeholder={t("commissioning.enter_share_description")}
        title={`${t("commissioning.description")} - ${getShareTypeVariationSizeLabel(
          selectedDescriptionRecord?.size ?? "",
        )}`}
      />
      <VirtualComponentModal
        visible={virtualComponentModalVisible}
        onClose={handleCloseVirtualComponentModal}
        share_type={share_type}
        share_type_variation={selectedVirtualComponentRecord?.id ?? null}
        share_type_variation_name={getShareTypeVariationSizeLabel(
          selectedVirtualComponentRecord?.size ?? "",
        )}
        onSave={handleSaveVirtualComponents}
      />

      <Modal
        title={`${t("commissioning.picture")} - ${getShareTypeVariationSizeLabel(
          selectedPictureRecord?.size ?? "",
        )}`}
        open={pictureModalVisible}
        // Sibling (not nested) of the parent ShareTypeVariationModal, so AntD's
        // auto-stacking doesn't lift it — pin it above the parent's 1000.
        zIndex={1100}
        onCancel={handleClosePictureModal}
        footer={[
          selectedPictureRecord?.picture && (
            <Button
              key="delete"
              danger
              icon={<DeleteOutlined />}
              loading={uploadingPicture}
              onClick={deletePicture}
            >
              {t("common.delete")}
            </Button>
          ),
          <ModalCloseFooter key="close" onClose={handleClosePictureModal} />,
        ]}
      >
        <PictureUploadField
          pictureUrl={selectedPictureRecord?.picture}
          uploading={uploadingPicture}
          onUpload={uploadPicture}
          previewVariant="block"
          showDelete={false}
        />
      </Modal>
    </>
  );
}
