import {
  DownloadOutlined,
  EyeOutlined,
  FileTextOutlined,
} from "@ant-design/icons";
import { Alert, Button, Card, Modal, Space, Typography } from "antd";
import ModalCloseFooter from "@shared/modals/ModalCloseFooter";
import dayjs from "dayjs";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useGdprProcessingActivitiesRetrieve } from "@shared/api/generated/gdpr/gdpr";
import { useTenant } from "@hooks/index";
import { downloadBlob, notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";

const { Paragraph, Text } = Typography;

/**
 * Art. 30 Record-of-Processing-Activities (VVT) export.
 *
 * The auditor question "show me your VVT for tenant X" is now
 * answered by clicking a button here instead of attaching a Word
 * doc. Two affordances:
 *
 *   - **View** — opens the JSON in a modal, pretty-printed. Useful
 *     for a quick look without leaving the office UI.
 *   - **Download** — saves ``vvt-<schema>-<YYYY-MM-DD>.json`` to
 *     disk. The filename embeds the tenant schema and the date so
 *     the auditor's bundle stays unambiguous when they review
 *     several Solawis on the same day.
 *
 * Backend: ``GET /api/gdpr/processing-activities/`` (IsAdmin-gated).
 * The codebase facts come from ``apps/gdpr/vvt.py``; the
 * controller block is overlaid from the live ``Tenant`` row on
 * each request.
 *
 * Fetched LAZILY: ``query.enabled`` is gated on the office actually
 * pressing one of the buttons. We don't want a JSON-of-the-VVT
 * fetched on every render of the GDPR page when 95% of visits are
 * about pending-deletion review, not VVT exports.
 */
export default function VVTExportCard() {
  const { t } = useTranslation();
  const { tenant } = useTenant();
  const [requested, setRequested] = useState<"view" | "download" | null>(null);
  const [viewerOpen, setViewerOpen] = useState(false);

  const { data, isFetching, isError, error } =
    useGdprProcessingActivitiesRetrieve({
      query: {
        enabled: requested !== null,
        // The endpoint is cheap to compute (static + one tenant
        // row read) but the response can grow with new activities.
        // Keep it fresh-ish so a tenant edit on the controller
        // block (when we ship the PUT) shows up quickly.
        staleTime: 60_000,
      },
    });

  // React Query keeps the previous ``data`` around while the next
  // fetch is in flight, so once the office has pressed a button
  // once we can keep showing the JSON.

  const handleView = () => {
    setRequested("view");
    setViewerOpen(true);
  };

  const handleDownload = () => {
    setRequested("download");
    if (data) {
      triggerDownload(data, tenant?.schema_name as string | undefined);
    }
  };

  // When the user pressed "download" and the data arrives in the
  // SAME render cycle, the handler above already had it. When the
  // press happened first and the query is still loading, we kick
  // the download as soon as ``data`` resolves below.
  if (requested === "download" && data && !isFetching) {
    // Fire-and-forget; idempotent because dataset id only changes
    // when data changes (which invalidates the request anyway).
    queueDownloadOnce(data, tenant?.schema_name as string | undefined);
  }

  return (
    <Card
      title={
        <span className="icon-title-row">
          <FileTextOutlined />
          {t("gdpr.vvt.title")}
        </span>
      }
      // Light-blue header — reuses the existing ``--color-info-bg``
      // token already applied to ``PlanningHarvestSharesBase`` info
      // strips and the email-template editor banner, so this card
      // stays visually consistent with the rest of the office UI.
      styles={{ header: { backgroundColor: "var(--color-info-bg)" } }}
    >
      <Paragraph>
        {t("gdpr.vvt.description")}
      </Paragraph>

      <Space>
        <Button
          icon={<EyeOutlined />}
          onClick={handleView}
          loading={isFetching && requested === "view"}
        >
          {t("gdpr.vvt.view")}
        </Button>
        <Button
          type="primary"
          icon={<DownloadOutlined />}
          onClick={handleDownload}
          loading={isFetching && requested === "download"}
        >
          {t("gdpr.vvt.download")}
        </Button>
      </Space>

      {isError && (
        <Alert
          type="error"
          style={{ marginTop: 16 }}
          message={t("gdpr.vvt.error")}
          description={getErrorMessage(error, t("gdpr.vvt.error"))}
        />
      )}

      <Modal
        title={t("gdpr.vvt.modal_title")}
        open={viewerOpen}
        onCancel={() => setViewerOpen(false)}
        footer={[
          <Button
            key="download"
            type="primary"
            icon={<DownloadOutlined />}
            disabled={!data}
            onClick={() =>
              data &&
              triggerDownload(data, tenant?.schema_name as string | undefined)
            }
          >
            {t("gdpr.vvt.download")}
          </Button>,
          <ModalCloseFooter key="close" onClose={() => setViewerOpen(false)} />,
        ]}
        width={900}
      >
        {data ? (
          <>
            <Text
              type="secondary"
              style={{ display: "block", marginBottom: 8 }}
            >
              {t("gdpr.vvt.doc_reference")}{" "}
              <Text code>
                {(data as { doc_reference?: string }).doc_reference}
              </Text>
            </Text>
            <pre className="json-viewer">
              {JSON.stringify(data, null, 2)}
            </pre>
          </>
        ) : (
          <Paragraph>{t("common.loading")}</Paragraph>
        )}
      </Modal>
    </Card>
  );
}

// Ensure a single download per (data identity, schema) pair so the
// re-render-loop in the parent doesn't spam Save dialogs.
let _lastDownloadKey: string | null = null;

function queueDownloadOnce(
  data: unknown,
  schemaName: string | undefined,
): void {
  const key = `${(data as { generated_at?: string }).generated_at ?? "x"}|${schemaName ?? ""}`;
  if (_lastDownloadKey === key) return;
  _lastDownloadKey = key;
  triggerDownload(data, schemaName);
}

function triggerDownload(data: unknown, schemaName: string | undefined): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  });
  const today = dayjs().format("YYYY-MM-DD");
  const stem = schemaName ? `vvt-${schemaName}-${today}` : `vvt-${today}`;
  downloadBlob(blob, `${stem}.json`);
  notify.success(`${stem}.json`);
}
