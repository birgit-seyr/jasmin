import type {
  LabelElement,
  LabelTemplate,
  LabelTemplateRequest,
  PrintModeEnum,
} from "@shared/api/generated/models";

/**
 * The label template's pieces as the label page, the editor and the PDF use
 * them. The field names mirror ``LABEL_FIELDS`` in the backend's
 * ``labels_serializer``.
 */
export const LABEL_TEXT_FIELDS = [
  "reseller_name",
  "reseller_address",
  "reseller_city",
  "article",
  "sort",
  "size",
  "amount_per_pu",
  "delivery_date",
  "order_number",
  "farm_name",
  "control_number",
  "static_text",
] as const;
export const LABEL_IMAGE_FIELDS = ["farm_logo", "organic_logo", "qr_code"] as const;
export const LABEL_FIELDS = [...LABEL_TEXT_FIELDS, ...LABEL_IMAGE_FIELDS] as const;
export type LabelField = (typeof LABEL_FIELDS)[number];
export type LabelAlign = "left" | "center" | "right";

/** An element whose content is the text typed into it, not an order's data. */
export const takesText = (field: string): boolean =>
  field === "static_text" || field === "qr_code";

/** The most elements a template holds, as the server allows. */
export const MAX_LABEL_ELEMENTS = 40;

/** An element the server refuses as it is: a text or QR code without content. */
export const isIncomplete = (element: LabelElement): boolean =>
  takesText(element.field) && !(element.text ?? "").trim();
export const isImageField = (field: string): boolean =>
  (LABEL_IMAGE_FIELDS as readonly string[]).includes(field);

/** The PDF's unit, points, per millimetre. */
export const PT_PER_MM = 72 / 25.4;
export const mmToPt = (mm: number): number => mm * PT_PER_MM;
export const A4_MM = { width: 210, height: 297 } as const;

/** An element with every value set, as the editor and the PDF read it. */
export type PlacedElement = Required<LabelElement>;

/** The template with its sizes as numbers. */
export interface LabelLayout {
  width: number;
  height: number;
  elements: PlacedElement[];
  printMode: PrintModeEnum;
  sheet: {
    columns: number;
    rows: number;
    marginTop: number;
    marginLeft: number;
    gapX: number;
    gapY: number;
  };
}

export function placedElement(element: LabelElement): PlacedElement {
  return {
    font_size_pt: 10,
    bold: false,
    align: "left",
    text: "",
    organic_prefix: true,
    ...element,
  };
}

export function layoutOf(template: LabelTemplate): LabelLayout {
  return {
    width: Number(template.width_mm),
    height: Number(template.height_mm),
    elements: template.elements.map(placedElement),
    printMode: template.print_mode ?? "label_printer",
    sheet: {
      columns: template.sheet_columns ?? 3,
      rows: template.sheet_rows ?? 8,
      marginTop: Number(template.sheet_margin_top_mm ?? 0),
      marginLeft: Number(template.sheet_margin_left_mm ?? 0),
      gapX: Number(template.sheet_gap_x_mm ?? 0),
      gapY: Number(template.sheet_gap_y_mm ?? 0),
    },
  };
}

/** The template the editor starts from: a 70 × 37 mm label with the
 *  reseller, the article and its variety, the delivery date and the amount. */
export const DEFAULT_LAYOUT: LabelLayout = {
  width: 70,
  height: 37,
  printMode: "label_printer",
  sheet: { columns: 3, rows: 8, marginTop: 0.5, marginLeft: 0, gapX: 0, gapY: 0 },
  elements: [
    placedElement({ id: "reseller", field: "reseller_name", x_mm: 2, y_mm: 2, width_mm: 66, height_mm: 6, bold: true }),
    placedElement({ id: "article", field: "article", x_mm: 2, y_mm: 10, width_mm: 66, height_mm: 9, font_size_pt: 15, bold: true, align: "center" }),
    placedElement({ id: "sort", field: "sort", x_mm: 2, y_mm: 20, width_mm: 66, height_mm: 6, align: "center" }),
    placedElement({ id: "delivery-date", field: "delivery_date", x_mm: 2, y_mm: 29, width_mm: 30, height_mm: 6, font_size_pt: 9 }),
    placedElement({ id: "amount", field: "amount_per_pu", x_mm: 40, y_mm: 28, width_mm: 28, height_mm: 7, font_size_pt: 13, bold: true, align: "right" }),
  ],
};

/** The layout as the API takes it, its sizes as tenth-millimetre strings. */
export function templateRequest(layout: LabelLayout, name: string): LabelTemplateRequest {
  const mm = (value: number) => value.toFixed(1);
  return {
    name,
    width_mm: mm(layout.width),
    height_mm: mm(layout.height),
    elements: layout.elements,
    print_mode: layout.printMode,
    sheet_columns: layout.sheet.columns,
    sheet_rows: layout.sheet.rows,
    sheet_margin_top_mm: mm(layout.sheet.marginTop),
    sheet_margin_left_mm: mm(layout.sheet.marginLeft),
    sheet_gap_x_mm: mm(layout.sheet.gapX),
    sheet_gap_y_mm: mm(layout.sheet.gapY),
  };
}

/** Whether an element reaches beyond the label (which the server refuses). */
export const isOutside = (element: LabelElement, layout: LabelLayout): boolean =>
  element.x_mm + element.width_mm > layout.width + 0.05 ||
  element.y_mm + element.height_mm > layout.height + 0.05;

/**
 * The top left corners of a sheet's labels in mm, row by row: the places one
 * A4 page holds.
 */
