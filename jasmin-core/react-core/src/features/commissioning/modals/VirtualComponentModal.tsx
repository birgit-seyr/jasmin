import { useQueryClient } from "@tanstack/react-query";
import {
  Checkbox,
  InputNumber,
  Modal,
  Space,
  Spin,
  Typography,
} from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ModalCancelSaveFooter } from "@shared/modals/shared";
import {
  commissioningVirtualVariationComponentsCreate,
  getCommissioningVirtualVariationComponentsListQueryKey,
  useCommissioningShareTypeVariationsList,
  useCommissioningVirtualVariationComponentsList,
} from "@shared/api/generated/commissioning/commissioning";
import type { VirtualVariationComponentsRequest } from "@shared/api/generated/models";
import { notify } from '@shared/utils';
import { getErrorMessage } from "@shared/utils/apiError";
import { getShareTypeVariationSizeLabelPure } from "@hooks/index";

const { Text } = Typography;

interface VirtualComponentModalProps {
  visible: boolean;
  onClose: () => void;
  share_type: string | number | null;
  share_type_variation: string | number | null;
  share_type_variation_name?: string;
  onSave?: (data: {
    share_type_variation: string | number | null;
    components: { physical_variation: string; quantity: number }[];
  }) => void;
  /** Always opened from inside ShareTypeVariationModal (a sibling modal with
   *  no AntD nesting auto-lift), so default above the parent's 1000. */
  zIndex?: number;
}

export default function VirtualComponentModal({
  visible,
  onClose,
  share_type,
  share_type_variation,
  share_type_variation_name,
  onSave,
  zIndex = 1100,
}: VirtualComponentModalProps) {
  const [saving, setSaving] = useState(false);
  const [selectedVariations, setSelectedVariations] = useState<Record<string, number>>({});

  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const queryEnabled = visible && !!share_type && !!share_type_variation;

  const { data: variationsData, isLoading: variationsLoading } =
    useCommissioningShareTypeVariationsList(
      queryEnabled
        ? { share_type: String(share_type), physical: true }
        : undefined,
      { query: { enabled: queryEnabled } },
    );

  const { data: rawComponentsData, isLoading: componentsLoading } =
    useCommissioningVirtualVariationComponentsList(
      queryEnabled
        ? { virtual_variation: String(share_type_variation) }
        : undefined,
      { query: { enabled: queryEnabled } },
    );

  const componentsData = rawComponentsData;

  const loading = variationsLoading || componentsLoading;

  const availableVariations = useMemo(
    () =>
      (variationsData || []).filter(
        (v) => String(v.id) !== String(share_type_variation),
      ),
    [variationsData, share_type_variation],
  );

  // Seed selectedVariations ONCE per open, when the components data first
  // arrives. The ref guard stops a background refetch (componentsData getting
  // a new reference) from re-seeding and clobbering the user's in-progress
  // checkbox / quantity edits. Reset on close so the next open re-seeds.
  const seededRef = useRef(false);
  useEffect(() => {
    if (!visible || seededRef.current || !componentsData) return;
    const selections: Record<string, number> = {};
    componentsData.forEach((component) => {
      selections[component.physical_variation] = component.quantity || 1;
    });
    setSelectedVariations(selections);
    seededRef.current = true;
  }, [visible, componentsData]);

  // Reset state when modal closes
  useEffect(() => {
    if (!visible) {
      setSelectedVariations({});
      seededRef.current = false;
    }
  }, [visible]);

  const handleCheckboxChange = useCallback(
    (variationId: string | number, checked: boolean) => {
      setSelectedVariations((prev) => {
        if (checked) {
          return { ...prev, [variationId]: 1 };
        } else {
          const newState = { ...prev };
          delete newState[variationId];
          return newState;
        }
      });
    },
    [],
  );

  const handleQuantityChange = useCallback(
    (variationId: string | number, quantity: number | null) => {
      setSelectedVariations((prev) => ({
        ...prev,
        [variationId]: quantity || 1,
      }));
    },
    [],
  );

  const handleSave = async () => {
    setSaving(true);
    try {
      const components = Object.entries(selectedVariations).map(
        ([physical_variation, quantity]) => ({
          physical_variation,
          quantity,
        }),
      );

      await commissioningVirtualVariationComponentsCreate({
        virtual_variation: String(share_type_variation),
        components,
      } as VirtualVariationComponentsRequest);

      queryClient.invalidateQueries({
        queryKey: getCommissioningVirtualVariationComponentsListQueryKey({
          virtual_variation: String(share_type_variation),
        }),
      });

      notify.success(t("common.saved_successfully"));
      onSave?.({
        share_type_variation,
        components,
      });
      onClose();
    } catch (error) {
      notify.error(getErrorMessage(error, t("common.error_saving")));
    } finally {
      setSaving(false);
    }
  };

  const isSelected = (variationId: string | number) =>
    variationId in selectedVariations;

  return (
    <Modal
      title={
        <div>
          {t("commissioning.virtual_components_for")}{" "}
          {share_type_variation_name}
        </div>
      }
      open={visible}
      onCancel={onClose}
      width={400}
      zIndex={zIndex}
      footer={
        <ModalCancelSaveFooter
          onCancel={onClose}
          onPrimary={handleSave}
          loading={saving}
          primaryDisabled={loading}
        />
      }
    >
      {loading ? (
        <div style={{ textAlign: "center", padding: "40px" }}>
          <Spin size="large" />
        </div>
      ) : (
        <div>
          {availableVariations.length === 0 ? (
            <Text type="warning">
              {t("commissioning.no_other_variations")}
            </Text>
          ) : (
            <>
              <div
                style={{
                  maxHeight: "300px",
                  overflowY: "auto",
                  border: "1px solid var(--color-border)",
                  borderRadius: "6px",
                  padding: "12px",
                }}
              >
                {availableVariations.map((variation) => (
                  <div
                    key={String(variation.id)}
                    className="flex-between"
                    style={{
                      padding: "8px 0",
                      borderBottom: "1px solid var(--color-bg-hover)",
                    }}
                  >
                    <Checkbox
                      checked={isSelected(variation.id!)}
                      onChange={(e) =>
                        handleCheckboxChange(variation.id!, e.target.checked)
                      }
                    >
                      <Text strong>
                        {(variation as unknown as { name?: string }).name ||
                          getShareTypeVariationSizeLabelPure(variation.size, t)}
                      </Text>
                    </Checkbox>

                    {isSelected(variation.id!) ? (
                      <Space size="small">
                        <Text type="secondary" style={{ fontSize: "0.85em" }}>
                          {t("commissioning.quantity")}:
                        </Text>
                        <InputNumber
                          min={1}
                          max={5}
                          step={1}
                          precision={0}
                          value={selectedVariations[variation.id!]}
                          onChange={(value) =>
                            handleQuantityChange(variation.id!, value)
                          }
                          style={{ width: "70px" }}
                          size="small"
                        />
                      </Space>
                    ) : null}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </Modal>
  );
}
