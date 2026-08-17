/** Shared number-to-words helpers. Durations show up in four places. */

export function clock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) seconds = 0;
  const whole = Math.floor(seconds);
  const h = Math.floor(whole / 3600);
  const m = Math.floor(whole / 60) % 60;
  const s = whole % 60;
  const tail = `${m.toString().padStart(h ? 2 : 1, "0")}:${s.toString().padStart(2, "0")}`;
  return h ? `${h}:${tail}` : tail;
}

/** "about 40 seconds", "12 minutes", "1 hr 20 min" — for prose, not for a clock. */
export function spell(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "no time at all";
  if (seconds < 90) return `${Math.round(seconds)} seconds`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} minutes`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} hr ${rest} min` : `${hours} hr`;
}

export function characters(count: number): string {
  if (count < 1000) return `${count} characters`;
  return `${Math.round(count / 100) / 10}k characters`;
}

/** Rough wav size from duration: 44.1 kHz, 16-bit, mono. */
export function fileSize(seconds: number | null): string {
  if (!seconds) return "";
  const bytes = seconds * 44100 * 2;
  if (bytes < 1e6) return `${Math.round(bytes / 1e3)} KB`;
  if (bytes < 1e9) return `${Math.round(bytes / 1e5) / 10} MB`;
  return `${Math.round(bytes / 1e8) / 10} GB`;
}

/** A byte count in the units a file manager would use. */
export function sizeOf(bytes: number): string {
  if (!bytes) return "";
  if (bytes < 1e3) return `${bytes} bytes`;
  if (bytes < 1e6) return `${Math.round(bytes / 1e3)} KB`;
  if (bytes < 1e9) return `${Math.round(bytes / 1e5) / 10} MB`;
  return `${Math.round(bytes / 1e8) / 10} GB`;
}

const RELATIVE = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

const HAS_OFFSET = /(?:Z|[+-]\d{2}:?\d{2})$/;

/**
 * Parse a server timestamp. Everything the API sends is UTC and carries an
 * offset; anything that somehow doesn't is still UTC, and must not be read as
 * local time or the whole clock shifts.
 */
function parseUtc(iso: string): number {
  return Date.parse(HAS_OFFSET.test(iso) ? iso : `${iso}Z`);
}

/** The moment, in whatever timezone the reader is sitting in. */
export function localTime(iso: string): string {
  const stamp = parseUtc(iso);
  if (!Number.isFinite(stamp)) return "";
  return new Date(stamp).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/** "just now", "4 minutes ago", "yesterday". */
export function ago(iso: string): string {
  const seconds = (parseUtc(iso) - Date.now()) / 1000;
  if (!Number.isFinite(seconds)) return "";
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [
    ["second", 60],
    ["minute", 60],
    ["hour", 24],
    ["day", 7],
    ["week", 4.35],
    ["month", 12],
  ];
  let value = seconds;
  for (const [unit, size] of steps) {
    if (Math.abs(value) < size) {
      return Math.abs(value) < 45 && unit === "second"
        ? "just now"
        : RELATIVE.format(Math.round(value), unit);
    }
    value /= size;
  }
  return RELATIVE.format(Math.round(value), "year");
}
