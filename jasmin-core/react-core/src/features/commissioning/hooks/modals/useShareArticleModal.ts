import { Form } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { commissioningShareArticlesCreate } from "@shared/api/generated/commissioning/commissioning";
import type { ShareArticle } from "@shared/api/generated/models";
import { useModalMutation } from "@shared/modals/shared";
import { syncPurchasedName } from "@shared/utils";
import { useActiveShareOptions } from "@hooks/useActiveShareOptions";
import { useUnitOptions } from "@hooks/useUnitOptions";
import { newShareArticleShareFlag } from "@features/commissioning/utils/newShareArticleShare";

const SHARE_FLAGS = ["harvest_share", "harvest_share_fruit"] as const;

export const useShareArticleModal = () => {
  const [isVisible, setIsVisible] = useState(false);
  const [form] = Form.useForm();
  const { t } = useTranslation();
  const { activeShareOptions } = useActiveShareOptions();
  const { unitOptions } = useUnitOptions();
  const { saving: loading, run } = useModalMutation();

  const fruit_and_veg_shares_are_separate =
    activeShareOptions.fruit_and_veg_shares_are_separate ?? false;

  // The dialog has no list filter, so a new article starts where the article
  // list starts one under "All".
  const farmRunsVegetableShare = activeShareOptions.HARVEST_SHARE === true;
  const shareDefaults = useMemo(() => {
    const ticked = newShareArticleShareFlag(null, farmRunsVegetableShare);
    return Object.fromEntries(SHARE_FLAGS.map((flag) => [flag, flag === ticked]));
  }, [farmRunsVegetableShare]);
  const customDefaultsRef = useRef<Record<string, unknown>>({});

  const openModal = useCallback((customDefaults: Record<string, unknown> = {}) => {
    form.resetFields();
    customDefaultsRef.current = customDefaults;
    form.setFieldsValue({ ...shareDefaults, is_active: true, ...customDefaults });
    setIsVisible(true);
  }, [form, shareDefaults]);

  // The share options may arrive after the dialog opened: seed the shares
  // again then, unless the page set them or the office already changed them.
  useEffect(() => {
    if (!isVisible) return;
    const reseed = SHARE_FLAGS.filter(
      (flag) => !(flag in customDefaultsRef.current) && !form.isFieldTouched(flag),
    );
    if (reseed.length > 0) {
      form.setFieldsValue(Object.fromEntries(reseed.map((flag) => [flag, shareDefaults[flag]])));
    }
  }, [isVisible, shareDefaults, form]);

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
