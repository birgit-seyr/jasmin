import type { Page } from "@playwright/test";
import { confirmStepUp, expect, test } from "../support/auth";
import { formatTenantDate, isoWeek, nextMonday } from "../support/dates";
import { t } from "../support/i18n";

// Seeded by seed_e2e_commissioning: the e2e tenant's only share type and
// variation, delivered on Thursdays at its only station.
const VARIATION_CARD = "E2E vegetables M";
const DELIVERY_WEEKDAY = 3;
// A valid German test IBAN.
const IBAN = "DE89370400440532013000";

test.use({ persona: "office" });

/**
 * Opens the "Number of shares" view on the week after the current one and
 * returns the seeded variation's count there (0 when nothing is delivered).
 */
async function sharesNextWeek(page: Page, week: number): Promise<number> {
  await page.goto("/commissioning/amount-share-type-variations");
  await expect(
    page.getByRole("heading", { name: t("commissioning.amount_share_type_variations") }),
  ).toBeVisible();
  const matrix = page.waitForResponse(
    (response) =>
      response.url().includes("/box_combination_matrix/") &&
      response.url().includes(`delivery_week=${week}`),
  );
  await page.getByRole("button", { name: t("common.next") }).click();
  expect((await matrix).status()).toBe(200);
  await expect(
    page.getByText(t("commissioning.week_short", { number: week }), { exact: true }),
  ).toBeVisible();

  const deliveryDayRow = page.getByRole("row", {
    name: new RegExp(`^${t(`commissioning.weekdays.${DELIVERY_WEEKDAY}`)}\\b`),
  });
  const noDeliveries = page.getByText(t("commissioning.packing_list_no_columns"));
  await expect(deliveryDayRow.or(noDeliveries)).toBeVisible();
  if (await noDeliveries.isVisible()) return 0;
  return Number(await deliveryDayRow.getByRole("cell").nth(1).innerText());
}

test("office creates a member with a subscription from next week, and the share is counted in that week", async ({
  page,
}) => {
  const lastName = `Run${Date.now()}`;
  const startMonday = nextMonday();
  const week = isoWeek(startMonday);
  const sharesBefore = await sharesNextWeek(page, week);

  // The member, added inline on the member list.
  await page.goto("/members/members");
  await page.getByRole("button", { name: t("table.add_record"), exact: true }).click();
  await page.getByRole("textbox", { name: t("members.first_name") }).fill("E2E");
  await page.getByRole("textbox", { name: t("members.last_name") }).fill(lastName);
  const memberCreated = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/commissioning/members/") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: t("table.save"), exact: true }).click();
  expect((await memberCreated).status()).toBe(201);

  // The lists grow with every run, so the new row is found through the search.
  await page
    .getByRole("searchbox", { name: t("table.search_placeholder") })
    .fill(lastName);
  const memberRow = page.getByRole("row").filter({ hasText: lastName });
  await memberRow.getByRole("link", { name: t("members.view_details") }).click();
  await expect(page.getByRole("heading", { name: `E2E ${lastName}` })).toBeVisible();

  // The subscription, from next Monday.
  await page.getByRole("button", { name: t("members.create_subscription") }).click();
  await page
    .getByRole("dialog", { name: t("members.additional_subscription") })
    .getByRole("button", { name: VARIATION_CARD })
    .click();
  const form = page.getByRole("dialog", { name: /E2E vegetables/ });
  const validFrom = form.getByRole("textbox", { name: t("abos.valid_from") });
  await validFrom.fill(formatTenantDate(startMonday));
  await validFrom.press("Enter");
  // AntD's role="option" elements are a hidden accessibility copy; the visible
  // entries carry their label as a title.
  await form.getByRole("combobox", { name: t("delivery.station") }).click();
  await page.getByTitle(/E2E station/).click();
  await form.getByRole("combobox", { name: t("abos.payment_cycle") }).click();
  await page.getByTitle(t("configuration.payment_cycle_weekly"), { exact: true }).click();

  // A new member has no SEPA mandate; recording one needs a step-up.
  await form.getByRole("button", { name: t("abos.set_up_sepa_mandate") }).click();
  const sepa = page.getByRole("dialog", { name: t("sepa.setup_title") });
  await sepa.getByRole("checkbox", { name: t("sepa.office_mandate_confirm") }).check();
  await sepa.getByRole("textbox", { name: t("sepa.iban") }).fill(IBAN);
  await sepa
    .getByRole("textbox", { name: t("sepa.account_holder") })
    .fill(`E2E ${lastName}`);
  await sepa.getByRole("button", { name: t("sepa.save") }).click();
  await confirmStepUp(page);
  await expect(sepa).toBeHidden();

  const subscriptionCreated = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/commissioning/abos/") &&
      response.request().method() === "POST",
  );
  await form.getByRole("button", { name: t("common.save"), exact: true }).click();
  expect((await subscriptionCreated).status()).toBe(201);
  const thanks = page.getByRole("dialog").filter({ hasText: t("common.thank_you") });
  await thanks.getByRole("button", { name: t("common.close") }).last().click();
  await expect(thanks).toBeHidden();

  // Approval, which is what creates the shares.
  await page.goto("/abos/abos");
  await page
    .getByRole("searchbox", { name: t("table.search_placeholder") })
    .fill(lastName);
  const subscriptionRow = page.getByRole("row").filter({ hasText: lastName });
  await subscriptionRow
    .getByRole("button", { name: t("members.admin_pending") })
    .click();
  const approval = page.getByRole("dialog", {
    name: t("members.admin_confirmation_title"),
  });
  const confirmed = page.waitForResponse((response) =>
    response.url().endsWith("/confirm/"),
  );
  await approval.getByRole("button", { name: t("members.confirm_abo") }).click();
  expect((await confirmed).status()).toBe(200);

  expect(await sharesNextWeek(page, week)).toBe(sharesBefore + 1);
});
