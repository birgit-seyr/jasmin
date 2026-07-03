const MemberLoans = () => {
  return <div>coming soon ...</div>;
};

export default MemberLoans;

// import { useQueryClient } from "@tanstack/react-query";
// import dayjs from "dayjs";
// import { useCallback, useMemo, useState } from "react";
// import { useTranslation } from "react-i18next";
// import {
//   commissioningMemberLoansCreate,
//   commissioningMemberLoansDestroy,
//   commissioningMemberLoansPartialUpdate,
//   getCommissioningMemberLoansListQueryKey,
//   useCommissioningMemberLoansList,
// } from "@shared/api/generated/commissioning/commissioning";
// import type { MemberLoan } from "@shared/api/generated/models";
// import { useRoles } from "@shared/auth";
// import { MemberSelector, YearSelector } from "@shared/selectors";
// import {
//   EditableTable,
//   gatedByPermission,
//   wrapApiFunctions,
// } from "@shared/tables";
// import type {
//   ApiFunctions,
//   EditableColumnConfig,
//   TableRecord,
// } from "@shared/tables/BasicEditableTable/types";
// import { ExplainerText, SummaryStatsCard } from "@shared/ui";
// import {
//   useCurrency,
//   useDateFormat,
//   useInvalidateAfterTableMutation,
//   useMembers,
//   useNumberFormat,
//   useTableRowSelection,
// } from "@hooks/index";

// export default function MemberLoans() {
//   const queryClient = useQueryClient();

//   const [selectedMember, setSelectedMember] = useState<string | null>(null);
//   const [selectedYear, setSelectedYear] = useState(dayjs().year());

//   const { t } = useTranslation();
//   const { isOffice } = useRoles();
//   const permissions = useMemo(() => gatedByPermission(isOffice), [isOffice]);
//   const { currencySymbol } = useCurrency();
//   const { format } = useNumberFormat();
//   const { formatDate } = useDateFormat();
//   const { members } = useMembers({ exclude_trial_members: true });

//   // Block selection of the placeholder add-row, and of loans the
//   // office already admin-confirmed (the AdminConfirmableMixin
//   // flips ``admin_confirmed`` once an office user signs off; we
//   // don't want bulk actions over finalized rows).
//   const {
//     selectedRowKeys,
//     onSelectedRowsChange: handleRowSelectionChange,
//     rowSelection: rowSelectionConfig,
//   } = useTableRowSelection(
//     (record: TableRecord) =>
//       record.key === -1 || Boolean(record.admin_confirmed),
//   );

//   // Single source of truth for the filter params: used both by the
//   // ``useQuery`` fetch and as ``baseParams`` for EditableTable so the
//   // two can't drift.
//   const listParams = useMemo(
//     () => ({
//       year: selectedYear,
//       ...(selectedMember !== null ? { member: selectedMember } : {}),
//     }),
//     [selectedYear, selectedMember],
//   );

//   // ``isFetching`` (not ``isLoading``) so the grid overlay shows on every
//   // member/param change — with the global ``staleTime: 0`` a cached key has
//   // ``isLoading === false`` and would otherwise show no spinner.
//   const { data: rawData, isFetching } =
//     useCommissioningMemberLoansList(listParams);
//   const data = useMemo(
//     () => (rawData ?? []) as unknown as TableRecord[],
//     [rawData],
//   );

//   // Mirrors the ``Members.tsx`` pattern — generated CRUD wrapped so
//   // EditableTable's controlled-state contract still works. No raw URLs.
//   // No ``list``: this page owns the data via ``useCommissioningMemberLoansList``
//   // (passed as ``initialData``). Supplying ``list`` would make EditableTable
//   // double-fetch the same endpoint (it auto-fetches when ``showSearchBar`` +
//   // ``apiFunctions.list`` are both set). Search filters client-side; mutations
//   // refresh through the ``onSaveSuccess``/``onDeleteSuccess`` invalidation.
//   const apiFunctions = useMemo<ApiFunctions>(
//     () =>
//       wrapApiFunctions<MemberLoan & TableRecord>({
//         create: (data) => commissioningMemberLoansCreate(data),
//         update: (id, data) => commissioningMemberLoansPartialUpdate(id, data),
//         delete: (id) => commissioningMemberLoansDestroy(id),
//       }),
//     [],
//   );

//   const summaryStats = useMemo(() => {
//     const totalLoans = data.reduce(
//       (sum, record) => sum + (Number(record.amount) || 0),
//       0,
//     );
//     return { totalLoans };
//   }, [data]);

