import { useMemo } from "react";
import { useCommissioningMembersList } from "@shared/api/generated/commissioning/commissioning";
import type { Member, CommissioningMembersListParams } from "@shared/api/generated/models";
import { toOptions, type Option } from "./internal/toOptions";

export type MemberOption = Option<Member>;

export const useMembers = (params: CommissioningMembersListParams = {}) => {
  const { data, isLoading, error, refetch } = useCommissioningMembersList(params);

  const members: MemberOption[] = useMemo(
    () =>
      toOptions(data, (m) => {
        const name = `${m.first_name ?? ""} ${m.last_name ?? ""}`.trim();
        return m.member_number ? `${m.member_number} - ${name}` : name;
      }),
    [data],
  );

  return {
    members,
    loading: isLoading,
    error,
    refetch,
  };
};
