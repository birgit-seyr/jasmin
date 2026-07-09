import { useCallback, useState } from "react";
import axiosInstance from "@shared/services/api";
import { notify } from "@shared/utils";
import { getErrorMessage } from "@shared/utils/apiError";

export interface UsePictureUploadOptions {
  /**
   * Detail endpoint carrying the picture ``FileField``. The upload posts
   * multipart ``FormData`` here (the generated JSON client can't send a file —
   * this is the documented raw-axios escape hatch); clearing sends a null JSON
   * PATCH to the same endpoint.
   */
  endpoint: string;
  /** Multipart field name (default ``picture``). */
  fieldName?: string;
  /** Refetch the owning list / detail after a successful change. */
  invalidate: () => void | Promise<void>;
  /** Success toast for both upload and delete. */
  successMessage: string;
  /** Fallback error toast (the server message wins when present). */
  errorMessage: string;
  /** Fired with the server response body after a successful upload. */
  onUploaded?: (data: unknown) => void;
  /** Fired after a successful delete. */
  onDeleted?: () => void;
}

/**
 * Shared picture-field lifecycle for detail endpoints that carry a FileField.
 * Owns the in-flight ``uploading`` flag, the toast, and the refetch. Callers
 * wire the preview + buttons via ``<PictureUploadField>`` (or their own UI).
 */
export function usePictureUpload({
  endpoint,
  fieldName = "picture",
  invalidate,
  successMessage,
  errorMessage,
  onUploaded,
  onDeleted,
}: UsePictureUploadOptions) {
  const [uploading, setUploading] = useState(false);

  const uploadPicture = useCallback(
    async (file: File) => {
      setUploading(true);
      try {
        const formData = new FormData();
        formData.append(fieldName, file);
        const response = await axiosInstance.patch(endpoint, formData, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        notify.success(successMessage);
        await invalidate();
        onUploaded?.(response.data);
      } catch (error) {
        notify.error(getErrorMessage(error, errorMessage));
      } finally {
        setUploading(false);
      }
    },
    [endpoint, fieldName, invalidate, successMessage, errorMessage, onUploaded],
  );

  const deletePicture = useCallback(async () => {
    setUploading(true);
    try {
      await axiosInstance.patch(endpoint, { [fieldName]: null });
      notify.success(successMessage);
      await invalidate();
      onDeleted?.();
    } catch (error) {
      notify.error(getErrorMessage(error, errorMessage));
    } finally {
      setUploading(false);
    }
  }, [endpoint, fieldName, invalidate, successMessage, errorMessage, onDeleted]);

  return { uploading, uploadPicture, deletePicture };
}

export default usePictureUpload;
