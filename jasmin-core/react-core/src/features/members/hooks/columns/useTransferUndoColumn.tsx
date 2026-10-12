import { RollbackOutlined } from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Popconfirm } from "antd";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  getCommissioningCoopSharesListQueryKey,
  getCommissioningMembersListQueryKey,
  useCommissioningCoopSharesReverseTransferCreate,
} from "@shared/api/generated/commissioning/commissioning";
import type {
  EditableColumnConfig,
  TableRecord,
} from "@shared/tables/BasicEditableTable/types";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";

interface TransferUndoColumnOptions {
  /** Whether the viewer may undo transfers (office). */
  enabled: boolean;
  /** Runs when undoing reopened the giving member's membership: a modal
   *  showing that member's exit is stale then. */
  onMemberReinstated: () => void;
}

/**
 * The coop-share grid's column with "Undo transfer" on the rows a transfer
 * created, the giver's and the receiver's alike. Undoing deletes both members'
 * rows from that transfer and, when it ended the giving member's membership,
 * reopens it.
 */
export function useTransferUndoColumn({
  enabled,
  onMemberReinstated,
}: TransferUndoColumnOptions) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { mutate, isPending, variables } =
    useCommissioningCoopSharesReverseTransferCreate({
      mutation: {
        meta: { silent: true },
        onSuccess: (result) => {
          // Both members' rows changed, and the giver's membership may have.
          void queryClient.invalidateQueries({
            queryKey: getCommissioningCoopSharesListQueryKey(),
          });
          void queryClient.invalidateQueries({
            queryKey: getCommissioningMembersListQueryKey(),
          });
          if (result.from_member_reinstated) {
            notify.success(t("members.transfer_undone_member_reinstated"));
            onMemberReinstated();
          } else {
            notify.success(t("members.transfer_undone"));
          }
        },
        onError: (error) =>
          notify.error(getErrorMessage(error, t("members.transfer_undo_failed"))),
      },
    });

  return useMemo<EditableColumnConfig<TableRecord>>(
    () => ({
      title: t("members.transfer_column"),
      dataIndex: "transfer",
      key: "transfer_undo",
      align: "center",
      width: "10em",
      required: false,
      disabled: true,
      readOnly: true,
      render: (_value: unknown, record: TableRecord) =>
        enabled && record.transfer && record.id != null ? (
          <Popconfirm
            title={t("members.undo_transfer_confirm_title")}
            description={t("members.undo_transfer_confirm_description")}
            okText={t("members.undo_transfer")}
            okButtonProps={{ danger: true }}
            cancelText={t("common.cancel")}
            onConfirm={() => mutate({ id: String(record.id) })}
          >
            <Button
              size="small"
              icon={<RollbackOutlined />}
              loading={isPending && variables?.id === String(record.id)}
            >
              {t("members.undo_transfer")}
            </Button>
          </Popconfirm>
        ) : null,
    }),
    [t, enabled, mutate, isPending, variables],
  );
}
