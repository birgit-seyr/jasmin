import { useMemo } from "react";
import { useCommissioningPlotsList } from "@shared/api/generated/commissioning/commissioning";
import type { Plot } from "@shared/api/generated/models";
import { toOptionsWithNull, type NullableOption } from "@hooks/internal/toOptions";

export type PlotOption = NullableOption<Plot>;

export const usePlots = () => {
  const { data, isLoading, error, refetch } = useCommissioningPlotsList({
    is_active: true,
  });

  const plots: PlotOption[] = useMemo(() => toOptionsWithNull(data, (p) => p.name), [data]);

  return {
    plots,
    // Every plot but the leading "no plot" entry.
    countPlots: plots.length - 1,
    loading: isLoading,
    error,
    refetch,
  };
};
