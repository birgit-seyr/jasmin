import {
  DeleteOutlined,
  EditOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { useCrates } from "@features/commissioning/hooks";
import type { CrateOption } from "@features/commissioning/hooks/useCrates";
import ShareTypeVariationPriceModal from "@features/commissioning/modals/prices/ShareTypeVariationPriceModal";
import {
  isSmallerShareSize,
  useActiveStatusColumn,
  useCapability,
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
import type { ShareTypeVariationRequest } from "@shared/api/generated/models/shareTypeVariationRequest";
import { useRoles } from "@shared/auth";
import ModalCloseFooter from "@shared/modals/ModalCloseFooter";
import RichTextEditorModal from "@shared/modals/RichTextEditorModal";
import {
  EditableTable,
  RowSaveRefused,
  gatedByPermissionOnlyEdit,
  periodsOverlap,
  permissionsWithDeletable,
  sameCellValue,
  withNewRowDefaults,
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
  RASTER_PICTURE_ACCEPT,
  ToolTipIcon,
  usePictureUpload,
} from "@shared/ui";
import { isFieldDisabled, notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Modal, Space, Spin } from "antd";
import dayjs from "dayjs";
import { useCallback, useMemo, useState } from "react";
import type { TFunction } from "i18next";
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
  is_packed_bulk?: boolean;
  /** ``is_packed_bulk`` as the table's choice; see ``packingColumn``. */
  packing?: Packing;
  [key: string]: unknown;
}

type Packing = "BOXED" | "LOOSE";

const startPrePacked = withNewRowDefaults<ShareTypeVariationRecord>({
  packing: "BOXED",
});
const startLoose = withNewRowDefaults<ShareTypeVariationRecord>({
  packing: "LOOSE",
});

/** The table's ``customEdit``: a new size starts packed like the farm's
 *  sizes, pre-packed where they differ, as the backend saves one without a
 *  choice. */
const newRowStart = (packingMode: string) =>
  packingMode === "BULK" ? startLoose : startPrePacked;

/** A virtual size is packed as the physical sizes it is made of. */
const isVirtual = (record: ShareTypeVariationRecord) =>
  record.variation_type === "virtual";

/**
 * The office chooses for every physical size whether it is pre-packed or
 * packed loose, and the farm's packing mode follows from its sizes. The table
 * holds the choice as ``packing``, which the save turns back into
 * ``is_packed_bulk``; a virtual size has none to make.
 */
function packingColumn(t: TFunction): EditableColumnConfig<ShareTypeVariationRecord> {
  const label = (packing: unknown) =>
    packing === "LOOSE"
      ? t("commissioning.packing_loose")
      : packing === "BOXED"
        ? t("commissioning.packing_boxed")
        : "";
  return {
    title: (
      <div className="text-xs">
        {t("commissioning.packing")}
        <ToolTipIcon title={t("tooltip.is_packed_bulk")} />
      </div>
    ),
    dataIndex: "packing",
    key: "packing",
    inputType: "select",
    required: true,
    options: [
      { value: "BOXED", label: label("BOXED") },
      { value: "LOOSE", label: label("LOOSE") },
    ],
    render: (packing, record) => (isVirtual(record) ? "—" : label(packing)),
    disabled: isVirtual,
    width: "7em",
    align: "center",
  };
}

/**
 * The button to the sizes a size is packed from, green for a virtual size. A
 * size is packed from smaller ones only, so one with no smaller physical size
 * beside it gets none, unless it is virtual already and its components need
 * taking out.
 */
function compositionColumn(
  t: TFunction,
  physicalSizes: string[],
  onOpen: (record: ShareTypeVariationRecord) => void,
): EditableColumnConfig<ShareTypeVariationRecord> {
  const canBeComposed = (record: ShareTypeVariationRecord) =>
    isVirtual(record) ||
    physicalSizes.some((size) => isSmallerShareSize(size, record.size));
  return {
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
        {record.key !== -1 && record.id && canBeComposed(record) && (
          <Button
            type="link"
            size="small"
            icon={
              <BubbleChartIcon
                style={{
                  color: isVirtual(record)
                    ? "var(--color-success)"
                    : "var(--color-text-primary)",
                }}
              />
            }
            onClick={() => onOpen(record)}
            title={t("commissioning.configure_virtual_components")}
          />
        )}
      </Space>
    ),
  };
}

/** What a share of the size weighs on average. A virtual size weighs what
 *  the sizes it is made of weigh, so it has no weight of its own to set. */
function weightColumn(
  t: TFunction,
  format: ReturnType<typeof useNumberFormat>["format"],
): EditableColumnConfig<ShareTypeVariationRecord> {
  return {
    title: t("commissioning.average_weight"),
    dataIndex: "average_weight",
    key: "average_weight",
    inputType: "positive_decimal2",
    width: "7em",
    suffix: "kg",
    align: "center",
    disabled: isVirtual,
    render: (weight, record) =>
      isVirtual(record)
        ? "—"
        : weight
          ? `${format(parseFloat(weight as string), 2)} kg`
          : null,
  };
}

