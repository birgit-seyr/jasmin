import { useTenant } from "@hooks/index";

/**
 * Whether the farm charges tax on its articles: an article's rate goes on the
 * resellers' documents and on the market scale, the only places that read it.
 */
export function useTaxesArticles(): boolean {
  const { getSetting } = useTenant();
  return (
    getSetting("sells_to_resellers", true) !== false ||
    getSetting("has_markets", true) !== false
  );
}
