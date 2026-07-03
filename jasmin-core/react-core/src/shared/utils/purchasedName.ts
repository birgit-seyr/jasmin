import type { TFunction } from "i18next";

/**
 * Returns the translated suffix appended to share-article names
 * that are marked as purchased (DE: "Zukauf", EN: "purchase", …).
 */
const getPurchasedSuffix = (t: TFunction): string =>
  t("commissioning.purchased_name_suffix");

/** Check whether *name* already contains the purchased suffix. */
export const hasPurchasedSuffix = (name: string, t: TFunction): boolean => {
  if (!name) return false;
  return name.includes(getPurchasedSuffix(t));
};

/** Append the purchased suffix to *name* (no-op if already present). */
const addPurchasedSuffix = (name: string, t: TFunction): string => {
  if (!name) return "";
  if (hasPurchasedSuffix(name, t)) return name;
  return `${name} ${getPurchasedSuffix(t)}`;
};

/** Remove the purchased suffix from *name*. */
export const removePurchasedSuffix = (name: string, t: TFunction): string => {
  if (!name) return "";
  const suffix = getPurchasedSuffix(t);
  return name.replace(new RegExp(`\\s*${suffix}\\s*`, "gi"), "").trim();
};

/**
 * Synchronise the `is_purchased` flag and article name:
 * - If `is_purchased` is true, ensure the suffix is present.
 * - If the name already contains the suffix, force `is_purchased` to true.
 *
 * Returns `{ name, is_purchased }`.
 */
export const syncPurchasedName = (
  name: string,
  isPurchased: boolean,
  t: TFunction,
): { name: string; is_purchased: boolean } => {
  let modifiedName = name || "";
  let modifiedIsPurchased = isPurchased;

  if (isPurchased && !hasPurchasedSuffix(modifiedName, t)) {
    modifiedName = addPurchasedSuffix(modifiedName, t);
  }

  if (hasPurchasedSuffix(name, t) && !isPurchased) {
    modifiedIsPurchased = true;
  }

  return { name: modifiedName, is_purchased: modifiedIsPurchased };
};
