import type { Page, Response } from "@playwright/test";
import { expect, gotoCapturingAccessToken, test } from "../support/auth";
import { t } from "../support/i18n";

// Seeded by seed_e2e_commissioning: an active article the farm sells.
const ARTICLE = "E2E carrots";

test.use({ persona: "office" });

interface DocumentResult {
  order_id: string;
  delivery_note_id: string;
  delivery_note_number: string;
  invoice_id?: string;
  invoice_number?: string;
}

/** Waits for a POST to ``path`` and returns its response. */
function posted(page: Page, path: string): Promise<Response> {
  return page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname.endsWith(path) &&
      response.request().method() === "POST",
  );
}

/** The single result of a bulk document request, asserted successful. */
async function documentResult(response: Response, status: number): Promise<DocumentResult> {
  expect(response.status()).toBe(status);
  const body = (await response.json()) as {
    successful: number;
    results: DocumentResult[];
  };
  expect(body.successful).toBe(1);
  return body.results[0];
}

/**
 * Picks a reseller in a ResellerSelector by typing its name. AntD renders the
 * open list for the eye and keeps an accessible copy of the options around the
 * active one beside it, too small to click, so the option is found there by
 * its name and picked from the keyboard once it is the active one.
 */
async function selectReseller(page: Page, label: string): Promise<void> {
  const combobox = page.getByRole("combobox", { name: t("placeholder.reseller_selector") });
  await combobox.fill(label);
  const option = page.getByRole("option", { name: label, exact: true });
  await expect(option).toBeAttached();
  await expect(combobox).toHaveAttribute(
    "aria-activedescendant",
    (await option.getAttribute("id")) ?? "",
  );
  await combobox.press("Enter");
  await expect(combobox).toHaveAttribute("aria-expanded", "false");
  // The pick shows in the selector itself; the open list lives elsewhere.
  await expect(
    page.locator(".reseller-selector").getByTitle(label, { exact: true }),
  ).toBeVisible();
}

