import { useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { Button } from "antd";
import i18n from "@shared/i18n";
import { notify } from '@shared/utils';
import { getErrorMessage, messageForErrorCode } from '@shared/utils/apiError';

interface BulkItemFailure {
  id?: string | number;
  error?: string;
  code?: string;
}

/**
 * Per-item failures a bulk endpoint reports next to what it did write.
 *
 * A partial-success body (HTTP 207) resolves exactly like a 200, so without
 * reading this the ids the endpoint refused — an inventory row that already
 * carries a count, an order that could not be finalized — vanish behind a
 * plain success.
 */
const partialFailures = (data: unknown): BulkItemFailure[] => {
  if (!data || typeof data !== "object") return [];
  const { errors } = data as { errors?: unknown };
  return Array.isArray(errors) ? (errors as BulkItemFailure[]) : [];
};

/** A skipped item's reason: its error code's translation when there is one,
 * else the server's own (English) text. */
const failureReason = ({ code, error }: BulkItemFailure): string =>
  (code && messageForErrorCode(code)) || error || "";

/** The body a bulk endpoint receives: the selected ids next to the caller's
 * own fields (e.g. ``{ model: "invoice" }``). Model ids are strings, so the
 * selected row keys travel as strings. */
export type BulkActionRequest<TPayload extends object> = TPayload & {
  ids: string[];
};

// Generic over the request and the response body. ``TPayload`` infers from
// the ``payload`` prop alone (``const``, so ``{ model: "invoice" }`` keeps
// its literal; ``NoInfer`` keeps ``apiFunction`` from widening it), so a
// generated client function takes the request as it is, and one that needs
// more than the ids refuses to compile without the ``payload`` carrying it.
// ``TResponse`` infers from the ``apiFunction`` return type, so
// ``onSuccess`` receives the typed body.
interface BulkActionButtonProps<TPayload extends object, TResponse> {
  selectedIds?: (string | number)[];
  apiFunction: (
    request: BulkActionRequest<NoInfer<TPayload>>,
  ) => Promise<TResponse>;
  buttonText: ReactNode;
  buttonProps?: Record<string, unknown>;
  onSuccess?: (data: TResponse, selectedIds: (string | number)[]) => void;
  onError?: (error: unknown, selectedIds: (string | number)[]) => void;
  disabled?: boolean;
  confirmMessage?: string;
  successMessage?: string;
  errorMessage?: string;
  payload?: TPayload;
  refreshData?: () => Promise<void> | void;
  icon?: ReactNode;
  style?: CSSProperties;
  onClearSelection?: () => void;
}

const BulkActionButton = <
  const TPayload extends object = Record<never, never>,
  TResponse = unknown,
>({
  selectedIds = [],
  apiFunction,
  buttonText,
  buttonProps = {},
  onSuccess,
  onError,
  disabled = false,
  confirmMessage,
  successMessage,
  errorMessage,
  payload,
  refreshData,
  icon,
  style = {},
  onClearSelection,
}: BulkActionButtonProps<TPayload, TResponse>) => {
  const [loading, setLoading] = useState(false);

  const handleClick = async () => {
    if (selectedIds.length === 0) {
      notify.warning(i18n.t("table.bulk_select_at_least_one"));
      return;
    }

    if (confirmMessage) {
      const confirmed = window.confirm(confirmMessage);
      if (!confirmed) return;
    }

    setLoading(true);

    try {
      // Without a ``payload`` prop ``TPayload`` is the empty default, so the
      // spread of ``undefined`` still yields the declared request.
      const request = {
        ...payload,
        ids: selectedIds.map(String),
      } as BulkActionRequest<TPayload>;
      const responseData = await apiFunction(request);

      if (onClearSelection) {
        onClearSelection();
      }

      const skipped = partialFailures(responseData);
      if (skipped.length > 0) {
        notify.warning(
          i18n.t("table.bulk_partial_skipped", {
            skipped: skipped.length,
            total: selectedIds.length,
            reason: failureReason(skipped[0]),
          }),
        );
      } else if (successMessage) {
        notify.success(successMessage);
      }

      if (onSuccess) {
        await onSuccess(responseData, selectedIds);
      }
      if (refreshData && typeof refreshData === "function") {
        await refreshData();
      }
    } catch (error: unknown) {
      console.error("Bulk action failed:", error);
      notify.error(errorMessage || getErrorMessage(error, "Action failed"));
      if (onError) {
        onError(error, selectedIds);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <Button
      onClick={handleClick}
      loading={loading}
      disabled={disabled || selectedIds.length === 0}
      icon={icon}
      size="small"
      {...buttonProps}
      style={{
        marginTop: "2.5em",
        height: "1.8em",
        ...style,
      }}
    >
      {buttonText}
    </Button>
  );
};

export default BulkActionButton;
