/**
 * The share-option flag (`harvest_share`, `harvest_share_fruit`, …) a new
 * share article starts ticked in: the option the office has filtered the
 * article list to, or else the vegetable share when the farm runs it. A farm
 * without a vegetable share starts the article in none, so the office picks.
 *
 * The article list and the add-article dialog both start new articles here,
 * so an article lands in the same share whichever way the office adds it.
 */
export function newShareArticleShareFlag(
  filteredShareFlag: string | null,
  farmRunsVegetableShare: boolean,
): string | null {
  if (filteredShareFlag) return filteredShareFlag;
  return farmRunsVegetableShare ? "harvest_share" : null;
}
