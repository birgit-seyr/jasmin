import { describe, expect, it } from "vitest";
import {
  DEFAULT_LAYOUT,
  clampMm,
  isOutside,
  labelAmounts,
  labelElementText,
  layoutOf,
  newElement,
  placedElement,
  sheetSlots,
  showsImage,
  templateRequest,
  withLabelCount,
  type LabelData,
  type LabelFarm,
} from "../labelLayout";

const label: LabelData = {
  resellerName: "Hofladen",
  resellerAddress: "Hauptstraße 1",
  resellerCity: "77933 Lahr",
  article: "Karotten",
  isOrganic: true,
  isCertified: true,
  sort: "Nantaise",
  size: "",
  amountPerPu: "5 kg",
  deliveryDate: "17.11.2026",
  orderNumber: "B-0042",
};

const farm: LabelFarm = {
  name: "Gärtnerei",
  controlNumber: "DE-ÖKO-006",
  organicEnabled: true,
  organicPrefix: "Bio",
};

const element = (field: string, values = {}) =>
  placedElement({ id: field, field, x_mm: 0, y_mm: 0, width_mm: 10, height_mm: 5, ...values });

describe("labelAmounts", () => {
  it("gives one label per packing unit", () => {
    expect(labelAmounts(15, 5)).toEqual([5, 5, 5]);
  });

  it("gives a part-filled unit a label of its own with what is left", () => {
    expect(labelAmounts(12.5, 5)).toEqual([5, 5, 2.5]);
  });

  it("gives a line without a packing-unit size one label with all of it", () => {
    expect(labelAmounts(7, 0)).toEqual([7]);
  });

  it("gives a line without an amount no label", () => {
    expect(labelAmounts(0, 5)).toEqual([]);
  });

  it("isn't thrown off by binary fractions", () => {
    expect(labelAmounts(0.3, 0.1)).toEqual([0.1, 0.1, 0.1]);
  });
});

describe("withLabelCount", () => {
  it("keeps the computed labels without a count of its own", () => {
    expect(withLabelCount([5, 2.5], null, 5)).toEqual([5, 2.5]);
  });

  it("keeps the first labels for a smaller count", () => {
    expect(withLabelCount([5, 5, 2.5], 2, 5)).toEqual([5, 5]);
  });

  it("adds full packing units for a larger count", () => {
    expect(withLabelCount([5, 2.5], 4, 5)).toEqual([5, 2.5, 5, 5]);
  });
});

describe("sheetSlots", () => {
  it("lays the labels out row by row from the margins, with the gaps between", () => {
    const slots = sheetSlots(
      { columns: 2, rows: 2, marginTop: 10, marginLeft: 5, gapX: 2, gapY: 1 },
      100,
      40,
    );

    expect(slots).toEqual([
      { x: 5, y: 10 },
      { x: 107, y: 10 },
      { x: 5, y: 51 },
      { x: 107, y: 51 },
    ]);
  });
});

describe("labelElementText", () => {
  it("puts the organic word before an organic article", () => {
    expect(labelElementText(element("article"), label, farm)).toBe("Bio Karotten");
  });

  it("leaves it off where the element says so, for a conventional article and for an uncertified farm", () => {
    expect(
      labelElementText(element("article", { organic_prefix: false }), label, farm),
    ).toBe("Karotten");
    expect(
      labelElementText(element("article"), { ...label, isOrganic: false }, farm),
    ).toBe("Karotten");
    expect(
      labelElementText(element("article"), label, { ...farm, organicEnabled: false }),
    ).toBe("Karotten");
  });

  it("prints the control number on organic and in-conversion articles only", () => {
    expect(labelElementText(element("control_number"), label, farm)).toBe("DE-ÖKO-006");
    expect(
      labelElementText(element("control_number"), { ...label, isCertified: false }, farm),
    ).toBe("");
  });

  it("prints a free text as typed, and the order line's data in the others", () => {
    expect(labelElementText(element("static_text", { text: "Danke!" }), label, farm)).toBe(
      "Danke!",
    );
    expect(labelElementText(element("amount_per_pu"), label, farm)).toBe("5 kg");
    expect(labelElementText(element("reseller_city"), label, farm)).toBe("77933 Lahr");
  });
});

describe("showsImage", () => {
  it("shows the organic logo on organic articles of a certified farm only", () => {
    expect(showsImage(element("organic_logo"), label, farm)).toBe(true);
    expect(showsImage(element("organic_logo"), { ...label, isOrganic: false }, farm)).toBe(
      false,
    );
  });

  it("shows a QR code only with content to encode", () => {
    expect(showsImage(element("qr_code"), label, farm)).toBe(false);
    expect(showsImage(element("qr_code", { text: "https://hof.example" }), label, farm)).toBe(
      true,
    );
  });
});

describe("placing elements", () => {
  it("snaps to half millimetres and keeps the element on the label", () => {
    expect(clampMm(3.26, 0, 50)).toBe(3.5);
    expect(clampMm(-4, 0, 50)).toBe(0);
    expect(clampMm(80, 0, 50)).toBe(50);
  });

  it("places a new element where it was dropped, inside the label", () => {
    const placed = newElement("sort", DEFAULT_LAYOUT, { x: 60, y: 3.2 });

    expect(placed).toMatchObject({ field: "sort", x_mm: 30, y_mm: 3, width_mm: 40 });
    expect(isOutside(placed, DEFAULT_LAYOUT)).toBe(false);
  });

  it("tells an element that reaches beyond the label", () => {
    expect(isOutside(element("sort", { x_mm: 65 }), DEFAULT_LAYOUT)).toBe(true);
  });
});

describe("the template on the wire", () => {
  it("reads the template's sizes as numbers and writes them back as tenth millimetres", () => {
    const layout = layoutOf({
      ...templateRequest(DEFAULT_LAYOUT, "Etikett"),
      id: "tpl-1",
      width_mm: "99.1",
    });

    expect(layout.width).toBe(99.1);
    expect(templateRequest(layout, "Etikett")).toMatchObject({
      width_mm: "99.1",
      height_mm: "37.0",
      sheet_margin_top_mm: "0.5",
    });
  });
});
