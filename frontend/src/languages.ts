const NAMES = new Intl.DisplayNames(["en"], { type: "language" });

function label(code: string): string {
  if (code === "na") return "Work it out for me";
  try {
    return NAMES.of(code) ?? code;
  } catch {
    return code;
  }
}

/** The model's languages, named and sorted, with "work it out" kept first. */
export function languageOptions(codes: string[]): { code: string; label: string }[] {
  const rest = codes
    .filter((code) => code !== "na")
    .map((code) => ({ code, label: label(code) }))
    .sort((a, b) => a.label.localeCompare(b.label));
  return [{ code: "na", label: label("na") }, ...rest];
}
