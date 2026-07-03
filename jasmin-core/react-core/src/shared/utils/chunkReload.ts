/**
 * Recovery for a failed lazy/dynamic ``import()`` of a route chunk.
 *
 * Two ways this happens:
 *  - PRODUCTION: a still-open tab runs an old bundle that references old hashed
 *    chunk files; after a deploy those files are gone, so the import 404s.
 *  - DEV (Vite dev server, e.g. the dev Docker stack): Vite re-optimizes
 *    dependencies on the fly when it first sees a route-only import, or the
 *    container hiccups under file-watch polling — the import then comes back as
 *    a 504 ("Outdated Optimize Dep").
 *
 * Both surface the same browser errors. A hard reload fetches the no-cache
 * ``index.html`` (prod) or the freshly re-optimized module graph (dev), so the
 * import resolves. ``main.tsx``'s ``vite:preloadError`` hook (prod-only event)
 * and the global ``ErrorBoundary`` (message-based, dev + prod) both route here
 * so they share ONE loop-guard.
 */

const RELOAD_AT_KEY = "chunk-reload-at";
const RELOAD_WINDOW_MS = 10_000;

/** True if ``error`` is a failed dynamic import / chunk load (not a normal app
 * bug). Message-based so it works in the dev server too, where Vite's
 * ``vite:preloadError`` event isn't emitted. */
export function isDynamicImportError(error: unknown): boolean {
  if (!error) return false;
  const name = (error as { name?: unknown }).name;
  if (name === "ChunkLoadError") return true;
  const message = (error as { message?: unknown }).message;
  if (typeof message !== "string") return false;
  return /failed to fetch dynamically imported module|error loading dynamically imported module|importing a module script failed|outdated optimize dep|unable to preload css/i.test(
    message,
  );
}

/**
 * Reload the page ONCE to recover a stale/failed chunk. Returns ``true`` if it
 * triggered a reload, ``false`` if the loop-guard blocked it.
 *
 * Guard: if we already reloaded for a chunk error within the last 10s and it's
 * STILL failing, the chunk is genuinely broken (offline, blocked by an
 * extension, a real 404) — don't reload-storm; let the caller surface the
 * error instead.
 */
export function reloadOnceForChunkError(): boolean {
  let last = 0;
  try {
    last = Number(window.sessionStorage.getItem(RELOAD_AT_KEY) ?? 0);
  } catch {
    // sessionStorage can throw (Firefox ETP / blocked storage) — reload anyway.
  }
  if (Date.now() - last < RELOAD_WINDOW_MS) return false;
  try {
    window.sessionStorage.setItem(RELOAD_AT_KEY, String(Date.now()));
  } catch {
    // ignore — the reload is more important than the guard bookkeeping.
  }
  window.location.reload();
  return true;
}
