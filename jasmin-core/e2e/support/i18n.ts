import { readFileSync } from "node:fs";
import path from "node:path";
import { LOCALES_DIR } from "./env";

/** The language the E2E tenants and their personas are seeded in. */
const LANGUAGE = "en";

const namespaces = new Map<string, Record<string, unknown>>();

function loadNamespace(namespace: string): Record<string, unknown> {
  let messages = namespaces.get(namespace);
  if (!messages) {
    const file = path.join(LOCALES_DIR, LANGUAGE, `${namespace}.json`);
    messages = JSON.parse(readFileSync(file, "utf8")) as Record<string, unknown>;
    namespaces.set(namespace, messages);
  }
  return messages;
}

/**
 * The English copy for an i18n key, read from the frontend's locale files the
 * way the app's ``t("ns.key")`` resolves it, so a copy edit doesn't break a
 * test. ``{{name}}`` placeholders are filled from ``values``. Throws on a
 * missing key instead of matching the raw key string.
 */
export function t(
  key: string,
  values: Record<string, string | number> = {},
): string {
  const [namespace, ...rest] = key.split(".");
  let node: unknown = loadNamespace(namespace);
  for (const part of rest) {
    node =
      typeof node === "object" && node !== null
        ? (node as Record<string, unknown>)[part]
        : undefined;
  }
  if (typeof node !== "string") {
    throw new Error(`No ${LANGUAGE} string for i18n key "${key}"`);
  }
  return node.replace(/\{\{(\w+)\}\}/g, (placeholder, name: string) =>
    name in values ? String(values[name]) : placeholder,
  );
}
