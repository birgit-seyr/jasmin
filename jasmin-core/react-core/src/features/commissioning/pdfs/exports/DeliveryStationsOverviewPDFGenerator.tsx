import type { TFunction } from "i18next";

import type { DeliveryStationsOverviewPDFProps } from "./DeliveryStationsOverviewPDF";
import ListPDFGenerator from "./ListPDFGenerator";

interface DeliveryStationsOverviewPDFGeneratorProps {
  tours: DeliveryStationsOverviewPDFProps["tours"] | null;
  week: number;
  dayName: string;
  filename: string;
  buttonText: string;
  t: TFunction;
}

export default function DeliveryStationsOverviewPDFGenerator({
  tours,
  week,
  dayName,
  filename,
  buttonText,
  t,
}: DeliveryStationsOverviewPDFGeneratorProps) {
  return (
    <ListPDFGenerator
      data={tours}
      isReady={tours !== null && tours.length > 0}
      filename={filename}
      buttonText={buttonText}
      documentLoader={() => import("./DeliveryStationsOverviewPDF")}
      documentProps={{
        tours: tours ?? [],
        week,
        dayName,
        t,
      }}
    />
  );
}
