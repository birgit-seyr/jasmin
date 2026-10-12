import {
  accountMenu,
  expect,
  gotoCapturingAccessToken,
  test,
} from "../support/auth";
import { t } from "../support/i18n";

// ``RequireRole``'s fallback is a literal in the app, not an i18n key.
const NOT_AUTHORIZED = "Not authorized.";
const MEMBER_PAGE = /\/members\/members\/(\w+)$/;

test.describe("member", () => {
  test.use({ persona: "member" });

  test("sees only the member portal, and the API only their own row", async ({
    page,
  }) => {
    const accessToken = await gotoCapturingAccessToken(page, "/");
    await expect(page).toHaveURL(MEMBER_PAGE);
    const memberId = MEMBER_PAGE.exec(new URL(page.url()).pathname)?.[1];
    await expect(accountMenu(page)).toBeVisible();
    await expect(
      page.getByRole("navigation", { name: t("nav.main") }),
    ).toBeHidden();

    // An office page by URL leads back to the member's own page.
    await page.goto("/members/dashboard");
    await expect(page).toHaveURL(`/members/members/${memberId}`);
    await expect(accountMenu(page)).toBeVisible();

    const headers = { Authorization: `Bearer ${accessToken}` };
    const members = await page.request.get("/api/commissioning/members/", {
      headers,
    });
    expect(members.status()).toBe(200);
    const rows = (await members.json()) as Array<{ id: string }>;
    expect(rows.map((row) => row.id)).toEqual([memberId]);

    const resellers = await page.request.get("/api/commissioning/resellers/", {
      headers,
    });
    expect(resellers.status()).toBe(403);
  });
});

test.describe("office", () => {
  test.use({ persona: "office" });

  test("does not see or reach the configuration area", async ({ page }) => {
    const accessToken = await gotoCapturingAccessToken(page, "/");
    const mainNavigation = page.getByRole("navigation", { name: t("nav.main") });
    await expect(
      mainNavigation.getByRole("link", { name: t("nav.members") }),
    ).toBeVisible();
    await expect(
      mainNavigation.getByRole("link", { name: t("nav.configuration") }),
    ).toHaveCount(0);

    await page.goto("/configuration/general");
    await expect(page.getByText(NOT_AUTHORIZED, { exact: true })).toBeVisible();

    const adminUsers = await page.request.get("/api/auth/admin/users/", {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    expect(adminUsers.status()).toBe(403);
  });
});

test.describe("admin", () => {
  test.use({ persona: "admin" });

  test("sees and reaches the configuration area", async ({ page }) => {
    const accessToken = await gotoCapturingAccessToken(page, "/");
    const configurationLink = page
      .getByRole("navigation", { name: t("nav.main") })
      .getByRole("link", { name: t("nav.configuration") });
    await expect(configurationLink).toBeVisible();

    await configurationLink.click();
    await expect(page).toHaveURL(/\/configuration\//);
    await page
      .getByRole("link", { name: t("configuration.general"), exact: true })
      .click();
    await expect(page).toHaveURL("/configuration/general");
    await expect(
      page.getByText(t("tenant.basic_info.title"), { exact: true }).first(),
    ).toBeVisible();
    await expect(page.getByText(NOT_AUTHORIZED, { exact: true })).toHaveCount(0);

    const adminUsers = await page.request.get("/api/auth/admin/users/", {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    expect(adminUsers.status()).toBe(200);
  });
});