//   const columns = useMemo<EditableColumnConfig<TableRecord>[]>(
//     () => [
//       {
//         title: <>{t("members.member")}</>,
//         dataIndex: "member_string",
//         key: "member_string",
//         inputType: "select",
//         fixed: true,
//         align: "left",
//         width: "18em",
//         hidden: selectedMember != null,
//         options: members,
//         foreignKey: {
//           valueField: "member",
//           displayField: "member_string",
//         },
//         sortable: true,
//       },
//       {
//         title: t("members.amount_of_member_loans"),
//         dataIndex: "amount",
//         key: "amount",
//         inputType: "positive_integer",
//         align: "center",
//         width: "8em",
//         required: true,
//         sortable: true,
//         render: (value: unknown) => (value ? format(Number(value), 0) : ""),
//       },
//       {
//         title: t("members.interest_rate"),
//         dataIndex: "interest_rate",
//         key: "interest_rate",
//         inputType: "positive_decimal2",
//         align: "center",
//         width: "8em",
//         suffix: "%",
//         required: true,
//         sortable: true,
//         render: (value: unknown) =>
//           value ? `${format(Number(value), 2)}%` : "",
//       },
//       {
//         title: t("members.start_date"),
//         dataIndex: "start_date",
//         key: "start_date",
//         inputType: "date",
//         align: "center",
//         required: false,
//         width: "10em",
//         sortable: true,
//         render: (value: unknown) => formatDate(value as string | null),
//       },
//       {
//         title: t("members.end_date"),
//         dataIndex: "end_date",
//         key: "end_date",
//         inputType: "date",
//         align: "center",
//         required: false,
//         width: "10em",
//         sortable: true,
//         render: (value: unknown) => formatDate(value as string | null),
//       },
//       {
//         title: t("members.paid_back_date"),
//         dataIndex: "paid_back_date",
//         key: "paid_back_date",
//         inputType: "date",
//         align: "center",
//         required: false,
//         width: "10em",
//         sortable: true,
//         render: (value: unknown) => formatDate(value as string | null),
//       },
//       {
//         title: t("members.cancelled_reason"),
//         dataIndex: "cancelled_reason",
//         key: "cancelled_reason",
//         inputType: "text",
//         align: "left",
//         required: false,
//       },
//     ],
//     [t, selectedMember, members, format, formatDate],
//   );

//   const customSave = useCallback(
//     (transformedData: Record<string, unknown>) => {
//       // New rows inherit the active filter values so the office
//       // doesn't have to re-pick year + member after each save.
//       return {
//         ...transformedData,
//         year: selectedYear,
//         member:
//           selectedMember == null ? transformedData.member : selectedMember,
//       };
//     },
//     [selectedYear, selectedMember],
//   );

//   const handleDataChange = useCallback(() => {
//     queryClient.invalidateQueries({
//       queryKey: getCommissioningMemberLoansListQueryKey(),
//     });
//   }, [queryClient]);

//   // Stop reorder-on-save on inline edits — same pattern Members.tsx
//   // uses. Save / delete bypass the broader invalidation so the row
//   // stays where it was on the page.
//   const { onSaveSuccess, onDeleteSuccess } =
//     useInvalidateAfterTableMutation(handleDataChange);

//   return (
//     <div>
//       <h1>{t("members.loans")}</h1>
//       <YearSelector
//         selectedYear={selectedYear}
//         setSelectedYear={setSelectedYear}
//       />
//       <MemberSelector
//         selectedMember={selectedMember}
//         setSelectedMember={setSelectedMember}
//         include_null_option={true}
//         excludeTrialMembers={true}
//       />

//       <SummaryStatsCard
//         stats={[
//           {
//             label: t("members.total_loans"),
//             value: summaryStats.totalLoans
//               ? `${format(summaryStats.totalLoans, 0)}${currencySymbol}`
//               : "",
//           },
//         ]}
//       />

//       <EditableTable
//         columns={columns}
//         apiFunctions={apiFunctions}
//         focusIndex="amount"
//         initialData={data}
//         loading={isFetching}
//         onSaveSuccess={onSaveSuccess}
//         onDeleteSuccess={onDeleteSuccess}
//         customSave={customSave}
//         permissions={permissions}
//         pagination={true}
//         showSearchBar={true}
//         rowSelection={rowSelectionConfig}
//         onSelectedRowsChange={handleRowSelectionChange}
//         selectedRowKeys={selectedRowKeys}
//       />

//       <ExplainerText title={t("common.info")}>
//         {t("explainers.member_loans")}
//       </ExplainerText>
//     </div>
//   );
// }
