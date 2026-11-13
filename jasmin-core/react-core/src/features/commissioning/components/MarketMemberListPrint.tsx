/**
 * The member list for the market stand: the cooperative's current members by
 * last name, fetched only when the list is printed.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { getCommissioningMembersListQueryOptions } from "@shared/api/generated/commissioning/commissioning";
import type { Member } from "@shared/api/generated/models";
import { generatePdfFilename } from "@shared/utils";
import { todayApiDate } from "@shared/utils/apiDate";
import { useDateFormat } from "@hooks/index";
import { MarketMemberListPDFGenerator } from "@features/commissioning/pdfs";
import type { MarketMemberListItem } from "@features/commissioning/pdfs/exports/MarketMemberListPDF";

/** The members the cooperative has today: confirmed, numbered and not yet
 *  past their exit date, by last name (a company by its name). */
function currentMembersByName(
  members: Member[],
  today: string,
): MarketMemberListItem[] {
  return members
    .flatMap((member) =>
      member.admin_confirmed &&
      member.member_number != null &&
      (!member.cancelled_effective_at || member.cancelled_effective_at >= today)
        ? [
            {
              id: member.id,
              last_name: member.last_name || member.company_name || "",
              first_name: member.first_name ?? "",
              member_number: member.member_number,
            },
          ]
        : [],
    )
    .sort(
      (a, b) =>
        a.last_name.localeCompare(b.last_name, "de") ||
        a.first_name.localeCompare(b.first_name, "de"),
    );
}

export default function MarketMemberListPrint() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { formatDate } = useDateFormat();

  const loadDocumentProps = useCallback(async () => {
    const members = await queryClient.fetchQuery(
      // ``is_active=false`` is an anonymised member.
      getCommissioningMembersListQueryOptions({ is_active: true }),
    );
    const today = todayApiDate();
    return {
      members: currentMembersByName(members, today),
      asOf: formatDate(today) ?? today,
      t,
    };
  }, [queryClient, formatDate, t]);

  return (
    <MarketMemberListPDFGenerator
      loadDocumentProps={loadDocumentProps}
      filename={generatePdfFilename([
        t("commissioning.market_member_list"),
        todayApiDate(),
      ])}
      buttonText={t("commissioning.market_member_list_pdf")}
    />
  );
}
