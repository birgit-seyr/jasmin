import { expect, test } from "../support/auth";
import { t } from "../support/i18n";

// The phone drawer is a curated list of the field jobs; the office pages stay
// on the desktop. The e2e tenant packs in boxes (the default packing mode), so
// the box packing lists are among them.
const FIELD_JOBS = [
  "commissioning.forecast",
  "commissioning.documentation_amounts",
  "commissioning.documentation_harvest",
  "commissioning.washing_list",
  "commissioning.harvesting_lists",
  "commissioning.packing_lists",
  "commissioning.commissioning_list_packing",
  "commissioning.commissioning_list_resellers_short",
].map((key) => t(key));

test.use({ persona: "office", viewport: { width: 390, height: 844 } });

test("on a phone the navigation drawer lists the field jobs only", async ({
  page,
}) => {
  await page.goto("/");
  // The desktop sidebar and its section switcher give way to the drawer.
  const openDrawer = page.getByRole("button", { name: t("nav.open_menu") });
  await expect(openDrawer).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: t("nav.main") }),
  ).toBeHidden();

  await openDrawer.click();
  const drawer = page.getByRole("dialog", { name: t("nav.navigation") });
  await expect(drawer.getByRole("link")).toHaveText(FIELD_JOBS);
  for (const officePage of ["nav.members", "nav.configuration"]) {
    await expect(drawer.getByText(t(officePage))).toHaveCount(0);
  }

  await drawer
    .getByRole("link", { name: t("commissioning.washing_list"), exact: true })
    .click();
  await expect(page).toHaveURL("/commissioning/washing-list");
  await expect(drawer).toBeHidden();
});
