import { useCallback, type KeyboardEvent } from "react";

/**
 * Returns an onKeyDown handler that submits the surrounding form when the
 * user presses Enter (without Shift, so multi-line inputs still work).
 */
export function useEnterToSubmit(submit: () => void) {
  return useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        submit();
      }
    },
    [submit],
  );
}
