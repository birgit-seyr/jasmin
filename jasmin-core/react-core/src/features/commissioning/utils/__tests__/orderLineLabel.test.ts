/**
 * orderLineArticleLabel: the article and its sort, then the size unless it is
 * the default M.
 */
import { describe, expect, it } from "vitest";

import { orderLineArticleLabel } from "../orderLineLabel";

const sizeLabel = (size: string) => `size:${size}`;

describe("orderLineArticleLabel", () => {
  it("joins article and sort and appends a non-default size", () => {
    expect(
      orderLineArticleLabel(
        { share_article_name: "Carrots", sort: "Nantaise", size: "L" },
        sizeLabel,
      ),
    ).toBe("Carrots Nantaise, size:L");
  });

  it("leaves out the default size M", () => {
    expect(
      orderLineArticleLabel({ share_article_name: "Carrots", sort: null, size: "M" }, sizeLabel),
    ).toBe("Carrots");
  });

  it("leaves out a missing sort and size", () => {
    expect(orderLineArticleLabel({ share_article_name: "Leek" }, sizeLabel)).toBe("Leek");
  });
});
