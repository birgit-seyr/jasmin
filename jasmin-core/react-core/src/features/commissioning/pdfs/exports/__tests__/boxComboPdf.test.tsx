/**
 * boxComboPdf: the shared building blocks of the box-combination matrices —
 * width and orientation maths, the group-by-base-share-type helper, the count
 * formatter and the two header rows.
 */
import { render, screen } from "@testing-library/react";
import type { TFunction } from "i18next";
import { describe, expect, it, vi } from "vitest";
import type { PackingBoxesMatrixColumn } from "@shared/api/generated/models";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: unknown) =>
      typeof fallback === "string" ? fallback : key,
    i18n: { language: "de", changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@react-pdf/renderer", async (importOriginal) => {
  const { pdfDomPrimitives } = await import(
    "@features/commissioning/pdfs/__tests__/pdfDomPrimitives"
  );
  return {
    ...(await importOriginal<typeof import("@react-pdf/renderer")>()),
    ...pdfDomPrimitives(),
  };
});

import { styleOf } from "../../__tests__/pdfDomPrimitives";
import {
  ComboColumnHeaderRow,
  ComboGroupHeaderRow,
  ComboHeader,
  boxComboStyles,
  comboColumnWidth,
  computeGroupEdges,
  formatComboCount,
  groupComboColumns,
  groupEdgeStyles,
  pickComboOrientation,
} from "../boxComboPdf";

const LABELS: Record<string, string> = {
  "commissioning.S": "small",
  "commissioning.M": "medium",
  "commissioning.L": "large",
  "commissioning.no_base_combination": "No base",
};
const t = ((key: string) => LABELS[key] ?? key) as unknown as TFunction;

const column = (
  overrides: Partial<PackingBoxesMatrixColumn> = {},
): PackingBoxesMatrixColumn => ({
  key: "col-1",
  base_variation_id: "var-1",
  base_size: "M",
  base_sort_order: 0,
  base_share_type_id: "type-veg",
  base_share_type_name: "Vegetables",
  base_share_type_short_name: "VEG",
  base_share_type_sort_index: 0,
  add_ons: [],
  count: 1,
  ...overrides,
});

const addOn = (shortName: string, size: string) =>
  ({
    share_type_short_name: shortName,
    size,
  }) as PackingBoxesMatrixColumn["add_ons"][number];

// A4 content widths: page width minus 2×40pt padding.
const PORTRAIT = 595.28 - 80;
const LANDSCAPE = 841.89 - 80;

describe("comboColumnWidth", () => {
  it("caps a few combos at the ideal width", () => {
    expect(
      comboColumnWidth({
        orientation: "portrait",
        comboCount: 2,
        fixedWidth: 100,
        flexMinWidth: 100,
      }),
    ).toBe(64);
  });

  it("shrinks many combos so the table fills the page exactly", () => {
    const width = comboColumnWidth({
      orientation: "portrait",
      comboCount: 10,
      fixedWidth: 100,
      flexMinWidth: 100,
    });
    expect(width).toBeCloseTo((PORTRAIT - 200) / 10);
    expect(width * 10 + 200).toBeCloseTo(PORTRAIT);
  });

  it("uses the wider landscape content area", () => {
    expect(
      comboColumnWidth({
        orientation: "landscape",
        comboCount: 12,
        fixedWidth: 100,
        flexMinWidth: 100,
      }),
    ).toBeCloseTo((LANDSCAPE - 200) / 12);
  });

  it("treats zero combos like one instead of dividing by zero", () => {
    expect(
      comboColumnWidth({
        orientation: "portrait",
        comboCount: 0,
        fixedWidth: 100,
        flexMinWidth: 100,
      }),
    ).toBe(64);
  });

  it("honours a custom ideal width", () => {
    expect(
      comboColumnWidth({
        orientation: "portrait",
        comboCount: 1,
        fixedWidth: 0,
        flexMinWidth: 0,
        comboIdeal: 90,
      }),
    ).toBe(90);
  });
});

