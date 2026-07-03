import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Single source of truth for the configuration-page autosave debounce.
 *
 * Hosts: ``hasChanges`` / ``saving`` flags, a per-change debounce
 * window, and the timer that fires the supplied ``save`` callback once
 * the window expires. Callers wire it up in three places:
 *
 *  1. ``markChanged(fieldType?)`` from every change handler. Pass the
 *     field's renderer type so the hook can shorten the delay for
 *     single-click inputs.
 *  2. ``hasChanges`` / ``saving`` into an ``<AutoSaveIndicator />``.
 *  3. ``save`` — usually a ``useCallback`` that PATCHes the right rows.
 *     The hook keeps a ``ref`` to the latest callback so its identity
 *     doesn't churn the autosave effect.
 *
 * Delay policy:
 *
 *  * ``"select"`` / ``"checkbox"`` / ``"switch"`` / ``"file"`` →
 *    immediate (``0 ms``). Single-click changes feel instant.
 *  * Anything else (text inputs, textareas, custom inputs) →
 *    ``debounceMs`` (default ``500 ms``) so a flurry of keystrokes
 *    coalesces into one PATCH.
 *
 *  Whichever delay the latest ``markChanged`` call sets wins — clicking
 *  a dropdown after typing immediately collapses the open window;
 *  typing after a dropdown click bumps it back to the debounced window.
 */
const IMMEDIATE_TYPES: ReadonlySet<string> = new Set([
  "select",
  "checkbox",
  "switch",
  "file",
]);

const DEFAULT_DEBOUNCE_MS = 500;

interface UseAutoSaveOptions {
  /**
   * The autosave only arms while this is ``true``. Typically
   * ``Boolean(tenant?.id) && !loading``.
   */
  enabled: boolean;
  /** PATCH callback fired when the debounce window expires. */
  save: () => Promise<void> | void;
  /**
   * Override the debounce window for text-input changes. Defaults to
   * 500 ms. Immediate-save types still go to 0 ms regardless.
   */
  debounceMs?: number;
}

interface UseAutoSaveReturn {
  hasChanges: boolean;
  saving: boolean;
  /**
   * True when the last autosave attempt failed. ``hasChanges`` stays true in
   * that case (the change is NOT persisted), and the autosave is disarmed
   * until the next ``markChanged`` so a persistent failure can't retry-loop.
   */
  saveError: boolean;
  /**
   * Mark the form dirty. Pass the field's renderer ``type`` so
   * dropdowns / checkboxes fire immediately and text inputs stay
   * debounced.
   */
  markChanged: (fieldType?: string) => void;
  /**
   * Manually force a save now (e.g. ``beforeunload`` listener).
   * Clears any pending debounce timer.
   */
  flush: () => Promise<void>;
}

export function useAutoSave(opts: UseAutoSaveOptions): UseAutoSaveReturn {
  const { enabled, save, debounceMs = DEFAULT_DEBOUNCE_MS } = opts;

  const [hasChanges, setHasChanges] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(false);
  const [delay, setDelay] = useState(debounceMs);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Keep a ref to the latest ``save`` so the autosave effect doesn't
  // re-arm every render when the caller passes an inline arrow.
  const saveRef = useRef(save);
  saveRef.current = save;

  const flush = useCallback(async () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setSaving(true);
    try {
      await saveRef.current();
      // Clear dirty ONLY after the save actually resolved.
      setHasChanges(false);
      setSaveError(false);
    } catch (err) {
      // The save handler rejected (and is expected to have surfaced the
      // failure to the user). Keep ``hasChanges`` so the indicator never
      // shows "saved" over a lost change, and flag the error so the autosave
      // does NOT immediately retry — a persistent failure (e.g. validation)
      // would otherwise loop every debounce window. The next ``markChanged``
      // clears the flag and re-arms. Swallow here so the ``void flush()`` in
      // the effect can't raise an unhandled rejection.
      console.error("Autosave failed:", err);
      setSaveError(true);
    } finally {
      setSaving(false);
    }
  }, []);

  const markChanged = useCallback(
    (fieldType?: string) => {
      setHasChanges(true);
      // A fresh edit clears any prior failure and re-arms the autosave.
      setSaveError(false);
      setDelay(fieldType && IMMEDIATE_TYPES.has(fieldType) ? 0 : debounceMs);
    },
    [debounceMs],
  );

  useEffect(() => {
    if (!enabled || !hasChanges || saving || saveError) return;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      void flush();
    }, delay);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [enabled, hasChanges, saving, saveError, delay, flush]);

  return { hasChanges, saving, saveError, markChanged, flush };
}
