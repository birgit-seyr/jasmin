import { useShareTypeVariationSizeOptions } from "@hooks/index";
import type { PackingBoxesMatrixAddOn } from "@shared/api/generated/models";

interface BoxCombinationLabelProps {
  /** SizeOptions code of the base box, or null for an orphan add-on box. */
  baseSize: string | null;
  addOns: Pick<PackingBoxesMatrixAddOn, "share_type_short_name" | "size">[];
  /** Shown in place of the base size when there is no base (orphan add-ons). */
  noBaseLabel?: string;
}

/**
 * Renders a box combination as its base size with one superscript badge per
 * add-on (`short_name·size`), e.g. **M** with superscripts `HONIG·M` `BROT·L`.
 * Sizes are labelled via `useShareTypeVariationSizeOptions` (covers every
 * SizeOptions code — S/M/L, HALF/FULL, ONE_SIZE, …).
 *
 * Reused by the packing boxes matrix and (planned) the delivery-station member
 * matrix so both render combinations identically.
 */
export default function BoxCombinationLabel({
  baseSize,
  addOns,
  noBaseLabel,
}: BoxCombinationLabelProps) {
  const { getShareTypeVariationSizeLabel } = useShareTypeVariationSizeOptions();
  const base = baseSize
    ? getShareTypeVariationSizeLabel(baseSize)
    : (noBaseLabel ?? "—");
  return (
    <span className="box-combo">
      <span className="box-combo__base">{base}</span>
      {addOns.map((addOn, index) => (
        <sup
          className="box-combo__addon"
          key={`${addOn.share_type_short_name}-${addOn.size}-${index}`}
        >
          {addOn.share_type_short_name}
          <span className="box-combo__addon-sep">·</span>
          {getShareTypeVariationSizeLabel(addOn.size)}
        </sup>
      ))}
    </span>
  );
}
