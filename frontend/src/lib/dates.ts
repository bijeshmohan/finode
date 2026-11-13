// Days as the server writes them (app/templating.py: friendly_date, short_date, date_chip). Every function takes the
// day and `today` as ISO strings (today from /api/auth/session, in FINODE_TIMEZONE), never the device's clock, and
// works on the numbers so the device's time zone cannot move a day.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"] as const;
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;

interface Day {
  year: number;
  month: number;
  day: number;
}

function parse(iso: string): Day {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) throw new Error(`not a day: ${iso}`);
  return { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]) };
}

function weekday(d: Day): string {
  return WEEKDAYS[new Date(Date.UTC(d.year, d.month - 1, d.day)).getUTCDay()] ?? "";
}

function month(d: Day): string {
  return MONTHS[d.month - 1] ?? "";
}

function dayBefore(iso: string): string {
  const d = parse(iso);
  return new Date(Date.UTC(d.year, d.month - 1, d.day - 1)).toISOString().slice(0, 10);
}

/** Today / Yesterday / Mon, 28 Sep / 28 Sep 2025. */
export function friendlyDate(iso: string, today: string): string {
  if (iso === today) return "Today";
  if (iso === dayBefore(today)) return "Yesterday";
  const d = parse(iso);
  if (d.year === parse(today).year) return `${weekday(d)}, ${String(d.day)} ${month(d)}`;
  return `${String(d.day)} ${month(d)} ${String(d.year)}`;
}

/** 1 Nov / 1 Nov 2027: no weekday, for a line that is already full. */
export function shortDate(iso: string, today: string): string {
  const d = parse(iso);
  const text = `${String(d.day)} ${month(d)}`;
  return d.year === parse(today).year ? text : `${text} ${String(d.year)}`;
}

/** The day on the Add screen's date chip: Today, 24 Oct / Wed, 21 Oct / 21 Oct 2025. */
export function dateChip(iso: string, today: string): string {
  const d = parse(iso);
  if (iso === today) return `Today, ${String(d.day)} ${month(d)}`;
  if (d.year === parse(today).year) return `${weekday(d)}, ${String(d.day)} ${month(d)}`;
  return `${String(d.day)} ${month(d)} ${String(d.year)}`;
}
