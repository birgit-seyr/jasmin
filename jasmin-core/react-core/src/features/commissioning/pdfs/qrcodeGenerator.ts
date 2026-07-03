import QRCode from "qrcode";
import type { TFunction } from "i18next";

interface EPCQRCodeParams {
  iban: string;
  bic?: string;
  beneficiary: string;
  amount: number;
  reference: string;
  remittanceInfo?: string;
}

/**
 * Generate EPC QR Code for SEPA payments (European Payment Standard)
 */
async function generateEPCQRCode({
  iban,
  beneficiary,
  amount,
  reference,
  remittanceInfo = "",
}: EPCQRCodeParams): Promise<string> {
  // EPC QR Code format (Version 002)
  const epcData = [
    "BCD", // Service Tag
    "002", // Version
    "1", // Character set (1 = UTF-8)
    "SCT", // Identification (SEPA Credit Transfer)
    beneficiary.substring(0, 70), // Beneficiary name (max 70 chars)
    iban.replace(/\s/g, ""), // IBAN (remove spaces)
    `EUR${amount.toFixed(2)}`, // Amount with currency
    "", // Purpose (optional)
    reference.substring(0, 35), // Structured reference (max 35 chars)
    remittanceInfo.substring(0, 140), // Unstructured remittance (max 140 chars)
    "", // Beneficiary to originator info
  ].join("\n");

  const qrCodeDataUrl = await QRCode.toDataURL(epcData, {
    errorCorrectionLevel: "M",
    margin: 1,
    width: 100,
  });

  return qrCodeDataUrl;
}

interface BankDetails {
  iban: string;
  bic?: string;
  beneficiary: string;
}

interface InvoiceQRData {
  prefix?: string;
  invoice_number?: string | number;
  total_brutto: number;
}

/**
 * Generate QR code for invoice payments using EPC format
 */
export async function generatePaymentQRCode(
  invoiceData: InvoiceQRData,
  bankDetails: BankDetails,
  t: TFunction,
): Promise<string> {
  const reference = `${invoiceData.prefix}-${invoiceData.invoice_number}`;

  return generateEPCQRCode({
    iban: bankDetails.iban,
    bic: bankDetails.bic,
    beneficiary: bankDetails.beneficiary,
    amount: invoiceData.total_brutto,
    reference,
    remittanceInfo: `${t("commissioning.invoice")} ${reference}`,
  });
}
