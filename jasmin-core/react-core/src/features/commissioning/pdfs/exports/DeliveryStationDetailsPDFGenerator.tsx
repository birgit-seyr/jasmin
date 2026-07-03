import type { TFunction } from "i18next";
import type {
  DeliveryStationDetailsPDFProps,
  StationPageData,
  TenantInfo,
} from "./DeliveryStationDetailsPDF";
import ListPDFGenerator from "./ListPDFGenerator";

interface DeliveryStationDetailsPDFGeneratorProps {
  pages: StationPageData[] | null;
  week: number;
  dayName: string;
  variations: DeliveryStationDetailsPDFProps["variations"] | null;
  tenant: TenantInfo;
  filename: string;
  buttonText: string;
  t: TFunction;
}

export default function DeliveryStationDetailsPDFGenerator({
  pages,
  week,
  dayName,
  variations,
  tenant,
  filename,
  buttonText,
  t,
}: DeliveryStationDetailsPDFGeneratorProps) {
  return (
    <ListPDFGenerator
      data={pages}
      isReady={!!variations && pages !== null && pages.length > 0}
      filename={filename}
      buttonText={buttonText}
      documentLoader={() => import("./DeliveryStationDetailsPDF")}
      documentProps={{
        pages: pages ?? [],
        week,
        dayName,
        variations: variations ?? [],
        tenant,
        t,
      }}
    />
  );
}
