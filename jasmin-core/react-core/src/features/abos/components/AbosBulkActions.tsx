/**
 * Bulk-action row for the Abos page: renew the selected subscriptions with the
 * same per-subscription logic as the daily auto-renewal sweep — each eligible
 * row gets an UNCONFIRMED renewal draft the office then reviews + confirms.
 * Ineligible rows (trial / cancelled / already renewed / open-ended) are skipped
 * server-side; an eligible row whose draft can't be built (no covering variation,
 * station-day out of range) fails — both are reported back PER ROW with a reason
 * so the office sees exactly what did NOT renew and why. Selection stays in page.
 */

import { Button, Modal, Popconfirm } from "antd";
import { useTranslation } from "react-i18next";
import { useCommissioningAbosBulkRenewCreate } from "@shared/api/generated/commissioning/commissioning";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import { ToolTipIcon } from "@shared/ui";

type Outcome = { id: string; label: string; reason: string };

export default function AbosBulkActions({
  selectedRowKeys,
  onClearSelection,
  onInvalidate,
}: {
  selectedRowKeys: (string | number)[];
  onClearSelection: () => void;
  onInvalidate: () => void;
}) {
  const { t } = useTranslation();
  const nothingSelected = selectedRowKeys.length === 0;

  const renderReasons = (items: Outcome[]) => (
    <ul style={{ margin: "4px 0 10px", paddingLeft: "1.2em" }}>
      {items.map((item) => (
        <li key={item.id}>
          <strong>{item.label}</strong> — {t(`abos.renewal_reason.${item.reason}`)}
        </li>
      ))}
    </ul>
  );

  const { mutate, isPending } = useCommissioningAbosBulkRenewCreate({
    mutation: {
      onSuccess: (result) => {
        const skipped = result.skipped ?? [];
        const failed = result.failed ?? [];
        if (skipped.length === 0 && failed.length === 0) {
          notify.success(
            t("abos.bulk_renew_all_created", { created: result.created }),
          );
        } else {
          // Some rows didn't renew — show the office exactly which + why.
          Modal.info({
            title: t("abos.bulk_renew_result", {
              created: result.created,
              skipped: skipped.length,
              failed: failed.length,
            }),
            width: 560,
            content: (
              <div>
                {failed.length > 0 && (
                  <>
                    <div>{t("abos.bulk_renew_failed_heading")}</div>
                    {renderReasons(failed)}
                  </>
                )}
                {skipped.length > 0 && (
                  <>
                    <div>{t("abos.bulk_renew_skipped_heading")}</div>
                    {renderReasons(skipped)}
                  </>
                )}
              </div>
            ),
          });
        }
        onInvalidate();
        onClearSelection();
      },
      onError: (error) =>
        notify.error(getErrorMessage(error, t("abos.bulk_renew_failed"))),
    },
  });

  return (
    <div className="button-row-spaced">
      <Popconfirm
        title={t("abos.bulk_renew_confirm", { count: selectedRowKeys.length })}
        icon={null}
        onConfirm={() =>
          mutate({ data: { subscription_ids: selectedRowKeys.map(String) } })
        }
        okText={t("common.yes")}
        cancelText={t("common.cancel")}
        disabled={nothingSelected}
      >
        <Button
          type="primary"
          disabled={nothingSelected}
          loading={isPending}
          size="small"
          style={{
            marginTop: "2.5em",
            height: "1.8em",
          }}
        >
          {t("abos.bulk_renew")}
        </Button>
        <ToolTipIcon title={t("tooltip.bulk_renew_abos")} />
      </Popconfirm>
    </div>
  );
}
