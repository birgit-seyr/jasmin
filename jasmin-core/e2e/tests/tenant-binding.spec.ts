import {
  accountMenu,
  expect,
  gotoCapturingAccessToken,
  signInButton,
  test,
} from "../support/auth";
import { OTHER_TENANT_URL } from "../support/env";

// Both tenants hold a test-office@example.com login, so a refusal on the other
// tenant comes from the tenant binding, not from an unknown user.
test.use({ persona: "office" });

test("a session from the e2e tenant is not accepted on another tenant", async ({
  page,
  context,
  playwright,
}) => {
  const accessToken = await gotoCapturingAccessToken(page, "/");
  await expect(accountMenu(page)).toBeVisible();

  // The refresh cookie is host-only, so the browser doesn't send it to the
  // other tenant's host at all.
  const otherTenantPage = await context.newPage();
  await otherTenantPage.goto(`${OTHER_TENANT_URL}/`);
  await expect(signInButton(otherTenantPage)).toBeVisible();
  await expect(accountMenu(otherTenantPage)).toBeHidden();

  // Carried over by hand, neither token is accepted there.
  const refreshCookie = (await context.cookies()).find(
    (cookie) => cookie.name === "refresh_token",
  );
  expect(refreshCookie, "refresh cookie of the e2e session").toBeDefined();
  const otherTenantApi = await playwright.request.newContext({
    baseURL: OTHER_TENANT_URL,
  });
  try {
    const withAccessToken = await otherTenantApi.get(
      "/api/auth/two-factor/status/",
      { headers: { Authorization: `Bearer ${accessToken}` } },
    );
    expect(withAccessToken.status()).toBe(401);

    const withRefreshCookie = await otherTenantApi.post("/api/auth/refresh/", {
      headers: { Cookie: `refresh_token=${refreshCookie?.value}` },
    });
    expect(withRefreshCookie.status()).toBe(401);
    expect(await withRefreshCookie.json()).toMatchObject({
      code: "auth.tenant_mismatch",
    });
  } finally {
    await otherTenantApi.dispose();
  }

  // The same access token still works on its own tenant.
  const ownTenant = await page.request.get("/api/auth/two-factor/status/", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  expect(ownTenant.status()).toBe(200);
});
