/**
 * newShareArticleShareFlag: a new share article starts in the filtered share,
 * else in the vegetable share when the farm runs it, else in none.
 */
import { describe, expect, it } from "vitest";

import { newShareArticleShareFlag } from "../newShareArticleShare";

describe("newShareArticleShareFlag", () => {
  it("takes the share the list is filtered to", () => {
    expect(newShareArticleShareFlag("harvest_share_fruit", true)).toBe("harvest_share_fruit");
    expect(newShareArticleShareFlag("harvest_share_fruit", false)).toBe("harvest_share_fruit");
  });

  it("falls back to the vegetable share when the farm runs it", () => {
    expect(newShareArticleShareFlag(null, true)).toBe("harvest_share");
  });

  it("starts in no share when the farm runs no vegetable share", () => {
    expect(newShareArticleShareFlag(null, false)).toBeNull();
  });
});
