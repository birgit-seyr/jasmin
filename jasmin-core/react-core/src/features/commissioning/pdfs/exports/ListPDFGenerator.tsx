import { useState } from "react";
import type { ComponentType } from "react";
import { Button } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import { downloadBlob } from "@shared/utils";

/**
 * Click-to-load list-PDF download button.
 *
 * Replaces the old ``<PDFDownloadLink>``-based ``ListPDFGenerator``
 * (which lived in ``ListPDFSharedComponents.tsx`` and statically
 * imported ``@react-pdf/renderer``). The whole point of splitting
 * this into its own file is to keep ``@react-pdf/renderer`` out of
 * the eager bundle: the only PDF-library import is INSIDE the click
 * handler.
 *
 * Pages that render this button (e.g. CleaningList, PackingListBoxes,
 * DeliveryStationsOverview, ...) now cost ~0 bytes of PDF library
 * payload at boot. The ~484 KB gzip ``@react-pdf/renderer`` chunk
 * only downloads when the user actually clicks Download.
 *
 * The wrappers (CleaningListPDFGenerator, PackingListPDFGenerator,
 * ...) pass a ``documentLoader`` that does a dynamic ``import()``,
 * so the document template itself ALSO stays out of the eager
 * bundle until clicked.
 */
interface ListPDFGeneratorProps<T, DocProps extends object> {
  /** Used purely as a readiness gate — when null/undefined or
   * ``isReady`` is false, the button is disabled. The wrapper is
   * responsible for passing the actual data INTO the document via
   * ``documentProps`` with whatever prop name the document expects
   * (``data``, ``pages``, ``tours``, ...). */
  data: T | null | undefined;
  isReady?: boolean;
  filename: string;
  buttonText: string;
  /** Dynamic-import factory for the PDF document component. The
   * loaded component is rendered with ``documentProps`` spread into
   * it — TypeScript checks the loader's return matches the props
   * shape, so passing the wrong-shape ``documentProps`` is a
   * compile error at the wrapper, not a runtime surprise. */
  documentLoader: () => Promise<{ default: ComponentType<DocProps> }>;
  /** All props passed to the loaded document component. Pinned to
   * the same ``DocProps`` type as ``documentLoader``'s return. */
  documentProps: DocProps;
}

export default function ListPDFGenerator<T, DocProps extends object>({
  data,
  isReady = true,
  filename,
  buttonText,
  documentLoader,
  documentProps,
}: ListPDFGeneratorProps<T, DocProps>) {
  const [generating, setGenerating] = useState(false);

  // Disable the button when there's nothing to export. ``data`` is the
  // readiness gate; an EMPTY array is still truthy, so check length when it's
  // an array — this keeps every list's Download disabled on no data without
  // each caller having to null-guard.
  const enabled = (Array.isArray(data) ? data.length > 0 : !!data) && isReady;

  const handleClick = async () => {
    if (!enabled) return;
    setGenerating(true);
    try {
      // Parallel: load the PDF library AND the document template
      // concurrently. Both stay in lazy chunks until this point.
      const [{ pdf }, { default: Document }] = await Promise.all([
        import("@react-pdf/renderer"),
        documentLoader(),
      ]);

      const blob = await pdf(<Document {...documentProps} />).toBlob();

      downloadBlob(blob, `${filename}.pdf`);
    } catch (error) {
      console.error("PDF generation error:", error);
    } finally {
      setGenerating(false);
    }
  };

  return (
    <Button
      type="primary"
      className="download-button"
      icon={<DownloadOutlined />}
      onClick={handleClick}
      loading={generating}
      disabled={!enabled}
    >
      {buttonText}
    </Button>
  );
}
