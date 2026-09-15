import { useQueryClient } from "@tanstack/react-query";
import { Alert, Checkbox, DatePicker, Form, Input, InputNumber, Modal } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import {
  getCommissioningCoopSharesListQueryKey,
  getCommissioningMembersListQueryKey,
  useCommissioningCoopSharesTransferCreate,
} from "@shared/api/generated/commissioning/commissioning";
import type { CoopShareTransfer } from "@shared/api/generated/models";
import { ModalCancelSaveFooter } from "@shared/modals/shared";
import MemberSelector from "@shared/selectors/MemberSelector";
import { notify } from "@shared/utils";
import { getErrorCode, getErrorMessage } from "@shared/utils/apiError";
import { useDateFormat, useMembers } from "@hooks/index";
import type { MemberOption } from "@hooks/useMembers";

interface FormValues {
  to_member: string | null;
  amount_of_coop_shares: number | null;
  transfer_date: Dayjs;
  note?: string;
  confirm_member_cancellation?: boolean;
}

interface CoopShareTransferModalProps {
  open: boolean;
  onClose: () => void;
  /** The giving member. */
  memberId: string;
  memberName?: string;
  /** Confirmed, paid, uncancelled shares of the giving member: the most that
   *  can be given. */
  availableShares: number;
  /** Confirmed, uncancelled shares of the giving member, paid or not. What stays
   *  after the transfer is counted from this, as the backend does. */
  confirmedTotal: number;
  /** Tenant minimum when the bounds apply to the giving member, otherwise null. */
  minShares: number | null;
  onTransferred: (transfer: CoopShareTransfer) => void;
}

interface ReceivingMemberFieldProps {
  value?: string | null;
  onChange?: (value: string | null) => void;
  excludeMemberId: string;
  ariaLabel: string;
}

/** Adapts ``MemberSelector`` to the ``value`` / ``onChange`` props Form.Item
 *  injects, offering only members the backend accepts as receivers: admitted,
 *  not rejected, not cancelled, and not the giving member. */
function ReceivingMemberField({
  value,
  onChange,
  excludeMemberId,
  ariaLabel,
}: ReceivingMemberFieldProps) {
  const canReceive = useCallback(
    (member: MemberOption) =>
      member.value !== excludeMemberId &&
      !!member.admin_confirmed &&
      !member.admin_rejected_at &&
      !member.cancelled_at,
    [excludeMemberId],
  );
  return (
    <MemberSelector
      selectedMember={value ?? null}
      setSelectedMember={(member) => onChange?.(member)}
      filterMember={canReceive}
      className="w-full"
      ariaLabel={ariaLabel}
    />
  );
}

/**
 * Transfers confirmed, paid coop shares of one member to another member
 * (``POST coop_shares/transfer/``). The backend enforces the rules; the form
 * mirrors the two outcomes the office should see before submitting: giving every
 * share cancels the member on the transfer date, and leaving between 0 and the
 * minimum is refused. Both sides get a note naming the other member.
 */
