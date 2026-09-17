import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";
import {
  Alert,
  Button,
  Card,
  Flex,
  Space,
  Spin,
  Table,
  Tag,
  Upload,
} from "antd";
import { InboxOutlined } from "@ant-design/icons";
import type { UploadFile } from "antd/es/upload/interface";

import { WeekSelector } from "@shared/selectors";
import { ExplainerText } from "@shared/ui";
import { ExternalCodeMappingsModal } from "@features/commissioning/modals";
import { useTenant } from "@hooks/index";
import {
  commissioningShareImportBatchesApplyCreate,
  commissioningShareImportBatchesPreviewCreate,
  commissioningShareImportBatchesUploadCreate,
  getCommissioningShareImportBatchesListQueryKey,
  useCommissioningShareImportBatchesList,
} from "@shared/api/generated/commissioning/commissioning";
import type { ShareImportUpload } from "@shared/api/generated/models";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";

type ImportBatchStatus =
  | "uploaded"
  | "validated"
  | "preview_ready"
  | "applied"
  | "failed"
  | "superseded";

interface DiffRow {
  variation_id: string;
  delivery_station_day_id: string;
  quantity?: number;
  old_quantity?: number;
  new_quantity?: number;
}

interface DiffReport {
  added?: DiffRow[];
  updated?: DiffRow[];
  removed?: DiffRow[];
  totals?: { added: number; updated: number; removed: number };
}

interface ShareImportBatch {
  id: string;
  original_filename: string | null;
  year: number;
  delivery_week: number;
  status: ImportBatchStatus;
  row_count: number;
  error_count: number;
  validation_report: Record<string, string[]>;
  diff_report: DiffReport;
  created_at: string;
  applied_at: string | null;
}

const STATUS_COLOR: Record<ImportBatchStatus, string> = {
  uploaded: "default",
  validated: "blue",
  preview_ready: "geekblue",
  applied: "green",
  failed: "red",
  superseded: "default",
};

/**
 * The batch a validation-failed 400 carries: apply nests it under `batch`,
 * preview returns its fields at the top level. Anything else — a network blip,
 * a coded refusal with no batch — yields null, so the batch already on screen
 * stays put.
 */
function failedBatchFromError(err: unknown): ShareImportBatch | null {
  const body = (err as { response?: { data?: unknown } })?.response?.data;
  if (!body || typeof body !== "object") return null;
  const nested = (body as { batch?: unknown }).batch;
  const candidate = nested && typeof nested === "object" ? nested : body;
  const { id, validation_report: report } = candidate as {
    id?: unknown;
    validation_report?: unknown;
  };
  if (typeof id !== "string" || typeof report !== "object" || report === null) {
    return null;
  }
  return candidate as ShareImportBatch;
}

