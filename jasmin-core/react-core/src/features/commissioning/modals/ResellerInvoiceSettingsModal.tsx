import {
  Col,
  Divider,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Space,
  Typography,
} from "antd";

import { ModalCancelSaveFooter } from "@shared/modals/shared";
import type { FC } from "react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { commissioningResellersPartialUpdate } from "@shared/api/generated/commissioning/commissioning";
import type { Reseller } from "@shared/api/generated/models";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";

const { Title, Paragraph } = Typography;

interface ResellerInvoiceSettingsModalProps {
  open: boolean;
  reseller: Reseller | null;
  onClose: () => void;
  /**
   * Called with the fresh server payload after a successful save so
   * the parent table can patch its row in-place without a refetch.
   */
  onSaved: (updated: Reseller) => void;
}

/**
 * Modal that holds every invoice-related field on a Reseller row:
 * customer identity (numbers, VAT-ID, IBAN), invoice recipient
 * address, where to send the invoice, and payment conditions.
 *
 * Triggered from a per-row green "Rechnung" button in
 * ``ListResellers.tsx``. Edits go through
 * ``commissioningResellersPartialUpdate`` and the parent table
 * receives the fresh row via ``onSaved`` so no full refetch is
 * needed.
 *
 * Field grouping kept aligned with how a German office user thinks
 * about invoices:
 *   1. "Kennung" — who is this customer in DATEV / wholesaler systems
 *      (customer_number, filial_number, UID/VAT, IBAN for refunds).
 *   2. "Rechnungsadresse" — where the printed / PDF invoice gets sent
 *      to (multi-line recipient block).
 *   3. "Versand" — should we email the invoice and to which address.
 *   4. "Zahlungskonditionen" — payment terms + Skonto.
 */
export const ResellerInvoiceSettingsModal: FC<
  ResellerInvoiceSettingsModalProps
