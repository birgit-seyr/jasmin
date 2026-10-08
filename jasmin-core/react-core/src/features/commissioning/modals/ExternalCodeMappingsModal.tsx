import { Modal } from "antd";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
  commissioningExternalCodeMappingsCreate,
  commissioningExternalCodeMappingsDestroy,
  commissioningExternalCodeMappingsPartialUpdate,
  useCommissioningDeliveryStationsList,
  useCommissioningExternalCodeMappingsList,
  useCommissioningSharesDeliveryDaysList,
  useCommissioningShareTypeVariationsList,
} from "@shared/api/generated/commissioning/commissioning";
import type { ExternalCodeMapping } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { useDateFormat } from "@hooks/configuration/useDateFormat";
import { useShareTypeVariationSizeOptions } from "@hooks/useShareTypeVariationSizeOptions";
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
import { ExplainerText } from "@shared/ui";
import { DELIVERY_DAY_SHORT_KEYS } from "@shared/utils/weekdayNames";
import { useNoteColumn } from "@hooks/index";

// A row being added carries none of the mapping's fields yet.
type MappingRow = TableRecord & Partial<Omit<ExternalCodeMapping, "id">>;

interface SelectOption {
  value: string;
  label: string;
}

interface ExternalCodeMappingsModalProps {
  open: boolean;
  onClose: () => void;
}

