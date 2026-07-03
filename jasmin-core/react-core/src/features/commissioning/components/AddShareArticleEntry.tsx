import { PlusOutlined } from "@ant-design/icons";
import { Button } from "antd";
import { useState } from "react";
import type { FC } from "react";
import { useTranslation } from "react-i18next";
import { ShareArticleModal } from '@features/commissioning/modals';

interface AddShareArticleEntryProps {
  disabled?: boolean;
  defaultValues?: Record<string, unknown>;
  onSuccess?: (savedData: Record<string, unknown>) => void;
}

const AddShareArticleEntry: FC<AddShareArticleEntryProps> = ({
  disabled = false,
  defaultValues,
  onSuccess,
}) => {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      <ShareArticleModal
        isOpen={isOpen}
        onClose={() => setIsOpen(false)}
        onSuccess={(data) => {
          setIsOpen(false);
          onSuccess?.(data);
        }}
        defaultValues={defaultValues}
      />
      <Button
        type="dashed"
        icon={<PlusOutlined />}
        onClick={() => setIsOpen(true)}
        disabled={disabled}
        className="new-share-article-entry-button"
      >
        {t("commissioning.add_share_article") || "Add Share Article"}
      </Button>
    </>
  );
};

export default AddShareArticleEntry;
