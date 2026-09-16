/**
 * One crate line of the harvesting list's first-page crate summary. Lives in
 * its own module so ``HarvestingListPDFGenerator`` can type the prop without
 * statically importing ``HarvestingListPDF`` — that import would pull
 * @react-pdf/renderer into the eager bundle.
 */
export interface CrateQuantity {
  crate_name?: string;
  quantity?: number;
}
