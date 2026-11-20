import { Button } from "antd";
import { useTranslation } from "react-i18next";
import {
  LABEL_FIELDS,
  type LabelField,
} from "@features/commissioning/utils/labelLayout";
import { LABEL_FIELD_DRAG_TYPE } from "./LabelCanvas";

/** The fields a label can show: dragged onto the label, or clicked to place
 *  one at its top left. */
export default function LabelFieldPalette({
  onAdd,
  hiddenFields = [],
  full = false,
}: {
  onAdd: (field: LabelField) => void;
  /** Fields the farm can't print, such as the organic ones without
   *  certification. */
  hiddenFields?: LabelField[];
  /** The label holds as many fields as a template may. */
  full?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="label-palette">
      <p className="label-palette__hint">{t("commissioning.labels.palette_hint")}</p>
      {LABEL_FIELDS.filter((field) => !hiddenFields.includes(field)).map((field) => (
        <Button
          key={field}
          size="small"
          disabled={full}
          draggable={!full}
          onDragStart={(event) =>
            event.dataTransfer.setData(LABEL_FIELD_DRAG_TYPE, field)
          }
          onClick={() => onAdd(field)}
        >
          {t(`commissioning.labels.fields.${field}`)}
        </Button>
      ))}
    </div>
  );
}
