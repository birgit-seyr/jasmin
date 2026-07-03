import type { ComponentType } from "react";
import type { TFunction } from "i18next";
import ListPDFGenerator from "./ListPDFGenerator";
import type { TenantInfo } from "./ListPDFSharedComponents";
import type {
  PackingListAllStationsPDFProps,
  PackingListPDFProps,
  PackingStationPage,
} from "./PackingListPDF";

interface PackingListPDFGeneratorProps {
  data: PackingListPDFProps["data"] | null;
  year: number;
  week: number | null;
  dayName: string;
  shareType?: string;
  variations: PackingListPDFProps["variations"] | null;
  variationsTotals?: PackingListPDFProps["variationsTotals"];
  packingStation?: string | number | null;
  titleKey?: string;
  /** Optional — when set, the PDF renders a branded strip with the
   *  tenant logo + name above the title. Useful for member-facing
   *  variants (e.g. self-pack lists handed to recipients). */
  tenant?: TenantInfo;
  showSize?: boolean;
  filename: string;
  buttonText: string;
  t: TFunction;
}

export default function PackingListPDFGenerator({
  data,
  year,
  week,
  dayName,
  shareType,
  variations,
  variationsTotals,
  packingStation,
  titleKey,
  tenant,
  showSize,
  filename,
  buttonText,
  t,
}: PackingListPDFGeneratorProps) {
  return (
    <ListPDFGenerator
      data={data}
      isReady={!!variations}
      filename={filename}
      buttonText={buttonText}
      documentLoader={() => import("./PackingListPDF")}
      documentProps={{
        data: data ?? [],
        year,
        week,
        dayName,
        shareType,
        variations: variations ?? [],
        variationsTotals,
        packingStation,
        titleKey,
        tenant,
        showSize,
        t,
      }}
    />
  );
}

interface PackingListAllStationsPDFGeneratorProps {
  pages: PackingStationPage[] | null;
  year: number;
  week: number | null;
  dayName: string;
  shareType?: string;
  variations: PackingListPDFProps["variations"] | null;
  tenant?: TenantInfo;
  showSize?: boolean;
  filename: string;
  buttonText: string;
  t: TFunction;
}

export function PackingListAllStationsPDFGenerator({
  pages,
  year,
  week,
  dayName,
  shareType,
  variations,
  tenant,
  showSize,
  filename,
  buttonText,
  t,
}: PackingListAllStationsPDFGeneratorProps) {
  return (
    // Explicit generic args:
    //   T (the readiness-gate data type) = PackingStationPage[]
    //   DocProps                          = PackingListAllStationsPDFProps
    //
    // Without these, TypeScript can't infer DocProps from the
    // ``.then((m) => ({ default: m.PackingListAllStationsPDF }))``
    // shim — the projection through ``.then`` loses the named-export
    // type and the inferred DocProps degrades to ``never``. Pinning
    // both generics here restores type-checking on documentProps.
    <ListPDFGenerator<PackingStationPage[], PackingListAllStationsPDFProps>
      data={pages}
      isReady={!!variations && !!pages && pages.length > 0}
      filename={filename}
      buttonText={buttonText}
      // ``PackingListAllStationsPDF`` is a NAMED export from
      // PackingListPDF (not the default). Normalize to a
      // ``{ default }`` shape so the loader contract matches. The
      // explicit return-type annotation keeps the dynamic-import
      // type narrow.
      documentLoader={(): Promise<{
        default: ComponentType<PackingListAllStationsPDFProps>;
      }> =>
        import("./PackingListPDF").then((m) => ({
          default: m.PackingListAllStationsPDF,
        }))
      }
      documentProps={{
        pages: pages ?? [],
        year,
        week,
        dayName,
        shareType,
        variations: variations ?? [],
        tenant,
        showSize,
        t,
      }}
    />
  );
}