export function sheetSlots(sheet: LabelLayout["sheet"], width: number, height: number) {
  const slots: { x: number; y: number }[] = [];
  for (let row = 0; row < sheet.rows; row += 1) {
    for (let column = 0; column < sheet.columns; column += 1) {
      slots.push({
        x: sheet.marginLeft + column * (width + sheet.gapX),
        y: sheet.marginTop + row * (height + sheet.gapY),
      });
    }
  }
  return slots;
}

/** Common A4 sheets of labels, for the editor to fill in at once. */
export const SHEET_PRESETS = [
  { key: "70x37", width: 70, height: 37, columns: 3, rows: 8, marginTop: 0.5, marginLeft: 0, gapX: 0, gapY: 0 },
  { key: "70x42.3", width: 70, height: 42.3, columns: 3, rows: 7, marginTop: 0.4, marginLeft: 0, gapX: 0, gapY: 0 },
  { key: "105x37", width: 105, height: 37, columns: 2, rows: 8, marginTop: 0.5, marginLeft: 0, gapX: 0, gapY: 0 },
  { key: "105x48", width: 105, height: 48, columns: 2, rows: 6, marginTop: 4.5, marginLeft: 0, gapX: 0, gapY: 0 },
  { key: "63.5x38.1", width: 63.5, height: 38.1, columns: 3, rows: 7, marginTop: 15.1, marginLeft: 7.2, gapX: 2.5, gapY: 0 },
  { key: "99.1x38.1", width: 99.1, height: 38.1, columns: 2, rows: 7, marginTop: 15.1, marginLeft: 4.6, gapX: 2.5, gapY: 0 },
] as const;

/**
 * The amount each label of an order line carries: one label per packing unit,
 * and one more for a part-filled unit with what is left. A line without a
 * packing-unit size gets one label with its whole amount.
 */
export function labelAmounts(amount: number, amountPerPu: number): number[] {
  if (!(amount > 0)) return [];
  if (!(amountPerPu > 0)) return [amount];
  const fullUnits = Math.floor(amount / amountPerPu + 1e-9);
  const rest = Math.round((amount - fullUnits * amountPerPu) * 1000) / 1000;
  const amounts: number[] = Array.from({ length: fullUnits }, () => amountPerPu);
  return rest > 0.0005 ? [...amounts, rest] : amounts;
}

/**
 * ``amounts`` cut or extended to ``count`` labels: the first ones kept, any
 * added one carrying a full packing unit. ``null`` keeps them as they are.
 */
export function withLabelCount(
  amounts: number[],
  count: number | null,
  amountPerPu: number,
): number[] {
  if (count === null) return amounts;
  if (count <= amounts.length) return amounts.slice(0, count);
  const fill = amountPerPu > 0 ? amountPerPu : (amounts[0] ?? 0);
  return [...amounts, ...Array.from({ length: count - amounts.length }, () => fill)];
}

/** One label's information, already worded for printing. */
export interface LabelData {
  resellerName: string;
  resellerAddress: string;
  resellerCity: string;
  article: string;
  isOrganic: boolean;
  /** Organic or in conversion: the farm's control number belongs on it. */
  isCertified: boolean;
  sort: string;
  size: string;
  amountPerPu: string;
  deliveryDate: string;
  orderNumber: string;
}

/** What the farm adds to every label. The organic word and mark only go on an
 *  organic article, and only for a certified farm. */
export interface LabelFarm {
  name: string;
  controlNumber: string;
  organicEnabled: boolean;
  organicPrefix: string;
}

/** The text an element prints on a label; empty for none. */
export function labelElementText(
  element: PlacedElement,
  label: LabelData,
  farm: LabelFarm,
): string {
  switch (element.field as LabelField) {
    case "reseller_name":
      return label.resellerName;
    case "reseller_address":
      return label.resellerAddress;
    case "reseller_city":
      return label.resellerCity;
    case "article":
      return element.organic_prefix && farm.organicEnabled && label.isOrganic
        ? `${farm.organicPrefix} ${label.article}`
        : label.article;
    case "sort":
      return label.sort;
    case "size":
      return label.size;
    case "amount_per_pu":
      return label.amountPerPu;
    case "delivery_date":
      return label.deliveryDate;
    case "order_number":
      return label.orderNumber;
    case "farm_name":
      return farm.name;
    case "control_number":
      return farm.organicEnabled && label.isCertified ? farm.controlNumber : "";
    case "static_text":
      return element.text;
    default:
      return "";
  }
}

/** Whether an image element shows on a label at all. */
export function showsImage(
  element: PlacedElement,
  label: LabelData,
  farm: LabelFarm,
): boolean {
  if (element.field === "organic_logo") return farm.organicEnabled && label.isOrganic;
  if (element.field === "qr_code") return element.text.trim() !== "";
  return element.field === "farm_logo";
}

/** A new element of ``field`` at the label's top left, sized for its kind. */
export function newElement(
  field: LabelField,
  layout: LabelLayout,
  at: { x: number; y: number } = { x: 1, y: 1 },
): PlacedElement {
  const image = isImageField(field);
  const width = Math.min(image ? 15 : 40, layout.width - 1);
  const height = Math.min(image ? 15 : 6, layout.height - 1);
  return placedElement({
    id: newElementId(),
    field,
    x_mm: clampMm(at.x, 0, layout.width - width),
    y_mm: clampMm(at.y, 0, layout.height - height),
    width_mm: width,
    height_mm: height,
    text: field === "static_text" ? "Text" : "",
  });
}

/** An id unique within the template. Not ``crypto.randomUUID``, which a page
 *  served over plain http (a dev machine reached on the LAN) doesn't have. */
function newElementId(): string {
  return `el-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** ``value`` within ``[min, max]``, on the half-millimetre grid. */
export function clampMm(value: number, min: number, max: number): number {
  const snapped = Math.round(value * 2) / 2;
  return Math.min(Math.max(snapped, min), Math.max(min, max));
}
