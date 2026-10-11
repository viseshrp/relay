const plurals = new Intl.PluralRules("en");
export function countLabel(
  value: number,
  singular: string,
  plural = `${singular}s`,
): string {
  return `${value.toLocaleString()} ${plurals.select(value) === "one" ? singular : plural}`;
}

export function relativeTime(
  value: string | null | undefined,
  now = Date.now(),
): string {
  if (!value || !Number.isFinite(Date.parse(value))) return "Not started";
  const seconds = (Date.parse(value) - now) / 1000;
  const format = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  for (const [unit, size] of [
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ] as const) {
    if (Math.abs(seconds) >= size)
      return format.format(Math.round(seconds / size), unit);
  }
  return format.format(Math.round(seconds), "second");
}