> = ({ open, reseller, onClose, onSaved }) => {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  // Reset form values whenever a new reseller is opened, so the
  // modal never shows the previous row's fields for a split second
  // before the new ones land.
  useEffect(() => {
    if (open && reseller) {
      form.setFieldsValue({
        customer_number: reseller.customer_number ?? null,
        filial_number: reseller.filial_number ?? null,
        uid: reseller.uid ?? "",
        // IBAN is never returned in plaintext (masked on read). Start empty;
        // an empty submit leaves the stored IBAN untouched (see handleSave).
        iban: "",
        invoice_name: reseller.invoice_name ?? "",
        invoice_name2: reseller.invoice_name2 ?? "",
        invoice_address: reseller.invoice_address ?? "",
        invoice_plz: reseller.invoice_plz ?? "",
        invoice_city: reseller.invoice_city ?? "",
        invoice_via_email: !!reseller.invoice_via_email,
        invoice_email: reseller.invoice_email ?? "",
        payment_terms_in_days: reseller.payment_terms_in_days ?? null,
        early_payment_discount_percent:
          reseller.early_payment_discount_percent ?? null,
        early_payment_discount_days:
          reseller.early_payment_discount_days ?? null,
      });
    }
  }, [open, reseller, form]);

  if (!reseller) return null;

  const handleSave = async () => {
    const values = await form.validateFields();
    const id = String(reseller.id ?? "");
    if (!id) return;
    setSaving(true);
    try {
      // ``early_payment_discount_percent`` is a Decimal-as-string on
      // the wire; the InputNumber yields a number — coerce to string
      // before sending so the server-side ``DecimalField`` parser
      // doesn't lose trailing zeros.
      const payload: Record<string, unknown> = { ...values };
      if (typeof payload.early_payment_discount_percent === "number") {
        payload.early_payment_discount_percent = String(
          payload.early_payment_discount_percent,
        );
      }
      // IBAN is write-on-change only: the field starts empty (the stored value
      // is masked, never returned). An empty value means "unchanged" — drop it
      // so we don't wipe the stored IBAN; only send a freshly typed one.
      if (!payload.iban) {
        delete payload.iban;
      }
      const updated = await commissioningResellersPartialUpdate(
        id,
        payload as unknown as Reseller,
      );
      notify.success(
        t("resellers.invoice_settings_saved"),
      );
      onSaved(updated);
      onClose();
    } catch (error) {
      notify.error(
        getErrorMessage(
          error,
          t("resellers.invoice_settings_save_error"),
        ),
      );
    } finally {
      setSaving(false);
    }
  };

  const sectionTitle = (key: string, fallback: string) => (
    <Title level={5} style={{ marginBottom: 8, marginTop: 16 }}>
      {t(key, fallback)}
    </Title>
  );

  const subtitle =
    reseller.invoice_name ||
    reseller.company_name ||
    `${reseller.first_name ?? ""} ${reseller.last_name ?? ""}`.trim();

  return (
    <Modal
      open={open}
      onCancel={onClose}
      width={720}
      destroyOnHidden
      title={
        <Space direction="vertical" size={0}>
          <span>
            {t("resellers.invoice_settings_title")}{" "}
            {subtitle}
          </span>
        </Space>
      }
      footer={
        <ModalCancelSaveFooter
          onCancel={onClose}
          onPrimary={handleSave}
          loading={saving}
        />
      }
    >
      <Paragraph type="secondary" style={{ marginBottom: 0 }}>
        {t("resellers.invoice_settings_intro")}
      </Paragraph>

      <Form form={form} layout="vertical" requiredMark={false}>
        {sectionTitle("resellers.invoice_section_identity", "Identifiers")}
        <Row gutter={12}>
          <Col span={12}>
            <Form.Item
              name="customer_number"
              label={t("resellers.customer_number")}
            >
              <InputNumber min={0} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="filial_number"
              label={t("resellers.filial_number")}
            >
              <InputNumber min={0} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={12}>
          <Col span={12}>
            <Form.Item name="uid" label={t("resellers.uid")}>
              <Input maxLength={100} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="iban"
              label={t("resellers.iban")}
              extra={
                reseller.iban_stored
                  ? `${t("resellers.iban_stored")}: ${reseller.iban_masked ?? ""}`
                  : undefined
              }
            >
              <Input
                maxLength={34}
                placeholder={
                  reseller.iban_stored
                    ? t("resellers.iban_type_to_change")
                    : undefined
                }
              />
            </Form.Item>
          </Col>
        </Row>

        <Divider style={{ margin: "8px 0 0" }} />

        {sectionTitle("resellers.invoice_section_address", "Invoice address")}
        <Form.Item
          name="invoice_name"
          label={t("resellers.invoice_name")}
        >
          <Input maxLength={200} />
        </Form.Item>
        <Form.Item
          name="invoice_name2"
          label={t("resellers.invoice_name2")}
        >
          <Input maxLength={200} />
        </Form.Item>
        <Form.Item
          name="invoice_address"
          label={t("resellers.invoice_address")}
        >
          <Input maxLength={300} />
        </Form.Item>
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item
              name="invoice_plz"
              label={t("resellers.invoice_plz")}
            >
              <Input maxLength={5} />
            </Form.Item>
          </Col>
          <Col span={16}>
            <Form.Item
              name="invoice_city"
              label={t("resellers.invoice_city")}
            >
              <Input maxLength={100} />
            </Form.Item>
          </Col>
        </Row>

        <Divider style={{ margin: "8px 0 0" }} />

        {sectionTitle("resellers.invoice_section_delivery", "Delivery")}
        <Row gutter={12} align="middle">
          <Col span={14}>
            <Form.Item
              name="invoice_email"
              label={t("resellers.invoice_email")}
              rules={[
                {
                  type: "email",
                  message: t("common.invalid_email"),
                },
              ]}
            >
              <Input maxLength={200} />
            </Form.Item>
          </Col>
        </Row>

        <Divider style={{ margin: "8px 0 0" }} />

        {sectionTitle(
          "resellers.invoice_section_payment",
          "Payment conditions",
        )}
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item
              name="payment_terms_in_days"
              label={t("resellers.payment_terms_in_days")}
            >
              <InputNumber min={0} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item
              name="early_payment_discount_percent"
              label={t("resellers.early_payment_discount_percent")}
            >
              <InputNumber
                min={0}
                max={100}
                step={0.01}
                style={{ width: "100%" }}
              />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item
              name="early_payment_discount_days"
              label={t("resellers.early_payment_discount_days")}
            >
              <InputNumber min={0} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
        </Row>
      </Form>
    </Modal>
  );
};

export default ResellerInvoiceSettingsModal;