describe("pickComboOrientation", () => {
  // (515.28 − 200) / n ≥ 42 holds up to n = 7.
  it("stays portrait while the combos fit at the readable minimum", () => {
    expect(
      pickComboOrientation({
        maxComboCount: 7,
        fixedWidth: 100,
        flexMinWidth: 100,
      }),
    ).toBe("portrait");
  });

  it("switches to landscape once they no longer fit", () => {
    expect(
      pickComboOrientation({
        maxComboCount: 8,
        fixedWidth: 100,
        flexMinWidth: 100,
      }),
    ).toBe("landscape");
  });

  it("stays portrait for an empty matrix", () => {
    expect(
      pickComboOrientation({
        maxComboCount: 0,
        fixedWidth: 100,
        flexMinWidth: 100,
      }),
    ).toBe("portrait");
  });

  it("honours a custom minimum width", () => {
    expect(
      pickComboOrientation({
        maxComboCount: 7,
        fixedWidth: 100,
        flexMinWidth: 100,
        comboMin: 50,
      }),
    ).toBe("landscape");
  });
});

describe("formatComboCount", () => {
  it.each([null, undefined, "", 0, "0", " ", Number.NaN, "abc", Infinity])(
    "leaves the cell blank for %s",
    (value) => {
      expect(formatComboCount(value)).toBe("");
    },
  );

  it.each([
    [5, "5"],
    ["7", "7"],
    [-3, "-3"],
    [12, "12"],
  ])("prints %s as %s", (value, expected) => {
    expect(formatComboCount(value)).toBe(expected);
  });
});

describe("groupComboColumns", () => {
  it("groups consecutive columns of the same base share type", () => {
    const groups = groupComboColumns(
      [
        column({ key: "a" }),
        column({ key: "b", base_size: "L" }),
        column({
          key: "c",
          base_share_type_id: "type-fruit",
          base_share_type_short_name: "FRU",
        }),
      ],
      t,
    );
    expect(groups.map((g) => [g.id, g.name, g.cols.map((c) => c.key)])).toEqual(
      [
        ["type-veg", "VEG", ["a", "b"]],
        ["type-fruit", "FRU", ["c"]],
      ],
    );
  });

  it("names the add-on-only combinations as having no base", () => {
    const groups = groupComboColumns(
      [
        column({
          key: "x",
          base_variation_id: null,
          base_share_type_id: null,
          base_share_type_short_name: "",
        }),
        column({
          key: "y",
          base_variation_id: null,
          base_share_type_id: null,
          base_share_type_short_name: "",
        }),
      ],
      t,
    );
    expect(groups).toHaveLength(1);
    expect(groups[0]).toMatchObject({ id: "__none__", name: "No base" });
    expect(groups[0].cols).toHaveLength(2);
  });

  it("returns no groups for no columns", () => {
    expect(groupComboColumns([], t)).toEqual([]);
  });
});

describe("computeGroupEdges / groupEdgeStyles", () => {
  const groups = groupComboColumns(
    [
      column({ key: "a" }),
      column({ key: "b" }),
      column({ key: "c" }),
      column({
        key: "d",
        base_share_type_id: "type-fruit",
        base_share_type_short_name: "FRU",
      }),
    ],
    t,
  );
  const edges = computeGroupEdges(groups);

  it("marks the first and last column of every group", () => {
    expect(Object.fromEntries(edges)).toEqual({
      a: { left: true, right: false },
      b: { left: false, right: false },
      c: { left: false, right: true },
      d: { left: true, right: true },
    });
  });

  it("returns the green rules for a group's edges only", () => {
    expect(groupEdgeStyles(edges, "a")).toEqual([
      boxComboStyles.groupBorderLeft,
      {},
    ]);
    expect(groupEdgeStyles(edges, "b")).toEqual([{}, {}]);
    expect(groupEdgeStyles(edges, "d")).toEqual([
      boxComboStyles.groupBorderLeft,
      boxComboStyles.groupBorderRight,
    ]);
  });

  it("adds no rule for an unknown column", () => {
    expect(groupEdgeStyles(edges, "missing")).toEqual([{}, {}]);
  });
});

