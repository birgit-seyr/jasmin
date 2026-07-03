import {
  CheckCircleFilled,
  CloseCircleFilled,
  LoadingOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Drawer,
  Progress,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from "antd";
import type { FC, ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useJob } from "@hooks/useJob";

const { Title, Paragraph, Text } = Typography;

interface PerItemResult {
  success: boolean;
  reseller_id?: string;
  reseller_name?: string;
  order_id?: string;
  invoice_number?: string;
  already_sent?: boolean;
  error?: string;
}

interface ProgressShape {
  processed?: number;
  successful?: number;
  failed?: number;
  total?: number;
}

interface JobProgressDrawerProps {
  /** Job to poll. ``null`` → drawer is closed. */
  jobId: string | null;
  /** Optional explicit close trigger; falls back to the drawer's own X. */
  onClose: () => void;
  /**
   * Overrides the drawer title. Defaults to the job kind translated
   * via ``job_progress.kind.<kind>`` (e.g.
   * ``job_progress.kind.offer.bulk_send``).
   */
  title?: ReactNode;
}

/**
 * Generic polling drawer for any ``BackgroundJob``. Shows a progress
 * bar in flight and a per-item result table once the worker writes
 * the final result blob.
 *
 * Designed to be kind-agnostic — the drawer reads ``result.results``
 * and renders a small set of columns it knows how to format
 * (reseller name, invoice number, success / error). When a new kind
 * lands and needs different columns, extend the table render block
 * in this file rather than forking the drawer.
 */
export const JobProgressDrawer: FC<JobProgressDrawerProps> = ({
  jobId,
  onClose,
  title,
}) => {
  const { t } = useTranslation();
  const { data: job, isLoading } = useJob(jobId);

  const progress: ProgressShape = (job?.progress ?? {}) as ProgressShape;
  const result = (job?.result ?? {}) as {
    total_processed?: number;
    successful?: number;
    failed?: number;
    results?: PerItemResult[];
  };

  const percent =
    progress.total && progress.total > 0
      ? Math.round(((progress.processed ?? 0) / progress.total) * 100)
      : job?.status === "done"
        ? 100
        : 0;

  const statusTag = (() => {
    if (!job) return null;
    if (job.status === "queued")
      return <Tag>{t("job_progress.queued")}</Tag>;
    if (job.status === "running")
      return (
        <Tag color="processing" icon={<LoadingOutlined />}>
          {t("job_progress.running")}
        </Tag>
      );
    if (job.status === "done")
      return (
        <Tag color="success" icon={<CheckCircleFilled />}>
          {t("job_progress.done")}
        </Tag>
      );
    return (
      <Tag color="error" icon={<CloseCircleFilled />}>
        {t("job_progress.failed")}
      </Tag>
    );
  })();

  return (
    <Drawer
      open={!!jobId}
      onClose={onClose}
      width={640}
      destroyOnHidden
      title={
        <Space>
          {title ??
            t("job_progress.title")}
          {statusTag}
        </Space>
      }
      footer={
        job?.status === "done" || job?.status === "failed" ? (
          <Button onClick={onClose}>
            {t("common.close")}
          </Button>
        ) : null
      }
    >
      {isLoading || !job ? (
        <Spin />
      ) : (
        <Space direction="vertical" size="middle" className="w-full">
          <Progress
            percent={percent}
            status={
              job.status === "failed"
                ? "exception"
                : job.status === "done"
                  ? "success"
                  : "active"
            }
          />

          <div role="status" aria-live="polite" aria-atomic="true">
            <Paragraph type="secondary" style={{ marginBottom: 0 }}>
              {t(
                "job_progress.counters",
                {
                  processed: progress.processed ?? result.successful ?? 0,
                  total: progress.total ?? result.total_processed ?? 0,
                  successful: progress.successful ?? result.successful ?? 0,
                  failed: progress.failed ?? result.failed ?? 0,
                },
              )}
            </Paragraph>
          </div>

          {/* Assertive completion announcement: AntD's <Progress> and the
              failure <Alert> already carry live semantics, but the SUCCESS
              ("done") case and a failure WITHOUT job.error have none. A
              visually-hidden assertive region fills both gaps. */}
          {(job.status === "done" || job.status === "failed") && (
            <span className="sr-only" role="alert">
              {job.status === "done"
                ? t("job_progress.announce_done")
                : t("job_progress.announce_failed")}
            </span>
          )}

          {job.status === "failed" && job.error && (
            <Alert
              type="error"
              showIcon
              message={t("job_progress.failed")}
              description={job.error}
            />
          )}

          {job.status === "done" && result.results && result.results.length > 0 && (
            <>
              <Title level={5} style={{ marginBottom: 0 }}>
                {t("job_progress.per_item_results")}
              </Title>
              <Table<PerItemResult>
                size="small"
                rowKey={(row, idx) =>
                  row.reseller_id ?? row.order_id ?? String(idx ?? 0)
                }
                pagination={false}
                dataSource={result.results}
                columns={[
                  {
                    title: t("job_progress.col_target"),
                    render: (_v, row) =>
                      row.reseller_name ??
                      row.invoice_number ??
                      row.order_id ??
                      "—",
                  },
                  {
                    title: t("job_progress.col_outcome"),
                    width: 140,
                    render: (_v, row) => {
                      if (row.already_sent) {
                        return (
                          <Tag color="default">
                            {t("job_progress.already_sent")}
                          </Tag>
                        );
                      }
                      if (row.success) {
                        return (
                          <Tag
                            color="success"
                            icon={<CheckCircleFilled />}
                          >
                            {t("job_progress.success")}
                          </Tag>
                        );
                      }
                      return (
                        <Tag color="error" icon={<CloseCircleFilled />}>
                          {t("job_progress.failure")}
                        </Tag>
                      );
                    },
                  },
                  {
                    title: t("job_progress.col_detail"),
                    render: (_v, row) =>
                      row.error ? <Text type="danger">{row.error}</Text> : null,
                  },
                ]}
              />
            </>
          )}
        </Space>
      )}
    </Drawer>
  );
};
