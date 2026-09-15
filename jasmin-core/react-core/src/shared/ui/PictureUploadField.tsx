import { DeleteOutlined, UploadOutlined } from "@ant-design/icons";
import { Button, Image, Space, Upload } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { notify } from "@shared/utils";
import "./PictureUploadField.css";

/**
 * The raster types the share-type-variation and delivery-station picture
 * endpoints accept (the backend re-encodes them and refuses anything else).
 * Never SVG — it is active content.
 */
export const RASTER_PICTURE_ACCEPT = "image/png,image/jpeg,image/webp,image/gif";

export interface PictureUploadFieldProps {
  /** Current picture URL to preview (falsy → no preview, "Upload" label). */
  pictureUrl?: string | null;
  /** In-flight flag from ``usePictureUpload`` — spins both buttons. */
  uploading: boolean;
  onUpload: (file: File) => void;
  /** When provided (and ``showDelete``), renders a delete button. */
  onDelete?: () => void;
  /**
   * Preview placement: ``inline`` (small square beside the buttons),
   * ``block`` (centered above), or ``none``. Default ``inline``.
   */
  previewVariant?: "inline" | "block" | "none";
  /** Render the delete button in this field (default true). */
  showDelete?: boolean;
  /**
   * Opt-in client-side shape check, for fields whose backend validator refuses
   * non-square or undersized images (the tenant app icon). Rejecting here is a
   * UX shortcut only — the serializer is the real gate — so a browser that
   * can't decode the file simply falls through to the upload and the server
   * answers. Off by default: the other consumers of this widget accept any
   * shape.
   */
  requireSquare?: boolean;
  /** Minimum width/height in pixels, enforced only when ``requireSquare``. */
  minSizePx?: number;
  /**
   * File-picker filter (the input's ``accept``). Default ``image/*``. Narrow it
   * to what the endpoint accepts (e.g. ``RASTER_PICTURE_ACCEPT``) so unsupported
   * types are not offered; the serializer remains the real gate.
   */
  accept?: string;
}

/**
 * The picture preview + upload/replace (+ optional delete) widget shared by the
 * delivery-station info modal and the share-type-variation picture modal. Pair
 * with ``usePictureUpload`` for the network side.
 */
export default function PictureUploadField({
  pictureUrl,
  uploading,
  onUpload,
  onDelete,
  previewVariant = "inline",
  showDelete = true,
  requireSquare = false,
  minSizePx,
  accept = "image/*",
}: PictureUploadFieldProps) {
  const { t } = useTranslation();

  const checkShapeThenUpload = (file: File) => {
    if (!requireSquare) {
      onUpload(file);
      return;
    }
    const objectUrl = URL.createObjectURL(file);
    const probe = new window.Image();
    probe.onload = () => {
      URL.revokeObjectURL(objectUrl);
      const { naturalWidth: width, naturalHeight: height } = probe;
      if (width !== height) {
        notify.error(t("common.picture_must_be_square", { width, height }));
        return;
      }
      if (minSizePx && width < minSizePx) {
        notify.error(t("common.picture_too_small", { min: minSizePx, width }));
        return;
      }
      onUpload(file);
    };
    // Undecodable here (exotic format, blocked object URL) → let the upload
    // through and let the serializer produce the authoritative error.
    probe.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      onUpload(file);
    };
    probe.src = objectUrl;
  };

  const uploadButton = (
    <Upload
      accept={accept}
      maxCount={1}
      showUploadList={false}
      beforeUpload={(file) => {
        checkShapeThenUpload(file);
        return false;
      }}
    >
      <Button icon={<UploadOutlined />} loading={uploading}>
        {pictureUrl ? t("common.replace") : t("common.upload")}
      </Button>
    </Upload>
  );

  const deleteButton: ReactNode =
    pictureUrl && showDelete && onDelete ? (
      <Button
        danger
        icon={<DeleteOutlined />}
        loading={uploading}
        onClick={onDelete}
      >
        {t("common.delete")}
      </Button>
    ) : null;

  if (previewVariant === "block") {
    return (
      <>
        {pictureUrl && (
          <div className="picture-upload-field__block-preview">
            <Image
              src={pictureUrl}
              alt=""
              className="picture-upload-field__block-image"
            />
          </div>
        )}
        {uploadButton}
      </>
    );
  }

  return (
    <Space align="start" wrap>
      {previewVariant === "inline" && pictureUrl && (
        <Image
          src={pictureUrl}
          alt=""
          className="picture-upload-field__inline-image"
        />
      )}
      <Space direction="vertical">
        {uploadButton}
        {deleteButton}
      </Space>
    </Space>
  );
}