export default function ExternalCodeMappingsModal({
  open,
  onClose,
}: ExternalCodeMappingsModalProps) {
  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const permissions = useMemo(() => gatedByPermission(isOffice), [isOffice]);
  const { getShareTypeVariationSizeLabel } = useShareTypeVariationSizeOptions();
  const { formatDate } = useDateFormat();
  const { noteColumn } = useNoteColumn();

  // React Query handles the initial load + caching. ``enabled: open``
  // keeps it idle until the modal is shown; ``onDataChange`` below
  // refetches after EditableTable mutations land. Without ``kind`` the
  // backend returns every mapping, which is what this modal lists.
  const {
    data: mappingsData,
    isLoading,
    refetch,
  } = useCommissioningExternalCodeMappingsList(
    {},
    { query: { enabled: open } },
  );
  const data = useMemo<TableRecord[]>(
    () => (mappingsData ?? []) as unknown as TableRecord[],
    [mappingsData],
  );

  // Fetch reference data for internal-id pickers via react-query.
  // `enabled: open` keeps queries idle until the modal is actually shown.
  const { data: variationsData } = useCommissioningShareTypeVariationsList(
    {},
    { query: { enabled: open } },
  );
  const { data: stationsData } = useCommissioningDeliveryStationsList(
    // delivery_day is optional on the backend; pass empty params.
    {} as Parameters<typeof useCommissioningDeliveryStationsList>[0],
    { query: { enabled: open } },
  );
  const { data: daysData } = useCommissioningSharesDeliveryDaysList(
    {},
    { query: { enabled: open } },
  );

  // Dated like the delivery days: a variation replaced from a week on and
  // its successor share their name and size, and the weekly import asks the
  // office to map the version valid then.
  const variationOptions = useMemo<SelectOption[]>(
    () =>
      (variationsData ?? []).map((v) => {
        const sizeLabel = getShareTypeVariationSizeLabel(v.size);
        const name =
          [v.share_type_name, sizeLabel].filter(Boolean).join(" · ") ||
          t("import_shares.mappings.no_label");
        const validity = [formatDate(v.valid_from), formatDate(v.valid_until)]
          .filter(Boolean)
          .join(" → ");
        return {
          value: v.id as string,
          label: `${v.id} — ${[name, validity].filter(Boolean).join(" · ")}`,
        };
      }),
    [variationsData, getShareTypeVariationSizeLabel, t, formatDate],
  );

  const stationOptions = useMemo<SelectOption[]>(
    () =>
      (stationsData ?? []).map((s) => {
        const parts = [s.short_name, s.city].filter(Boolean);
        return {
          value: s.id as string,
          label: `${s.id} — ${parts.join(" · ") || t("import_shares.mappings.no_label")}`,
        };
      }),
    [stationsData, t],
  );

  const dayOptions = useMemo<SelectOption[]>(
    () =>
      (daysData ?? []).map((d) => {
        const dayShort = t(DELIVERY_DAY_SHORT_KEYS[d.day_number]);
        const validity = [formatDate(d.valid_from), formatDate(d.valid_until)]
          .filter(Boolean)
          .join(" → ");
        const parts = [dayShort, validity].filter(Boolean);
        return {
          value: d.id as string,
          label: `${d.id} — ${parts.join(" · ")}`,
        };
      }),
    [daysData, t, formatDate],
  );

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<ExternalCodeMapping & TableRecord>({
        create: (payload) => commissioningExternalCodeMappingsCreate(payload),
        update: (id, payload) =>
          commissioningExternalCodeMappingsPartialUpdate(String(id), payload),
        delete: async (id) => {
          await commissioningExternalCodeMappingsDestroy(String(id));
        },
      }),
    [],
  );

  const kindOptions = useMemo(
    () => [
      {
        value: "variation",
        label: t("import_shares.mappings.kind_variation"),
      },
      {
        value: "station",
        label: t("import_shares.mappings.kind_station"),
      },
      {
        value: "day",
        label: t("import_shares.mappings.kind_day"),
      },
    ],
    [t],
  );

  const kindLabel = (k: string) =>
    kindOptions.find((o) => o.value === k)?.label ?? k;

  const optionsByKind = useMemo<Record<string, SelectOption[]>>(
    () => ({
      variation: variationOptions,
      station: stationOptions,
      day: dayOptions,
    }),
    [variationOptions, stationOptions, dayOptions],
  );

  // Only the mapping's own kind names its object: an id of another kind's
  // object is one the import can't resolve, so it shows as the bare id.
  const internalIdLabel = (kind: string | undefined, id: string) => {
    if (!id) return "";
    const kindList = kind ? (optionsByKind[kind] ?? []) : [];
    return kindList.find((o) => o.value === id)?.label ?? id;
  };

  const columns: EditableColumnConfig<MappingRow>[] = [
    {
      title: <>{t("import_shares.mappings.kind")}</>,
      dataIndex: "kind",
      key: "kind",
      inputType: "select",
      options: kindOptions,
      required: true,
      width: "14em",
      align: "left",
      sortable: true,
      render: (v) => kindLabel(String(v ?? "")),
      // When kind changes during edit, clear internal_id (old id no longer valid)
      onFieldChange: () => ({ internal_id: undefined }),
    },
    {
      title: <>{t("import_shares.mappings.external_code")}</>,
      dataIndex: "external_code",
      key: "external_code",
      inputType: "text",
      required: true,
      width: "14em",
      align: "left",
      sortable: true,
    },
    {
      title: <>{t("import_shares.mappings.internal_id")}</>,
      dataIndex: "internal_id",
      key: "internal_id",
      inputType: "select",
      // Dynamic options based on the kind currently selected on this row
      // (form values, not just the persisted record). When kind isn't set
      // yet, fall back to the union so the column is never empty/disabled.
      options: (record) => {
        const kind = record.kind;
        if (kind && optionsByKind[kind]) return optionsByKind[kind];
        return [...variationOptions, ...stationOptions, ...dayOptions];
      },
      required: true,
      width: "35em",
      align: "left",
      render: (v, record) =>
        internalIdLabel(record.kind, String(v ?? "")),
    },
    noteColumn,
  ];

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={1200}
      destroyOnHidden
      title={t("import_shares.mappings.title")}
    >
      <p className="modal-subtitle">
        {t("import_shares.mappings.subtitle")}
      </p>

      <EditableTable
        columns={columns}
        apiFunctions={apiFunctions}
        initialData={data}
        loading={isLoading}
        onSaveSuccess={() => void refetch()}
        onDeleteSuccess={() => void refetch()}
        focusIndex="external_code"
        uniqueCheck={["kind", "external_code"]}
        uniqueCheckMessage={t("validation.unique.external_code_mapping")}
        permissions={permissions}
      />

      <ExplainerText>
        {t("import_shares.mappings.explainer_body")}
      </ExplainerText>
    </Modal>
  );
}
