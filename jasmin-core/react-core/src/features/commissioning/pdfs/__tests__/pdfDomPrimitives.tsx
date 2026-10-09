import type { ReactNode } from "react";

/**
 * DOM stand-ins for the @react-pdf/renderer primitives, so a document's
 * tree renders into jsdom and its printed text, styles and page flags can be
 * read with Testing Library. Spread into a ``vi.mock("@react-pdf/renderer")``
 * factory on top of the real module (which keeps ``StyleSheet`` / ``Font``).
 *
 * A ``Text`` with a ``render`` prop prints what it returns for page
 * ``PDF_PAGE_INFO.pageNumber`` of ``PDF_PAGE_INFO.totalPages``.
 */
export const PDF_PAGE_INFO = { pageNumber: 2, totalPages: 5 };

type StyleInput = unknown;

/** Merge a react-pdf style (object, array, nested arrays, falsy entries) into
 *  one plain object, the way react-pdf resolves it. */
export function flattenStyle(style: StyleInput): Record<string, unknown> {
  if (!style) return {};
  if (Array.isArray(style)) {
    return Object.assign({}, ...style.map((entry) => flattenStyle(entry)));
  }
  if (typeof style === "object") return { ...(style as object) };
  return {};
}

interface PrimitiveProps {
  children?: ReactNode;
  style?: StyleInput;
  fixed?: boolean;
  wrap?: boolean;
  render?: (info: typeof PDF_PAGE_INFO) => ReactNode;
  src?: string;
  orientation?: string;
  size?: string;
}

const styleAttr = (style: StyleInput) => JSON.stringify(flattenStyle(style));

export function pdfDomPrimitives() {
  return {
    Document: ({ children }: PrimitiveProps) => (
      <div data-pdf="document">{children}</div>
    ),
    Page: ({ children, orientation, size, style }: PrimitiveProps) => (
      <div
        data-pdf="page"
        data-orientation={orientation ?? "portrait"}
        data-size={size}
        data-style={styleAttr(style)}
      >
        {children}
      </div>
    ),
    View: ({ children, style, fixed, wrap }: PrimitiveProps) => (
      <div
        data-pdf="view"
        data-style={styleAttr(style)}
        data-fixed={fixed ? "true" : undefined}
        data-wrap={wrap === false ? "false" : undefined}
      >
        {children}
      </div>
    ),
    Text: ({ children, style, render, fixed }: PrimitiveProps) => (
      <span
        data-pdf="text"
        data-style={styleAttr(style)}
        data-fixed={fixed ? "true" : undefined}
      >
        {render ? render(PDF_PAGE_INFO) : children}
      </span>
    ),
    Image: ({ src }: PrimitiveProps) => (
      <img data-pdf="image" alt="" src={src} />
    ),
    PDFViewer: ({ children }: PrimitiveProps) => (
      <div data-pdf="viewer">{children}</div>
    ),
  };
}

/** The parsed ``data-style`` of a rendered primitive. */
export function styleOf(element: Element | null): Record<string, unknown> {
  const raw = element?.getAttribute("data-style");
  return raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
}
