export { calculateTableScrollWidth } from './tableScrollWidth';
export {
    createStringSorter,
    createNumberSorter,
    createDateSorter,
    createBooleanSorter,
} from './tableSorters';

export {
    getDateRangeStatus,
    createDateRangeStatusSorter,
    createDateRangeStatusRenderer,
    DATE_RANGE_STATUS_COLOR
} from './dateRangeStatus';

export {
    isFieldDisabled,
    editableOnlyOnCreate,
    getStatusColor,
} from './columnEditability';

export { decimalsForUnit, formatAmountForUnit, renderNumber } from './amountFormat';
export { getShareOptionLabel } from './shareOptionLabel';

export { getDayName } from './weekdayNames';
export { generatePdfFilename } from './pdfFilename';
export { formatWeekLabel, formatDayLabel } from './weekLabels';
// NB: pdfColumns (extractPdfColumns) is intentionally NOT re-exported here.
// It statically imports @react-pdf/renderer, pulling in the ~450 kB gzip PDF chunk, and re-exporting
// through this barrel pulls that library into the entry chunk for every page
// (the barrel is imported app-wide). PDF-only consumers import from
// "@shared/utils/pdfColumns" directly so the lib stays in the lazy PDF chunks.
export {
    hasPurchasedSuffix,
    removePurchasedSuffix,
    syncPurchasedName,
} from './purchasedName';
export { default as notify } from './notify';
export { logger } from './logger';
export { buildCsvString, downloadCsvBlob, resolveCsvDialect } from './csv';
export { downloadBlob } from './downloadBlob';
export { openStoredPdf } from './openStoredPdf';
export { zipFilesToBlob } from './zip';
export type { ZipEntry } from './zip';
export { activeAtDateForWeek, dateForWeekDayNumber, isoWeekRangeLabel, isWeekInPast, isYearInPast } from './weekRange';
export { pickTierPrice, pickTierPriceFromAmount } from './tierPrice';
export { isSepaMandateActiveForTerm } from './sepaMandate';
export { variationAllowsTrial, filterVariationsForTrial } from './trialVariations';
export type { TrialAllowable } from './trialVariations';
export { toApiDate } from './apiDate';
export { unwrapList } from './unwrapList';
export { buildMonthAxis } from './monthAxis';
export type { MonthAxis } from './monthAxis';