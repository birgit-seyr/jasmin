import {
  accountMenu,
  expect,
  logInThroughUi,
  signInButton,
  test,
} from "../support/auth";
import { t } from "../support/i18n";

// Starts logged out and logs in itself: the flow under test is the login, and
// its logout revokes the refresh token, which would end a shared session.
test("office stays logged in across a hard reload and is logged out after logout", async ({
  page,
}) => {
  await logInThroughUi(page, "office");
  await expect(page).toHaveURL("/");
  const mainNavigation = page.getByRole("navigation", { name: t("nav.main") });
  await expect(mainNavigation).toBeVisible();

  // A reload drops the in-memory access token; the refresh cookie, sent
  // through the gateway to this tenant's host, has to bring the session back.
  const refreshAfterReload = page.waitForResponse((response) =>
    response.url().endsWith("/api/auth/refresh/"),
  );
  await page.reload();
  expect((await refreshAfterReload).status()).toBe(200);
  await expect(mainNavigation).toBeVisible();
  await expect(page).toHaveURL("/");

  await accountMenu(page).click();
  await page.getByRole("menuitem", { name: t("common.logout") }).click();
  await expect(signInButton(page)).toBeVisible();

  await page.reload();
  await expect(signInButton(page)).toBeVisible();
  await expect(accountMenu(page)).toBeHidden();
});
