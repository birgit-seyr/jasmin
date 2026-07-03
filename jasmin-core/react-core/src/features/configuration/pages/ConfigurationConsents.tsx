import {
  CheckOutlined,
  DownloadOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Space, Tag, Typography } from "antd";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  commissioningConsentDocumentsDestroy,
  getCommissioningConsentDocumentsListQueryKey,
  useCommissioningConsentDocumentsList,
} from "@shared/api/generated/commissioning/commissioning";
import type { ConsentDocument } from "@shared/api/generated/models";
import { useRoles } from "@shared/auth";
import { EditableTable } from "@shared/tables";
import type {
  ApiFunctions,
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { consentKindTagColor } from "@shared/consent/consentKindColors";
import { downloadConsentPdf } from "@shared/consent/downloadConsentPdf";
import { DateRangeStatusLegend, ExplainerText, ToolTipIcon } from "@shared/ui";
import { useActiveStatusColumn, useDateFormat, useTenant } from "@hooks/index";
import {
  ConsentDocumentModal,
  type ConsentDocumentModalMode,
} from "@features/configuration/modals";

const { Paragraph, Text } = Typography;

export default function ConfigurationConsents() {
  const { t } = useTranslation();
  const { isOffice } = useRoles();
  const queryClient = useQueryClient();

  const { tenant } = useTenant();
  const tenantLanguage = (tenant?.tenant_language as string) || "de";
  const { dateFormat, formatDateWithFallback } = useDateFormat();

  const [modalState, setModalState] = useState<{
    open: boolean;
    mode: ConsentDocumentModalMode;
    document: ConsentDocument | null;
  }>({ open: false, mode: "create", document: null });

  const { data: rawData, isLoading } = useCommissioningConsentDocumentsList({
    locale: tenantLanguage as never,
  });
  const data = useMemo<TableRecord[]>(() => {
    if (!rawData) return [];
    const all = Array.isArray(rawData)
      ? rawData
      : ((rawData as { results?: ConsentDocument[] }).results ?? []);
    return all as unknown as TableRecord[];
  }, [rawData]);

  // EditableTable is wired up read-only for create/update — those
  // go through ``ConsentDocumentModal``. Delete IS wired here, but
  // only for rows that haven't been consented to yet
  // (``can_be_deleted === true``) — the per-row check below gates
  // it. The serializer's ``can_be_deleted`` field + the FK's
  // ``on_delete=PROTECT`` enforce the same at the DB layer; this
  // is the UI half of that pair.
  const apiFunctions: ApiFunctions = useMemo(
    () => ({
      create: () => Promise.reject(new Error("Use the modal to create.")),
      update: () =>
        Promise.reject(new Error("ConsentDocument is append-only.")),
      delete: (id) => commissioningConsentDocumentsDestroy(id),
    }),
    [],
  );

  // After a row delete, refresh the consent list (the same query key the
  // create/edit modal invalidates). Without this the deleted row lingers in
  // the cached list until a full reload.
  const onDeleteSuccess = useCallback(() => {
    void queryClient.invalidateQueries({
      queryKey: getCommissioningConsentDocumentsListQueryKey(),
    });
  }, [queryClient]);

  // Office can delete, but only unused documents — the per-row
  // ``canDeleteRecord`` predicate honours the serializer's
  // ``can_be_deleted`` flag.
  const permissions = useMemo(
    () => ({
      canAdd: false,
      canEdit: false,
      canDelete: isOffice,
      canDeleteRecord: (record: TableRecord) => record.can_be_deleted !== false,
    }),
    [isOffice],
  );

  const activeStatusColumn = useActiveStatusColumn({
    defaultSortOrder: "descend",
  });

  const renderDate = useCallback(
    (value: unknown) => formatDateWithFallback(value as string, "—"),
    [formatDateWithFallback],
  );

  const columns: EditableColumnConfig<TableRecord>[] = useMemo(
    () =>
      [
        activeStatusColumn,
        {
          // "In use" indicator — checkmark when at least one
          // ConsentRecord references this document. Same visual idiom
          // as ConfigurationTimeManagement's in-use column.
          title: (
            <div className="checkbox-column-title">
              {t("configuration.in_use")}
            </div>
          ),
          dataIndex: "can_be_deleted",
          key: "can_be_deleted",
          width: "4em",
          align: "center",
          readOnly: true,
          render: (_: unknown, record: TableRecord) =>
            record.can_be_deleted === false ? (
              <CheckOutlined className="icon-check-success" />
            ) : null,
        },
        {
          title: t("consent.admin.col_kind"),
          dataIndex: "kind",
          key: "kind",
          inputType: "text",
          width: "12em",
          align: "left",
          sortable: true,
          render: (value: unknown) => (
            <Tag color={consentKindTagColor(value as string)}>
              {t(`consent.kind.${value as string}`)}
            </Tag>
          ),
        },
        {
          title: t("consent.admin.col_version"),
          dataIndex: "version",
          key: "version",
          inputType: "text",
          width: "8em",
          align: "center",
          sortable: true,
        },
        {
          title: t("consent.admin.col_title"),
          dataIndex: "title",
          key: "title",
        },
        {
          title: t("configuration.valid_from"),
          dataIndex: "valid_from",
          key: "valid_from",
          inputType: "date",
          width: "10em",
          align: "center",
          sortable: true,
          render: renderDate,
        },
        {
          title: t("configuration.valid_until"),
          dataIndex: "valid_until",
          key: "valid_until",
          inputType: "date",
          width: "10em",
          align: "center",
          sortable: true,
          render: renderDate,
        },
        {
          title: (
            <>
              {t("consent.admin.col_hash")}
              <ToolTipIcon title={t("tooltip.hash_consent_documents")} />
            </>
          ),
          dataIndex: "body_sha256",
          key: "body_sha256",
          width: "8em",
          align: "center",
          render: (value: unknown) =>
            value ? (
              <Text code style={{ fontSize: 11 }}>
                {(value as string).slice(0, 8)}…
              </Text>
            ) : (
              "—"
            ),
        },
        {
          title: "",
          dataIndex: "_actions",
          key: "_actions",
          width: "13em",
          align: "center",
          render: (_: unknown, record: TableRecord) => (
            <Space size="small">
              <Button
                type="primary"
                size="small"
                onClick={() =>
                  setModalState({
                    open: true,
                    mode: "view",
                    document: record as unknown as ConsentDocument,
                  })
                }
              >
                {t("consent.admin.view_body")}
              </Button>
              <Button
                size="small"
                icon={<DownloadOutlined />}
                onClick={() => downloadConsentPdf(record.id as string)}
                disabled={!record.id}
              >
                {t("consent.download")}
              </Button>
            </Space>
          ),
        },
      ] as EditableColumnConfig<TableRecord>[],
    [activeStatusColumn, renderDate, t],
  );

  return (
    <>
      <h1>{t("consent.admin.title")}</h1>
      <Paragraph type="secondary">{t("consent.admin.subtitle")}</Paragraph>

      <div style={{ marginBottom: 16 }}>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          disabled={!isOffice}
          onClick={() =>
            setModalState({ open: true, mode: "create", document: null })
          }
        >
          {t("consent.admin.new_version")}
        </Button>
      </div>

      <EditableTable
        columns={columns}
        apiFunctions={apiFunctions}
        focusIndex="version"
        initialData={data}
        loading={isLoading}
        onDeleteSuccess={onDeleteSuccess}
        permissions={permissions}
      />
      <DateRangeStatusLegend />

      <ExplainerText title={t("common.info")}>
        {t("explainers.configuration_consents")}
      </ExplainerText>

      <ConsentDocumentModal
        open={modalState.open}
        mode={modalState.mode}
        document={modalState.document}
        tenantLanguage={tenantLanguage}
        dateFormat={dateFormat}
        onClose={() =>
          setModalState({ open: false, mode: "create", document: null })
        }
      />
    </>
  );
}
