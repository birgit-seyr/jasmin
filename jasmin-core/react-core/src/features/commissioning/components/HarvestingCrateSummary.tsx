/**
 * "Needed harvesting crates" summary under the HarvestingList table —
 * compact card on mobile, small bordered table on desktop. Pure
 * presentation; the aggregation lives in ``useHarvestingListData``.
 */

import { Card, Table } from "antd";
import { useTranslation } from "react-i18next";
import { ToolTipIcon } from "@shared/ui";
import type { CrateSummaryEntry } from "@features/commissioning/hooks/useHarvestingListData";

export default function HarvestingCrateSummary({
  crateSummary,
  isMobile,
  showMobileCard,
}: {
  crateSummary: CrateSummaryEntry[];
  isMobile: boolean;
  /** Mobile only renders the card once data finished loading and the
   *  list actually has rows — mirrors the page's previous inline rule. */
  showMobileCard: boolean;
}) {
  const { t } = useTranslation();

  if (isMobile) {
    if (!showMobileCard) return null;
    return (
      <Card
        size="small"
        style={{
          backgroundColor: "#fff9e6",
          marginTop: "1em",
          marginBottom: "1em",
          fontSize: "0.8em",
        }}
        styles={{ body: { padding: "8px 12px" } }}
        title={
          <span style={{ fontSize: "0.85em" }}>
            {t("commissioning.needed_harvesting_crates")}
          </span>
        }
      >
        {crateSummary.length === 0 ? (
          <div className="text-muted">{t("table.no_data")}</div>
        ) : (
          crateSummary.map((item) => (
            <div
              key={item.key}
              style={{
                display: "flex",
                justifyContent: "space-between",
                padding: "2px 0",
                borderBottom: "1px solid #f0e6c0",
              }}
            >
              <span style={{ fontWeight: 500 }}>{item.crate_name}</span>
              <span style={{ fontWeight: 600 }}>{item.quantity}</span>
            </div>
          ))
        )}
      </Card>
    );
  }

  const columns = [
    {
      title: (
        <>
          {t("commissioning.needed_harvesting_crates")}
          <ToolTipIcon title={t("tooltip.needed_harvesting_crates")} />
        </>
      ),
      dataIndex: "crate_name",
      key: "crate_name",
      width: "14em",
    },
    {
      title: t("commissioning.quantity"),
      dataIndex: "quantity",
      key: "quantity",
      align: "center" as const,
      width: "8em",
    },
  ];

  return (
    <div style={{ marginBottom: "2em", marginTop: "2em" }}>
      <Table
        columns={columns}
        dataSource={crateSummary}
        pagination={false}
        size="small"
        className="compact-table custom-forecast-table"
        style={{ width: "22em", marginTop: "1em" }}
        locale={{
          emptyText: <div style={{ height: "2em" }}>{t("table.no_data")}</div>,
        }}
      />
    </div>
  );
}
