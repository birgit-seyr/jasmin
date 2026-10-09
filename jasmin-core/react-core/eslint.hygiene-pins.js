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
  "src/features/abos/modals/NewSubscriptionModal.tsx": 91,
  "src/features/auth/pages/LoginPage.tsx": 31,
  "src/features/commissioning/components/OrderInfoPanel.tsx": 32,
  "src/features/commissioning/hooks/columns/useOrderColumns.tsx": 31,
  "src/features/commissioning/modals/ShareTypeVariationModal.tsx": 32,
  "src/features/commissioning/pdfs/forResellers/InvoicePDF.tsx": 29,
  "src/features/commissioning/pdfs/zugferd.ts": 34,
  "src/features/configuration/components/SettingsRenderer.tsx": 32,
  "src/features/configuration/pages/ConfigurationGeneral.tsx": 36,
  "src/features/customer/components/CustomerDocumentsCard.tsx": 28,
  "src/features/members/components/CurrentWeekDeliveryCard.tsx": 26,
  "src/features/members/components/UpcomingDeliveriesCard.tsx": 37,
  "src/features/members/modals/AdminConfirmationModalMembers.tsx": 26,
  "src/features/members/modals/CoopSharesModal.tsx": 34,
  "src/features/members/modals/DeliveryStationMemberModal.tsx": 42,
  "src/features/members/pages/MemberDetail.tsx": 26,
  "src/features/members/pages/Members.tsx": 42,
  "src/features/public/pages/PublicLegalNoticePage.tsx": 59,
  "src/shared/modals/UserInfoModal.tsx": 50,
  "src/shared/services/api.ts": 30,
  "src/shared/tables/BasicEditableTable/EditableCell.tsx": 34,
  "src/shared/tables/BasicEditableTable/EditableTable.tsx": 50,
  "src/shared/tables/BasicEditableTable/FormInput.tsx": 35,
  "src/shared/tables/BasicEditableTable/useEditableTable.ts": 41,
  "src/shared/ui/JobProgressDrawer.tsx": 34,
};

// Longest function per file, blank lines and comments excluded.
export const functionLengthPins = {
  "src/features/abos/hooks/columns/useAbosColumns.tsx": 586,
  "src/features/abos/modals/NewSubscriptionModal.tsx": 892,
  "src/features/abos/pages/WaitingListAbos.tsx": 469,
  "src/features/commissioning/hooks/columns/useHarvestingListColumns.tsx": 458,
  "src/features/commissioning/hooks/columns/useOrderColumns.tsx": 429,
  "src/features/commissioning/hooks/columns/useShareArticleListColumns.tsx": 490,
  "src/features/commissioning/hooks/useOrdersData.ts": 616,
  "src/features/commissioning/modals/DeliveryStationDetailModal.tsx": 415,
  "src/features/commissioning/modals/InvoiceModal.tsx": 407,
  "src/features/commissioning/modals/ShareTypeVariationModal.tsx": 601,
  "src/features/commissioning/pages/DeliveryNotes.tsx": 460,
  "src/features/commissioning/pages/Forecast.tsx": 428,
  "src/features/commissioning/pages/Invoices.tsx": 753,
  "src/features/commissioning/pages/ListResellers.tsx": 404,
  "src/features/commissioning/pages/LoggingStorage.tsx": 457,
  "src/features/commissioning/pages/Orders.tsx": 474,
  "src/features/commissioning/pages/PlanningShareContentBase.tsx": 832,
  "src/features/commissioning/pages/PlanningShareContentLongTermBase.tsx": 519,
  "src/features/commissioning/pages/PurchaseList.tsx": 493,
  "src/features/configuration/pages/ConfigurationGeneral.tsx": 451,
  "src/features/members/modals/CoopSharesModal.tsx": 467,
  "src/features/members/pages/Members.tsx": 768,
  "src/shared/layout/sidebars/CommissioningSidebar.tsx": 601,
  "src/shared/tables/BasicEditableTable/EditableTable.tsx": 836,
  "src/shared/tables/BasicEditableTable/FormInput.tsx": 472,
  "src/shared/tables/BasicEditableTable/useEditableTable.ts": 536,
};

// Total file length, blank lines and comments INCLUDED — a file you have to
// scroll is a file you have to scroll.
export const fileLengthPins = {
  "src/features/abos/modals/NewSubscriptionModal.tsx": 1272,
  "src/features/commissioning/pages/PlanningShareContentBase.tsx": 1225,
  "src/features/members/pages/Members.tsx": 1018,
  "src/shared/tables/BasicEditableTable/EditableTable.tsx": 1146,
};
