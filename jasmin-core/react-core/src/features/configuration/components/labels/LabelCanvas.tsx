import {
  useEffect,
  useRef,
  useState,
  type DragEvent,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import { useTranslation } from "react-i18next";
// The labels print in Roboto; the canvas shows them in it, so what fits here
// fits on the label.
import "@fontsource/roboto/400.css";
import "@fontsource/roboto/700.css";
import {
  clampMm,
  isImageField,
  isIncomplete,
  isOutside,
  labelElementText,
  type LabelData,
  type LabelFarm,
  type LabelField,
  type LabelLayout,
  type PlacedElement,
} from "@features/commissioning/utils/labelLayout";

/** The data type the palette's fields are dragged with. */
export const LABEL_FIELD_DRAG_TYPE = "application/x-jasmin-label-field";

// The label is drawn at its real size, CSS pixels per millimetre (96 per
// inch), so a field's mm on the screen are its mm on the paper as near as the
// screen's own scaling allows; a label wider than the space is shrunk to fit.
const PX_PER_MM = 96 / 25.4;
const MM_PER_PT = 25.4 / 72;

interface LabelCanvasProps {
  layout: LabelLayout;
  sample: LabelData;
  farm: LabelFarm;
  logoUrl: string | null;
  bioLogoUrl: string | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onChange: (id: string, change: Partial<PlacedElement>) => void;
  onRemove: (id: string) => void;
  onAdd: (field: LabelField, at: { x: number; y: number }) => void;
}

interface Drag {
  mode: "move" | "resize";
  element: PlacedElement;
  startX: number;
  startY: number;
}

// A field is a flex box, which places its text by justify-content: text-align
// only lines up the lines of text that wraps.
const JUSTIFY: Record<string, "flex-start" | "center" | "flex-end"> = {
  left: "flex-start",
  center: "center",
  right: "flex-end",
};

const ARROWS: Record<string, [number, number]> = {
  ArrowLeft: [-1, 0],
  ArrowRight: [1, 0],
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
};

/**
 * The label to scale with its fields on it, filled with sample data. A field
 * moves by dragging it or with the arrow keys (Shift: 5 mm), grows at its
 * corner or with Alt and the arrow keys, and goes with Delete. A field dragged
 * in from the palette lands where it is dropped.
 */
export default function LabelCanvas({
  layout,
  sample,
  farm,
  logoUrl,
  bioLogoUrl,
  selectedId,
  onSelect,
  onChange,
  onRemove,
  onAdd,
}: LabelCanvasProps) {
  const { t } = useTranslation();
  const canvasRef = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);

  // The width there is for the label; unknown (0) where nothing measures it.
  const frameRef = useRef<HTMLDivElement>(null);
  const [frameWidth, setFrameWidth] = useState(0);
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) =>
      setFrameWidth(entry.contentRect.width),
    );
    observer.observe(frame);
    return () => observer.disconnect();
  }, []);
  // A few pixels kept free for the label's border and shadow.
  const scale =
    frameWidth > 0 ? Math.min(PX_PER_MM, (frameWidth - 4) / layout.width) : PX_PER_MM;
  const shownPercent = Math.round((scale / PX_PER_MM) * 100);

  const placed = (element: PlacedElement, dx: number, dy: number, mode: Drag["mode"]) =>
    mode === "move"
      ? {
          x_mm: clampMm(element.x_mm + dx, 0, layout.width - element.width_mm),
          y_mm: clampMm(element.y_mm + dy, 0, layout.height - element.height_mm),
        }
      : {
          width_mm: clampMm(element.width_mm + dx, 1, layout.width - element.x_mm),
          height_mm: clampMm(element.height_mm + dy, 1, layout.height - element.y_mm),
        };

  const startDrag = (
    event: PointerEvent<HTMLElement>,
    element: PlacedElement,
    mode: Drag["mode"],
  ) => {
    // Only the main button drags: a context menu would swallow the release
    // and leave the field following the pointer.
    if (event.button !== 0) return;
    event.stopPropagation();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    drag.current = { mode, element, startX: event.clientX, startY: event.clientY };
    onSelect(element.id);
  };

  const moveDrag = (event: PointerEvent<HTMLDivElement>) => {
    const current = drag.current;
    if (!current) return;
    onChange(
      current.element.id,
      placed(
        current.element,
        (event.clientX - current.startX) / scale,
        (event.clientY - current.startY) / scale,
        current.mode,
      ),
    );
  };

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, element: PlacedElement) => {
    if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      onRemove(element.id);
      return;
    }
    const arrow = ARROWS[event.key];
    if (!arrow) return;
    event.preventDefault();
    const step = event.shiftKey ? 5 : 1;
    onChange(
      element.id,
      placed(element, arrow[0] * step, arrow[1] * step, event.altKey ? "resize" : "move"),
    );
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    const field = event.dataTransfer.getData(LABEL_FIELD_DRAG_TYPE) as LabelField;
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!field || !rect) return;
    event.preventDefault();
    onAdd(field, {
      x: (event.clientX - rect.left) / scale,
      y: (event.clientY - rect.top) / scale,
    });
  };

  const content = (element: PlacedElement) => {
    const name = t(`commissioning.labels.fields.${element.field}`);
    if (element.field === "farm_logo" && logoUrl) return <img src={logoUrl} alt={name} />;
    if (element.field === "organic_logo" && bioLogoUrl) return <img src={bioLogoUrl} alt={name} />;
    if (isImageField(element.field)) return <span className="label-canvas__placeholder">{name}</span>;
    return labelElementText(element, sample, farm) || (
      <span className="label-canvas__placeholder">{name}</span>
    );
  };

  const field = (element: PlacedElement) => {
    const classes = ["label-canvas__element"];
    if (element.id === selectedId) classes.push("label-canvas__element--selected");
    if (isOutside(element, layout) || isIncomplete(element)) {
      classes.push("label-canvas__element--invalid");
    }
    return (
      <button
        key={element.id}
        type="button"
        className={classes.join(" ")}
        aria-pressed={element.id === selectedId}
        aria-label={t("commissioning.labels.element_aria", {
          field: t(`commissioning.labels.fields.${element.field}`),
        })}
        style={{
          left: element.x_mm * scale,
          top: element.y_mm * scale,
          width: element.width_mm * scale,
          height: element.height_mm * scale,
          fontSize: element.font_size_pt * MM_PER_PT * scale,
          fontWeight: element.bold ? 700 : 400,
          textAlign: element.align as "left" | "center" | "right",
          justifyContent: JUSTIFY[element.align] ?? "flex-start",
        }}
        onPointerDown={(event) => startDrag(event, element, "move")}
        onKeyDown={(event) => onKeyDown(event, element)}
        onFocus={() => onSelect(element.id)}
      >
        {content(element)}
        <span
          className="label-canvas__resize"
          aria-hidden="true"
          onPointerDown={(event) => startDrag(event, element, "resize")}
        />
      </button>
    );
  };

  return (
    <div ref={frameRef} className="label-canvas-frame">
      {shownPercent < 100 && (
        <p className="label-canvas-frame__scale">
          {t("commissioning.labels.shown_smaller", { percent: shownPercent })}
        </p>
      )}
      <div
        ref={canvasRef}
        role="group"
        aria-label={t("commissioning.labels.canvas_aria", {
          width: layout.width,
          height: layout.height,
        })}
        className="label-canvas"
        // The label's size and the fields' places are its geometry in mm.
        style={{ width: layout.width * scale, height: layout.height * scale }}
        onPointerMove={moveDrag}
        onPointerUp={() => (drag.current = null)}
        onPointerCancel={() => (drag.current = null)}
        onDragOver={(event) => event.preventDefault()}
        onDrop={onDrop}
      >
        {layout.elements.map(field)}
      </div>
    </div>
  );
}
