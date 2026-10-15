import type { TFunction } from "i18next";
import { getErrorCode, getErrorMessage } from "@shared/utils/apiError";

/**
 * What the office reads when a waiting-list offer is refused: the page's own
 * wording when a capacity gate filled up between render and click, else the
 * refusal's own message (an entry whose subscription or member was cancelled
 * or rejected, a member without an email address, onboarding mode, …), else a
 * generic one.
 */
export function offerErrorMessage(error: unknown, t: TFunction): string {
  switch (getErrorCode(error)) {
    case "share_type_variation.over_capacity":
      return t("abos.offer_variation_full");
    case "delivery_station.over_capacity":
      return t("abos.offer_station_full");
    default:
      return getErrorMessage(error, t("abos.offer_failed"));
  }
}
