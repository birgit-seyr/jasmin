import { useTranslation } from "react-i18next";

import { PastWarningMessage } from "@shared/ui";

/**
 * Shown in place of the packing-list / harvest-share-planning grids when the
 * selected week has no share-type variations (and/or no delivery-station days),
 * so the dynamically-built variation columns would be empty. Rendering a grid
 * with no data columns is meaningless — surface a configuration hint instead.
 *
 * Renders via ``PastWarningMessage`` so it matches the read-only-week warning
 * styling shown on the same pages.
 */
export default function NoVariationColumnsBanner() {
  const { t } = useTranslation();
  return (
    <PastWarningMessage>
      <strong>{t("commissioning.no_variation_columns_title")}</strong>{" "}
      {t("commissioning.no_variation_columns_message")}
    </PastWarningMessage>
  );
}