export default function CoopShareTransferModal({
  open,
  onClose,
  memberId,
  memberName,
  availableShares,
  confirmedTotal,
  minShares,
  onTransferred,
}: CoopShareTransferModalProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<FormValues>();
  const { dateFormat, formatDate, formatDateForAPI } = useDateFormat();
  const { members } = useMembers();
  const amount = Form.useWatch("amount_of_coop_shares", form);

  const remaining = confirmedTotal - (amount ?? 0);
  const cancelsMember = amount != null && amount > 0 && remaining === 0;
  const belowMinimum =
    amount != null && minShares != null && remaining > 0 && remaining < minShares;

  const memberLabel = (id: string | null) => {
    const member = members.find((option) => option.value === id);
    if (!member) return id === memberId ? (memberName ?? "") : "";
    const name = `${member.first_name ?? ""} ${member.last_name ?? ""}`.trim();
    return member.member_number ? `#${member.member_number} ${name}` : name;
  };

  const { mutate: transfer, isPending } =
    useCommissioningCoopSharesTransferCreate({
      mutation: {
        onSuccess: (result) => {
          // Both members' coop share lists and the members list totals change.
          queryClient.invalidateQueries({
            queryKey: getCommissioningCoopSharesListQueryKey(),
          });
          queryClient.invalidateQueries({
            queryKey: getCommissioningMembersListQueryKey(),
          });
          notify.success(
            t("members.transfer_success", {
              count: result.amount_of_coop_shares,
            }),
          );
          onTransferred(result);
          onClose();
        },
        onError: (err) => {
          notify.error(
            getErrorCode(err) === "member.has_active_subscriptions"
              ? t("members.transfer_active_subscriptions_error")
              : getErrorMessage(err, t("members.transfer_failed")),
          );
        },
      },
    });

  const handleSubmit = async () => {
    let values: FormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    const count = values.amount_of_coop_shares!;
    const date = formatDate(values.transfer_date);
    const freeNote = values.note?.trim() || null;
    const withFreeNote = (line: string) =>
      freeNote ? `${line} – ${freeNote}` : line;
    transfer({
      data: {
        from_member: memberId,
        to_member: values.to_member!,
        amount_of_coop_shares: count,
        transfer_date: formatDateForAPI(values.transfer_date)!,
        confirm_member_cancellation: !!values.confirm_member_cancellation,
        note: freeNote,
        from_member_note: withFreeNote(
          t("members.transfer_note_given", {
            count,
            member: memberLabel(values.to_member),
            date,
          }),
        ),
        to_member_note: withFreeNote(
          t("members.transfer_note_received", {
            count,
            member: memberLabel(memberId),
            date,
          }),
        ),
      },
    });
  };

  const requiredRule = {
    required: true,
    message: t("members.transfer_field_required"),
  };

  return (
    <Modal
      title={
        memberName
          ? `${t("members.transfer_coop_shares")} — ${memberName}`
          : t("members.transfer_coop_shares")
      }
      open={open}
      onCancel={onClose}
      destroyOnHidden
      footer={
        <ModalCancelSaveFooter
          onCancel={onClose}
          onPrimary={handleSubmit}
          loading={isPending}
          primaryDisabled={belowMinimum}
          primaryLabel={t("members.transfer_submit")}
        />
      }
    >
      <p className="coop-share-transfer-available">
        {t("members.transfer_available", { count: availableShares })}
      </p>
      <Form
        form={form}
        layout="vertical"
        preserve={false}
        initialValues={{ transfer_date: dayjs() }}
      >
        <Form.Item
          name="to_member"
          label={t("members.transfer_to_member")}
          rules={[requiredRule]}
        >
          <ReceivingMemberField
            excludeMemberId={memberId}
            ariaLabel={t("members.transfer_to_member")}
          />
        </Form.Item>
        <Form.Item
          name="amount_of_coop_shares"
          label={t("members.transfer_amount")}
          rules={[
            requiredRule,
            {
              // A ``max`` on the input would silently lower a typo to the maximum.
              validator: (_: unknown, value: number | null) =>
                value == null || value <= availableShares
                  ? Promise.resolve()
                  : Promise.reject(
                      new Error(
                        t("members.transfer_amount_above_available", {
                          count: availableShares,
                        }),
                      ),
                    ),
            },
          ]}
        >
          <InputNumber className="w-full" min={1} precision={0} step={1} />
        </Form.Item>
        <Form.Item
          name="transfer_date"
          label={t("members.transfer_date")}
          rules={[requiredRule]}
        >
          {/* The backend refuses future transfer dates. */}
          <DatePicker
            className="w-full"
            format={dateFormat}
            disabledDate={(current) => current.isAfter(dayjs(), "day")}
          />
        </Form.Item>
        <Form.Item name="note" label={t("members.transfer_note")}>
          {/* The note is also added to both generated row notes, which hold at
              most 2000 characters. */}
          <Input.TextArea rows={2} maxLength={1000} />
        </Form.Item>
        {cancelsMember && (
          <>
            <Alert
              type="warning"
              showIcon
              message={t("members.transfer_cancels_member")}
            />
            <Form.Item
              name="confirm_member_cancellation"
              valuePropName="checked"
              rules={[
                {
                  validator: (_: unknown, checked?: boolean) =>
                    checked
                      ? Promise.resolve()
                      : Promise.reject(
                          new Error(
                            t("members.transfer_confirm_cancellation_required"),
                          ),
                        ),
                },
              ]}
            >
              <Checkbox>{t("members.transfer_confirm_cancellation")}</Checkbox>
            </Form.Item>
          </>
        )}
        {belowMinimum && (
          <Alert
            type="error"
            showIcon
            message={t("members.transfer_below_minimum", {
              remaining,
              min: minShares,
            })}
          />
        )}
      </Form>
    </Modal>
  );
}
