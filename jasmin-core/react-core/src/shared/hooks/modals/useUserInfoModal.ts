import { useCallback, useState } from 'react';
import type { TableRecord } from '@shared/tables/BasicEditableTable/types';

export type AccountStatus =
  | 'active'
  | 'pending_approval'
  | 'pending_invitation'
  | 'inactive';

export interface LinkedUserInfo {
  id?: string;
  email?: string;
  first_name?: string;
  last_name?: string;
  account_status?: AccountStatus;
  is_active?: boolean;
  last_login?: string | null;
  date_joined?: string | null;
  activated_at?: string | null;
  inactivated_at?: string | null;
  invitation_expires_at?: string | null;
  is_invitation_expired?: boolean;
  roles?: string[];
}

interface UserRecord extends TableRecord {
  // Snapshot of the linked JasminUser, served by the backend
  // (e.g. ResellerSerializer.linked_user_info).
  linked_user_info?: LinkedUserInfo | null;
}

export type UserStatusVariant =
  | 'userActive'
  | 'userPendingApproval'
  | 'userPendingInvitation'
  | 'userPendingInvitationExpired'
  | 'userInactive'
  | 'userNotInvited';

interface UserStatus {
  variant: UserStatusVariant;
  key: string;
  priority: number;
  accountStatus?: AccountStatus | null;
  isInvitationExpired?: boolean;
}

const ACCOUNT_STATUS_TO_STATUS: Record<AccountStatus, UserStatus> = {
  active: { variant: 'userActive', key: 'status_active', priority: 4 },
  pending_approval: {
    variant: 'userPendingApproval',
    key: 'status_pending_approval',
    priority: 3,
  },
  pending_invitation: {
    variant: 'userPendingInvitation',
    key: 'status_pending_invitation',
    priority: 2,
  },
  inactive: { variant: 'userInactive', key: 'status_inactive', priority: 1 },
};

export const useUserInfoModal = () => {
  const [isUserInfoModalOpen, setIsUserInfoModalOpen] = useState(false);
  const [selectedUserRecord, setSelectedUserRecord] = useState<UserRecord | null>(null);

  const handleOpenUserInfoModal = useCallback((record: UserRecord) => {
    setSelectedUserRecord(record);
    setIsUserInfoModalOpen(true);
  }, []);

  const handleCloseUserInfoModal = useCallback(() => {
    setIsUserInfoModalOpen(false);
    setSelectedUserRecord(null);
  }, []);

  const getUserStatus = useCallback((record: UserRecord): UserStatus => {
    const info = record.linked_user_info;
    if (info && info.account_status) {
      const base = ACCOUNT_STATUS_TO_STATUS[info.account_status];
      // For pending_invitation, swap to the "expired" variant when the
      // invitation token is past its expires_at — same icon, red color.
      if (
        info.account_status === 'pending_invitation' &&
        info.is_invitation_expired
      ) {
        return {
          ...base,
          variant: 'userPendingInvitationExpired',
          accountStatus: info.account_status,
          isInvitationExpired: true,
        };
      }
      return {
        ...base,
        accountStatus: info.account_status,
        isInvitationExpired: !!info.is_invitation_expired,
      };
    }
    return { variant: 'userNotInvited', key: 'status_no_user', priority: 0, accountStatus: null };
  }, []);

  const getUserStatusSorter = useCallback(
    (a: TableRecord, b: TableRecord) => {
      const statusA = getUserStatus(a as UserRecord);
      const statusB = getUserStatus(b as UserRecord);
      return statusB.priority - statusA.priority;
    },
    [getUserStatus],
  );

  return {
    isUserInfoModalOpen,
    selectedUserRecord,
    handleOpenUserInfoModal,
    handleCloseUserInfoModal,
    getUserStatus,
    getUserStatusSorter,
  };
};
