import { readFile } from "node:fs/promises";
import { expect, test } from "../support/auth";
import { t } from "../support/i18n";

const BOM = "\uFEFF";
// The member register's header is German on purpose (a machine-readable
// export); only delimiter, decimals and dates follow the tenant's csv_format.
const HEADER = [
  "Mitgliedsnummer",
  "Name",
  "Adresse",
  "PLZ",
  "Ort",
  "Eintrittsdatum",
  "Austrittsdatum",
  "Anzahl Geschäftsanteile",
  "Geschäftsguthaben",
];
// The member persona, confirmed by seed_e2e_commissioning; the register
// writes "last first".
const MEMBER_PERSONA_NAME = "Member Test";

test.use({ persona: "office" });

test("the member register downloads in the tenant's csv format", async ({
  page,
}) => {
  await page.goto("/members/members");
  await page
    .getByRole("button", { name: t("members.export_member_register") })
    .click();
  const dialog = page.getByRole("dialog", {
    name: t("members.export_member_register"),
  });
  await dialog.getByRole("textbox").first().click();
  await page.getByText(t("common.this_year"), { exact: true }).click();

  const download = page.waitForEvent("download");
  await dialog.getByRole("button", { name: t("common.download") }).click();
  const file = await download;
  const year = new Date().getFullYear();
  expect(file.suggestedFilename()).toBe(
    `mitgliederliste_${year}-01-01_${year}-12-31.csv`,
  );

  const content = await readFile(await file.path(), "utf8");
  // Exactly one UTF-8 BOM, for Excel: the server writes it, and the
  // download must not add a second.
  expect(content.startsWith(BOM), "a UTF-8 BOM for Excel").toBe(true);
  expect(content.startsWith(BOM + BOM), "a second BOM").toBe(false);
  const lines = content.slice(BOM.length).trimEnd().split(/\r?\n/);
  // The e2e tenant runs in English with the "de" csv format: semicolons, even
  // though the UI language would suggest commas.
  expect(lines[0]).toBe(HEADER.join(";"));

  const personaRow = lines
    .map((line) => line.split(";"))
    .find((cells) => cells[1] === MEMBER_PERSONA_NAME);
  expect(personaRow, `${MEMBER_PERSONA_NAME} in the register`).toBeDefined();
  const cells = personaRow ?? [];
  expect(cells).toHaveLength(HEADER.length);
  expect(cells[0]).toMatch(/^\d+$/);
  // Dates as dd.mm.yyyy and a decimal comma.
  expect(cells[5]).toMatch(/^\d{2}\.\d{2}\.\d{4}$/);
  expect(cells[6]).toBe("");
  expect(cells[8]).toBe("0,00");
});
