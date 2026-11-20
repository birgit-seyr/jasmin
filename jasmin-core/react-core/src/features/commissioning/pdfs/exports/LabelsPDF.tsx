import { Document, Image, Page, Text, View } from "@react-pdf/renderer";
import "../registerRoboto";
import {
  A4_MM,
  isImageField,
  mmToPt,
  sheetSlots,
  type LabelLayout,
  type PlacedElement,
} from "@features/commissioning/utils/labelLayout";

// The line height of a label's text, as the editor draws it.
const LINE_HEIGHT = 1.2;

/** One printed label: each element's text, or an image's data URL, by the
 *  element's id. An element without an entry prints nothing. */
export type PrintedLabel = Record<string, string>;

export interface LabelsPDFProps {
  layout: LabelLayout;
  labels: PrintedLabel[];
  /** On A4 sheets, the place (from 1) the first label goes to, so a sheet
   *  already partly used can be filled up. */
  startPosition?: number;
}

const ElementBox = ({
  element,
  value,
}: {
  element: PlacedElement;
  value: string | undefined;
}) => {
  if (!value) return null;
  return (
    <View
      style={{
        position: "absolute",
        left: mmToPt(element.x_mm),
        top: mmToPt(element.y_mm),
        width: mmToPt(element.width_mm),
        height: mmToPt(element.height_mm),
        overflow: "hidden",
        justifyContent: "center",
      }}
    >
      {isImageField(element.field) ? (
        <Image src={value} style={{ width: "100%", height: "100%", objectFit: "contain" }} />
      ) : (
        <Text
          style={{
            fontFamily: "Roboto",
            fontSize: element.font_size_pt,
            fontWeight: element.bold ? 700 : 400,
            lineHeight: LINE_HEIGHT,
            textAlign: element.align as "left" | "center" | "right",
            // As many lines as the box holds, so the last one isn't cut through.
            maxLines: Math.max(
              1,
              Math.floor(mmToPt(element.height_mm) / (element.font_size_pt * LINE_HEIGHT)),
            ),
            textOverflow: "ellipsis",
          }}
        >
          {value}
        </Text>
      )}
    </View>
  );
};

const LabelFace = ({
  layout,
  label,
  left = 0,
  top = 0,
}: {
  layout: LabelLayout;
  label: PrintedLabel;
  left?: number;
  top?: number;
}) => (
  <View
    style={{
      position: "absolute",
      left: mmToPt(left),
      top: mmToPt(top),
      width: mmToPt(layout.width),
      height: mmToPt(layout.height),
    }}
  >
    {layout.elements.map((element) => (
      <ElementBox key={element.id} element={element} value={label[element.id]} />
    ))}
  </View>
);

/** The labels split into A4 pages, each place holding a label or, before the
 *  start position, staying empty. */
function sheetPages(layout: LabelLayout, labels: PrintedLabel[], startPosition: number) {
  const slots = sheetSlots(layout.sheet, layout.width, layout.height);
  const placed: (PrintedLabel | null)[] = [
    ...Array.from({ length: Math.min(Math.max(startPosition, 1), slots.length) - 1 }, () => null),
    ...labels,
  ];
  const pages: (PrintedLabel | null)[][] = [];
  for (let start = 0; start < placed.length; start += slots.length) {
    pages.push(placed.slice(start, start + slots.length));
  }
  return { slots, pages };
}

const LabelsPDF = ({ layout, labels, startPosition = 1 }: LabelsPDFProps) => {
  if (layout.printMode === "sheet") {
    const { slots, pages } = sheetPages(layout, labels, startPosition);
    return (
      <Document>
        {/* A fixed list, built once per download: the index is a stable key. */}
        {pages.map((page, pageIndex) => (
          <Page key={pageIndex} size={[mmToPt(A4_MM.width), mmToPt(A4_MM.height)]}>
            {page.map((label, slotIndex) =>
              label ? (
                <LabelFace
                  key={slotIndex}
                  layout={layout}
                  label={label}
                  left={slots[slotIndex].x}
                  top={slots[slotIndex].y}
                />
              ) : null,
            )}
          </Page>
        ))}
      </Document>
    );
  }
  return (
    <Document>
      {labels.map((label, index) => (
        <Page key={index} size={[mmToPt(layout.width), mmToPt(layout.height)]}>
          <LabelFace layout={layout} label={label} />
        </Page>
      ))}
    </Document>
  );
};

export default LabelsPDF;
