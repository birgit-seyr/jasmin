// Hygiene debt register for the size/complexity gates in eslint.config.js.
//
// Each entry pins ONE file at the worst value it currently has, instead of
// switching the rule off for that file. A pin is a ceiling: the file cannot get
// worse, and a new oversized function added to an already-listed file still
// fails. Switching the rule off per file would have blinded these exact files —
// the ones most likely to grow — which is the opposite of what the gate is for.
//
// The numbers are measured, not chosen. To shrink one: split the function or the
// file, re-run `npm run lint`, and lower the number to whatever the file now
// reports (delete the entry once it drops under the global threshold). A pin may
// only ever go DOWN — raising one is how a gate quietly stops gating.
//
// Global thresholds live in eslint.config.js: complexity 25,
// max-lines-per-function 400, max-lines 1000.

// Cyclomatic complexity per function; worst function in each file.
export const complexityPins = {
  "src/features/abos/modals/AdminConfirmationModalAbos.tsx": 27,
  "src/features/abos/modals/NewSubscriptionModal.tsx": 93,
  "src/features/auth/pages/LoginPage.tsx": 31,
  "src/features/commissioning/components/mobileCards/HarvestingMobileCard.tsx": 28,
  "src/features/commissioning/components/OrderInfoPanel.tsx": 32,
  "src/features/commissioning/hooks/columns/useOrderColumns.tsx": 31,
  "src/features/commissioning/modals/ShareTypeVariationModal.tsx": 32,
  "src/features/commissioning/pages/PlanningShareContentBase.tsx": 26,
  "src/features/commissioning/pdfs/forResellers/InvoicePDF.tsx": 30,
  "src/features/commissioning/pdfs/zugferd.ts": 34,
  "src/features/configuration/components/SettingsRenderer.tsx": 34,
  "src/features/configuration/pages/ConfigurationGeneral.tsx": 36,
  "src/features/customer/components/CustomerDocumentsCard.tsx": 28,
  "src/features/customer/components/CustomerOrderHeader.tsx": 27,
  "src/features/members/components/CurrentWeekDeliveryCard.tsx": 26,
  "src/features/members/components/UpcomingDeliveriesCard.tsx": 37,
  "src/features/members/modals/AdminConfirmationModalMembers.tsx": 26,
  "src/features/members/modals/CoopSharesModal.tsx": 35,
  "src/features/members/modals/DeliveryStationMemberModal.tsx": 44,
  "src/features/members/pages/MemberDetail.tsx": 34,
  "src/features/members/pages/Members.tsx": 50,
  "src/features/public/pages/PublicLegalNoticePage.tsx": 59,
  "src/shared/modals/UserInfoModal.tsx": 50,
  "src/shared/services/api.ts": 32,
  "src/shared/tables/BasicEditableTable/EditableCell.tsx": 34,
  "src/shared/tables/BasicEditableTable/EditableTable.tsx": 51,
  "src/shared/tables/BasicEditableTable/FormInput.tsx": 35,
  "src/shared/tables/BasicEditableTable/useEditableTable.ts": 65,
  "src/shared/ui/JobProgressDrawer.tsx": 35,
};

// Longest function per file, blank lines and comments excluded.
export const functionLengthPins = {
  "src/features/abos/hooks/columns/useAbosColumns.tsx": 590,
  "src/features/abos/modals/NewSubscriptionModal.tsx": 901,
  "src/features/abos/pages/WaitingListAbos.tsx": 470,
  "src/features/commissioning/hooks/columns/useHarvestingListColumns.tsx": 484,
  "src/features/commissioning/hooks/columns/useOrderColumns.tsx": 433,
  "src/features/commissioning/hooks/columns/useShareArticleListColumns.tsx": 490,
  "src/features/commissioning/hooks/useOrdersData.ts": 634,
  "src/features/commissioning/modals/DeliveryStationDetailModal.tsx": 455,
  "src/features/commissioning/modals/InvoiceModal.tsx": 486,
  "src/features/commissioning/modals/ShareTypeVariationModal.tsx": 611,
  "src/features/commissioning/pages/DeliveryNotes.tsx": 481,
  "src/features/commissioning/pages/DeliveryStationsDetails.tsx": 440,
  "src/features/commissioning/pages/Forecast.tsx": 464,
  "src/features/commissioning/pages/Invoices.tsx": 763,
  "src/features/commissioning/pages/ListResellers.tsx": 413,
  "src/features/commissioning/pages/LoggingStorage.tsx": 497,
  "src/features/commissioning/pages/Orders.tsx": 477,
  "src/features/commissioning/pages/PackingListBulk.tsx": 413,
  "src/features/commissioning/pages/PlanningShareContentBase.tsx": 859,
  "src/features/commissioning/pages/PlanningShareContentLongTermBase.tsx": 561,
  "src/features/commissioning/pages/PurchaseList.tsx": 528,
  "src/features/configuration/pages/ConfigurationGeneral.tsx": 453,
  "src/features/members/modals/CoopSharesModal.tsx": 472,
  "src/features/members/pages/MemberDetail.tsx": 437,
  "src/features/members/pages/Members.tsx": 826,
  "src/shared/layout/sidebars/CommissioningSidebar.tsx": 610,
  "src/shared/tables/BasicEditableTable/EditableTable.tsx": 925,
  "src/shared/tables/BasicEditableTable/FormInput.tsx": 481,
  "src/shared/tables/BasicEditableTable/useEditableTable.ts": 595,
};

// Total file length, blank lines and comments INCLUDED — a file you have to
// scroll is a file you have to scroll.
export const fileLengthPins = {
  "src/features/abos/modals/NewSubscriptionModal.tsx": 1280,
  "src/features/commissioning/pages/PlanningShareContentBase.tsx": 1252,
  "src/features/members/pages/Members.tsx": 1078,
  "src/shared/tables/BasicEditableTable/EditableTable.tsx": 1278,
};
