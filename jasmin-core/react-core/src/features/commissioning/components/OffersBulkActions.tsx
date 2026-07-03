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

  return (
    <div className="button-row-spaced">
      <BulkActionButton
        selectedIds={selectedRowKeys}
        apiFunction={(payload) =>
          commissioningBulkFinalizeCreate(payload as never)
        }
        payload={{
          model: "offer",
          app_label: "commissioning",
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
            await commissioningBulkCopyOffersToNextWeekCreate({
              ids: selectedRowKeys as number[],
            } as never);
            notify.success(t("commissioning.copied_to_next_week"));
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
          style={{
            marginTop: "2.5em",
            height: "1.8em",
          }}
        >
          {t("commissioning.copy_selected_to_next_week")}
        </Button>
      </Popconfirm>

      {otherOfferGroups.length > 0 &&
        otherOfferGroups.map((offerGroup) => (
          <Popconfirm
            key={offerGroup.id as string}
            title={
              t("commissioning.confirm_copy_to_offer_group", {
                offerGroup: offerGroup.name,
              }) || `Copy to ${offerGroup.name}?`
            }
            icon={null}
            onConfirm={async () => {
              try {
                await commissioningBulkCopyOffersToOfferGroupCreate({
                  ids: selectedRowKeys as number[],
                  year: selectedYear,
                  delivery_week: selectedWeek,
                  offer_group: offerGroup.id,
                } as never);
                notify.success(
                  t("commissioning.copied_to_offer_group", {
                    offerGroup: offerGroup.name,
                  }),
                );
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
              style={{
                marginTop: "2.5em",
                height: "1.8em",
              }}
            >
              {t("commissioning.copy_to_offer_group", {
                name: offerGroup.name,
              }) || `Copy to ${offerGroup.name}`}
            </Button>
          </Popconfirm>
        ))}
    </div>
  );
}
