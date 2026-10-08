/**
 * Bulk-action row for the Offers page: finalize the selected offers,
 * copy them to next week, or copy them into another offer group. The
 * selection state stays in the page; this component owns the buttons
 * and their API calls.
 */

import { Button, Popconfirm } from "antd";
import { useTranslation } from "react-i18next";
import {
  commissioningBulkCopyOffersToNextWeekCreate,
  commissioningBulkCopyOffersToOfferGroupCreate,
  commissioningBulkFinalizeCreate,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  BulkCopyOffersResponse,
  BulkCopyOffersToOfferGroupRequest,
  BulkFinalizeRequest,
  BulkIdsRequest,
} from "@shared/api/generated/models";
import { BulkActionButton } from "@shared/ui";
import type { useOffersData } from "@features/commissioning/hooks/useOffersData";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";

type OffersData = ReturnType<typeof useOffersData>;

export default function OffersBulkActions({
  selectedRowKeys,
  onClearSelection,
  onInvalidate,
  otherOfferGroups,
  selectedYear,
  selectedWeek,
}: {
  selectedRowKeys: (string | number)[];
  onClearSelection: () => void;
  onInvalidate: () => void;
  otherOfferGroups: OffersData["otherOfferGroups"];
  selectedYear: number;
  selectedWeek: number;
}) {
  const { t } = useTranslation();
  const nothingSelected = selectedRowKeys.length === 0;
  const selectedIds = selectedRowKeys.map(String);

  // The backend skips an offer whose copy already exists at the target, so a
  // successful request may have copied only some of the offers, or none.
  const reportCopy = (
    result: BulkCopyOffersResponse,
    messageKey: "copied_to_next_week" | "copied_to_offer_group",
    values: Record<string, unknown> = {},
  ) => {
    const counts = {
      count: result.total_copied,
      skipped: result.skipped_count,
      ...values,
    };
    if (result.total_copied === 0) {
      notify.warning(t(`commissioning.${messageKey}_none`, counts));
    } else if (result.skipped_count > 0) {
      notify.success(t(`commissioning.${messageKey}_some_skipped`, counts));
    } else {
      notify.success(t(`commissioning.${messageKey}`, counts));
    }
  };

  return (
    <div className="button-row-spaced">
      <BulkActionButton
        selectedIds={selectedRowKeys}
        apiFunction={() => {
          const body: BulkFinalizeRequest = {
            ids: selectedIds,
            model: "offer",
            app_label: "commissioning",
          };
          return commissioningBulkFinalizeCreate(body);
        }}
        buttonText={t("commissioning.finalize")}
        buttonProps={{ type: "primary" }}
        disabled={nothingSelected}
        onClearSelection={onClearSelection}
        onSuccess={onInvalidate}
      />

      <Popconfirm
        title={t("commissioning.confirm_offers_copy_title")}
        icon={null}
        onConfirm={async () => {
          try {
            const body: BulkIdsRequest = { ids: selectedIds };
            const result =
              await commissioningBulkCopyOffersToNextWeekCreate(body);
            reportCopy(result, "copied_to_next_week");
            onClearSelection();
          } catch (error) {
            notify.error(getErrorMessage(error, t("commissioning.copy_failed")));
          }
        }}
        okText={t("common.yes")}
        cancelText={t("common.cancel")}
        disabled={nothingSelected}
      >
        {" "}
        <Button
          disabled={nothingSelected}
          type="primary"
          className="selected-rows-action-button"
        >
          {t("commissioning.copy_selected_to_next_week")}
        </Button>
      </Popconfirm>

      {otherOfferGroups.length > 0 &&
        otherOfferGroups.map((offerGroup) => (
          <Popconfirm
            key={offerGroup.value}
            title={t("commissioning.confirm_copy_to_offer_group", {
              offerGroup: offerGroup.name,
            })}
            icon={null}
            onConfirm={async () => {
              try {
                const body: BulkCopyOffersToOfferGroupRequest = {
                  ids: selectedIds,
                  year: selectedYear,
                  delivery_week: selectedWeek,
                  offer_group: offerGroup.value,
                };
                const result =
                  await commissioningBulkCopyOffersToOfferGroupCreate(body);
                reportCopy(result, "copied_to_offer_group", {
                  offerGroup: offerGroup.name,
                });
                onClearSelection();
              } catch (error) {
                notify.error(
                  getErrorMessage(error, t("commissioning.copy_failed")),
                );
              }
            }}
            okText={t("common.yes")}
            cancelText={t("common.cancel")}
            disabled={nothingSelected}
          >
            <Button
              disabled={nothingSelected}
              type="primary"
              className="selected-rows-action-button"
            >
              {t("commissioning.copy_to_offer_group", {
                name: offerGroup.name,
              })}
            </Button>
          </Popconfirm>
        ))}
    </div>
  );
}
