import type { TFunction } from "i18next";
import type { StationPageData, TenantInfo } from "./DeliveryStationDetailsPDF";
import ListPDFGenerator from "./ListPDFGenerator";

interface DeliveryStationDetailsPDFGeneratorProps {
  pages: StationPageData[] | null;
  week: number;
  dayName: string;
  tenant: TenantInfo;
  filename: string;
  buttonText: string;
  t: TFunction;
}

export default function DeliveryStationDetailsPDFGenerator({
  pages,
  week,
  dayName,
  tenant,
  filename,
  buttonText,
  t,
}: DeliveryStationDetailsPDFGeneratorProps) {
  return (
    <ListPDFGenerator
      data={pages}
      isReady={pages !== null && pages.length > 0}
      filename={filename}
      buttonText={buttonText}
      documentLoader={() => import("./DeliveryStationDetailsPDF")}
      documentProps={{
        pages: pages ?? [],
        week,
        dayName,
        tenant,
        t,
      }}
    />
  );
}
