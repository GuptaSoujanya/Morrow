/** Single mutable store for the whole app, plus small helpers that read/write it.
 * Views read from `S` directly and call `requestRender()` (wired in main.js) after changing it. */

function savedOverviewDays() {
  try {
    const raw = localStorage.getItem('overview-days');
    const saved = raw === null ? 14 : Number(raw);
    return [7, 14, 30, 0].includes(saved) ? saved : 14;
  } catch { return 14; }
}

export const S = {
  meta: null,
  status: null,
  course: null,
  online: true,
  route: { name: "overview", arg: "" },
  signature: "",
  pendingRender: false,

  forms: {},
  previews: {},
  runButtons: {},

  overview: null,
  overviewDays: savedOverviewDays(),
  funnelGroup: "all",
  searchesOpen: false,

  drafts: {},
  runNext: 0,

  consoleSize: "collapsed",
  revealedSecrets: new Set(),
  loadedFiles: {},
};

export function form(action) {
  return (S.forms[action] = S.forms[action] || {});
}

export function running() {
  return !!(S.status && S.status.run.running);
}

export function setOverviewDays(days) {
  S.overviewDays = days;
  try { localStorage.setItem("overview-days", String(days)); } catch { /* Storage may be disabled. */ }
}

/** Small seam so leaf modules (forms, console) can trigger a status refresh / render without
 * importing main.js directly (which would create an import cycle). main.js fills these in. */
export const hooks = {
  refreshStatus: async () => {},
  refreshCourse: async () => {},
  requestRender: () => {},
};
