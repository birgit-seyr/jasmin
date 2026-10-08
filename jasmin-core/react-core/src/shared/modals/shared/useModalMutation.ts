import { useCallback, useRef, useState } from "react";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";

export interface ModalMutationOptions<T> {
  /** Toast shown on success. Omit for a silent success. */
  successMessage?: string;
  /** Fallback toast on failure (the server message wins when present). */
  errorMessage?: string;
  /** Runs after a successful action — close the modal, patch the parent, … */
  onSuccess?: (result: T) => void;
}

/**
 * The "save + validate-already-done + notify + saving-flag" lifecycle every
 * edit modal repeats. Owns the in-flight ``saving`` flag and wraps a single
 * async action in try/catch/finally so callers only supply the mutation and
 * their own toast strings.
 *
 * Usage::
 *
 *   const { saving, run } = useModalMutation();
 *   const handleSubmit = (values) =>
 *     run(async () => api.update(id, values), {
 *       successMessage: savedMessage,   // a translated string the caller passes
 *       errorMessage: saveErrorMessage, // a translated string the caller passes
 *       onSuccess: (updated) => { onSaved(updated); onClose(); },
 *     });
 *
 * Validation stays with the caller (or ``EditFormModal``) so validation
 * failures never surface a toast — only the action's own errors do.
 *
 * While an action runs, a further ``run`` is ignored and resolves to
 * ``undefined``: the OK button is disabled while saving, but Enter in the form
 * and a click racing an Enter would otherwise send the save twice.
 */
export function useModalMutation() {
  const [saving, setSaving] = useState(false);
  const inFlight = useRef(false);

  const run = useCallback(
    async <T,>(
      action: () => Promise<T>,
      options?: ModalMutationOptions<T>,
    ): Promise<T | undefined> => {
      if (inFlight.current) return undefined;
      inFlight.current = true;
      setSaving(true);
      try {
        const result = await action();
        if (options?.successMessage) notify.success(options.successMessage);
        options?.onSuccess?.(result);
        return result;
      } catch (error) {
        notify.error(getErrorMessage(error, options?.errorMessage));
        return undefined;
      } finally {
        inFlight.current = false;
        setSaving(false);
      }
    },
    [],
  );

  return { saving, run };
}

export default useModalMutation;