/** The crate a size goes out to the delivery stations in. */
function crateColumn(
  t: TFunction,
  crates: CrateOption[],
): EditableColumnConfig<ShareTypeVariationRecord> {
  return {
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
  };
}

interface SubscriptionColumnActions {
  onOpenPrices: (record: ShareTypeVariationRecord) => void;
  onOpenDescription: (record: ShareTypeVariationRecord) => void;
  onOpenPicture: (record: ShareTypeVariationRecord) => void;
}

/**
 * The columns only subscriptions use: the capacity, the description and
 * picture shown where a subscription's variation is picked, whether a trial
 * subscription may take the variation, and the button to its prices. A tenant
 * that uploads its weekly share amounts, as every tenant inside Tapir does,
 * runs no subscriptions, so it gets none of them.
 */
function useSubscriptionColumns({
  onOpenPrices,
  onOpenDescription,
  onOpenPicture,
}: SubscriptionColumnActions): {
  capacityColumns: EditableColumnConfig<ShareTypeVariationRecord>[];
  pickerColumns: EditableColumnConfig<ShareTypeVariationRecord>[];
  trialColumns: EditableColumnConfig<ShareTypeVariationRecord>[];
  priceColumns: EditableColumnConfig<ShareTypeVariationRecord>[];
} {
  const { t } = useTranslation();
  const { getSetting } = useTenant();
  const weeklyUpload = getSetting(
    "uploads_weekly_share_amount",
    false,
  ) as boolean;
  const allowsTrialSubscriptions = getSetting(
    "allows_trial_subscriptions",
    false,
  ) as boolean;
  return useMemo(() => {
    if (weeklyUpload) {
      return {
        capacityColumns: [],
        pickerColumns: [],
        trialColumns: [],
        priceColumns: [],
      };
    }
    return {
      capacityColumns: [
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
      ] satisfies EditableColumnConfig<ShareTypeVariationRecord>[],
      pickerColumns: [
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
              return <span className="color-text-tertiary">-</span>;
            }

            return (
              <Space>
                <Button
                  type="link"
                  size="small"
                  icon={<EditOutlined />}
                  onClick={() => onOpenDescription(record)}
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
              return <span className="color-text-tertiary">-</span>;
            }
            return (
              <Button
                type="link"
                size="small"
                aria-label={t("commissioning.view_picture")}
                onClick={() => onOpenPicture(record)}
              >
                {record.picture ? (
                  <img
                    src={record.picture}
                    alt=""
                    className="table-picture-thumbnail"
                  />
                ) : (
                  <UploadOutlined />
                )}
              </Button>
            );
          },
        },
      ] satisfies EditableColumnConfig<ShareTypeVariationRecord>[],
      trialColumns: allowsTrialSubscriptions
        ? ([
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
              align: "center",
            },
          ] satisfies EditableColumnConfig<ShareTypeVariationRecord>[])
        : [],
      priceColumns: [
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
                  onClick={() => onOpenPrices(record)}
                >
                  {t("commissioning.configure_prices")}
                </Button>
              )}
            </>
          ),
        },
      ] satisfies EditableColumnConfig<ShareTypeVariationRecord>[],
    };
  }, [
    weeklyUpload,
    allowsTrialSubscriptions,
    onOpenPrices,
    onOpenDescription,
    onOpenPicture,
    t,
  ]);
}

interface ShareTypeVariationModalProps {
  visible: boolean;
  onClose: () => void;
  share_type: string | null;
  share_type_name: string;
  onSave?: () => void;
}

/**
 * Whether a variation of another size, valid on a day `variation` covers, has
 * its sort order: the backend's variation lists order by it first, so a tie
 * would leave the order to the id. Variations of one size never run at the
 * same time — the table refuses overlapping periods — so a successor may keep
 * its predecessor's sort order.
 */
