import { useQueryClient } from "@tanstack/react-query";
import { Alert, InputNumber, Modal, Space, Statistic, Typography } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  getCommissioningMembersRetrieveQueryKey,
  getCommissioningMyMemberDataRetrieveQueryKey,
  useCommissioningConsentDocumentsCurrentRetrieve,
  useCommissioningMyCoopSharesSubscribeCreate,
  useCommissioningMyMemberDataRetrieve,
} from "@shared/api/generated/commissioning/commissioning";
import ConsentBlock, { ConsentDocumentKind } from "@shared/consent/ConsentBlock";
import { getErrorMessage } from "@shared/utils/apiError";
import { blockNonNumericKeys } from "@shared/utils/numberFormat";
import { useCurrency, useTenant } from "@hooks/index";

const { Text } = Typography;

interface MemberCoopSharesModalProps {
  isOpen: boolean;
  onClose: () => void;
  memberId: string;
  /** Exit date if the membership is cancelled — blocks subscribing new shares. */
  memberCancelledEffectiveAt?: string | null;
}

/**
 * Member self-service cooperative-share subscription ("Zeichnung"). The member
 * picks how many shares to subscribe; the share is created pending office
 * confirmation (admin_confirmed=False) via the member-scoped endpoint. When the
 * tenant has uploaded a Zeichnungsvertrag, the member must acknowledge it
 * before submitting. Office users use the richer (editable) CoopSharesModal.
 */
export default function MemberCoopSharesModal({
  isOpen,
  onClose,
  memberId,
  memberCancelledEffectiveAt = null,
}: MemberCoopSharesModalProps) {
  const { t, i18n } = useTranslation();
  const { getSetting } = useTenant();
  const { currencySymbol } = useCurrency();
  const queryClient = useQueryClient();
  const locale = i18n.language || "de";

  const [amount, setAmount] = useState<number | null>(null);
  const [agreed, setAgreed] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const valueOneRaw = getSetting("value_one_coop_share");
  const valueOne = valueOneRaw == null ? 0 : Number(valueOneRaw);

  // Current CONFIRMED holdings (owned equity) — same authoritative source as
  // the member card, so the "you currently hold X" figure is always correct
  // and consistent. Pending shares aren't owned yet, so they're not counted
  // here; the shares being subscribed now are themselves pending until the
  // office confirms them (see the note below).
  const { data: myData } = useCommissioningMyMemberDataRetrieve({
    query: { enabled: isOpen },
  });
  const currentTotal = useMemo(
    () =>
      (myData?.coop_shares ?? [])
        .filter((s) => s.admin_confirmed && !s.cancelled_at)
        .reduce((acc, s) => acc + Number(s.amount_of_coop_shares ?? 0), 0),
    [myData],
  );

  const reset = () => {
    setAmount(null);
    setAgreed(false);
    setSubmitError(null);
  };

  const { mutate, isPending } = useCommissioningMyCoopSharesSubscribeCreate({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({
          queryKey: getCommissioningMembersRetrieveQueryKey(memberId),
        });
        // The member self-view card splits confirmed/pending from my_member_data.
        queryClient.invalidateQueries({
          queryKey: getCommissioningMyMemberDataRetrieveQueryKey(),
        });
        reset();
        onClose();
      },
      onError: (err) => {
        setSubmitError(getErrorMessage(err, t("members.coop_subscribe_error")));
      },
    },
  });

  // A published coop-share contract (ConsentKind.coop_contract) is a
  // first-class consent document: when one is active the member must agree,
  // and the backend records a ConsentRecord as proof. No document → no gate.
  const { data: contractDoc } = useCommissioningConsentDocumentsCurrentRetrieve(
    { kind: ConsentDocumentKind.coop_contract, locale },
    { query: { enabled: isOpen, retry: false } },
  );
  const contractRequired = Boolean(contractDoc);
  // A member who has left the co-op cannot subscribe new shares (the backend
  // rejects with MemberAlreadyCancelled) — block submit + explain why.
  const memberCancelled = !!memberCancelledEffectiveAt;
  const canSubmit =
    !!amount &&
    amount > 0 &&
    (!contractRequired || agreed) &&
    !isPending &&
    !memberCancelled;
  const newTotal = currentTotal + (amount ?? 0);

  const handleSubmit = () => {
    if (!amount || amount <= 0) return;
    setSubmitError(null);
    mutate({
      data: { amount_of_coop_shares: String(amount), agreed_to_contract: agreed },
    });
  };

  return (
    <Modal
      open={isOpen}
      onCancel={() => {
        reset();
        onClose();
      }}
      title={t("members.subscribe_coop_shares")}
      okText={t("members.subscribe_coop_shares")}
      onOk={handleSubmit}
      okButtonProps={{ disabled: !canSubmit, loading: isPending }}
    >
      <Space direction="vertical" size="middle" className="w-full">
        {memberCancelled && (
          <Alert
            type="warning"
            showIcon
            message={t("members.coop_subscribe_member_cancelled")}
          />
        )}
        <Space size="large">
          <Statistic
            title={t("members.shares_current_total")}
            value={currentTotal}
            precision={currentTotal % 1 === 0 ? 0 : 2}
          />
          {valueOne > 0 && (
            <Statistic
              title={t("members.coop_shares_total_value")}
              value={currentTotal * valueOne}
              prefix={currencySymbol}
              precision={2}
            />
          )}
        </Space>

        <div>
          <Text>{t("members.coop_subscribe_amount_label")}</Text>
          <InputNumber
            min={1}
            step={1}
            precision={0}
            value={amount}
            onChange={setAmount}
            className="w-full"
            // Integer-only: hard-block non-digit keystrokes (AntD otherwise
            // only coerces on blur).
            onKeyDown={blockNonNumericKeys({
              allowDecimal: false,
              decimalChar: ".",
            })}
          />
        </div>

        {!!amount && amount > 0 && valueOne > 0 && (
          <Text type="secondary">
            {t("members.coop_subscribe_new_total", { total: newTotal })} —{" "}
            {currencySymbol}
            {(newTotal * valueOne).toFixed(2)}
          </Text>
        )}

        {contractRequired && (
          <ConsentBlock
            kind={ConsentDocumentKind.coop_contract}
            locale={locale}
            checked={agreed}
            onChange={(checked) => setAgreed(checked)}
          />
        )}

        <Alert
          type="info"
          showIcon
          message={t("members.coop_subscribe_pending_note")}
        />

        {submitError && <Alert type="error" showIcon message={submitError} />}
      </Space>
    </Modal>
  );
}