test("an order becomes a delivery note and an invoice, which is finalized and cancelled for good", async ({
  page,
}) => {
  // Four documents, three of them rendered to PDF in the browser.
  test.slow();
  const accessToken = await gotoCapturingAccessToken(page, "/commissioning/orders");
  const auth = { Authorization: `Bearer ${accessToken}` };

  // A reseller of its own: a reseller has one order per delivery day, and
  // this one ends the test finalized.
  const company = `Run${Date.now()} Grocer`;
  const reseller = await page.request.post("/api/commissioning/resellers/", {
    headers: auth,
    data: {
      company_name: company,
      first_name: "Erika",
      last_name: "Example",
      address: "Market Street 1",
      zip_code: "12345",
      city: "Kiwi Town",
      email: "grocer@example.com",
      is_reseller: true,
      is_active_reseller: true,
    },
  });
  expect(reseller.status()).toBe(201);
  const resellerLabel = `${company} - Erika - Example`;

  // The order, entered as a free article on today's delivery day.
  await page.reload();
  await selectReseller(page, resellerLabel);
  await page
    .getByRole("tab", { name: new RegExp(`^${t("commissioning.orders_from_articles")}`) })
    .click();
  const articles = page.getByRole("tabpanel", {
    name: new RegExp(`^${t("commissioning.orders_from_articles")}`),
  });
  await articles.getByRole("button", { name: t("table.add_record"), exact: true }).click();
  await articles.getByRole("combobox", { name: t("commissioning.share_articles") }).click();
  await page.getByTitle(ARTICLE, { exact: true }).click();
  await articles
    .getByRole("textbox", { name: t("commissioning.ordered_amount") })
    .fill("12");
  await articles
    .getByRole("textbox", { name: t("commissioning.single_price") })
    .fill("2,50");
  const orderSaved = posted(page, "/api/commissioning/order_contents/");
  await articles.getByRole("button", { name: t("table.save"), exact: true }).click();
  expect((await orderSaved).status()).toBe(200);
  const articleRow = articles.getByRole("row").filter({ hasText: ARTICLE });
  await expect(articleRow.getByRole("button", { name: t("table.edit") })).toBeVisible();

  // The delivery note finalizes the order: its rows can't be edited any more.
  const deliveryNoteCreated = posted(page, "/api/commissioning/bulk_create_documents_from_orders/");
  await page
    .getByRole("button", { name: t("commissioning.create_delivery_note"), exact: true })
    .click();
  await documentResult(await deliveryNoteCreated, 201);
  await expect(articleRow).toBeVisible();
  await expect(articleRow.getByRole("button", { name: t("table.edit") })).toHaveCount(0);

  // The invoice finalizes the delivery note; finalizing the invoice uploads
  // its PDF.
  const invoiceCreated = posted(page, "/api/commissioning/bulk_create_documents_from_orders/");
  await page
    .getByRole("button", { name: t("commissioning.create_invoice"), exact: true })
    .click();
  const { order_id: orderId, delivery_note_number: deliveryNote } = await documentResult(
    await invoiceCreated,
    201,
  );
  const invoiceFinalized = posted(page, "/api/commissioning/bulk_finalize_documents/");
  const invoicePdfUploaded = page.waitForResponse(
    (response) =>
      /\/api\/commissioning\/invoices\/\w+\/upload_pdf\/$/.test(response.url()) &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: t("commissioning.finalize_invoice"), exact: true })
    .click();
  const { invoice_id: invoiceId, invoice_number: invoice } = await documentResult(
    await invoiceFinalized,
    200,
  );
  expect((await invoicePdfUploaded).status()).toBe(200);
  // "Finalized" is screen-reader text right before the number.
  await expect(
    page.getByText(new RegExp(`^${t("commissioning.finalized")}\\s*${invoice}$`)),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: t("commissioning.delete_invoice") }),
  ).toHaveCount(0);

  // Nor does the API delete it, whatever a client sends.
  const deleted = await page.request.delete(`/api/commissioning/invoices/${invoiceId}/`, {
    headers: auth,
  });
  expect(deleted.status(), `DELETE of the finalized ${invoice}`).toBe(409);

  // The cancellation, on the invoices page.
  await page.goto("/commissioning/invoices");
  await selectReseller(page, resellerLabel);
  const deliveryNoteRow = page.getByRole("row", {
    name: new RegExp(`${t("commissioning.finalized")} ${deliveryNote}\\b`),
  });
  await expect(deliveryNoteRow).toHaveAccessibleName(
    new RegExp(`${t("commissioning.finalized")} ${invoice}\\b`),
  );
  await deliveryNoteRow
    .getByRole("button", { name: t("commissioning.create_storno"), exact: true })
    .click();
  const cancellation = page
    .getByRole("dialog")
    .filter({ hasText: t("commissioning.create_storno") });
  await cancellation
    .getByRole("textbox", { name: t("commissioning.storno_reason_placeholder") })
    .fill("Wrong amount");
  const cancelled = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/commissioning/invoices/${invoiceId}/create_storno/`),
  );
  await cancellation
    .getByRole("button", { name: t("commissioning.create_storno"), exact: true })
    .click();
  const cancelledResponse = await cancelled;
  expect(cancelledResponse.status()).toBe(201);
  await expect(cancellation).toBeHidden();
  const cancellationPdf = deliveryNoteRow.getByRole("button", {
    name: new RegExp(`^${t("commissioning.storno_pdf")} RK-\\d+$`),
  });
  await expect(cancellationPdf).toBeVisible();
  const cancellationNumber = (await cancellationPdf.innerText()).match(/RK-\d+/)?.[0];
  await expect(deliveryNoteRow).toHaveAccessibleName(
    new RegExp(`${t("commissioning.storno_short")} ${cancellationNumber}\\b`),
  );

  // A cancellation is final: the row keeps the cancelled invoice and offers
  // no new one.
  await expect(deliveryNoteRow).toHaveAccessibleName(
    new RegExp(`${t("commissioning.finalized")} ${invoice}\\b`),
  );
  await expect(
    deliveryNoteRow.getByRole("button", { name: t("commissioning.create_invoice"), exact: true }),
  ).toHaveCount(0);

  // Nor does the API invoice the delivery note again: the bulk request
  // reports the order as failed.
  const reinvoiced = await page.request.post(
    "/api/commissioning/bulk_create_documents_from_orders/",
    { headers: auth, data: { model: "invoice", ids: [orderId] } },
  );
  expect(reinvoiced.status(), `a new invoice for ${deliveryNote}`).toBe(207);
  const refusal = (await reinvoiced.json()) as {
    successful: number;
    failed: number;
    errors: { order_id: string; error: string }[];
  };
  expect(refusal.successful).toBe(0);
  expect(refusal.failed).toBe(1);
  expect(refusal.errors[0].order_id).toBe(orderId);
  expect(refusal.errors[0].error).toContain("Invoice already exists");
});
