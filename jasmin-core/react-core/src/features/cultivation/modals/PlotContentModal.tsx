import { PlusOutlined } from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Flex, Modal, Spin } from "antd";
import type { FC } from "react";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  cultivationPlotContentsCreate,
  cultivationPlotContentsDestroy,
  cultivationPlotContentsPartialUpdate,
  getCultivationPlotContentsListQueryKey,
  useCultivationBedTypesList,
  useCultivationPlotContentsList,
} from "@shared/api/generated/cultivation/cultivation";
import type { PlotContent } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import ModalCloseFooter from "@shared/modals/ModalCloseFooter";
import {
  EditableTable,
  permissionsWithDeletable,
  wrapApiFunctions,
} from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  SelectOption,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import BedTypeModal from "./BedTypeModal";

type PlotContentRow = PlotContent & TableRecord;

interface PlotLike {
  id?: string;
  name?: string | null;
}

interface PlotContentModalProps {
  visible: boolean;
  onClose: () => void;
  plot: PlotLike | null;
}

/**
 * Per-plot bed composition, opened from the Plots list (mirrors the
 * delivery-station-day detail modal). The plot_contents endpoint is not
 * plot-filtered server-side, so we fetch the (small) list and scope it to this
 * plot; ``customSave`` stamps the plot onto every row. A dashed button opens the
 * quick-create {@link BedTypeModal} so a missing bed type can be added inline.
 */
const PlotContentModal: FC<PlotContentModalProps> = ({
  visible,
  onClose,
  plot,
}) => {
  const { t } = useTranslation();
  const { isGardener } = useRoles();
  const queryClient = useQueryClient();
  const [bedTypeModalOpen, setBedTypeModalOpen] = useState(false);

  const {
    data: rawData,
    isLoading,
    isFetching,
  } = useCultivationPlotContentsList({ query: { enabled: visible } });

  const rows = useMemo<PlotContentRow[]>(
    () =>
      ((rawData ?? []) as unknown as PlotContentRow[]).filter(
        (row) => row.plot === plot?.id,
      ),
    [rawData, plot?.id],
  );

  const { data: bedTypes, refetch: refetchBedTypes } =
    useCultivationBedTypesList();
  const bedTypeOptions = useMemo<SelectOption[]>(
    () =>
      (bedTypes ?? []).map((b) => ({
        value: b.id as string,
        label: b.name || (b.id as string),
      })),
    [bedTypes],
  );
  const bedTypeNameById = useMemo(() => {
    const map = new Map<string, string>();
    (bedTypes ?? []).forEach((b) => {
      if (b.id) map.set(b.id, b.name || b.id);
    });
    return map;
  }, [bedTypes]);

  const invalidateData = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: getCultivationPlotContentsListQueryKey(),
    });
  }, [queryClient]);

  const apiFunctions = useMemo<ApiFunctions>(
    () =>
      wrapApiFunctions<PlotContentRow>({
        create: (data) => cultivationPlotContentsCreate(data),
        update: (id, data) => cultivationPlotContentsPartialUpdate(id, data),
        delete: (id) => cultivationPlotContentsDestroy(id),
      }),
    [],
  );

  const customSave = useCallback(
    (transformed: Record<string, unknown>) => ({
      ...transformed,
      plot: plot?.id,
    }),
    [plot?.id],
  );

  const permissions = useMemo(
    () => permissionsWithDeletable(isGardener),
    [isGardener],
  );

  const columns = useMemo<EditableColumnConfig<PlotContentRow>[]>(
    () => [
      {
        title: <>{t("cultivation.plot_content_bed_type")}</>,
        dataIndex: "bed_type",
        key: "bed_type",
        inputType: "select",
        required: true,
        width: "18em",
        align: "left",
        options: bedTypeOptions,
        render: (value: unknown) =>
          value ? (bedTypeNameById.get(String(value)) ?? "") : "",
      },
      {
        title: <>{t("cultivation.plot_content_amount")}</>,
        dataIndex: "amount",
        key: "amount",
        inputType: "positive_integer",
        required: true,
        width: "12em",
      },
    ],
    [t, bedTypeOptions, bedTypeNameById],
  );

  return (
    <>
      <Modal
        title={`${t("cultivation.list_plot_contents")} — ${plot?.name || ""}`}
        open={visible}
        onCancel={onClose}
        width={720}
        destroyOnHidden
        footer={[<ModalCloseFooter key="close" onClose={onClose} />]}
      >
        {isLoading ? (
          <div className="loading-placeholder">
            <Spin size="large" />
          </div>
        ) : (
          <Flex vertical gap="middle" align="start">
            <EditableTable<PlotContentRow>
              columns={columns}
              apiFunctions={apiFunctions}
              initialData={rows}
              loading={isFetching}
              onSaveSuccess={invalidateData}
              onDeleteSuccess={invalidateData}
              customSave={customSave}
              permissions={permissions}
              uniqueCheck={["bed_type"]}
              uniqueCheckMessage={t("cultivation.plot_content_unique")}
              focusIndex="bed_type"
              forceInlineMode={true}
            />
            <Button
              type="dashed"
              icon={<PlusOutlined />}
              onClick={() => setBedTypeModalOpen(true)}
            >
              {t("cultivation.add_bed_type")}
            </Button>
          </Flex>
        )}
      </Modal>

      <BedTypeModal
        isOpen={bedTypeModalOpen}
        onClose={() => setBedTypeModalOpen(false)}
        onSuccess={() => {
          setBedTypeModalOpen(false);
          refetchBedTypes();
        }}
        zIndex={1100}
      />
    </>
  );
};

export default PlotContentModal;
