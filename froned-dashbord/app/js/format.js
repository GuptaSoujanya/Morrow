/** Pure formatting helpers — no DOM, so these are the easiest to unit test. */

export function num(n) {
  return Number(n || 0).toLocaleString("en-IN");
}

export function counted(n, noun, plural = `${noun}s`) {
  return `${n} ${n === 1 ? noun : plural}`;
}

export function share(part, whole) {
  if (!whole) return "–";
  return `${Math.round((part / whole) * 100)}%`;
}

export function sentence(text) {
  const trimmed = String(text || "").trim();
  if (!trimmed) return "Something went wrong.";
  return /[.!?]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}

export function localDay(isoDay) {
  const [y, m, d] = String(isoDay).split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
}

export function shortDate(isoDay) {
  if (!isoDay) return "–";
  return localDay(isoDay).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

export function longDate(isoDay) {
  if (!isoDay) return "–";
  return localDay(isoDay).toLocaleDateString("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

export function duration(seconds) {
  if (seconds === null || seconds === undefined) return "–";
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${r}s`;
  return `${r}s`;
}

/** The headline KPI "change" chip: direction + percent, or null when there is nothing to compare. */
export function changeFrom(current, before, days) {
  if (!days || before === null || before === undefined) return null;
  if (!before && !current) return null;
  if (!before) return { dir: "up", text: "new" };
  const pct = Math.round(((current - before) / before) * 100);
  if (pct === 0) return { dir: "flat", text: "flat" };
  return { dir: pct > 0 ? "up" : "down", text: `${pct > 0 ? "+" : ""}${pct}%` };
}

export function rangeText(overview) {
  if (!overview.days) return overview.first ? `Since ${shortDate(overview.first)}` : "Nothing recorded yet";
  return `${shortDate(overview.start)} – ${shortDate(overview.end)}`;
}
