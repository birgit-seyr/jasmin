import { useMemo } from "react";
import { useCommissioningScaleTaxCodesList } from "@shared/api/generated/commissioning/commissioning";
import type { ScaleTaxCode } from "@shared/api/generated/models";
import { toOptions, type Option } from "@hooks/internal/toOptions";
import { useNumberFormat } from "@hooks/useNumberFormat";

export type ScaleTaxCodeOption = Option<ScaleTaxCode>;

/** The scale's VAT codes as select options, labelled "7,00 % (1)". */
export const useScaleTaxCodes = () => {
  const { data, isLoading } = useCommissioningScaleTaxCodesList();
  const { format } = useNumberFormat();

  // Memoized so the options keep one reference between renders, for the
  // column memos that list them as a dependency.
  const scaleTaxCodes: ScaleTaxCodeOption[] = useMemo(
    () =>
      toOptions(
        data,
        (taxCode) => `${format(taxCode.tax_rate)} % (${taxCode.code})`,
      ),
    [data, format],
  );

  return { scaleTaxCodes, loading: isLoading };
};
