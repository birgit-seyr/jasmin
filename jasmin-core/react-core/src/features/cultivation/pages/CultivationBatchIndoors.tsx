import CultivationBatchList from "../components/CultivationBatchList";

/**
 * Greenhouse / tunnel cultivation batches. Planned separately — the outdoor
 * placement solver deliberately skips these (and greenhouse plots), so protected
 * cultivation is never silently placed on outdoor beds.
 */
export default function CultivationBatchIndoors() {
  return (
    <CultivationBatchList
      isGreenhouse
      titleKey="cultivation.batches_indoors"
      descriptionKey="cultivation.batches_indoors_description"
      explainerKey="explainers.cultivation_batches_indoors"
    />
  );
}
