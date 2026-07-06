import { useCurrency, useDateFormat, useTimeFormat } from "@hooks/index";
import type { BillingRun } from "@shared/api/generated/models";
import {
  getPaymentsBillingRunsListQueryKey,
  paymentsBillingRunsDestroy,
  paymentsBillingRunsExportCreate,
  usePaymentsBillingRunsList,
} from "@shared/api/generated/payments-—-billing-runs/payments-—-billing-runs";
import { YearSelector } from "@shared/selectors";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import { CreateBillingRunModal } from "@features/abos/modals/CreateBillingRunModal";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Flex, Popconfirm, Space, Table, Tag } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

const STATUS_COLOR: Record<string, string> = {
  DRAFT: "blue",
  EXPORTED: "green",
  CANCELLED: "default",
};

export default function DebitsAbos() {
  const { t } = useTranslation();
  const { formatDateTimeWithFallback } = useTimeFormat();
  const { formatDateWithFallback } = useDateFormat();
  const { formatCurrency } = useCurrency();
  const [createOpen, setCreateOpen] = useState(false);
  const [selectedYear, setSelectedYear] = useState<number>(dayjs().year());
  const queryClient = useQueryClient();

  // Filtered server-side by the period's year (period_start year).
  const {
    data: runsData,
    isFetching,
    error,
  } = usePaymentsBillingRunsList({
    year: selectedYear,
  });

  const runs = useMemo(
    () =>
      [...(runsData ?? [])].sort((a, b) =>
        (b.created_at ?? "").localeCompare(a.created_at ?? ""),
      ),
    [runsData],
  );

  useEffect(() => {
    if (error) {
      console.error(error);
      notify.error(t("abos.debits_load_error"));
    }
  }, [error, t]);

  const invalidateRuns = useCallback(
    () =>
      // No params → invalidates every year-filtered variant of the list (a
      // newly-created run may belong to a different year than the active filter).
      queryClient.invalidateQueries({
        queryKey: getPaymentsBillingRunsListQueryKey(),
      }),
    [queryClient],
  );

  const handleExport = async (run: BillingRun) => {
    if (!run.id) return;
    try {
      await paymentsBillingRunsExportCreate(run.id);
      notify.success(t("abos.debits_run_exported"));
      await invalidateRuns();
    } catch (err: unknown) {
      console.error(err);
      // Surface the backend's specific reason (e.g. "tenant IBAN missing") —
      // getErrorMessage reads the Jasmin ``{code, message}`` body; the i18n key
      // is only the fallback when the error carries no message.
      notify.error(getErrorMessage(err, t("abos.debits_run_export_error")));
    }
  };

  const handleDelete = async (run: BillingRun) => {
    if (!run.id) return;
    try {
      await paymentsBillingRunsDestroy(run.id);
      notify.success(t("abos.debits_run_deleted"));
      await invalidateRuns();
    } catch (err) {
      console.error(err);
      notify.error(t("abos.debits_run_delete_error"));
    }
  };

  const columns = [
    {
      title: t("abos.debits_col_month"),
      key: "month",
      render: (_: unknown, r: BillingRun) =>
        r.period_start
          ? `${t(`common.months.${dayjs(r.period_start).month() + 1}`)} ${dayjs(r.period_start).year()}`
          : "—",
    },

    {
      title: t("abos.debits_col_period"),
      key: "period",
      render: (_: unknown, r: BillingRun) =>
        `${formatDateWithFallback(r.period_start, "—")} → ${formatDateWithFallback(r.period_end, "—")}`,
    },
    {
      title: t("abos.debits_col_collection_date"),
      dataIndex: "collection_date",
      key: "collection_date",
      render: (v?: string) => formatDateWithFallback(v, "—"),
    },
    {
      title: t("abos.debits_col_status"),
      dataIndex: "status",
      key: "status",
      render: (s?: string) =>
        s ? (
          <Tag color={STATUS_COLOR[s] ?? "default"}>
            {t(`abos.run_status.${s}`)}
          </Tag>
        ) : null,
    },
    {
      title: t("abos.debits_col_charges"),
      dataIndex: "charge_count",
      key: "charge_count",
      align: "right" as const,
    },
    {
      title: t("abos.debits_col_total"),
      dataIndex: "total_amount",
      key: "total_amount",
      align: "right" as const,
      render: (v?: string) => (v ? formatCurrency(Number(v)) : "—"),
    },
    {
      title: t("abos.debits_col_files"),
      key: "files",
      render: (_: unknown, r: BillingRun) =>
        // The export artifact is now a pain.008.001.02 SEPA XML file
        // that the office uploads directly to their bank's portal.
        // ``r.sepa_xml_export_url`` is the FileField download URL on
        // the BillingRun row (see BillingRunSerializer).
        r.sepa_xml_export_url ? (
          <a
            href={r.sepa_xml_export_url}
            target="_blank"
            rel="noopener noreferrer"
            // Keep the backend's ``billing_run_<id>`` base but append the run's
            // billing month (YYYY-MM — filesystem-safe, sortable) so downloaded
            // files are self-describing. ``download`` is honoured for the
            // same-origin /media URL.
            download={`billing_run_${r.id}_${dayjs(r.period_start).format("YYYY-MM")}.xml`}
          >
            pain.008 XML
          </a>
        ) : (
          <span style={{ color: "#aaa" }}>pain.008 XML</span>
        ),
    },
    {
      title: t("abos.debits_col_created_at"),
      dataIndex: "created_at",
      key: "created_at",
      render: (v?: string) => formatDateTimeWithFallback(v, "—"),
    },
    {
      title: t("abos.debits_col_actions"),
      key: "actions",
      render: (_: unknown, r: BillingRun) => (
        <Space>
          {r.status === "DRAFT" && (
            <Popconfirm
              title={t("abos.debits_export_confirm")}
              onConfirm={() => handleExport(r)}
              okText={t("common.yes")}
              cancelText={t("common.no")}
            >
              <Button type="primary" size="small">
                {t("abos.debits_export")}
              </Button>
            </Popconfirm>
          )}
          {r.status === "DRAFT" && (
            <Popconfirm
              title={t("abos.debits_delete_confirm")}
              onConfirm={() => handleDelete(r)}
              okText={t("common.yes")}
              cancelText={t("common.no")}
            >
              <Button danger size="small">
                {t("common.delete")}
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Flex justify="space-between" align="center" gap="small">
        <h1>{t("abos.debits")}</h1>
        <Button type="primary" onClick={() => setCreateOpen(true)}>
          {t("abos.debits_create_run")}
        </Button>
      </Flex>

      <div style={{ margin: "16px 0" }}>
        <YearSelector
          selectedYear={selectedYear}
          setSelectedYear={setSelectedYear}
        />
      </div>

      <Table
        rowKey="id"
        loading={isFetching}
        dataSource={runs}
        columns={columns}
        pagination={false}
        size="small"
        className="custom-jasmin-table"
      />

      <CreateBillingRunModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={invalidateRuns}
      />
    </div>
  );
}
