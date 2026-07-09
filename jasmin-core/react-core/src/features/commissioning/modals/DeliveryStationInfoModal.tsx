import { useQueryClient } from "@tanstack/react-query";
import { Col, Form, Input, Row, Switch, Typography } from "antd";
import type { FC } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  commissioningDeliveryStationsPartialUpdate,
  getCommissioningDeliveryStationsListQueryKey,
} from "@shared/api/generated/commissioning/commissioning";
import type { DeliveryStation } from "@shared/api/generated/models";
import { EditFormModal, useModalMutation } from "@shared/modals/shared";
import { PictureUploadField, usePictureUpload } from "@shared/ui";
import { notify } from "@shared/utils";

const { Paragraph } = Typography;

// Backend coords are DecimalField(max_digits=12, decimal_places=10) → at most 2
// integer digits (|value| < 100). Fine for lat (±90) and DE/EU longitudes; a
// longitude ≥ 100 would be rejected server-side, so validate up front.
const COORD_PATTERN = /^-?\d{1,2}(\.\d{1,10})?$/;

/**
 * Parse coordinates from a Google-Maps URL or a plain "lat,lng" string.
 * Google Maps carries the place pin as ``!3d<lat>!4d<lng>`` (most precise) and
 * the map centre as ``@<lat>,<lng>,<zoom>z``.
 */
function parseCoords(text: string): { lat: string; lon: string } | null {
  const patterns: RegExp[] = [
    /!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)/,
    /@(-?\d+\.\d+),(-?\d+\.\d+)/,
    /^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/,
  ];
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match) return { lat: match[1], lon: match[2] };
  }
  return null;
}

interface DeliveryStationInfoModalProps {
  open: boolean;
  deliveryStation: DeliveryStation | null;
  onClose: () => void;
  onSaved: () => void;
}

/**
 * Per-row modal for the member-facing station info (pickup instructions, access
 * code, messenger link, contact, photo, self-service) plus coordinates. Coords
 * persist to the linked ContactEntity via the normal station partial update.
 * Mirrors ResellerInvoiceSettingsModal.
 */
