/** Minimal hash router: `#/<section>` or `#/<section>/<arg>`. Pure parsing lives here so it
 * can be unit tested without a DOM/location object. */

export const SECTIONS = [
  ["overview", "Launchpad", "grid"],
  ["bots", "Bot Crew", "bot"],
  ["analytics", "Insights", "chart"],
  ["pipeline", "Flows", "refresh"],
  ["naukri", "Apply on Naukri", "send"],
  ["boards", "Job boards", "globe"],
  ["sites", "Company sites", "globe"],
  ["profile", "Naukri profile", "refresh"],
  ["linkedin", "LinkedIn post", "pen"],
  ["resume", "Tailor resume", "file"],
  ["reports", "Reports", "chart"],
  ["study", "Learning path", "book"],
  ["todo", "Action inbox", "check"],
  ["setup", "Preferences", "sliders"],
  ["files", "My profile & files", "folder"],
  ["records", "Applications", "file"],
  ["research", "Research Studio", "book"],
  ["data", "Data hub", "folder"],
  ["outreach", "Recruiter drafts", "send"],
  ["linkedin-profile", "LinkedIn profile", "person"],
];

const NAMES = new Set(SECTIONS.map(([name]) => name));
const DEFAULT_ROUTE = { name: "overview", arg: "" };

export function parseHash(hash) {
  const raw = String(hash || "").replace(/^#\/?/, "");
  if (!raw) return { ...DEFAULT_ROUTE };
  let [name, ...rest] = raw.split("/");
  if (name === 'today') name = 'overview';
  if (!NAMES.has(name)) return { ...DEFAULT_ROUTE };
  try { return { name, arg: decodeURIComponent(rest.join("/")) }; }
  catch { return { ...DEFAULT_ROUTE }; }
}

export function parseRoute(loc = window.location) {
  return parseHash(loc.hash);
}

export function routeHref(name, arg = "") {
  return arg ? `#/${name}/${encodeURIComponent(arg)}` : `#/${name}`;
}

export function navigate(name, arg = "") {
  window.location.hash = routeHref(name, arg);
}
