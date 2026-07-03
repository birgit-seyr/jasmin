/**
 * Sanctioned logging façade — use this instead of raw `console.*`.
 *
 * `debug` / `info` are DEV-ONLY (silent in production) for diagnostic noise
 * that shouldn't reach users' consoles. `warn` / `error` always pass through
 * (and survive the prod build — terser keeps `console.warn` / `console.error`
 * while dropping `console.log` / `info` / `debug`).
 *
 * The `no-console` ESLint rule forbids bare `console.log` / `info` / `debug`
 * everywhere except this file (and tests), which is what nudges code here —
 * so debug leftovers can't silently ship and intentional dev logging has a
 * single, prod-safe home.
 */
const isDev = import.meta.env.DEV;

export const logger = {
  debug: (...args: unknown[]): void => {
    if (isDev) console.debug(...args);
  },
  info: (...args: unknown[]): void => {
    if (isDev) console.info(...args);
  },
  warn: (...args: unknown[]): void => {
    console.warn(...args);
  },
  error: (...args: unknown[]): void => {
    console.error(...args);
  },
};
