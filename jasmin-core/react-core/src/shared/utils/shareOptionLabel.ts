import type { TFunction } from "i18next";
import type { ShareTypeEnum } from "@shared/api/generated/models";

/**
 * Localize a share-option (ShareTypeEnum) code via the shared
 * `commissioning.share_option.*` keys — the single home for the label that was
 * re-inlined (with a banned runtime fallback) across the share-article table,
 * the article list page and the packing page.
 */
export function getShareOptionLabel(
  value: ShareTypeEnum | string,
  t: TFunction,
): string {
  return t(`commissioning.share_option.${value}`);
}
