/**
 * Get CSS custom property value from :root.
 * @param variableName - CSS variable name (with or without --)
 * @returns The CSS variable value
 */
export const getCSSVariable = (variableName: string): string => {
  // Add -- prefix if not provided
  const varName = variableName.startsWith("--")
    ? variableName
    : `--${variableName}`;

  return getComputedStyle(document.documentElement)
    .getPropertyValue(varName)
    .trim();
};

/**
 * Get CSS variable as a number (useful for px, rem, etc.).
 * @param variableName - CSS variable name
 * @returns Parsed number value
 */
export const getCSSVariableAsNumber = (variableName: string): number => {
  const value = getCSSVariable(variableName);
  return parseFloat(value) || 0;
};
