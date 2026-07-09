export {
    calculateTableScrollWidth,
    createStringSorter,
    createNumberSorter,
    createDateSorter,
    createBooleanSorter,
} from './tableUtils'

export {
    getDateRangeStatus,
    createDateRangeStatusSorter,
    createDateRangeStatusRenderer,
    isFieldDisabled,
    editableOnlyOnCreate,
    getStatusColor,
    DATE_RANGE_STATUS_COLOR
} from './columnUtils';

export { decimalsForUnit, formatAmountForUnit, renderNumber } from './amountFormat';
export { getShareOptionLabel } from './shareOptionLabel';

export { getDayName } from './dayNamesUtil';
export { generatePdfFilename, formatWeekLabel, formatDayLabel } from './filenameUtils';
// NB: pdfUtils (extractPdfColumns / stripHtmlToText) is intentionally NOT
// re-exported here. It statically imports @react-pdf/renderer (~484KB gzip),
// and re-exporting through this barrel pulled that library into the entry
// chunk for every page (the barrel is imported app-wide). PDF-only consumers
// import from "@shared/utils/pdfUtils" directly so the lib stays in the lazy
// PDF chunks.
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
export { toApiDate } from './apiDate';
export { unwrapList } from './unwrapList';
export { buildMonthAxis } from './monthAxis';
export type { MonthAxis } from './monthAxis';