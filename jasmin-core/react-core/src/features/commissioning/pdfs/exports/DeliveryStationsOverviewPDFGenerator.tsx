import type { TFunction } from "i18next";
import type { DeliveryStationsOverviewPDFProps } from "./DeliveryStationsOverviewPDF";
import ListPDFGenerator from "./ListPDFGenerator";

interface DeliveryStationsOverviewPDFGeneratorProps {
  tours: DeliveryStationsOverviewPDFProps["tours"] | null;
  week: number;
  dayName: string;
  variations: DeliveryStationsOverviewPDFProps["variations"] | null;
  filename: string;
  buttonText: string;
  t: TFunction;
}

export default function DeliveryStationsOverviewPDFGenerator({
  tours,
  week,
  dayName,
  variations,
  filename,
  buttonText,
  t,
}: DeliveryStationsOverviewPDFGeneratorProps) {
  return (
    <ListPDFGenerator
      data={tours}
      isReady={!!variations && tours !== null && tours.length > 0}
      filename={filename}
      buttonText={buttonText}
      documentLoader={() => import("./DeliveryStationsOverviewPDF")}
      documentProps={{
        tours: tours ?? [],
        week,
        dayName,
        variations: variations ?? [],
        t,
      }}
    />
  );
}
