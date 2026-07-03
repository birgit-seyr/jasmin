import type { ReactNode } from "react";
import { Document, Page, Text, View } from "@react-pdf/renderer";
import { useTranslation } from "react-i18next";
import "../registerRoboto";
import { baseStyles } from "./baseStyles";
import { listStyles } from "./listPdfBase";
import { ListPDFFooter, ListPDFHeader } from "./ListPDFSharedComponents";
import { extractPdfColumns } from "@shared/utils/pdfUtils";

interface BaseListPDFProps {
  data: Record<string, unknown>[];
  title: string;
  subtitle: string;
  /** Green-outline category pill above the title (e.g. the list name). */
  pill?: string;
  columns: unknown[];
  /** Rendered once, on the first page, before the table (e.g. a totals
   *  card). Flows naturally — no manual line budgeting. */
  firstPageContent?: ReactNode;
  /** Page orientation. Defaults to portrait; the harvest list uses
   *  landscape because it carries many (dynamic) columns. */
  orientation?: "portrait" | "landscape";
}

/**
 * Generic table-style PDF that renders a single ``data`` array with the
 * column set described by ``columns`` (via ``extractPdfColumns``). Used by
 * PurchaseList (through PurchaseListPDFGenerator) and as the inner table for
 * HarvestingListPDF.
 *
 * Built exactly like the hand-rolled list PDFs (WashingListPDF et al.): one
 * ``Page`` with the shared ``ListPDFHeader``/``ListPDFFooter``, a ``fixed``
 * table header that repeats, and rows that flow with react-pdf's natural
 * pagination. (It previously went through a bespoke ``PaginatedDocument``
 * that sliced the data into pages by hand and budgeted vertical space for
 * the first-page content — unnecessary now that the table just wraps.)
 */
const BaseListPDF = ({
  data,
  title,
  subtitle,
  pill,
  columns,
  firstPageContent,
  orientation = "portrait",
}: BaseListPDFProps) => {
  const { t } = useTranslation();
  const pdfConfig = extractPdfColumns(columns);

  return (
    <Document>
      <Page size="A4" orientation={orientation} style={listStyles.page}>
        <ListPDFHeader pill={pill}>
          <Text style={listStyles.title}>{title}</Text>
          {subtitle ? (
            <Text style={listStyles.subtitle}>{subtitle}</Text>
          ) : null}
        </ListPDFHeader>

        {firstPageContent}

        {data.length > 0 && (
          <View style={baseStyles.table}>
            {/* ``fixed`` so the column header repeats on every page. */}
            <View fixed>{pdfConfig.renderHeader(baseStyles)}</View>
            {data.map((item, index) => {
              const key =
                (item.id as string) ||
                (item.key as string) ||
                (item.share_article as string) ||
                `item-${index}`;
              return (
                <View key={key} wrap={false}>
                  {pdfConfig.renderRow(item, baseStyles)}
                </View>
              );
            })}
          </View>
        )}

        <ListPDFFooter t={t} />
      </Page>
    </Document>
  );
};

export default BaseListPDF;
