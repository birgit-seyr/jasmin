import { useCommissioningPlotsList } from "@shared/api/generated/commissioning/commissioning";
import type { Plot } from "@shared/api/generated/models";
import { toOptions, toOptionsWithNull, type NullableOption } from "@hooks/internal/toOptions";

export type PlotOption = NullableOption<Plot>;

export const usePlots = () => {
  const { data, isLoading, error, refetch } = useCommissioningPlotsList({
    is_active: true,
  });

  const options = toOptions(data, (p) => p.name);
  const plots: PlotOption[] = toOptionsWithNull(data, (p) => p.name);

  return {
    plots,
    countPlots: options.length,
    loading: isLoading,
    error,
    refetch,
  };
};
