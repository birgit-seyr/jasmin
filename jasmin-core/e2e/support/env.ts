import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

/** The ``e2e`` tenant every flow runs in (seeded by ``seed_e2e``). */
export const BASE_URL = process.env.E2E_BASE_URL ?? "http://e2e.localhost:3000";

/** A second tenant with the same persona logins (seeded by ``seed_e2e``). */
export const OTHER_TENANT_URL =
  process.env.E2E_OTHER_BASE_URL ?? "http://e2e-other.localhost:3000";

/** The password ``seed_test_users`` gives every persona. */
export const PERSONA_PASSWORD = "Test-Test-2026";

export const PERSONAS = {
  admin: "test-admin@example.com",
  office: "test-office@example.com",
  member: "test-member@example.com",
} as const;

export type Persona = keyof typeof PERSONAS;

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
