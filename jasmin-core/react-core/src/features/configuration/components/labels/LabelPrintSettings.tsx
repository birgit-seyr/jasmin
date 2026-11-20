import { Form, Segmented, Select } from "antd";
import { useTranslation } from "react-i18next";
import NumberInput from "@shared/ui/NumberInput";
import type { PrintModeEnum } from "@shared/api/generated/models";
import {
  SHEET_PRESETS,
  type LabelLayout,
} from "@features/commissioning/utils/labelLayout";

type Sheet = LabelLayout["sheet"];

const SHEET_FIELDS: { key: keyof Sheet; unit?: "mm"; min: number; max: number }[] = [
  { key: "columns", min: 1, max: 10 },
  { key: "rows", min: 1, max: 30 },
  { key: "marginTop", unit: "mm", min: 0, max: 150 },
  { key: "marginLeft", unit: "mm", min: 0, max: 150 },
  { key: "gapX", unit: "mm", min: 0, max: 100 },
  { key: "gapY", unit: "mm", min: 0, max: 100 },
];

/** The label's size, and whether it prints one label per page on a label
 *  printer or on A4 sheets of labels, laid out here or from a preset. */
export default function LabelPrintSettings({
  layout,
  onChange,
}: {
  layout: LabelLayout;
  onChange: (change: Partial<LabelLayout>) => void;
}) {
  const { t } = useTranslation();
  const setSheet = (change: Partial<Sheet>) =>
    onChange({ sheet: { ...layout.sheet, ...change } });

  return (
    <Form layout="vertical" className="label-print-settings">
      <div className="label-panel__grid">
        <Form.Item label={t("commissioning.labels.label_width")}>
          <NumberInput
            aria-label={t("commissioning.labels.label_width")}
            value={layout.width}
            min={10}
            max={300}
            precision={1}
            suffix="mm"
            onChange={(value) => value !== null && onChange({ width: value })}
          />
        </Form.Item>
        <Form.Item label={t("commissioning.labels.label_height")}>
          <NumberInput
            aria-label={t("commissioning.labels.label_height")}
            value={layout.height}
            min={5}
            max={200}
            precision={1}
            suffix="mm"
            onChange={(value) => value !== null && onChange({ height: value })}
          />
        </Form.Item>
      </div>
      <Form.Item label={t("commissioning.labels.print_mode")}>
        <Segmented<PrintModeEnum>
          value={layout.printMode}
          options={[
            { value: "label_printer", label: t("commissioning.labels.print_mode_label_printer") },
            { value: "sheet", label: t("commissioning.labels.print_mode_sheet") },
          ]}
          onChange={(printMode) => onChange({ printMode })}
        />
      </Form.Item>
      {layout.printMode === "sheet" && (
        <>
          <Form.Item label={t("commissioning.labels.sheet_preset")}>
            <Select
              aria-label={t("commissioning.labels.sheet_preset")}
              placeholder={t("commissioning.labels.sheet_preset_placeholder")}
              value={null}
              options={SHEET_PRESETS.map((preset) => ({
                value: preset.key,
                label: t("commissioning.labels.sheet_preset_option", {
                  width: preset.width,
                  height: preset.height,
                  columns: preset.columns,
                  rows: preset.rows,
                }),
              }))}
              onChange={(key) => {
                const preset = SHEET_PRESETS.find((candidate) => candidate.key === key);
                if (!preset) return;
                const { width, height, columns, rows, marginTop, marginLeft, gapX, gapY } =
                  preset;
                onChange({
                  width,
                  height,
                  sheet: { columns, rows, marginTop, marginLeft, gapX, gapY },
                });
              }}
            />
          </Form.Item>
          <div className="label-panel__grid">
            {SHEET_FIELDS.map(({ key, unit, min, max }) => (
              <Form.Item key={key} label={t(`commissioning.labels.sheet_${key}`)}>
                <NumberInput
                  aria-label={t(`commissioning.labels.sheet_${key}`)}
                  value={layout.sheet[key]}
                  min={min}
                  max={max}
                  precision={unit ? 1 : 0}
                  suffix={unit}
                  onChange={(value) => value !== null && setSheet({ [key]: value })}
                />
              </Form.Item>
            ))}
          </div>
        </>
      )}
    </Form>
  );
}
