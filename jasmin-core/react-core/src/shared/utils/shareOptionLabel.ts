import type { TFunction } from "i18next";
import type { ShareTypeEnum } from "@shared/api/generated/models";

/**
 * Localize a share-option (ShareTypeEnum) code via the shared
 * `commissioning.share_option.*` keys — the single home for the label.
 */
export function getShareOptionLabel(
  value: ShareTypeEnum | string,
  t: TFunction,
): string {
  return t(`commissioning.share_option.${value}`);
}
