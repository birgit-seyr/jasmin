import { Button } from "antd";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

export const useShareArticlePriceColumn = (handleOpenModal: (record: Record<string, unknown>) => void) => {
  const { t } = useTranslation();

  const priceModalColumn = useMemo(
    () => ({
      title: "",
      dataIndex: "actions",
      key: "actions",
      fixed: true,
      width: "6em",
      align: "center",
      readOnly: true,
      disabled: true,
      render: (_: unknown, record: Record<string, unknown>) => (
        <Button
          type="primary"
          size="small"
          onClick={() => handleOpenModal(record)}
          disabled={record.key === -1 || !record.id}
          title={t("commissioning.manage_prices")}
        >
          {t("commissioning.prices")}
        </Button>
      ),
    }),
    [handleOpenModal, t],
  );

  return priceModalColumn;
};
