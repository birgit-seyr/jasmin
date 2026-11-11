/**
 * Bulk-action row for the market prices page: copy the selected prices into
 * the next week, or put them on sale or take them off it. The selection state
 * stays in the page; this component owns the buttons and their API calls.
 */

import { Button, Popconfirm } from "antd";
import { useTranslation } from "react-i18next";
import {
  commissioningMarketPricesBulkCopyToNextWeekCreate,
  commissioningMarketPricesBulkSetActiveCreate,
} from "@shared/api/generated/commissioning/commissioning";
import { BulkActionButton } from "@shared/ui";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";

export default function MarketPricesBulkActions({
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
  const count = { count: selectedRowKeys.length };

  // The backend skips a PLU that already has a price next week, so a
  // successful copy may have copied only some of the prices, or none.
  const handleCopyToNextWeek = async () => {
    try {
      const result = await commissioningMarketPricesBulkCopyToNextWeekCreate({
        ids: selectedRowKeys.map(String),
      });
      const counts = {
        count: result.total_copied,
        skipped: result.skipped_count,
      };
      if (result.total_copied === 0) {
        notify.warning(t("commissioning.market_prices_copied_none", counts));
      } else if (result.skipped_count > 0) {
        notify.success(
          t("commissioning.market_prices_copied_some_skipped", counts),
        );
      } else {
        notify.success(t("commissioning.market_prices_copied", counts));
      }
      onClearSelection();
    } catch (error) {
      notify.error(getErrorMessage(error, t("commissioning.copy_failed")));
    }
  };

  return (
    <>
      <div className="bulk-actions-header">
        <strong>{t("commissioning.for_selected")}</strong>
      </div>
      <div className="button-row-spaced">
        <Popconfirm
          title={t("commissioning.market_prices_copy_confirm")}
          icon={null}
          onConfirm={handleCopyToNextWeek}
          okText={t("common.yes")}
          cancelText={t("common.cancel")}
          disabled={nothingSelected}
        >
          <Button
            disabled={nothingSelected}
            type="primary"
            className="selected-rows-action-button"
          >
            {t("commissioning.copy_selected_to_next_week")}
          </Button>
        </Popconfirm>
        <BulkActionButton
          selectedIds={selectedRowKeys}
          apiFunction={commissioningMarketPricesBulkSetActiveCreate}
          payload={{ is_active: true }}
          buttonText={t("commissioning.market_prices_activate")}
          successMessage={t("commissioning.market_prices_activated", count)}
          onClearSelection={onClearSelection}
          onSuccess={onInvalidate}
        />
        <BulkActionButton
          selectedIds={selectedRowKeys}
          apiFunction={commissioningMarketPricesBulkSetActiveCreate}
          payload={{ is_active: false }}
          buttonText={t("commissioning.market_prices_deactivate")}
          successMessage={t("commissioning.market_prices_deactivated", count)}
          onClearSelection={onClearSelection}
          onSuccess={onInvalidate}
        />
      </div>
    </>
  );
}
