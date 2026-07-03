import { useMemo } from 'react';
import { useLocale } from '@shared/contexts/LocalContext';
import { getCSSVariable, getCSSVariableAsNumber } from '@shared/utils/helpers';

export const useTheme = () => {
  const { theme } = useLocale();

  // `theme` is intentionally in the dep array even though the body doesn't
  // read it directly: the CSS variables we resolve here change whenever the
  // theme changes, so this memo must rebuild on a theme switch.
  const themeTokens = useMemo(
    () => ({
      colorPrimary: getCSSVariable('--color-primary'),
      colorSuccess: getCSSVariable('--color-success'),
      colorWarning: getCSSVariable('--color-warning'),
      colorError: getCSSVariable('--color-error'),
      colorInfo: getCSSVariable('--color-info'),
      borderRadius: getCSSVariableAsNumber('--border-radius'),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [theme],
  );

  return themeTokens;
};
