import { describe, expect, it } from "vitest";

import { buildLiveRecord } from "../buildLiveRecord";
import type { EditableColumnConfig, TableRecord } from "../types";

/** Minimal column factory so tests stay readable. */
function col<T extends TableRecord>(
  partial: Partial<EditableColumnConfig<T>> & { dataIndex: string },
): EditableColumnConfig<T> {
  return {
    title: partial.dataIndex,
    editable: true,
    ...partial,
  } as EditableColumnConfig<T>;
}

describe("buildLiveRecord", () => {
  it("returns the original record when no form values are present", () => {
    const record = { key: "1", id: "1", name: "alice" };
    expect(buildLiveRecord(record, undefined, [])).toEqual(record);
  });

  it("merges form values over the original record (form wins)", () => {
    const record = { key: "1", id: "1", name: "alice", age: 30 };
    const form = { name: "bob" };
    expect(buildLiveRecord(record, form, [col({ dataIndex: "name" })])).toEqual({
      key: "1",
      id: "1",
      name: "bob",
      age: 30,
    });
  });

  it("treats a null record as an empty object", () => {
    expect(buildLiveRecord(null, { x: 1 }, [])).toEqual({ x: 1 });
  });

  it("reverse-maps a foreign-key dataIndex back onto its valueField", () => {
    // Edit form holds `share_article_name` (the displayed text), but consumers
    // such as `disabled(record)` expect to read the FK id at `share_article`.
    const record = {
      key: "row-1",
      id: "row-1",
      share_article: "old-id",
      share_article_name: "Old Name",
    };
    const form = { share_article_name: "new-id" };
    const columns = [
      col<typeof record>({
        dataIndex: "share_article_name",
        foreignKey: { valueField: "share_article" } as never,
      }),
    ];

    const live = buildLiveRecord(record, form, columns);

    expect(live.share_article).toBe("new-id");
    expect(live.share_article_name).toBe("new-id");
  });

  it("walks nested children when reverse-mapping FKs", () => {
    const record = { key: "1", id: "1", outer: "old" };
    const form = { outer: "new-id" };
    const columns = [
      col({
        dataIndex: "group",
        children: [
          col({
            dataIndex: "outer",
            foreignKey: { valueField: "outer_id" } as never,
          }),
        ],
      }),
    ];

    const live = buildLiveRecord(record, form, columns);
    expect(live.outer_id).toBe("new-id");
  });

  it("does not touch FK fields whose dataIndex isn't in the form", () => {
    const record = { key: "1", id: "1", share_article: "old" };
    const form = { unrelated: "x" };
    const columns = [
      col({
        dataIndex: "share_article_name",
        foreignKey: { valueField: "share_article" } as never,
      }),
    ];

    const live = buildLiveRecord(record, form, columns);
    expect(live.share_article).toBe("old");
  });
});
