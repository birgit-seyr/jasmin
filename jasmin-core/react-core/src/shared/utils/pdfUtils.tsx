import { Text, View } from "@react-pdf/renderer";
import type { Styles } from "@react-pdf/renderer";
import type { ReactElement, ReactNode } from "react";

type Style = Styles[string];

/**
 * Loose shape for a table column as consumed by the PDF exporter. Every
 * field is optional because callers pass partial antd-style column configs
 * (the `pdf` sub-object carries the export-specific overrides).
 */
interface PdfColumn {
  children?: PdfColumn[];
  pdf?: PdfColumn;
  hasChildren?: boolean;
  parentTitle?: ReactNode;
  include?: boolean;
  width?: string | number;
  align?: "left" | "center" | "right";
  title?: ReactNode;
  headerStyle?: Style;
  style?: Style;
  dataKey?: string;
  dataIndex?: string;
  key?: string | number;
  render?: (item: Record<string, unknown>) => ReactNode;
  /** Render an empty bordered "tick box" cell (a printable ✓/done square)
   *  instead of text — staff tick it by hand on the printout. */
  tickBox?: boolean;
}

/**
 * Extract PDF-ready column definitions from table columns, handling nested
 * children.
 */
export const extractPdfColumns = (rawColumns: readonly unknown[]) => {
  const columns = rawColumns as PdfColumn[];

  // Flatten columns to handle children
  const flattenColumns = (cols: PdfColumn[]): PdfColumn[] => {
    const flattened: PdfColumn[] = [];
    cols.forEach((col) => {
      if (col.children && col.children.length > 0) {
        // Recursively flatten children
        flattened.push(...flattenColumns(col.children));
      } else if (col.pdf?.include) {
        // Only include columns that have PDF config and are marked for inclusion
        flattened.push({
          ...col.pdf,
          dataIndex: col.dataIndex,
          key: col.key,
          parentTitle: col.parentTitle, // Track parent title if needed
        });
      }
    });
    return flattened;
  };

  // Get structure for header rendering (preserving hierarchy)
  const getHeaderStructure = (
    cols: PdfColumn[],
    parentTitle: ReactNode = null,
  ): PdfColumn[] => {
    return cols.map((col) => {
      if (col.children && col.children.length > 0) {
        return {
          ...col,
          parentTitle,
          children: getHeaderStructure(col.children, col.title),
          hasChildren: true,
        };
      } else {
        return {
          ...col,
          parentTitle,
          hasChildren: false,
        };
      }
    });
  };

  const pdfColumns = flattenColumns(columns);
  const headerStructure = getHeaderStructure(
    columns.filter(
      (col) =>
        col.pdf?.include ||
        (col.children && col.children.some((child) => child.pdf?.include)),
    ),
  );

  const renderHeader = (baseStyles: Styles): ReactElement => {
    // Calculate if we need multi-level headers
    const hasNestedColumns = headerStructure.some((col) => col.hasChildren);

    if (!hasNestedColumns) {
      // Simple single-row header
      return (
        <View style={baseStyles.tableRow}>
          {pdfColumns.map((col, index) => (
            <View
              key={col.key}
              style={[
                baseStyles.tableColHeader,
                index === pdfColumns.length - 1 &&
                  baseStyles.tableColHeaderLast,
                { width: col.width },
              ].filter(Boolean) as Style[]}
            >
              <Text
                style={[
                  col.align === "center"
                    ? baseStyles.tableCellHeaderCenter
                    : col.align === "right"
                      ? baseStyles.tableCellHeaderRight
                      : baseStyles.tableCellHeaderLeft,
                  col.headerStyle || {},
                ]}
              >
                {col.title}
              </Text>
            </View>
          ))}
        </View>
      );
    }

    // Multi-level header rendering
    return (
      <View>
        {/* Parent header row */}
        <View style={baseStyles.tableRow}>
          {headerStructure.map((col, index) => {
            if (col.hasChildren) {
              // Calculate total width of children - FIX HERE
              const childrenWidth = (col.children ?? [])
                .filter((child) => child.pdf?.include)
                .reduce((total, child) => {
                  // Parse the width properly
                  const widthStr = child.pdf?.width;
                  const width =
                    typeof widthStr === "string"
                      ? parseFloat(widthStr.replace("%", ""))
                      : (widthStr ?? 0);
                  return total + (isNaN(width) ? 0 : width);
                }, 0);

              return (
                <View
                  key={col.key || `parent-${index}`}
                  style={[
                    baseStyles.tableColHeader,
                    { width: `${childrenWidth}%` },
                  ]}
                >
                  <Text
                    style={[
                      baseStyles.tableCellHeaderCenter,
                      col.headerStyle || {},
                    ]}
                  >
                    {col.title}
                  </Text>
                </View>
              );
            } else if (col.pdf?.include) {
              // Single column that spans both rows
              return (
                <View
                  key={col.key}
                  style={[
                    baseStyles.tableColHeader,
                    { width: col.pdf.width, minHeight: 40 }, // Double height for spanning
                  ]}
                >
                  <Text
                    style={[
                      col.pdf.align === "center"
                        ? baseStyles.tableCellHeaderCenter
                        : col.pdf.align === "right"
                          ? baseStyles.tableCellHeaderRight
                          : baseStyles.tableCellHeaderLeft,
                      col.pdf.headerStyle || {},
                    ]}
                  >
                    {col.pdf.title}
                  </Text>
                </View>
              );
            }
            return null;
          })}
        </View>

        {/* Children header row */}
        <View style={baseStyles.tableRow}>
          {headerStructure.map((col) => {
            if (col.hasChildren) {
              return (col.children ?? [])
                .filter((child) => child.pdf?.include)
                .map((child) => (
                  <View
                    key={child.key}
                    style={[
                      baseStyles.tableColHeader,
                      { width: child.pdf?.width },
                    ]}
                  >
                    <Text
                      style={[
                        child.pdf?.align === "center"
                          ? baseStyles.tableCellHeaderCenter
                          : child.pdf?.align === "right"
                            ? baseStyles.tableCellHeaderRight
                            : baseStyles.tableCellHeaderLeft,
                        child.pdf?.headerStyle || {},
                      ]}
                    >
                      {child.pdf?.title}
                    </Text>
                  </View>
                ));
            }
            return null; // Single columns are already rendered in the first row
          })}
        </View>
      </View>
    );
  };

  const renderRow = (
    item: Record<string, unknown>,
    baseStyles: Styles,
  ): ReactElement => (
    <View style={baseStyles.tableRow}>
      {pdfColumns.map((col, index) => {
        const value = col.render
          ? col.render(item)
          : (item[(col.dataKey || col.dataIndex) ?? ""] as ReactNode);

        return (
          <View
            key={col.key}
            style={[
              baseStyles.tableCol,
              index === pdfColumns.length - 1 && baseStyles.tableColLast,
              { width: col.width },
            ].filter(Boolean) as Style[]}
          >
            {col.tickBox ? (
              <View
                style={{
                  width: 11,
                  height: 11,
                  borderWidth: 1,
                  borderColor: "#666",
                  borderRadius: 2,
                  alignSelf: "center",
                }}
              />
            ) : (
              <Text
                style={[
                  baseStyles.tableCell,
                  col.align === "center"
                    ? baseStyles.tableCellCenter
                    : col.align === "right"
                      ? baseStyles.tableCellAmount
                      : baseStyles.tableCellLeft,
                  col.style || {},
                ]}
              >
                {value || "—"}
              </Text>
            )}
          </View>
        );
      })}
    </View>
  );

  return {
    pdfColumns,
    renderHeader,
    renderRow,
    hasNestedColumns: headerStructure.some((col) => col.hasChildren),
  };
};

export const stripHtmlToText = (html: string | null | undefined): string => {
  if (!html) return "";
  let text = html.replace(/<br\s*\/?>/gi, "\n");
  text = text.replace(/<\/p>/gi, "\n");
  text = text.replace(/<[^>]*>/g, "");
  // Decode HTML entities without using DOM
  text = text
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#039;/g, "'")
    .replace(/&nbsp;/g, " ");
  // Collapse whitespace introduced by HTML that's pretty-printed across
  // source lines: a literal newline between two ``<p>`` tags (or before
  // a ``<br/>``) survives the tag strip and stacks with the ``\n`` we
  // emitted for ``</p>`` / ``<br/>``, producing a blank line in the
  // rendered PDF for every wrapped paragraph. Normalise:
  //   - strip trailing spaces/tabs at end of each line
  //   - collapse runs of two-or-more newlines (mixed with whitespace)
  //     down to a single newline so paragraphs render flush
  text = text
    .replace(/[ \t]+\n/g, "\n")
    .replace(/(?:[ \t]*\n[ \t]*){2,}/g, "\n");
  return text.trim();
};
