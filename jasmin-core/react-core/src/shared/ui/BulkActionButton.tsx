import { useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { Button } from "antd";
import axiosService from "@shared/services/api";
import { notify } from '@shared/utils';
import { getErrorMessage } from '@shared/utils/apiError';

// Generic over the response body: ``TResponse`` infers from the
// ``apiFunction`` return type, so ``onSuccess`` receives the typed body
// (e.g. ``BulkOperationResponse`` from the generated bulk endpoints)
// instead of ``unknown``. Defaults to ``unknown`` for the ``apiEndpoint``
// path and for callers that ignore the response.
interface BulkActionButtonProps<TResponse = unknown> {
  selectedIds?: (string | number)[];
  apiEndpoint?: string;
  apiFunction?: (payload: Record<string, unknown>) => Promise<TResponse>;
  method?: string;
  buttonText: ReactNode;
  buttonProps?: Record<string, unknown>;
  onSuccess?: (data: TResponse, selectedIds: (string | number)[]) => void;
  onError?: (error: unknown, selectedIds: (string | number)[]) => void;
  disabled?: boolean;
  confirmMessage?: string;
  successMessage?: string;
  errorMessage?: string;
  payload?: Record<string, unknown>;
  refreshData?: () => Promise<void> | void;
  icon?: ReactNode;
  style?: CSSProperties;
  onClearSelection?: () => void;
}

const BulkActionButton = <TResponse = unknown,>({
  selectedIds = [],
  apiEndpoint,
  apiFunction,
  method = "POST",
  buttonText,
  buttonProps = {},
  onSuccess,
  onError,
  disabled = false,
  confirmMessage,
  successMessage,
  errorMessage,
  payload = {},
  refreshData,
  icon,
  style = {},
  onClearSelection,
}: BulkActionButtonProps<TResponse>) => {
  const [loading, setLoading] = useState(false);

  const handleClick = async () => {
    if (selectedIds.length === 0) {
      notify.warning("Please select at least one item");
      return;
    }

    if (confirmMessage) {
      const confirmed = window.confirm(confirmMessage);
      if (!confirmed) return;
    }

    setLoading(true);

    try {
      const requestPayload = {
        ids: selectedIds,
        ...payload,
      };

      let responseData: TResponse;

      if (apiFunction) {
        responseData = await apiFunction(requestPayload);
      } else if (apiEndpoint) {
        let response;
        switch (method.toUpperCase()) {
          case "POST":
            response = await axiosService.post(apiEndpoint, requestPayload);
            break;
          case "PUT":
            response = await axiosService.put(apiEndpoint, requestPayload);
            break;
          case "PATCH":
            response = await axiosService.patch(apiEndpoint, requestPayload);
            break;
          case "DELETE":
            response = await axiosService.delete(apiEndpoint, {
              data: requestPayload,
            });
            break;
          default:
            throw new Error(`Unsupported method: ${method}`);
        }
        responseData = response.data;

        if (response.status >= 200 && response.status < 300) {
          if (onClearSelection) {
            onClearSelection();
          }
        }
      } else {
        throw new Error("Either apiEndpoint or apiFunction must be provided");
      }

      if (apiFunction && onClearSelection) {
        onClearSelection();
      }

      if (successMessage) {
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
