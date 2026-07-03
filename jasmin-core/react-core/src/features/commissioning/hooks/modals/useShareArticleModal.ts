import { Form } from "antd";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { commissioningShareArticlesCreate } from "@shared/api/generated/commissioning/commissioning";
import type { ShareArticle } from "@shared/api/generated/models";
import { syncPurchasedName } from "@shared/utils";
import { useActiveShareOptions } from "@hooks/useActiveShareOptions";
import { useUnitOptions } from "@hooks/useUnitOptions";

export const useShareArticleModal = () => {
  const [isVisible, setIsVisible] = useState(false);
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm();
  const { t } = useTranslation();
  const { activeShareOptions } = useActiveShareOptions();
  const { unitOptions } = useUnitOptions();

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

  const saveShareArticle = useCallback(async (onSuccess?: (data: unknown) => void) => {
    try {
      setLoading(true);
      const values = await form.validateFields();

      // Apply the same customSave logic as in ListHarvestShareArticles
      const shareTypeFlags = [
        "harvest_share",
        "harvest_share_fruit",
      ];

      const share_option_list = shareTypeFlags
        .filter((flag) => values[flag])
        .map((flag) => flag.toUpperCase());

      const { name: syncedName, is_purchased: syncedPurchased } =
        syncPurchasedName(values.name || "", !!values.is_purchased, t);

      const transformedData = {
        ...values,
        name: syncedName,
        is_purchased: syncedPurchased,
        share_option_list: share_option_list,
      };

      const response = await commissioningShareArticlesCreate(transformedData as unknown as ShareArticle);
      
      closeModal();
      
      if (onSuccess) {
        onSuccess(response);
      }
    } catch (error) {
      console.error("Failed to save share article:", error);
    } finally {
      setLoading(false);
    }
  }, [form, t, closeModal]);

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