export default function ImportShares() {
  const { t } = useTranslation();
  const { getSetting } = useTenant();

  const now = dayjs();
  const [selectedYear, setSelectedYear] = useState<number>(now.isoWeekYear());
  const [selectedWeek, setSelectedWeek] = useState<number | null>(
    now.isoWeek(),
  );

  const csvFormat = (getSetting("csv_format", "de") as string).toLowerCase();

  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [activeBatch, setActiveBatch] = useState<ShareImportBatch | null>(null);
  const [busy, setBusy] = useState(false);
  const [mappingsOpen, setMappingsOpen] = useState(false);

  // React Query — failures route through the global queryCache.onError
  // toast. Writes call `fetchBatches()` to invalidate and refetch.
  const queryClient = useQueryClient();
  const { data: rawBatches, isFetching: loading } =
    useCommissioningShareImportBatchesList();
  const batches = useMemo<ShareImportBatch[]>(
    () => (rawBatches ?? []) as unknown as ShareImportBatch[],
    [rawBatches],
  );
  const fetchBatches = useCallback(async () => {
    await queryClient.invalidateQueries({
      queryKey: getCommissioningShareImportBatchesListQueryKey(),
    });
  }, [queryClient]);

  const handleUpload = async () => {
    if (!selectedWeek) {
      notify.error(t("import_shares.select_week"));
      return;
    }
    if (fileList.length === 0) {
      notify.error(t("import_shares.no_file"));
      return;
    }
    setBusy(true);
    try {
      const data = await commissioningShareImportBatchesUploadCreate({
        // The generated client appends each field to FormData; `file` is
        // typed as `string` in the spec but FormData.append accepts a Blob.
        file: fileList[0].originFileObj as unknown as string,
        year: selectedYear,
        delivery_week: selectedWeek,
      } as ShareImportUpload);
      setActiveBatch(data as unknown as ShareImportBatch);
      setFileList([]);
      await fetchBatches();
      notify.success(
        t("import_shares.uploaded", {
          status: (data as unknown as ShareImportBatch).status,
        }),
      );
    } catch (err: unknown) {
      // Routed through the shared extractor so a coded refusal — a file whose
      // batch already decided this week, say — reaches the office as its
      // localized text rather than a generic "upload failed".
      notify.error(getErrorMessage(err, t("import_shares.upload_failed")));
    } finally {
      setBusy(false);
    }
  };

  const runAction = async (batchId: string, action: "preview" | "apply") => {
    setBusy(true);
    try {
      const data =
        action === "preview"
          ? await commissioningShareImportBatchesPreviewCreate(batchId)
          : await commissioningShareImportBatchesApplyCreate(batchId);
      setActiveBatch(data as unknown as ShareImportBatch);
      await fetchBatches();
      notify.success(
        `${action}: ${(data as unknown as ShareImportBatch).status}`,
      );
    } catch (err: unknown) {
      // A validation failure answers 400 with the batch that failed. Showing
      // it keeps the per-row report in step with the file just rejected; the
      // batch from the last successful action would otherwise stay on screen.
      // The backend persists that failure before answering, so the history
      // list is refreshed too — its cached row would otherwise keep the
      // pre-failure status, and re-selecting it would swap the report on
      // screen for the stale row's empty one.
      const failedBatch = failedBatchFromError(err);
      if (failedBatch) {
        setActiveBatch(failedBatch);
        await fetchBatches();
      }
      notify.error(getErrorMessage(err, t("import_shares.action_failed")));
    } finally {
      setBusy(false);
    }
  };

  const errorRows = useMemo(() => {
    if (!activeBatch) return [];
    return Object.entries(activeBatch.validation_report || {}).map(
      ([row, errs]) => ({ key: row, row, errors: errs.join("; ") }),
    );
  }, [activeBatch]);

  const diffSection = (title: string, rows: DiffRow[] | undefined) => {
    if (!rows || rows.length === 0) return null;
    const cols = [
      {
        title: t("import_shares.columns.variation"),
        dataIndex: "variation_id",
      },
      {
        title: t("import_shares.columns.station_day"),
        dataIndex: "delivery_station_day_id",
      },
      ...(rows[0].quantity !== undefined
        ? [
            {
              title: t("import_shares.columns.qty"),
              dataIndex: "quantity",
            },
          ]
        : []),
      ...(rows[0].old_quantity !== undefined
        ? [
            {
              title: t("import_shares.columns.old"),
              dataIndex: "old_quantity",
            },
            {
              title: t("import_shares.columns.new"),
              dataIndex: "new_quantity",
            },
          ]
        : []),
    ];
    return (
      <Card
        size="small"
        title={`${title} (${rows.length})`}
        style={{ marginTop: 12 }}
      >
        <Table
          size="small"
          className="custom-jasmin-table"
          rowKey={(r) => `${r.variation_id}|${r.delivery_station_day_id}`}
          columns={cols}
          dataSource={rows}
          pagination={{ pageSize: 10 }}
        />
      </Card>
    );
  };

  return (
    <div>
      <div>
        <h1>{t("import_shares.title")}</h1>

        <WeekSelector
          selectedYear={selectedYear}
          setSelectedYear={setSelectedYear}
          selectedWeek={selectedWeek}
          setSelectedWeek={setSelectedWeek}
        />
      </div>

      <Upload.Dragger
        accept=".csv,text/csv"
        beforeUpload={(file) => {
          setFileList([
            { uid: file.uid, name: file.name, originFileObj: file },
          ]);
          return false; // prevent auto-upload
        }}
        fileList={fileList}
        onRemove={() => setFileList([])}
        maxCount={1}
        style={{ width: "30%", marginTop: 16 }}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">{t("import_shares.drop_hint")}</p>
      </Upload.Dragger>

      <Button
        type="primary"
        loading={busy}
        onClick={handleUpload}
        style={{ marginTop: 12 }}
        disabled={fileList.length === 0 || !selectedWeek}
      >
        {t("import_shares.upload_btn")}
      </Button>

      {activeBatch && (
        <Card
          title={
            <Space>
              {t("import_shares.batch")} {activeBatch.id}
              <Tag color={STATUS_COLOR[activeBatch.status]}>
                {t(
                  `import_shares.status.${activeBatch.status}`,
                  activeBatch.status,
                )}
              </Tag>
            </Space>
          }
          style={{ marginTop: 16 }}
          extra={
            <Space>
              <Button
                onClick={() => runAction(activeBatch.id, "preview")}
                disabled={
                  activeBatch.status === "applied" ||
                  activeBatch.status === "superseded"
                }
                loading={busy}
              >
                {t("import_shares.preview_btn")}
              </Button>
              <Button
                type="primary"
                danger
                onClick={() => runAction(activeBatch.id, "apply")}
                // An applied or superseded batch is refused by the backend —
                // the same statuses that grey out Preview.
                disabled={
                  activeBatch.status === "applied" ||
                  activeBatch.status === "superseded" ||
                  activeBatch.error_count > 0
                }
                loading={busy}
              >
                {t("import_shares.apply_btn")}
              </Button>
            </Space>
          }
        >
          {activeBatch.error_count > 0 && (
            <Alert
              type="error"
              showIcon
              message={t("import_shares.has_errors", {
                n: activeBatch.error_count,
              })}
              style={{ marginBottom: 12 }}
            />
          )}

          {errorRows.length > 0 && (
            <Card size="small" title={t("import_shares.errors")}>
              <Table
                size="small"
                className="custom-jasmin-table"
                rowKey="row"
                columns={[
                  {
                    title: t("import_shares.columns.row"),
                    dataIndex: "row",
                    width: 80,
                  },
                  {
                    title: t("import_shares.columns.errors"),
                    dataIndex: "errors",
                  },
                ]}
                dataSource={errorRows}
                pagination={{ pageSize: 10 }}
              />
            </Card>
          )}

          {activeBatch.diff_report?.totals && (
            <Alert
              type="info"
              showIcon
              message={t("import_shares.diff_summary", {
                a: activeBatch.diff_report.totals.added,
                u: activeBatch.diff_report.totals.updated,
                r: activeBatch.diff_report.totals.removed,
              })}
              style={{ marginTop: 12 }}
            />
          )}
          {diffSection(
            t("import_shares.added"),
            activeBatch.diff_report?.added,
          )}
          {diffSection(
            t("import_shares.updated"),
            activeBatch.diff_report?.updated,
          )}
          {diffSection(
            t("import_shares.removed"),
            activeBatch.diff_report?.removed,
          )}
        </Card>
      )}

      <Card title={t("import_shares.history")} style={{ marginTop: 16 }}>
        <Spin spinning={loading}>
          <Table
            size="small"
            className="custom-jasmin-table"
            rowKey="id"
            dataSource={batches}
            onRow={(record) => ({
              onClick: () => setActiveBatch(record),
              style: { cursor: "pointer" },
            })}
            columns={[
              {
                title: t("import_shares.columns.year"),
                dataIndex: "year",
                width: 80,
              },
              {
                title: t("import_shares.columns.week"),
                dataIndex: "delivery_week",
                width: 80,
              },
              {
                title: t("import_shares.columns.status"),
                dataIndex: "status",
                width: 130,
                render: (s: ImportBatchStatus) => (
                  <Tag color={STATUS_COLOR[s]}>
                    {t(`import_shares.status.${s}`)}
                  </Tag>
                ),
              },
              {
                title: t("import_shares.columns.rows"),
                dataIndex: "row_count",
                width: 80,
              },
              {
                title: t("import_shares.columns.errors_count"),
                dataIndex: "error_count",
                width: 80,
              },
              {
                title: t("import_shares.columns.file"),
                dataIndex: "original_filename",
              },
              {
                title: t("import_shares.columns.created"),
                dataIndex: "created_at",
                render: (v: string) => new Date(v).toLocaleString(),
              },
            ]}
          />
        </Spin>
      </Card>

      <ExplainerText maxWidth="75%">
        <Flex vertical gap="1em">
          <div>
            <strong>{t("import_shares.explainer.reimport_heading")}</strong>
            <div>{t("import_shares.explainer.reimport_body")}</div>
          </div>

          <div>
            <strong>{t("import_shares.explainer.csv_heading")}</strong>
            <div style={{ marginTop: 4 }}>
              {t("import_shares.explainer.csv_intro")}
            </div>
            <div style={{ marginTop: 4 }}>
              <strong>
                {t("import_shares.explainer.tenant_csv_format_label")}:
              </strong>{" "}
              {csvFormat === "en"
                ? t("import_shares.explainer.tenant_csv_format_en")
                : t("import_shares.explainer.tenant_csv_format_de")}
            </div>
            <div style={{ marginTop: 4 }}>
              <strong>{t("import_shares.explainer.csv_required")}:</strong>{" "}
              <code>year</code>, <code>delivery_week</code>,{" "}
              <code>delivery_station_code</code>, <code>delivery_day_code</code>
              , <code>variation_code</code>, <code>quantity</code>
            </div>
            <div style={{ marginTop: 4 }}>
              <strong>{t("import_shares.explainer.csv_optional")}:</strong>{" "}
              <code>external_ref</code>, <code>note</code>
            </div>
            <div style={{ marginTop: 8, fontWeight: 500 }}>
              {t("import_shares.explainer.csv_example")}:
            </div>
            <pre
              style={{
                background: "var(--color-bg-subtle)",
                padding: 8,
                marginTop: 4,
                marginBottom: 8,
                fontSize: 12,
                overflowX: "auto",
              }}
            >
              {`year,delivery_week,delivery_station_code,delivery_day_code,variation_code,quantity
${selectedYear},${selectedWeek ?? 14},STN-001,WED,VEG-S,12
${selectedYear},${selectedWeek ?? 14},STN-001,WED,VEG-M,18
${selectedYear},${selectedWeek ?? 14},STN-002,THU,VEG-L,7`}
            </pre>
            <div>
              {t("import_shares.explainer.csv_codes_hint")}
              {/* A real <button> (not an href-less <a>) so it's keyboard-
                  activable; type="link" + zero padding keeps it inline in text. */}
              <Button
                type="link"
                onClick={() => setMappingsOpen(true)}
                style={{ padding: 0, height: "auto" }}
              >
                {t("import_shares.explainer.csv_codes_link")}
              </Button>
              {t("import_shares.explainer.csv_codes_hint_end")}
            </div>
          </div>
        </Flex>
      </ExplainerText>

      <ExternalCodeMappingsModal
        open={mappingsOpen}
        onClose={() => setMappingsOpen(false)}
      />
    </div>
  );
}
