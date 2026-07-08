/**
 * Bulk-action row for the Abos page: renew the selected subscriptions with the
 * same per-subscription logic as the daily auto-renewal sweep — each eligible
 * row gets an UNCONFIRMED renewal draft the office then reviews + confirms.
 * Ineligible rows (trial / cancelled / already renewed / open-ended) are skipped
 * server-side; an eligible row whose draft can't be built (no covering variation,
 * station-day out of range) fails — both are reported back PER ROW with a reason
 * so the office sees exactly what did NOT renew and why. Selection stays in page.
 *
 * The renew button opens a small modal to set ONE common end date for the batch
 * (pre-set to ~one year out, on a Sunday), adjustable before confirming. Omitting
 * a date keeps each predecessor's term length (the sweep's default).
 */

import { Button, DatePicker, Modal } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useCommissioningAbosBulkRenewCreate } from "@shared/api/generated/commissioning/commissioning";
import { useDateFormat } from "@hooks/index";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import { ToolTipIcon } from "@shared/ui";

type Outcome = { id: string; label: string; reason: string };

// The Sunday on or after one year from today — the default new end date.
const nextYearSunday = (): Dayjs => {
  const base = dayjs().add(1, "year");
  const dayOfWeek = base.day(); // 0 = Sunday
  return dayOfWeek === 0 ? base : base.add(7 - dayOfWeek, "day");
};

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
  const { dateFormat, formatDateForAPI } = useDateFormat();
  const nothingSelected = selectedRowKeys.length === 0;
  const [modalOpen, setModalOpen] = useState(false);
  const [validUntil, setValidUntil] = useState<Dayjs | null>(nextYearSunday);

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
        setModalOpen(false);
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

  const openModal = () => {
    setValidUntil(nextYearSunday()); // fresh pre-set each time it opens
    setModalOpen(true);
  };

  const handleConfirm = () => {
    mutate({
      data: {
        subscription_ids: selectedRowKeys.map(String),
        valid_until: validUntil ? formatDateForAPI(validUntil) : undefined,
      },
    });
  };

  return (
    <div className="button-row-spaced">
      <Button
        type="primary"
        disabled={nothingSelected}
        loading={isPending}
        size="small"
        style={{ marginTop: "2.5em", height: "1.8em" }}
        onClick={openModal}
      >
        {t("abos.bulk_renew")}
      </Button>
      <ToolTipIcon title={t("tooltip.bulk_renew_abos")} />

      <Modal
        open={modalOpen}
        title={t("abos.bulk_renew_modal_title", {
          count: selectedRowKeys.length,
        })}
        okText={t("abos.bulk_renew")}
        cancelText={t("common.cancel")}
        confirmLoading={isPending}
        okButtonProps={{ disabled: !validUntil }}
        onOk={handleConfirm}
        onCancel={() => setModalOpen(false)}
        destroyOnHidden
      >
        <p>{t("abos.bulk_renew_confirm", { count: selectedRowKeys.length })}</p>
        <label>
          {t("abos.bulk_renew_new_end_date")}{" "}
          <ToolTipIcon title={t("configuration.valid_until_must_be_sunday")} />
        </label>
        <DatePicker
          value={validUntil}
          onChange={setValidUntil}
          format={dateFormat}
          allowClear={false}
          disabledDate={(current) => current.day() !== 0}
          style={{ width: "100%", marginTop: 6 }}
        />
      </Modal>
    </div>
  );
}
