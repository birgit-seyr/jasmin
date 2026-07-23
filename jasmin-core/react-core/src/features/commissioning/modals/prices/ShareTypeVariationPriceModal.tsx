import {
  useActiveStatusColumn,
  useCurrency,
  useDefaultTaxRates,
  useTenant,
  useTimeBoundColumns,
} from "@hooks/index";
import {
  commissioningShareTypeVariationPriceCreate,
  commissioningShareTypeVariationPriceDestroy,
  commissioningShareTypeVariationPricePartialUpdate,
  getCommissioningShareTypeVariationPriceListQueryKey,
  useCommissioningShareTypeVariationPriceList,
} from "@shared/api/generated/commissioning/commissioning";
import type { ShareTypeVariationGrossPrice } from "@shared/api/generated/models/shareTypeVariationGrossPrice";
import { useTenantsSettingsUpdateCurrentSettingsUpdate } from "@shared/api/generated/tenants/tenants";
import type { EditableColumnConfig } from "@shared/tables/BasicEditableTable/types";
import { ToolTipIcon } from "@shared/ui";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import { Checkbox } from "antd";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import PriceEditorModal from "./PriceEditorModal";
import { buildCurrencyPriceColumn, buildTaxRateColumn } from "./priceColumns";

interface ShareTypeVariationPriceModalProps {
  visible: boolean;
  onClose: () => void;
  share_type_variation: string | null;
  share_type_variation_name: string;
  onSave?: () => void;
}

export default function ShareTypeVariationPriceModal({
  visible,
  onClose,
  share_type_variation,
  share_type_variation_name,
}: ShareTypeVariationPriceModalProps) {
  const { t } = useTranslation();
  const { currencySymbol } = useCurrency();
  const { getSetting, refreshTenant } = useTenant();
  const { shares: defaultTaxRateShares } = useDefaultTaxRates();

  // ``allows_solidarity_pricing`` is a TENANT-WIDE setting, edited right here
  // (moved out of the payments config page) so the office can flip it while
  // setting a variation's prices. Local state mirrors the setting for INSTANT
  // column reveal on toggle; the change is persisted to the tenant and the
  // context refreshed so every other reader (subscriptions, dashboards) agrees.
  const [allowsSolidarity, setAllowsSolidarity] = useState(() =>
    Boolean(getSetting("allows_solidarity_pricing", false)),
  );

  // Re-seed when the modal (re)opens or the tenant setting loads/changes, so a
  // value set elsewhere is reflected. While the modal is open the local state
  // stays authoritative: ``getSetting``'s identity only changes once the
  // refetched tenant lands, so an optimistic toggle isn't clobbered mid-save.
  useEffect(() => {
    if (visible) {
      setAllowsSolidarity(
        Boolean(getSetting("allows_solidarity_pricing", false)),
      );
    }
  }, [visible, getSetting]);

  const updateSettings = useTenantsSettingsUpdateCurrentSettingsUpdate();

  const handleToggleSolidarity = (checked: boolean) => {
    setAllowsSolidarity(checked); // instant: reveal/hide the solidarity column
    updateSettings.mutate(
      { data: { settings: { allows_solidarity_pricing: checked } } },
      {
        onSuccess: () => refreshTenant(),
        onError: (error) => {
          setAllowsSolidarity(!checked); // revert the optimistic toggle
          notify.error(getErrorMessage(error, t("common.error")));
        },
      },
    );
  };

  const activeStatusColumn = useActiveStatusColumn({
    defaultSortOrder: "descend",
  });
  const { validFromColumn, validUntilColumn } = useTimeBoundColumns();

  const columns = useMemo<EditableColumnConfig[]>(
    () =>
      [
        activeStatusColumn,
        validFromColumn,
        validUntilColumn,
        buildCurrencyPriceColumn({
          // The brutto price is only a *reference* ("Richtpreis") when
          // solidarity pricing is on — members then choose their own price
          // around it. With solidarity off it is the fixed price, so the
          // hint would be misleading; only show it when solidarity is on.
          title: (
            <>
              {t("commissioning.price_brutto")}
              {allowsSolidarity && (
                <ToolTipIcon
                  title={t("tooltip.share_type_variation_price_brutto")}
                />
              )}
            </>
          ),
          dataIndex: "price_per_delivery",
          currencySymbol,
          width: "6em",
          required: true,
        }),
        // Solidarity floor — only when the tenant enables solidarity pricing.
        // Optional (null = no explicit floor; the reference price is the floor).
        ...(allowsSolidarity
          ? [
              buildCurrencyPriceColumn({
                title: (
                  <>
                    {t("commissioning.solidarity_min_price")}
                    <ToolTipIcon title={t("tooltip.solidarity_min_price")} />
                  </>
                ),
                dataIndex: "solidarity_min_price_per_delivery",
                currencySymbol,
                width: "7em",
                required: false,
              }),
            ]
          : []),
        buildTaxRateColumn(t, {
          title: t("commissioning.tax_rate"),
          inputType: "positive_integer",
          renderDecimals: 0,
          width: "5em",
        }),
        {
          title: (
            <>
              {t("commissioning.price_sum_articles")}
              <ToolTipIcon title={t("tooltip.price_sum_articles")} />
            </>
          ),
          dataIndex: "price_sum_articles",
          key: "price_sum_articles",
          inputType: "positive_decimal2",
          required: false,
          width: "9em",
          align: "center",
          render: buildCurrencyPriceColumn({
            title: "",
            dataIndex: "price_sum_articles",
            currencySymbol,
          }).render,
        },
      ] as EditableColumnConfig[],
    [
      t,
      currencySymbol,
      activeStatusColumn,
      validFromColumn,
      validUntilColumn,
      allowsSolidarity,
    ],
  );

  return (
    <PriceEditorModal<ShareTypeVariationGrossPrice>
      visible={visible}
      onClose={onClose}
      intro={
        <div className="mb-1em">
          <Checkbox
            checked={allowsSolidarity}
            disabled={updateSettings.isPending}
            onChange={(e) => handleToggleSolidarity(e.target.checked)}
            aria-label={t("settings.payments.allows_solidarity_pricing")}
          >
            {t("settings.payments.allows_solidarity_pricing")}
          </Checkbox>
          <ToolTipIcon
            title={t("settings.payments.allows_solidarity_pricing_desc")}
          />
        </div>
      }
      title={
        <div>
          {t("commissioning.prices_for_size")} {share_type_variation_name}
        </div>
      }
      width={800}
      fkField="share_type_variation"
      fkValue={share_type_variation}
      defaultTaxRate={defaultTaxRateShares}
      columns={columns}
      listHook={useCommissioningShareTypeVariationPriceList}
      getListQueryKey={getCommissioningShareTypeVariationPriceListQueryKey}
      api={{
        create: commissioningShareTypeVariationPriceCreate,
        partialUpdate: commissioningShareTypeVariationPricePartialUpdate,
        destroy: commissioningShareTypeVariationPriceDestroy,
      }}
    />
  );
}
