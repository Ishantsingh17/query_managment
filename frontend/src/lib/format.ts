const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

function parse(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

const pad = (n: number) => String(n).padStart(2, "0");

/** "14 Jul 2025" */
export function formatDate(value: string | null | undefined): string {
  const date = parse(value);
  if (!date) return "—";
  return `${date.getDate()} ${MONTHS[date.getMonth()]} ${date.getFullYear()}`;
}

/** "09:42" */
export function formatTime(value: string | null | undefined): string {
  const date = parse(value);
  if (!date) return "—";
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** "14 Jul 2025 09:42" */
export function formatDateTime(value: string | null | undefined): string {
  const date = parse(value);
  if (!date) return "—";
  return `${formatDate(value)} ${formatTime(value)}`;
}

/** 0.97 -> "97%" */
export function formatConfidence(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

/** "READY_FOR_REVIEW" -> "Ready For Review" */
export function titleCase(value: string): string {
  return value
    .toLowerCase()
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function pluralise(count: number, singular: string, plural?: string): string {
  return `${count} ${count === 1 ? singular : (plural ?? `${singular}s`)}`;
}
