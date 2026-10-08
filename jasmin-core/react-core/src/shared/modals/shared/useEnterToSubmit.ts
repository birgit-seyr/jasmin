import { useCallback, useRef, type KeyboardEvent } from "react";

/**
 * Returns an onKeyDown handler that submits the surrounding form when the
 * user presses Enter (without Shift, so multi-line inputs still work).
 *
 * When ``submit`` returns a promise, Enter does nothing until it settles, so
 * pressing Enter again while a save runs can't send the save a second time.
 * Return the save's promise from ``submit`` to get that guard.
 */
export function useEnterToSubmit(submit: () => unknown) {
  const pending = useRef(false);
  return useCallback(
    (e: KeyboardEvent) => {
      if (e.key !== "Enter" || e.shiftKey) return;
      e.preventDefault();
      if (pending.current) return;
      const result = submit();
      if (result instanceof Promise) {
        pending.current = true;
        const release = () => {
          pending.current = false;
        };
        void result.then(release, release);
      }
    },
    [submit],
  );
}