function sortOrderTaken(
  variations: ShareTypeVariationRecord[],
  variation: Record<string, unknown>,
  record: TableRecord,
): boolean {
  const sortOrder = variation.sort_order;
  if (sortOrder == null || sortOrder === "") return false;
  return variations.some(
    (other) =>
      other.id !== record.id &&
      !sameCellValue(other.size, variation.size) &&
      sameCellValue(other.sort_order, sortOrder) &&
      periodsOverlap(other, variation),
  );
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
  const { getSetting, refreshTenant } = useTenant();
  const packing_mode = getSetting("packing_mode", "BOXES") as
    "BOXES" | "BULK" | "MIXED";
  // Tenant-wide gate for on-off (per-delivery opt-in) variations.
  // When False, the three opt-in configuration columns are hidden;
  // backend also refuses to persist ``requires_optin=True`` in that
  // state (see ``ShareTypeVariation.clean``).
  const allows_share_type_variation_optin = getSetting(
    "allows_share_type_variation_optin",
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
  // Where a host syncs the share types in, the office edits their sizes but
  // adds and deletes none.
  const offersShareTypes = useCapability("share_types");
  const offersDeliveryStations = useCapability("delivery_stations");
  const permissions = useMemo(
    () =>
      offersShareTypes
        ? permissionsWithDeletable(isOffice)
        : gatedByPermissionOnlyEdit(isOffice),
    [isOffice, offersShareTypes],
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
    // One variation per share type and size at a time.
    overlapGroup: ["share_type", "size"],
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
    () =>
      ((rawData ?? []) as unknown as ShareTypeVariationRecord[]).map(
        (row): ShareTypeVariationRecord => ({
          ...row,
          packing: row.is_packed_bulk ? "LOOSE" : "BOXED",
        }),
      ),
    [rawData],
  );

  const physicalSizes = useMemo(
    () => data.filter((row) => !isVirtual(row)).map((row) => row.size ?? ""),
    [data],
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
  // keeps the just-added row at the top across the create refetch. An update
  // patches the saved size into the cached list instead: the table lays the
  // response over the row it has, and the response carries no ``packing``,
  // which only the list derives from ``is_packed_bulk``. The farm's packing
  // mode follows from its sizes, so every change reloads the tenant's
  // settings too.
  const handleSaveSuccess = useCallback(
    (record: TableRecord, action: "create" | "update") => {
      if (action === "create") {
        invalidateData();
      } else {
        // The table hands an update's response over as it came.
        const saved = record as unknown as ShareTypeVariation;
        queryClient.setQueryData<ShareTypeVariation[]>(
          getCommissioningShareTypeVariationsListQueryKey(listParams),
          (rows) =>
            rows?.map((row) => (row.id === saved.id ? { ...row, ...saved } : row)),
        );
      }
      void refreshTenant();
    },
    [invalidateData, refreshTenant, queryClient, listParams],
  );

  // A deleted size, or one its components turn virtual or physical, changes
  // the list and the packing mode alike.
  const reloadSizes = useCallback(() => {
    invalidateData();
    void refreshTenant();
  }, [invalidateData, refreshTenant]);

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
          { description: htmlContent },
        );
        notify.success(t("common.saved_successfully"));
        invalidateData();
      } catch (error) {
        notify.error(getErrorMessage(error, t("common.error_saving")));
        // Keeps the editor open with the text.
        throw error;
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

  const { capacityColumns, pickerColumns, trialColumns, priceColumns } =
    useSubscriptionColumns({
      onOpenPrices: handleOpenPriceModal,
      onOpenDescription: handleOpenDescriptionModal,
      onOpenPicture: handleOpenPictureModal,
    });

  const columns = useMemo<EditableColumnConfig<ShareTypeVariationRecord>[]>(
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
        compositionColumn(t, physicalSizes, handleOpenVirtualComponentModal),
        weightColumn(t, format),
        ...capacityColumns,
        ...pickerColumns,
        // Where a host runs the delivery stations, the crates going out to
        // them are its business too.
        ...(offersDeliveryStations ? [crateColumn(t, crates)] : []),
        ...trialColumns,
        packingColumn(t),
        // ---- On-off (per-delivery opt-in) columns ------------------
        // Hidden when the tenant hasn't enabled the feature OR this share type
        // has jokers (jokers and opt-in are mutually exclusive). Backend
        // mirrors both with a ``ValidationError`` on ``ShareTypeVariation.clean()``
        // so admin saves can't bypass.
        ...(showOptinColumns
          ? ([
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
                align: "center",
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
                align: "center",
                render: (_: unknown, record: ShareTypeVariationRecord) => (
                  <>
                    {record.requires_optin == false
                      ? "-"
                      : record.optin_deadline_days_before_delivery}
                  </>
                ),
              },
            ] satisfies EditableColumnConfig<ShareTypeVariationRecord>[])
          : []),
        ...priceColumns,
      ],
    [
      t,
      crates,
      shareTypeVariationSizeOptions,
      getShareTypeVariationSizeLabel,
      activeStatusColumn,
      format,
      priceColumns,
      physicalSizes,
      handleOpenVirtualComponentModal,
      validFromColumn,
      validUntilColumn,
      showOptinColumns,
      capacityColumns,
      pickerColumns,
      trialColumns,
      offersDeliveryStations,
    ],
  );

  const customSave = useCallback(
    (transformedData: Record<string, unknown>, record: TableRecord) => {
      // The picture has its own upload. Where its column isn't shown, the row
      // still holds its address, which the backend refuses as no file.
      const { packing, picture: _picture, ...fields } = transformedData;
      const choosesPacking = packing && !isVirtual(record);
      const variation: Record<string, unknown> = {
        ...fields,
        share_type,
        ...(choosesPacking ? { is_packed_bulk: packing === "LOOSE" } : {}),
      };
      if (sortOrderTaken(data, variation, record)) {
        const message = t("validation.unique.sort_order");
        throw new RowSaveRefused(message, { sort_order: message });
      }
      return variation;
    },
    [share_type, data, t],
  );

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<ShareTypeVariationRequest & TableRecord>({
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
              onDeleteSuccess={reloadSizes}
              permissions={permissions}
              customSave={customSave}
              customEdit={newRowStart(packing_mode)}
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
        // The variation rows carry their active prices.
        onSave={invalidateData}
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
        share_type_variation_size={selectedVirtualComponentRecord?.size}
        onSave={reloadSizes}
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
          accept={RASTER_PICTURE_ACCEPT}
        />
      </Modal>
    </>
  );
}