describe("ComboHeader", () => {
  it("prints the base size and one badge per add-on", () => {
    render(
      <ComboHeader
        column={column({
          base_size: "L",
          add_ons: [addOn("FRU", "S"), addOn("EGG", "M")],
        })}
        t={t}
      />,
    );
    expect(screen.getByText("large")).toBeInTheDocument();
    expect(screen.getByText("FRU·small EGG·medium")).toBeInTheDocument();
  });

  it("prints a dash for a combination without a base and no badge line without add-ons", () => {
    const { container } = render(
      <ComboHeader column={column({ base_variation_id: null })} t={t} />,
    );
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(container.querySelectorAll("[data-pdf='text']")).toHaveLength(1);
  });

  it("prints every size of a multi-size base", () => {
    render(<ComboHeader column={column({ base_size: "S,L" })} t={t} />);
    expect(screen.getByText("small, large")).toBeInTheDocument();
  });
});

describe("ComboGroupHeaderRow", () => {
  const groups = groupComboColumns(
    [
      column({ key: "a" }),
      column({ key: "b" }),
      column({
        key: "c",
        base_share_type_id: "type-fruit",
        base_share_type_short_name: "FRU",
      }),
    ],
    t,
  );

  it("spans each share-type name over its combinations, between the fixed slots", () => {
    const { container } = render(
      <ComboGroupHeaderRow
        groups={groups}
        comboWidth={50}
        leading={<span>Article</span>}
        trailing={<span>Note</span>}
      />,
    );
    const row = container.firstElementChild!;
    expect(row).toHaveAttribute("data-fixed", "true");
    expect(row.textContent).toBe("ArticleVEGFRUNote");
    expect(styleOf(screen.getByText("VEG").parentElement).width).toBe(100);
    expect(styleOf(screen.getByText("FRU").parentElement).width).toBe(50);
    expect(styleOf(screen.getByText("VEG").parentElement)).toMatchObject({
      borderLeftWidth: 1.5,
      borderRightWidth: 1.5,
    });
    expect(styleOf(row).borderBottomWidth).not.toBe(0.5);
  });

  it("adds the slim divider when asked", () => {
    const { container } = render(
      <ComboGroupHeaderRow groups={groups} comboWidth={50} thinBorderBottom />,
    );
    expect(styleOf(container.firstElementChild).borderBottomWidth).toBe(0.5);
  });
});

describe("ComboColumnHeaderRow", () => {
  it("prints one header per combination with its group's edge rules", () => {
    const columns = [
      column({ key: "a", base_size: "S" }),
      column({ key: "b", base_size: "L" }),
    ];
    const groupEdges = computeGroupEdges(groupComboColumns(columns, t));
    const { container } = render(
      <ComboColumnHeaderRow
        columns={columns}
        comboWidth={40}
        groupEdges={groupEdges}
        t={t}
        leading={<span>Article</span>}
        trailing={<span>✓</span>}
      />,
    );
    const row = container.firstElementChild!;
    expect(row).toHaveAttribute("data-fixed", "true");
    expect(row.textContent).toBe("Articlesmalllarge✓");

    const smallCell = screen.getByText("small").closest("[data-pdf='view']")!
      .parentElement;
    const largeCell = screen.getByText("large").closest("[data-pdf='view']")!
      .parentElement;
    expect(styleOf(smallCell)).toMatchObject({ width: 40, borderLeftWidth: 1.5 });
    expect(styleOf(smallCell).borderRightWidth).toBeUndefined();
    expect(styleOf(largeCell)).toMatchObject({
      width: 40,
      borderRightWidth: 1.5,
    });
    expect(styleOf(largeCell).borderLeftWidth).toBeUndefined();
  });
});
