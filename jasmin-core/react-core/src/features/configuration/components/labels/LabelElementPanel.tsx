import { Button, Card, Form, Input, Segmented, Switch } from "antd";
import { useTranslation } from "react-i18next";
import NumberInput from "@shared/ui/NumberInput";
import {
  isImageField,
  takesText,
  type LabelAlign,
  type PlacedElement,
} from "@features/commissioning/utils/labelLayout";

const POSITION_KEYS = ["x_mm", "y_mm", "width_mm", "height_mm"] as const;

/** The selected field's place, size and style, typed in exactly. */
export default function LabelElementPanel({
  element,
  onChange,
  onRemove,
}: {
  element: PlacedElement;
  onChange: (change: Partial<PlacedElement>) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const isText = !isImageField(element.field);
  return (
    <Card size="small" title={t(`commissioning.labels.fields.${element.field}`)}>
      <Form layout="vertical" className="label-panel">
        <div className="label-panel__grid">
          {POSITION_KEYS.map((key) => (
            <Form.Item key={key} label={t(`commissioning.labels.${key}`)}>
              <NumberInput
                aria-label={t(`commissioning.labels.${key}`)}
                value={element[key]}
                min={key === "width_mm" || key === "height_mm" ? 1 : 0}
                step={0.5}
                precision={1}
                suffix="mm"
                onChange={(value) => value !== null && onChange({ [key]: value })}
              />
            </Form.Item>
          ))}
        </div>
        {isText && (
          <>
            <Form.Item label={t("commissioning.labels.font_size_pt")}>
              <NumberInput
                aria-label={t("commissioning.labels.font_size_pt")}
                value={element.font_size_pt}
                min={4}
                max={72}
                suffix="pt"
                onChange={(value) => value !== null && onChange({ font_size_pt: value })}
              />
            </Form.Item>
            <Form.Item label={t("commissioning.labels.bold")}>
              <Switch
                aria-label={t("commissioning.labels.bold")}
                checked={element.bold}
                onChange={(checked) => onChange({ bold: checked })}
              />
            </Form.Item>
            <Form.Item label={t("commissioning.labels.align")}>
              <Segmented<LabelAlign>
                value={element.align as LabelAlign}
                options={(["left", "center", "right"] as const).map((align) => ({
                  value: align,
                  label: t(`commissioning.labels.align_${align}`),
                }))}
                onChange={(align) => onChange({ align })}
              />
            </Form.Item>
          </>
        )}
        {takesText(element.field) && (
          <Form.Item label={t(`commissioning.labels.text_${element.field}`)}>
            <Input
              aria-label={t(`commissioning.labels.text_${element.field}`)}
              value={element.text}
              maxLength={500}
              onChange={(event) => onChange({ text: event.target.value })}
            />
          </Form.Item>
        )}
        {element.field === "article" && (
          <Form.Item label={t("commissioning.labels.organic_prefix")}>
            <Switch
              aria-label={t("commissioning.labels.organic_prefix")}
              checked={element.organic_prefix}
              onChange={(checked) => onChange({ organic_prefix: checked })}
            />
          </Form.Item>
        )}
        <Button danger onClick={onRemove}>
          {t("commissioning.labels.remove")}
        </Button>
      </Form>
    </Card>
  );
}
