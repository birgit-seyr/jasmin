import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useActiveStatusColumn, useCurrency, useDefaultTaxRates, useNumberFormat, useTimeBoundColumns } from "@hooks/index";
import {
  useCommissioningCrateNetPricesList,
  getCommissioningCrateNetPricesListQueryKey,
  commissioningCrateNetPricesCreate,
  commissioningCrateNetPricesPartialUpdate,
  commissioningCrateNetPricesDestroy,
} from "@shared/api/generated/commissioning/commissioning";
import type { CrateNetPrice } from "@shared/api/generated/models/crateNetPrice";
import type { EditableColumnConfig } from "@shared/tables/BasicEditableTable/types";
import PriceEditorModal from "./PriceEditorModal";
import { buildCurrencyPriceColumn, buildTaxRateColumn } from "./priceColumns";

interface CratePriceModalProps {
  visible: boolean;
  onClose: () => void;
  crate: string | null;
  crate_name: string;
  onSave?: () => void;
}

export default function CratePriceModal({
  visible,
  onClose,
  crate,
  crate_name,
}: CratePriceModalProps) {
  const { t } = useTranslation();
  const { currencySymbol } = useCurrency();
  const { locale } = useNumberFormat();
  const activeStatusColumn = useActiveStatusColumn({
    defaultSortOrder: "descend",
  });
  const { validFromColumn, validUntilColumn } = useTimeBoundColumns({
    width: "9em",
  });

  const { crates: defaultTaxRateCrates } = useDefaultTaxRates();

  const columns = useMemo<EditableColumnConfig[]>(
    () =>
      [
        activeStatusColumn,
        validFromColumn,
        validUntilColumn,
        buildCurrencyPriceColumn({
          title: t("commissioning.price_netto"),
          dataIndex: "price",
          currencySymbol,
          width: "7em",
          wrapInText: false,
          locale,
        }),
        buildTaxRateColumn(t, { locale }),
      ] as EditableColumnConfig[],
    [t, currencySymbol, locale, activeStatusColumn, validFromColumn, validUntilColumn],
  );

  return (
    <PriceEditorModal<CrateNetPrice, CrateNetPrice>
      visible={visible}
      onClose={onClose}
      title={
        <div>
          {t("commissioning.prices_for_crate")}
          {crate_name}
        </div>
      }
      fkField="crate"
      fkValue={crate}
      defaultTaxRate={defaultTaxRateCrates}
      columns={columns}
      listHook={useCommissioningCrateNetPricesList}
      getListQueryKey={getCommissioningCrateNetPricesListQueryKey}
      api={{
        create: commissioningCrateNetPricesCreate,
        partialUpdate: commissioningCrateNetPricesPartialUpdate,
        destroy: commissioningCrateNetPricesDestroy,
      }}
    />
  );
}
