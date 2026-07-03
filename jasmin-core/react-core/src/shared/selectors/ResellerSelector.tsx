import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useCommissioningResellersList } from "@shared/api/generated/commissioning/commissioning";
import type {
  CommissioningResellersListParams,
  Reseller,
} from "@shared/api/generated/models";
import BaseEntitySelector, { type SelectorOption } from "./BaseEntitySelector";

interface ResellerSelectorProps {
  selectedReseller: string | null;
  setSelectedReseller: (value: string | null) => void;
  onResellerChange?: ((value: string | null) => void) | null;
  include_null_option?: boolean;
  preserveSelection?: boolean;
  year?: number | null;
  delivery_week?: number | null;
  delivery_day?: string | null;
  has_orders_without_invoice?: boolean;
  userType?: "reseller" | "seller";
}

const ResellerSelector = ({
  selectedReseller,
  setSelectedReseller,
  onResellerChange = null,
  include_null_option = false,
  preserveSelection = true,
  year = null,
  delivery_week = null,
  delivery_day = null,
  has_orders_without_invoice = false,
  userType = "reseller",
}: ResellerSelectorProps) => {
  const { t } = useTranslation();

  // `has_orders_without_invoice` is supported by the backend but missing
  // from the Orval-generated type — extend it locally.
  type Params = CommissioningResellersListParams & {
    has_orders_without_invoice?: boolean;
  };

  const queryParams = useMemo<Params>(() => {
    const params: Params = {};
    if (year) params.year = year;
    if (delivery_week) params.delivery_week = delivery_week;
    if (delivery_day) params.delivery_day = delivery_day;
    if (has_orders_without_invoice)
      params.has_orders_without_invoice = has_orders_without_invoice;

    if (userType === "reseller") {
      params.is_reseller = true;
      params.is_active_reseller = true;
    } else {
      params.is_seller = true;
      params.is_active_seller = true;
    }
    return params;
  }, [year, delivery_week, delivery_day, has_orders_without_invoice, userType]);

  const { data, isLoading: loading } = useCommissioningResellersList(queryParams);
  // Memoize the empty-fallback so `resellers` keeps a stable identity when
  // the query hasn't returned yet — otherwise the `options` memo below
  // would invalidate on every render until data lands.
  const resellers: Reseller[] = useMemo(() => data ?? [], [data]);

  const options = useMemo<SelectorOption<string | null>[]>(() => {
    const opts: SelectorOption<string | null>[] = [];
    if (include_null_option) {
      opts.push({ value: null, label: t("commissioning.all_resellers") });
    }
    for (const r of resellers) {
      const text = `${r.company_name ?? ""}${
        r.first_name ? ` - ${r.first_name}` : ""
      }${r.last_name ? ` - ${r.last_name}` : ""}`;
      opts.push({
        value: r.id!,
        label: (
          <div className={r.has_orders ? "with-orders" : "without-orders"}>
            {text}
          </div>
        ),
      });
    }
    return opts;
  }, [resellers, include_null_option, t]);

  return (
    <BaseEntitySelector<string | null>
      value={selectedReseller}
      onValueChange={setSelectedReseller}
      onChange={onResellerChange}
      options={options}
      loading={loading}
      placeholder={
        userType === "reseller"
          ? t("placeholder.reseller_selector")
          : t("placeholder.seller_selector")
      }
      style={
        userType === "reseller"
          ? { width: "22em" }
          : { width: "22em", marginLeft: "2em" }
      }
      preserveSelection={preserveSelection}
    />
  );
};

export default ResellerSelector;
