import { getSizeLabelOrEmpty } from "../components/mobileCards/sizeLabel";

interface OrderLineArticle {
  share_article_name: string;
  sort?: string | null;
  size?: string | null;
}

/**
 * An order line's article as the packing lists name it: the article and its
 * sort, then ", <size>" unless the size is the default M.
 */
export function orderLineArticleLabel(
  line: OrderLineArticle,
  getVegetableSizeLabel: (size: string) => string,
): string {
  const name = [line.share_article_name, line.sort].filter(Boolean).join(" ");
  const size = getSizeLabelOrEmpty(line.size, getVegetableSizeLabel);
  return size ? `${name}, ${size}` : name;
}
