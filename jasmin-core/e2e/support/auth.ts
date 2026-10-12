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
  PLATFORM_URL,
  SUPER_ADMIN_EMAIL,
  SUPER_ADMIN_STORAGE_STATE,
  storageStatePath,
  type Persona,
} from "./env";
import { t } from "./i18n";

const LOGIN_PATH = "/api/auth/login/";
const REFRESH_PATH = "/api/auth/refresh/";
const SUPER_ADMIN_LOGIN_PATH = "/api/super-admin/auth/login/";
const SUPER_ADMIN_REFRESH_PATH = "/api/super-admin/auth/refresh/";

/** The account menu every signed-in layout (office, member, customer) shows. */
export function accountMenu(page: Page): Locator {
  return page.getByRole("button", { name: t("profile.menu_aria") });
}

export function signInButton(page: Page): Locator {
  return page.getByRole("button", { name: t("auth.login_card.sign_in") });
}

/** Logs a persona in through the login form and waits for the signed-in app. */
export async function logInThroughUi(page: Page, persona: Persona): Promise<void> {
  await logInWithPassword(page, PERSONAS[persona], PERSONA_PASSWORD);
}

/** Logs ``email`` in through the login form and waits for the signed-in app. */
export async function logInWithPassword(
  page: Page,
  email: string,
  password: string,
): Promise<void> {
  await page.goto("/login");
  await page
    .getByRole("textbox", { name: t("auth.login_card.email") })
    .fill(email);
  await page
    .getByLabel(t("auth.login_card.password"), { exact: true })
    .fill(password);
  const loginResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith(LOGIN_PATH) &&
      response.request().method() === "POST",
  );
  await signInButton(page).click();
  const response = await loginResponse;
  expect(response.status(), `login as ${email}`).toBe(200);
  const body = (await response.json()) as { requires_2fa?: boolean };
  expect(
    body.requires_2fa,
    `${email} has two-factor auth; run seed_e2e again to remove it`,
  ).toBeFalsy();
  await expect(accountMenu(page)).toBeVisible();
}

/**
 * Logs the platform super-admin in through the platform's login form. The page
 * is English-only and its labels aren't tied to the inputs, so the fields are
 * found by their placeholders.
 */
export async function logInAsSuperAdminThroughUi(page: Page): Promise<void> {
  await page.goto(`${PLATFORM_URL}/`);
  await page.getByPlaceholder("admin@platform.com").fill(SUPER_ADMIN_EMAIL);
  await page.getByPlaceholder("••••••••").fill(PERSONA_PASSWORD);
  const loginResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith(SUPER_ADMIN_LOGIN_PATH) &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Login to Platform" }).click();
  expect((await loginResponse).status(), "super-admin login").toBe(200);
  await expect(page.getByRole("heading", { name: "All Tenants" })).toBeVisible();
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

/** One login realm: where its refresh cookie lives and how to get a new one. */
interface Session {
  file: string;
  baseURL: string;
  refreshPath: string;
  cookieName: string;
  logIn: (api: APIRequestContext) => Promise<void>;
}

function personaSession(persona: Persona): Session {
  return {
    file: storageStatePath(persona),
    baseURL: BASE_URL,
    refreshPath: REFRESH_PATH,
    cookieName: "refresh_token",
    logIn: async (api) => {
      const response = await api.post(LOGIN_PATH, {
        data: { email: PERSONAS[persona], password: PERSONA_PASSWORD },
      });
      expect(response.status(), `API login as ${persona}`).toBe(200);
      const body = (await response.json()) as { requires_2fa?: boolean };
      expect(body.requires_2fa, `${persona} has two-factor auth`).toBeFalsy();
    },
  };
}

// The super-admin login is throttled to 10 an hour per IP, so a broken chain
// costs one of them; the setup project spends one more per run.
const SUPER_ADMIN_SESSION: Session = {
  file: SUPER_ADMIN_STORAGE_STATE,
  baseURL: PLATFORM_URL,
  refreshPath: SUPER_ADMIN_REFRESH_PATH,
  cookieName: "sa_refresh_token",
  logIn: async (api) => {
    const response = await api.post(SUPER_ADMIN_LOGIN_PATH, {
      data: { email: SUPER_ADMIN_EMAIL, password: PERSONA_PASSWORD },
    });
    expect(response.status(), "API login as the super-admin").toBe(200);
  },
};

/**
 * Hands a test a refresh cookie that is still valid, and the access token the
 * refresh behind it returned.
 *
 * Refresh tokens rotate and the old one is blacklisted on every refresh, so a
 * saved cookie is good for exactly one refresh. The page's silent refresh
 * spends it, and the context fixture below writes the rotated one back after
 * each test. When that chain broke (a test logged out, or ended mid-refresh),
 * this logs in again over the API.
 */
async function refreshSavedSession(
  session: Session,
): Promise<{ file: string; access: string }> {
  const saved = readSavedState(session.file);
  const api = await request.newContext({
    baseURL: session.baseURL,
    storageState: saved ? { cookies: saved.cookies, origins: [] } : undefined,
  });
  try {
    let refresh = saved ? await api.post(session.refreshPath) : undefined;
    if (!refresh?.ok()) {
      await session.logIn(api);
      refresh = await api.post(session.refreshPath);
      expect(refresh.status(), "refresh after an API login").toBe(200);
    }
    const { access } = (await refresh.json()) as { access: string };
    const { cookies } = await api.storageState();
    mkdirSync(path.dirname(session.file), { recursive: true });
    writeFileSync(
      session.file,
      JSON.stringify({ cookies, origins: saved?.origins ?? [] }, null, 2),
    );
    return { file: session.file, access };
  } finally {
    await api.dispose();
  }
}

/**
 * An access token for ``persona``, for API calls a test makes as someone
 * other than its own persona. It keeps the persona's saved session going.
 */
export async function accessTokenFor(persona: Persona): Promise<string> {
  return (await refreshSavedSession(personaSession(persona))).access;
}

function hasRefreshCookie(state: SavedState, cookieName: string): boolean {
  return state.cookies.some(
    (cookie) => cookie.name === cookieName && cookie.value !== "",
  );
}

interface SessionFixtures {
  /** The persona a test runs as; unset, the test starts logged out. */
  persona: Persona | undefined;
  /** Whether the test runs as the platform super-admin instead. */
  superAdmin: boolean;
}

function sessionOf(
  persona: Persona | undefined,
  superAdmin: boolean,
): Session | undefined {
  if (superAdmin) return SUPER_ADMIN_SESSION;
  return persona ? personaSession(persona) : undefined;
}

export const test = base.extend<SessionFixtures>({
  persona: [undefined, { option: true }],
  superAdmin: [false, { option: true }],

  storageState: async ({ persona, superAdmin, storageState }, use) => {
    const session = sessionOf(persona, superAdmin);
    await use(session ? (await refreshSavedSession(session)).file : storageState);
  },

  context: async ({ context, persona, superAdmin }, use) => {
    await use(context);
    const session = sessionOf(persona, superAdmin);
    if (!session) return;
    const state = await context.storageState();
    if (hasRefreshCookie(state, session.cookieName)) {
      writeFileSync(session.file, JSON.stringify(state, null, 2));
    }
  },
});

export { expect };
