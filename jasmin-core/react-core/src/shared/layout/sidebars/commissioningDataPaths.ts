/**
 * The pages of commissioning's data section: the article, crate, storage,
 * delivery-station, reseller, seller and plot lists and the default
 * quantities. Where the data is a section of its own (no
 * ``configuration_section``), opening one of them selects that section, though
 * they live under /commissioning.
 */
export const COMMISSIONING_DATA_PATHS = [
  "/commissioning/list-harvest-share-articles",
  "/commissioning/default-share-articles-in-share",
  "/commissioning/list-crates",
  "/commissioning/list-extra-articles",
  "/commissioning/list-storages",
  "/commissioning/list-delivery-stations",
  "/commissioning/delivery-tours",
  "/commissioning/list-resellers",
  "/commissioning/list-offer-groups",
  "/commissioning/list-sellers",
  "/commissioning/list-plots",
] as const;

export const isCommissioningDataPath = (pathname: string): boolean =>
  COMMISSIONING_DATA_PATHS.some(
    (path) => pathname === path || pathname.startsWith(`${path}/`),
  );
