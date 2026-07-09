import { Form } from "antd";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { commissioningShareArticlesCreate } from "@shared/api/generated/commissioning/commissioning";
import type { ShareArticle } from "@shared/api/generated/models";
import { useModalMutation } from "@shared/modals/shared";
import { syncPurchasedName } from "@shared/utils";
import { useActiveShareOptions } from "@hooks/useActiveShareOptions";
import { useUnitOptions } from "@hooks/useUnitOptions";

export const useShareArticleModal = () => {
  const [isVisible, setIsVisible] = useState(false);
  const [form] = Form.useForm();
  const { t } = useTranslation();
  const { activeShareOptions } = useActiveShareOptions();
  const { unitOptions } = useUnitOptions();
  const { saving: loading, run } = useModalMutation();

  const fruit_and_veg_shares_are_separate =
    activeShareOptions.fruit_and_veg_shares_are_separate ?? false;

  const openModal = useCallback((customDefaults: Record<string, unknown> = {}) => {
    form.resetFields();

    const baseDefaults = {
      harvest_share: !fruit_and_veg_shares_are_separate,
      harvest_share_fruit: fruit_and_veg_shares_are_separate,
      is_active: true,
    };
    const finalDefaults = {
      ...baseDefaults,
      ...customDefaults
    };

    form.setFieldsValue(finalDefaults);
    setIsVisible(true);
  }, [form, fruit_and_veg_shares_are_separate]);

  const closeModal = useCallback(() => {
    setIsVisible(false);
    form.resetFields();
  }, [form]);

  const saveShareArticle = useCallback(
    async (onSuccess?: (data: unknown) => void) => {
      let values: Record<string, unknown>;
      try {
        values = await form.validateFields();
      } catch {
        // validation errors are shown inline by antd — no toast.
        return;
      }
      await run(
        async () => {
          // Apply the same customSave logic as in ListHarvestShareArticles
          const shareTypeFlags = ["harvest_share", "harvest_share_fruit"];

          const share_option_list = shareTypeFlags
            .filter((flag) => values[flag])
            .map((flag) => flag.toUpperCase());

          const { name: syncedName, is_purchased: syncedPurchased } =
            syncPurchasedName(
              (values.name as string) || "",
              !!values.is_purchased,
              t,
            );

          const transformedData = {
            ...values,
            name: syncedName,
            is_purchased: syncedPurchased,
            share_option_list,
          };

          return commissioningShareArticlesCreate(
            transformedData as unknown as ShareArticle,
          );
        },
        {
          errorMessage: t("commissioning.share_article_save_error"),
          onSuccess: (response) => {
            closeModal();
            onSuccess?.(response);
          },
        },
      );
    },
    [form, t, run, closeModal],
  );

  return {
    isVisible,
    loading,
    form,
    unitOptions,
    fruit_and_veg_shares_are_separate,
    openModal,
    closeModal,
    saveShareArticle,
    t,
  };
};
