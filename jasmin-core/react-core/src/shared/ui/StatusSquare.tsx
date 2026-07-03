import "./StatusSquare.css";

export type StatusSquareVariant = "active" | "upcoming" | "pending";

interface StatusSquareProps {
  variant: StatusSquareVariant;
  /** Accessible label / hover tooltip (e.g. "Active" / "Coming"). */
  title?: string;
}

/**
 * Small coloured square status indicator. ``active`` = green, ``upcoming`` =
 * blue, ``pending`` = gold (not yet confirmed). Used to prefix subscription
 * rows on the member detail page. Decorative — pair with adjacent text for
 * screen readers.
 */
export default function StatusSquare({ variant, title }: StatusSquareProps) {
  return (
    <span
      className={`status-square status-square--${variant}`}
      title={title}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    />
  );
}
