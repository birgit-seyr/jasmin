/**
 * SuperAdmin → Ops Checklist
 *
 * One table of recurring operational tasks (key rotations, restore
 * drills, OS upgrades, etc.). Each row shows: title, interval, when
 * it was last run, when the next run is due, an "overdue" badge, and
 * a "Mark done" button that POSTs a completion note.
 *
 * Backed by:
 *   GET   /api/super-admin/ops-checklist/
 *   POST  /api/super-admin/ops-checklist/<id>/mark-done/
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  Alert,
  Button,
  Form,
  Input,
  Modal,
  Space,
  Spin,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import {
  CheckCircleOutlined,
  CopyOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import axiosService from "@shared/services/api";
import { SUPER_ADMIN_ENDPOINTS } from "@features/platform/services/superAdmin";

// Kinds the backend's ``run-rotation`` endpoint will dispatch.
// Must stay in sync with ``DISPATCHABLE_KINDS`` in
// ``apps/shared/super_admin/services/rotation.py``.
// ``rotate_field_encryption`` is deliberately omitted — that one has
// its own chunked management command (re-encrypts every ciphertext
// row in every tenant) and isn't safe to fire from an HTTP request.
const ROTATION_KINDS = new Set<string>([
  "rotate_django_secret",
  "rotate_db_password",
  "rotate_bunny_token",
  "rotate_email_creds",
]);

interface RotationResult {
  kind: string;
  generated_secret: string | null;
  instructions: string;
  items_affected: number;
  extras: Record<string, string>;
}

const { Title, Paragraph, Text } = Typography;

interface OpsChecklistRun {
  id: number;
  completed_at: string;
  completed_by_email: string | null;
  notes: string;
}

interface OpsChecklistItem {
  id: number;
  kind: string;
  title: string;
  description: string;
  interval_days: number;
  is_active: boolean;
  created_at: string;
  last_run: OpsChecklistRun | null;
  next_due_at: string;
  is_overdue: boolean;
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "never";
  const d = new Date(iso);
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  return `${dd}.${mm}.${d.getFullYear()}`;
}

export default function SuperAdminOpsChecklist() {
  const queryClient = useQueryClient();
  const [activeItem, setActiveItem] = useState<OpsChecklistItem | null>(null);
  const [notes, setNotes] = useState("");
  // Separate state for the rotation flow — the result modal must NOT
  // share the mark-done modal's lifecycle, because a successful
  // rotation often leads into a "now mark it done" follow-up.
  const [rotatingItem, setRotatingItem] = useState<OpsChecklistItem | null>(
    null,
  );
  const [rotationResult, setRotationResult] = useState<RotationResult | null>(
    null,
  );
  const [rotating, setRotating] = useState(false);

  // The super-admin endpoints aren't part of the tenant-scoped orval
  // schema, so we hit them through ``axiosService`` directly while
  // letting TanStack Query own the fetch lifecycle.
  const itemsQuery = useQuery<OpsChecklistItem[]>({
    queryKey: ["super-admin", "ops-checklist"],
    queryFn: async () => {
      const res = await axiosService.get<OpsChecklistItem[]>(
        SUPER_ADMIN_ENDPOINTS.opsChecklist,
      );
      return res.data;
    },
  });

  // Memoize the `?? []` fallback so a fresh empty array each render doesn't
  // churn the overdueCount / sortedItems memos below.
  const items = useMemo(() => itemsQuery.data ?? [], [itemsQuery.data]);
  const loading = itemsQuery.isPending;
  const error = itemsQuery.isError
    ? itemsQuery.error instanceof Error
      ? itemsQuery.error.message
      : "Failed to load checklist."
    : null;

  const overdueCount = useMemo(
    () => items.filter((i) => i.is_overdue).length,
    [items],
  );

  const sortedItems = useMemo(
    () =>
      [...items].sort(
        (a, b) =>
          new Date(a.next_due_at).getTime() -
          new Date(b.next_due_at).getTime(),
      ),
    [items],
  );

  const handleRunRotation = async (item: OpsChecklistItem) => {
    setRotatingItem(item);
    setRotationResult(null);
    setRotating(true);
    try {
      const res = await axiosService.post<RotationResult>(
        SUPER_ADMIN_ENDPOINTS.opsChecklistRunRotation(item.id),
        {},
      );
      setRotationResult(res.data);
    } catch (err) {
      message.error(
        err instanceof Error ? err.message : "Failed to run rotation.",
      );
      setRotatingItem(null);
    } finally {
      setRotating(false);
    }
  };

  const handleCopySecret = async () => {
    if (!rotationResult?.generated_secret) return;
    try {
      await navigator.clipboard.writeText(rotationResult.generated_secret);
      message.success("Secret copied to clipboard.");
    } catch {
      message.error(
        "Couldn't write to clipboard. Select the text and copy manually.",
      );
    }
  };

  const markDoneMutation = useMutation({
    mutationFn: async (item: OpsChecklistItem) => {
      await axiosService.post<OpsChecklistItem>(
        SUPER_ADMIN_ENDPOINTS.opsChecklistMarkDone(item.id),
        { notes },
      );
    },
    onSuccess: (_data, item) => {
      // Invalidate so the table reloads with the new last_run +
      // next_due_at instead of hand-patching a single row.
      void queryClient.invalidateQueries({
        queryKey: ["super-admin", "ops-checklist"],
      });
      message.success(`Marked "${item.title}" as done.`);
      setActiveItem(null);
      setNotes("");
    },
    onError: (err) => {
      message.error(
        err instanceof Error ? err.message : "Failed to mark item done.",
      );
    },
  });

  const handleMarkDone = () => {
    if (!activeItem) return;
    markDoneMutation.mutate(activeItem);
  };

  const submitting = markDoneMutation.isPending;

  const columns = [
    {
      title: "Task",
      key: "title",
      render: (_: unknown, row: OpsChecklistItem) => (
        <div>
          <Text strong>{row.title}</Text>
          {row.description && (
            <Paragraph
              type="secondary"
              style={{ marginBottom: 0, fontSize: 12, whiteSpace: "pre-wrap" }}
            >
              {row.description}
            </Paragraph>
          )}
        </div>
      ),
    },
    {
      title: "Interval",
      key: "interval",
      width: 110,
      render: (_: unknown, row: OpsChecklistItem) =>
        `every ${row.interval_days} d`,
    },
    {
      title: "Last run",
      key: "last_run",
      width: 200,
      render: (_: unknown, row: OpsChecklistItem) => {
        if (!row.last_run) return <Text type="secondary">never</Text>;
        const who = row.last_run.completed_by_email ?? "?";
        return (
          <Tooltip
            title={
              row.last_run.notes ? (
                <span style={{ whiteSpace: "pre-wrap" }}>
                  {row.last_run.notes}
                </span>
              ) : (
                "(no notes)"
              )
            }
          >
            <span>
              {formatDate(row.last_run.completed_at)} <Text type="secondary">— {who}</Text>
            </span>
          </Tooltip>
        );
      },
    },
    {
      title: "Next due",
      key: "next_due",
      width: 160,
      render: (_: unknown, row: OpsChecklistItem) => (
        <Space>
          <span>{formatDate(row.next_due_at)}</span>
          {row.is_overdue && <Tag color="red">overdue</Tag>}
        </Space>
      ),
    },
    {
      title: "",
      key: "action",
      width: 240,
      render: (_: unknown, row: OpsChecklistItem) => (
        <Space>
          {ROTATION_KINDS.has(row.kind) && (
            <Tooltip
              title={
                "Generate the new secret / runbook for this rotation. " +
                "Doesn't mark the task done — you'll do that after applying."
              }
            >
              <Button
                size="small"
                icon={<ThunderboltOutlined />}
                onClick={() => handleRunRotation(row)}
                loading={rotating && rotatingItem?.id === row.id}
              >
                Run rotation
              </Button>
            </Tooltip>
          )}
          <Button
            type="primary"
            size="small"
            icon={<CheckCircleOutlined />}
            onClick={() => {
              setActiveItem(row);
              setNotes("");
            }}
          >
            Mark done
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: "24px 32px" }}>
      <div style={{ marginBottom: 16 }}>
        <Title level={2} style={{ marginBottom: 4 }}>
          Operational checklist
        </Title>
        <Text type="secondary">
          Recurring platform-ops tasks (key rotations, restore drills, OS
          upgrades). Weekly digest of overdue items goes to{" "}
          <code>settings.ADMINS</code> via the Huey scheduler.
        </Text>
      </div>

      {error && (
        <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />
      )}

      {overdueCount > 0 && (
        <Alert
          type="warning"
          showIcon
          message={`${overdueCount} task(s) overdue`}
          style={{ marginBottom: 16 }}
        />
      )}

      {loading ? (
        <Spin size="large" />
      ) : (
        <Table<OpsChecklistItem>
          rowKey="id"
          dataSource={sortedItems}
          columns={columns}
          pagination={false}
          size="small"
        />
      )}

      <Modal
        open={rotatingItem != null}
        title={`Rotation: ${rotatingItem?.title ?? ""}`}
        onCancel={() => {
          setRotatingItem(null);
          setRotationResult(null);
        }}
        onOk={() => {
          // After acknowledging, drop the result from React state so
          // the secret doesn't linger in the in-memory store any
          // longer than necessary.
          setRotatingItem(null);
          setRotationResult(null);
        }}
        okText="Done — close"
        cancelButtonProps={{ style: { display: "none" } }}
        width={720}
      >
        {rotating && <Spin />}
        {rotationResult && (
          <>
            {rotationResult.generated_secret && (
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 16 }}
                message="Save this secret now — it won't be shown again"
                description={
                  <>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      We don't store the new value anywhere on the
                      platform; we just generated it. Copy it into
                      your password manager / .env file BEFORE you
                      close this modal.
                    </Text>
                    <div
                      style={{
                        marginTop: 8,
                        padding: 12,
                        background: "var(--color-bg-subtle)",
                        border: "1px solid #d9d9d9",
                        borderRadius: 4,
                        fontFamily: "monospace",
                        fontSize: 13,
                        wordBreak: "break-all",
                      }}
                    >
                      {rotationResult.generated_secret}
                    </div>
                    <Button
                      size="small"
                      icon={<CopyOutlined />}
                      onClick={handleCopySecret}
                      style={{ marginTop: 8 }}
                    >
                      Copy to clipboard
                    </Button>
                  </>
                }
              />
            )}
            {rotationResult.items_affected > 0 && (
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 16 }}
                message={`${rotationResult.items_affected} record(s) modified.`}
              />
            )}
            <Paragraph strong>Next steps</Paragraph>
            <Paragraph
              style={{
                whiteSpace: "pre-wrap",
                fontFamily: "monospace",
                fontSize: 12,
                padding: 12,
                background: "var(--color-bg-elevated)",
                border: "1px solid #f0f0f0",
                borderRadius: 4,
              }}
            >
              {rotationResult.instructions}
            </Paragraph>
          </>
        )}
      </Modal>

      <Modal
        open={activeItem != null}
        title={`Mark done: ${activeItem?.title ?? ""}`}
        onCancel={() => {
          if (submitting) return;
          setActiveItem(null);
          setNotes("");
        }}
        onOk={handleMarkDone}
        confirmLoading={submitting}
        okText="Record completion"
      >
        <Paragraph type="secondary">
          Records this task as completed now, with you as the actor.
          Notes are kept forever as the audit trail — be specific about
          what changed.
        </Paragraph>
        <Form layout="vertical">
          <Form.Item label="Notes (optional)">
            <Input.TextArea
              rows={4}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="What was rotated / restored / upgraded? Any drift to flag?"
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
