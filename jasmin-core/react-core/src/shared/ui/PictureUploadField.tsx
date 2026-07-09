import { DeleteOutlined, UploadOutlined } from "@ant-design/icons";
import { Button, Image, Space, Upload } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import "./PictureUploadField.css";

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
}: PictureUploadFieldProps) {
  const { t } = useTranslation();

  const uploadButton = (
    <Upload
      accept="image/*"
      maxCount={1}
      showUploadList={false}
      beforeUpload={(file) => {
        onUpload(file);
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
