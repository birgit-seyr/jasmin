import { test as setup } from "@playwright/test";
import { logInAsSuperAdminThroughUi, logInThroughUi } from "../support/auth";
import {
  PERSONAS,
  SUPER_ADMIN_STORAGE_STATE,
  storageStatePath,
  type Persona,
} from "../support/env";

// One UI login per persona per run, which also keeps the suite well under the
// login throttle (20 a minute per IP and tenant). The saved state carries the
// refresh cookie only: the access token stays in page memory, so every test
// page gets its own through the silent refresh on load.
for (const persona of Object.keys(PERSONAS) as Persona[]) {
  setup(`log in as ${persona}`, async ({ page }) => {
    await logInThroughUi(page, persona);
    await page.context().storageState({ path: storageStatePath(persona) });
  });
}

// The super-admin login is throttled to 10 an hour per IP, so the platform
// session is logged in once here, too, and every test reuses it.
setup("log in as the super-admin", async ({ page }) => {
  await logInAsSuperAdminThroughUi(page);
  await page.context().storageState({ path: SUPER_ADMIN_STORAGE_STATE });
});
