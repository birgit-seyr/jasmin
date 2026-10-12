import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

/** The ``e2e`` tenant every flow runs in (seeded by ``seed_e2e``). */
export const BASE_URL = process.env.E2E_BASE_URL ?? "http://e2e.localhost:3000";

/** A second tenant with the same persona logins (seeded by ``seed_e2e``). */
export const OTHER_TENANT_URL =
  process.env.E2E_OTHER_BASE_URL ?? "http://e2e-other.localhost:3000";

/** The super-admin platform (``SUPER_ADMIN_SUBDOMAIN``, ``marillen`` in dev). */
export const PLATFORM_URL =
  process.env.E2E_PLATFORM_URL ?? "http://marillen.localhost:3000";

/** The dev stack's MailHog, which catches every mail the backend sends. */
export const MAILHOG_URL = process.env.E2E_MAILHOG_URL ?? "http://localhost:8025";

/** The password ``seed_test_users`` gives every persona. */
export const PERSONA_PASSWORD = "Test-Test-2026";

export const PERSONAS = {
  admin: "test-admin@example.com",
  office: "test-office@example.com",
  member: "test-member@example.com",
} as const;

export type Persona = keyof typeof PERSONAS;

/** The platform super-admin ``seed_e2e`` creates, with the persona password. */
export const SUPER_ADMIN_EMAIL = "e2e-superadmin@example.com";

/** Saved browser state of the super-admin session on the platform host. */
export const SUPER_ADMIN_STORAGE_STATE = path.join(
  here,
  "..",
  ".auth",
  "super-admin.json",
);

/** Saved browser state per persona, written by the setup project. */
export function storageStatePath(persona: Persona): string {
  return path.join(here, "..", ".auth", `${persona}.json`);
}

/** The frontend's locale files, read for the copy the tests assert. */
export const LOCALES_DIR = path.join(
  here,
  "..",
  "..",
  "react-core",
  "src",
  "shared",
  "i18n",
  "locales",
);
