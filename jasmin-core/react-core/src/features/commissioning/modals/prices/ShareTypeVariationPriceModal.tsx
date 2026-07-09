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
import type { EditableColumnConfig } from "@shared/tables/BasicEditableTable/types";
import { ToolTipIcon } from "@shared/ui";
import { useMemo } from "react";
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
  const { getSetting } = useTenant();
  const { shares: defaultTaxRateShares } = useDefaultTaxRates();
  const allowsSolidarity = Boolean(
    getSetting("allows_solidarity_pricing", false),
  );

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
          title: <>{t("commissioning.price_brutto")}</>,
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
    <PriceEditorModal<
      ShareTypeVariationGrossPrice,
      ShareTypeVariationGrossPrice
    >
      visible={visible}
      onClose={onClose}
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
