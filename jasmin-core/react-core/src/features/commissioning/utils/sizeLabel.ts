/** The size label to append to an article's name, or "" for the default size M. */
export function getSizeLabelOrEmpty(
  size: string | null | undefined,
  getVegetableSizeLabel: (size: string) => string,
): string {
  return size && size !== "M" ? getVegetableSizeLabel(size) : "";
}
