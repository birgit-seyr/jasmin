import { mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import path from "node:path";
import {
  expect,
  request,
  test as base,
  type APIRequestContext,
  type BrowserContext,
  type Locator,
  type Page,
} from "@playwright/test";
import {
  BASE_URL,
  PERSONA_PASSWORD,
  PERSONAS,
  storageStatePath,
  type Persona,
} from "./env";
import { t } from "./i18n";

const LOGIN_PATH = "/api/auth/login/";
const REFRESH_PATH = "/api/auth/refresh/";

/** The account menu every signed-in layout (office, member, customer) shows. */
export function accountMenu(page: Page): Locator {
  return page.getByRole("button", { name: t("profile.menu_aria") });
}

export function signInButton(page: Page): Locator {
  return page.getByRole("button", { name: t("auth.login_card.sign_in") });
}

/** Logs a persona in through the login form and waits for the signed-in app. */
export async function logInThroughUi(page: Page, persona: Persona): Promise<void> {
  await page.goto("/login");
  await page
    .getByRole("textbox", { name: t("auth.login_card.email") })
    .fill(PERSONAS[persona]);
  await page
    .getByLabel(t("auth.login_card.password"), { exact: true })
    .fill(PERSONA_PASSWORD);
  const loginResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith(LOGIN_PATH) &&
      response.request().method() === "POST",
  );
  await signInButton(page).click();
  const response = await loginResponse;
  expect(response.status(), `login as ${persona}`).toBe(200);
  const body = (await response.json()) as { requires_2fa?: boolean };
  expect(
    body.requires_2fa,
    `${persona} has two-factor auth; run seed_e2e again to remove it`,
  ).toBeFalsy();
  await expect(accountMenu(page)).toBeVisible();
}

/**
 * Answers the step-up prompt the app opens when an action needs a fresh
 * password confirmation. The personas have no two-factor device, so the
 * password alone confirms (``STEP_UP_REQUIRES_TOTP`` asks only users with one).
 */
export async function confirmStepUp(page: Page): Promise<void> {
  const dialog = page.getByRole("dialog", { name: t("auth.step_up.title") });
  await dialog
    .getByRole("textbox", { name: t("auth.step_up.password") })
    .fill(PERSONA_PASSWORD);
  await dialog.getByRole("button", { name: t("auth.step_up.submit") }).click();
  await expect(dialog).toBeHidden();
}

/**
 * Opens ``url`` and returns the access token the app's silent refresh on load
 * obtained. The token lives only in the page's memory, so this is the one way
 * to hold it outside the page.
 */
export async function gotoCapturingAccessToken(
  page: Page,
  url: string,
): Promise<string> {
  const refreshResponse = page.waitForResponse((response) =>
    response.url().endsWith(REFRESH_PATH),
  );
  await page.goto(url);
  const response = await refreshResponse;
  expect(response.status(), "silent refresh on load").toBe(200);
  return ((await response.json()) as { access: string }).access;
}

interface SavedState {
  cookies: Awaited<ReturnType<BrowserContext["storageState"]>>["cookies"];
  origins: Awaited<ReturnType<BrowserContext["storageState"]>>["origins"];
}

function readSavedState(file: string): SavedState | undefined {
  if (!existsSync(file)) return undefined;
  return JSON.parse(readFileSync(file, "utf8")) as SavedState;
}

async function logInThroughApi(
  api: APIRequestContext,
  persona: Persona,
): Promise<void> {
  const response = await api.post(LOGIN_PATH, {
    data: { email: PERSONAS[persona], password: PERSONA_PASSWORD },
  });
  expect(response.status(), `API login as ${persona}`).toBe(200);
  const body = (await response.json()) as { requires_2fa?: boolean };
  expect(body.requires_2fa, `${persona} has two-factor auth`).toBeFalsy();
}

/**
 * Hands a test a refresh cookie that is still valid.
 *
 * Refresh tokens rotate and the old one is blacklisted on every refresh, so a
 * saved cookie is good for exactly one refresh. The page's silent refresh
 * spends it, and the context fixture below writes the rotated one back after
 * each test. When that chain broke (a test logged out, or ended mid-refresh),
 * this logs the persona in again over the API.
 */
async function freshStorageState(persona: Persona): Promise<string> {
  const file = storageStatePath(persona);
  const saved = readSavedState(file);
  const api = await request.newContext({
    baseURL: BASE_URL,
    storageState: saved ? { cookies: saved.cookies, origins: [] } : undefined,
  });
  try {
    const refreshed = saved ? (await api.post(REFRESH_PATH)).ok() : false;
    if (!refreshed) await logInThroughApi(api, persona);
    const { cookies } = await api.storageState();
    mkdirSync(path.dirname(file), { recursive: true });
    writeFileSync(
      file,
      JSON.stringify({ cookies, origins: saved?.origins ?? [] }, null, 2),
    );
  } finally {
    await api.dispose();
  }
  return file;
}

function hasRefreshCookie(state: SavedState): boolean {
  return state.cookies.some(
    (cookie) => cookie.name === "refresh_token" && cookie.value !== "",
  );
}

interface SessionFixtures {
  /** The persona a test runs as; unset, the test starts logged out. */
  persona: Persona | undefined;
}

export const test = base.extend<SessionFixtures>({
  persona: [undefined, { option: true }],

  storageState: async ({ persona, storageState }, use) => {
    await use(persona ? await freshStorageState(persona) : storageState);
  },

  context: async ({ context, persona }, use) => {
    await use(context);
    if (!persona) return;
    const state = await context.storageState();
    if (hasRefreshCookie(state)) {
      writeFileSync(storageStatePath(persona), JSON.stringify(state, null, 2));
    }
  },
});

export { expect };