export const DeliveryStationInfoModal: FC<DeliveryStationInfoModalProps> = ({
  open,
  deliveryStation,
  onClose,
  onSaved,
}) => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [form] = Form.useForm();
  const { saving, run } = useModalMutation();
  // The uploaded picture is handled outside the form (multipart), so track its
  // current URL locally so the preview updates immediately after upload/delete.
  const [pictureUrl, setPictureUrl] = useState<string | null>(null);

  const invalidateStations = useCallback(
    () =>
      queryClient.invalidateQueries({
        queryKey: getCommissioningDeliveryStationsListQueryKey(),
      }),
    [queryClient],
  );

  const { uploading, uploadPicture, deletePicture } = usePictureUpload({
    endpoint: `/api/commissioning/delivery_stations/${deliveryStation?.id ?? ""}/`,
    invalidate: invalidateStations,
    successMessage: t("delivery_stations.picture_saved"),
    errorMessage: t("delivery_stations.picture_save_error"),
    onUploaded: (data) =>
      setPictureUrl((data as DeliveryStation)?.picture ?? null),
    onDeleted: () => setPictureUrl(null),
  });

  useEffect(() => {
    if (open && deliveryStation) {
      setPictureUrl(deliveryStation.picture ?? null);
    }
  }, [open, deliveryStation]);

  const initialValues = useMemo<Record<string, unknown> | null>(
    () =>
      deliveryStation
        ? {
            info: deliveryStation.info ?? "",
            access_code: deliveryStation.access_code ?? "",
            messenger_group_link: deliveryStation.messenger_group_link ?? "",
            contact_name: deliveryStation.contact_name ?? "",
            contact_phone: deliveryStation.contact_phone ?? "",
            photo_link: deliveryStation.photo_link ?? "",
            self_service: !!deliveryStation.self_service,
            coords_lat: deliveryStation.coords_lat ?? "",
            coords_lon: deliveryStation.coords_lon ?? "",
          }
        : null,
    [deliveryStation],
  );

  if (!deliveryStation) return null;

  const handlePaste = (value: string) => {
    const parsed = parseCoords(value);
    if (parsed) {
      form.setFieldsValue({ coords_lat: parsed.lat, coords_lon: parsed.lon });
      notify.success(t("delivery_stations.coordinates_parsed"));
    }
  };

  const handleSubmit = (values: Record<string, unknown>) =>
    run(
      async () => {
        const payload: Record<string, unknown> = { ...values };
        // Empty coord strings aren't valid decimals — send null to clear.
        for (const key of ["coords_lat", "coords_lon"]) {
          if (payload[key] === "" || payload[key] === undefined)
            payload[key] = null;
        }
        await commissioningDeliveryStationsPartialUpdate(
          String(deliveryStation.id ?? ""),
          payload as unknown as DeliveryStation,
        );
        await invalidateStations();
      },
      {
        successMessage: t("delivery_stations.info_saved"),
        errorMessage: t("delivery_stations.info_save_error"),
        onSuccess: () => {
          onSaved();
          onClose();
        },
      },
    );

  return (
    <EditFormModal
      open={open}
      form={form}
      width={640}
      title={`${t("delivery_stations.member_info_title")} — ${deliveryStation.short_name ?? ""}`}
      description={
        <Paragraph type="secondary">
          {t("delivery_stations.member_info_intro")}
        </Paragraph>
      }
      initialValues={initialValues}
      onSubmit={handleSubmit}
      onCancel={onClose}
      loading={saving}
      requiredMark={false}
    >
      <Form.Item name="info" label={t("delivery_stations.info")}>
        <Input.TextArea rows={3} maxLength={1024} showCount />
      </Form.Item>
      <Row gutter={12}>
        <Col span={12}>
          <Form.Item
            name="access_code"
            label={t("delivery_stations.access_code")}
          >
            <Input maxLength={100} />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item
            name="messenger_group_link"
            label={t("delivery_stations.messenger_group_link")}
          >
            <Input maxLength={150} />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={12}>
        <Col span={12}>
          <Form.Item
            name="contact_name"
            label={t("delivery_stations.contact_name")}
          >
            <Input maxLength={150} />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item
            name="contact_phone"
            label={t("delivery_stations.contact_phone")}
          >
            <Input maxLength={50} />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item label={t("delivery_stations.picture")}>
        <PictureUploadField
          pictureUrl={pictureUrl}
          uploading={uploading}
          onUpload={uploadPicture}
          onDelete={deletePicture}
          previewVariant="inline"
        />
      </Form.Item>

      <Form.Item
        name="self_service"
        label={t("delivery_stations.self_service")}
        valuePropName="checked"
      >
        <Switch />
      </Form.Item>

      <Form.Item label={t("delivery_stations.paste_maps_link")}>
        <Input
          allowClear
          aria-label={t("delivery_stations.paste_maps_link")}
          placeholder={t("delivery_stations.paste_maps_link_placeholder")}
          onChange={(event) => handlePaste(event.target.value)}
        />
      </Form.Item>
      <Row gutter={12}>
        <Col span={12}>
          <Form.Item
            name="coords_lat"
            label={t("delivery_stations.coords_lat")}
            rules={[
              {
                pattern: COORD_PATTERN,
                message: t("delivery_stations.invalid_coordinate"),
              },
            ]}
          >
            <Input />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item
            name="coords_lon"
            label={t("delivery_stations.coords_lon")}
            rules={[
              {
                pattern: COORD_PATTERN,
                message: t("delivery_stations.invalid_coordinate"),
              },
            ]}
          >
            <Input />
          </Form.Item>
        </Col>
      </Row>
    </EditFormModal>
  );
};

export default DeliveryStationInfoModal;
