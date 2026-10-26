import CultivationBatchList from "../components/CultivationBatchList";

/** Outdoor cultivation batches — the ones the placement solver plans. */
export default function CultivationBatchOutdoors() {
  return (
    <CultivationBatchList
      isGreenhouse={false}
      titleKey="cultivation.batches_outdoors"
      descriptionKey="cultivation.batches_outdoors_description"
      explainerKey="explainers.cultivation_batches_outdoors"
    />
  );
}
