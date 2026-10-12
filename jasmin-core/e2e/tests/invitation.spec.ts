import { expect, logInWithPassword, test } from "../support/auth";
import { BASE_URL } from "../support/env";
import { t } from "../support/i18n";
import { clearMailbox, linksIn, waitForMail } from "../support/mailhog";

const SET_PASSWORD_LINK = /\/set-password\/[0-9a-f-]{36}$/;

test.use({ persona: "office" });

test("an invited member sets a password through the mailed link and logs in", async ({
  page,
  browser,
}) => {
  const lastName = `Run${Date.now()}`;
  const email = `${lastName.toLowerCase()}@example.com`;
  // Passes the server's policy (12 characters, a strong zxcvbn score).
  const password = `${lastName}-Kiwi!Harbor#Lamp`;
  await clearMailbox(email);

  // The member, added inline on the member list.
  await page.goto("/members/members");
  await page.getByRole("button", { name: t("table.add_record"), exact: true }).click();
  await page.getByRole("textbox", { name: t("members.first_name") }).fill("E2E");
  await page.getByRole("textbox", { name: t("members.last_name") }).fill(lastName);
  await page.getByRole("textbox", { name: t("members.email") }).fill(email);
  const memberCreated = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/commissioning/members/") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: t("table.save"), exact: true }).click();
  expect((await memberCreated).status()).toBe(201);

  // The invitation, from the member's account status.
  await page
    .getByRole("searchbox", { name: t("table.search_placeholder") })
    .fill(lastName);
  const memberRow = page.getByRole("row").filter({ hasText: lastName });
  await memberRow
    .getByRole("button", { name: t("button_library.user_not_invited") })
    .click();
  await page
    .getByRole("dialog", { name: t("members.user_info_modal_title") })
    .getByRole("button", { name: t("users.send_invitation") })
    .click();
  const invited = page.waitForResponse(
    (response) =>
      response.url().endsWith("/send_invitation/") &&
      response.request().method() === "POST",
  );
  const invitation = page.getByRole("dialog", { name: t("members.send_invitation") });
  await expect(invitation.getByRole("textbox", { name: t("members.email") })).toHaveValue(
    email,
  );
  await invitation
    .getByRole("button", { name: t("commissioning.send"), exact: true })
    .click();
  expect((await invited).status()).toBe(200);
  await expect(
    memberRow.getByRole("button", { name: t("button_library.user_pending_invitation") }),
  ).toBeVisible();

  // The mail links to this tenant's own host and port (frontend_base_url).
  const mail = await waitForMail(email);
  const link = linksIn(mail).find((candidate) => SET_PASSWORD_LINK.test(candidate));
  expect(link, `a set-password link in "${mail.subject}"`).toMatch(
    new RegExp(`^${BASE_URL.replace(/\./g, "\\.")}/set-password/[0-9a-f-]{36}$`),
  );

  // The invitee opens it in a browser of their own.
  const inviteeContext = await browser.newContext({
    baseURL: BASE_URL,
    locale: "en-US",
  });
  try {
    const invitee = await inviteeContext.newPage();
    await invitee.goto(link ?? "");
    await invitee
      .getByLabel(t("auth.set_password.choose_password"), { exact: true })
      .fill(password);
    await invitee
      .getByLabel(t("auth.set_password.confirm_password"), { exact: true })
      .fill(password);
    await invitee
      .getByRole("button", { name: t("auth.set_password.submit") })
      .click();
    await expect(invitee.getByText(t("auth.set_password.success"))).toBeVisible();
    await expect(invitee).toHaveURL("/login");

    await logInWithPassword(invitee, email, password);
    await expect(invitee).toHaveURL(/\/members\/members\/\w+$/);
    await expect(
      invitee.getByRole("heading", { name: `E2E ${lastName}` }),
    ).toBeVisible();
  } finally {
    await inviteeContext.close();
  }
});
