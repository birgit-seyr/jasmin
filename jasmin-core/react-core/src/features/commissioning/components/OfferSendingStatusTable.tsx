/**
 * "Which reseller got the offer email when" table under the Offers
 * page. Pure presentation; the sending-status query lives in
 * ``useOffersData``.
 */

import { CheckCircleOutlined, CloseCircleOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { EditableTable, READ_ONLY_PERMISSION } from "@shared/tables";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { useDateFormat } from "@hooks/index";

export default function OfferSendingStatusTable({
  sendingStatus,
  loading,
}: {
  sendingStatus: Record<string, unknown>[];
  loading: boolean;
}) {
  const { t } = useTranslation();
  const { formatDate } = useDateFormat();

  const rows: TableRecord[] = sendingStatus.map((record) => ({
    ...record,
    key: (record.id as string) ?? (record.name as string),
  }));

  const columns: EditableColumnConfig<TableRecord>[] = [
    {
      title: t("commissioning.reseller"),
      dataIndex: "name",
      key: "name",
      width: "22em",
    },
    {
      title: t("commissioning.offer_sent"),
      dataIndex: "sent_at",
      key: "sent_at",
      align: "left",
      width: "24em",
      render: (_: unknown, record: TableRecord) =>
        // A11Y-14: status must not be conveyed by colour alone — the icon is
        // aria-hidden and a visible text label (the date carries a sr-only
        // "sent" prefix; the not-sent state shows its label) makes it readable.
        record.sent_at ? (
          <div style={{ fontSize: "0.85em", marginTop: "4px" }}>
            <CheckCircleOutlined
              className="text-success"
              style={{ fontSize: "18px" }}
              aria-hidden="true"
            />
            <span className="sr-only">{t("commissioning.offer_sent")}: </span>
            {formatDate(record.sent_at as string)}
          </div>
        ) : (
          <div style={{ fontSize: "0.85em", marginTop: "4px" }}>
            <CloseCircleOutlined
              className="text-error"
              style={{ fontSize: "18px" }}
              aria-hidden="true"
            />
            {t("commissioning.offer_not_sent")}
          </div>
        ),
    },
  ];

  return (
    <div style={{ marginTop: "2em", marginBottom: "2em" }}>
      <EditableTable
        columns={columns}
        initialData={rows}
        loading={loading}
        permissions={READ_ONLY_PERMISSION}
        style={{ width: "46em" }}
      />
    </div>
  );
}
