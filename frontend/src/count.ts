const plurals = new Intl.PluralRules("en");
export function countLabel(
  value: number,
  singular: string,
  plural = `${singular}s`,
): string {
  return `${value.toLocaleString()} ${plurals.select(value) === "one" ? singular : plural}`;
}
