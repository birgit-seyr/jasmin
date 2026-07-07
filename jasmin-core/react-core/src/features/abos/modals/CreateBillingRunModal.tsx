import { DatePicker, Form, Modal } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { paymentsBillingRunsCreate } from "@shared/api/generated/payments-—-billing-runs/payments-—-billing-runs";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";
import { ToolTipIcon } from "@shared/ui";
import { useTenant } from "@hooks/index";
import { useDateFormat } from "@hooks/index";

interface FormValues {
  period_month: Dayjs;
  collection_date: Dayjs;
}

interface CreateBillingRunModalProps {
  open: boolean;
  onClose: () => void;
  /** Called after a run was created successfully (parent refreshes the list). */
  onCreated: () => void;
}

export function CreateBillingRunModal({
  open,
  onClose,
  onCreated,
}: CreateBillingRunModalProps) {
  const { t } = useTranslation();
  const [form] = Form.useForm<FormValues>();
  const [submitting, setSubmitting] = useState(false);
  const { getSetting } = useTenant();
  const collectionDay = getSetting("sepa_collection_day_of_month", 5) || 5;
  const { dateFormat } = useDateFormat();

  const handleCreate = async () => {
    let values: FormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setSubmitting(true);
    try {
      const start = values.period_month.startOf("month");
      const end = values.period_month.endOf("month");
      await paymentsBillingRunsCreate({
        period_start: start.format("YYYY-MM-DD"),
        period_end: end.format("YYYY-MM-DD"),
        collection_date: values.collection_date.format("YYYY-MM-DD"),
      });
      notify.success(t("abos.debits_run_created"));
      form.resetFields();
      onClose();
      onCreated();
    } catch (err: unknown) {
      console.error(err);
      // Surface the backend's specific reason (getErrorMessage reads the Jasmin
      // {code, message} body; the i18n key is only the fallback).
      notify.error(getErrorMessage(err, t("abos.debits_run_create_error")));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title={t("abos.debits_create_run")}
      open={open}
      onOk={handleCreate}
      onCancel={onClose}
      confirmLoading={submitting}
      okText={t("common.create")}
      cancelText={t("common.cancel")}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        preserve={false}
        onValuesChange={(changed: Partial<FormValues>) => {
          // Default the SEPA collection date from the tenant setting
          // (sepa_collection_day_of_month) once a billing month is chosen:
          // that day of the chosen month, never in the past. Office can override.
          if (changed.period_month) {
            const today = dayjs().startOf("day");
            const candidate = changed.period_month.date(collectionDay);
            form.setFieldValue(
              "collection_date",
              candidate.isBefore(today) ? today : candidate,
            );
          }
        }}
      >
        <Form.Item
          name="period_month"
          label={
            <>
              {t("abos.debits_period_month")}
              <ToolTipIcon title={t("abos.debits_period_month_help")} />
            </>
          }
          rules={[{ required: true }]}
        >
          <DatePicker picker="month" format="MMMM YYYY" className="w-full" />
        </Form.Item>
        <Form.Item
          name="collection_date"
          label={
            <>
              {t("abos.debits_collection_date")}
              <ToolTipIcon title={t("abos.debits_collection_date_help")} />
            </>
          }
          rules={[{ required: true }]}
        >
          {/* Disable past dates: a SEPA RequestedCollectionDate can't settle
              before today, so the backend rejects it (billing_run.invalid_
              collection_date). Keep the picker in sync with that guard. */}
          <DatePicker
            className="w-full"
            format={dateFormat}
            disabledDate={(current) => current.isBefore(dayjs().startOf("day"))}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
