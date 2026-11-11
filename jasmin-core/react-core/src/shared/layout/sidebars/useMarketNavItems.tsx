import { useTenant } from "@hooks/index";
import { type RoleGatedItem } from "@shared/auth";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import StorefrontIcon from "@mui/icons-material/Storefront";

/**
 * The commissioning sidebar's market section: the weekly market prices, and
 * the PLUs, product groups and scale VAT codes they rest on. A farm without
 * markets gets no section.
 */
export function useMarketNavItems(): RoleGatedItem[] {
  const { t } = useTranslation();
  const { getSetting } = useTenant();
  const has_markets = getSetting("has_markets", true);

  if (!has_markets) return [];

  const link = (
    path: string,
    label: string,
    requireRole: RoleGatedItem["requireRole"],
  ): RoleGatedItem => ({
    key: `commissioning-${path}`,
    requireRole,
    label: <Link to={`/commissioning/${path}`}>{label}</Link>,
  });

  return [
    {
      key: "commissioning-markets",

      requireRole: "isStaff",
      icon: <StorefrontIcon />,
      label: (
        <div className="sidebar-section-header">
          {t("commissioning.markets")}
        </div>
      ),
      children: [
        link("market-prices", t("commissioning.market_prices"), "isStaff"),
        link(
          "list-market-articles",
          t("commissioning.list_market_articles"),
          "isOffice",
        ),
        link(
          "list-market-product-groups",
          t("commissioning.list_market_product_groups"),
          "isOffice",
        ),
        link(
          "list-scale-tax-codes",
          t("commissioning.list_scale_tax_codes"),
          "isOffice",
        ),
      ],
    },
  ];
}
