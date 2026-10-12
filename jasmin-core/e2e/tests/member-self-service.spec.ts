import {
  accessTokenFor,
  accountMenu,
  expect,
  gotoCapturingAccessToken,
  test,
} from "../support/auth";
import { t } from "../support/i18n";

const MEMBER_PAGE = /\/members\/members\/(\w+)$/;
// Seeded by seed_e2e_commissioning: the member persona's weekly subscription.
const SHARE_TYPE = "E2E vegetables";
// Another persona with a member row in the e2e tenant (seed_test_users).
const OTHER_MEMBER_EMAIL = "test-staff-member@example.com";

test.use({ persona: "member" });

test("a member edits their own contact details, sees their payment plan, and nobody else's data", async ({
  page,
}) => {
  const accessToken = await gotoCapturingAccessToken(page, "/");
  await expect(page).toHaveURL(MEMBER_PAGE);

  // The payment plan of the seeded subscription, next charge first.
  const nextCharge = page
    .getByRole("listitem")
    .filter({ hasText: t("members.next_payment") });
  await expect(nextCharge).toContainText(SHARE_TYPE);
  await expect(nextCharge).toContainText(t("abos.charge_status.PLANNED"));

  // Contact details, through the account menu.
  const street = `Run${Date.now()} Street 1`;
  await accountMenu(page).click();
  await page.getByRole("menuitem", { name: t("profile.tab_my_data") }).click();
  const profile = page.getByRole("dialog", { name: t("profile.title") });
  await profile.getByRole("textbox", { name: t("profile.address"), exact: true }).fill(street);
  await profile.getByRole("textbox", { name: t("profile.zip_code") }).fill("12345");
  await profile.getByRole("textbox", { name: t("profile.city") }).fill("Kiwi Town");
  const saved = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/commissioning/my_member_data/") &&
      response.request().method() === "PATCH",
  );
  await profile.getByRole("button", { name: t("common.save"), exact: true }).click();
  expect((await saved).status()).toBe(200);
  await expect(page.getByText(t("profile.saved"))).toBeVisible();

  // Stored, not just kept in the form: a reload reads it back.
  await page.reload();
  await accountMenu(page).click();
  await page.getByRole("menuitem", { name: t("profile.tab_my_data") }).click();
  await expect(
    profile.getByRole("textbox", { name: t("profile.address"), exact: true }),
  ).toHaveValue(street);

  // Another member's row, by id: refused by the API and the member page.
  const officeToken = await accessTokenFor("office");
  const members = await page.request.get("/api/commissioning/members/", {
    headers: { Authorization: `Bearer ${officeToken}` },
  });
  expect(members.status()).toBe(200);
  const otherMember = ((await members.json()) as Array<{ id: string; email: string }>)
    .find((member) => member.email === OTHER_MEMBER_EMAIL);
  expect(otherMember, `the member row of ${OTHER_MEMBER_EMAIL}`).toBeDefined();
  const otherId = otherMember?.id ?? "";

  const asMember = { headers: { Authorization: `Bearer ${accessToken}` } };
  expect(
    (await page.request.get(`/api/commissioning/members/${otherId}/`, asMember)).status(),
  ).toBe(404);
  expect(
    (
      await page.request.get("/api/payments/charge_schedules/", {
        ...asMember,
        params: { member: otherId },
      })
    ).status(),
  ).toBe(403);

  await page.goto(`/members/members/${otherId}`);
  await expect(page.getByText(t("members.member_not_found"))).toBeVisible();
  await expect(page.getByText(OTHER_MEMBER_EMAIL)).toHaveCount(0);
});
