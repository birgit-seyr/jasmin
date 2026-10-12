import { expect, test } from "../support/auth";
import { PLATFORM_URL } from "../support/env";

// The platform pages are English-only, so their copy is asserted as written.
test.use({ superAdmin: true });

test("the super-admin's session on the platform host lists the tenants", async ({
  page,
}) => {
  const refreshed = page.waitForResponse((response) =>
    response.url().endsWith("/api/super-admin/auth/refresh/"),
  );
  const tenantList = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/super-admin/tenants/" &&
      response.request().method() === "GET",
  );
  await page.goto(`${PLATFORM_URL}/`);
  expect((await refreshed).status(), "silent refresh on the platform").toBe(200);
  expect((await tenantList).status()).toBe(200);

  await expect(page.getByRole("heading", { name: "All Tenants" })).toBeVisible();
  for (const [schema, name, domain] of [
    ["e2e", "E2E Farm", "e2e.localhost"],
    ["e2e_other", "E2E Other Farm", "e2e-other.localhost"],
  ]) {
    const row = page
      .getByRole("row")
      .filter({ has: page.getByRole("cell", { name: domain, exact: true }) });
    await expect(row.getByRole("cell", { name: schema, exact: true })).toBeVisible();
    await expect(row.getByRole("cell", { name, exact: true })).toBeVisible();
  }
  // The public schema is the platform itself, never a tenant in the list.
  await expect(
    page.getByRole("cell", { name: "public", exact: true }),
  ).toHaveCount(0);
});
