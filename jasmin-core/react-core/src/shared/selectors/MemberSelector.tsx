import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { CommissioningMembersListParams } from "@shared/api/generated/models";
import { useMembers } from "@hooks/index";
import type { MemberOption } from "@hooks/useMembers";
import BaseEntitySelector, { type SelectorOption } from "./BaseEntitySelector";

interface MemberSelectorProps {
  selectedMember: string | null;
  setSelectedMember: (value: string | null) => void;
  onMemberChange?: ((value: string | null) => void) | null;
  include_null_option?: boolean;
  onlyWithSubscriptions?: boolean | null;
  excludeTrialMembers?: boolean | null;
  /** Keeps only the members this returns true for. */
  filterMember?: (member: MemberOption) => boolean;
  /** Replaces the default fixed width and left margin, e.g. inside a form. */
  className?: string;
  ariaLabel?: string;
}

const MemberSelector = ({
  selectedMember,
  setSelectedMember,
  onMemberChange = null,
  include_null_option = false,
  onlyWithSubscriptions = null,
  excludeTrialMembers = null,
  filterMember,
  className,
  ariaLabel,
}: MemberSelectorProps) => {
  const { t } = useTranslation();

  const memberParams = useMemo<CommissioningMembersListParams>(() => {
    const params: CommissioningMembersListParams = {};
    if (onlyWithSubscriptions !== null)
      params.only_with_subscriptions = onlyWithSubscriptions;
    if (excludeTrialMembers !== null)
      params.exclude_trial_members = excludeTrialMembers;
    return params;
  }, [onlyWithSubscriptions, excludeTrialMembers]);

  const { members } = useMembers(memberParams);

  const options = useMemo<SelectorOption<string | null>[]>(() => {
    const opts: SelectorOption<string | null>[] = [];
    if (include_null_option) {
      opts.push({ value: null, label: t("commissioning.all_members") });
    }
    members.forEach((member) => {
      if (filterMember && !filterMember(member)) return;
      const label =
        member.member_number && member.first_name && member.last_name
          ? `# ${member.member_number} - ${member.first_name} ${member.last_name}`
          : `${member.first_name ?? ""} ${member.last_name ?? ""}`.trim();
      opts.push({ value: member.value, label });
    });
    return opts;
  }, [members, include_null_option, filterMember, t]);

  return (
    <BaseEntitySelector<string | null>
      value={selectedMember}
      onValueChange={setSelectedMember}
      onChange={onMemberChange}
      options={options}
      placeholder={t("placeholder.member_selector")}
      style={className ? undefined : { width: "24em", marginLeft: "1em" }}
      className={className}
      ariaLabel={ariaLabel}
      showSearch
      optionFilterProp="label"
    />
  );
};

export default MemberSelector;
