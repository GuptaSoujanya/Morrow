/** Hand-drawn SVG icon set (24x24 viewBox, stroke-based) — no emoji anywhere in the UI. */

import { svg } from "./dom.js";

const PATHS = {
  bot: ["M5 7h14v13H5z", "M12 3v4", "M9 12h.01M15 12h.01", "M9 16h6", "M2 11v5M22 11v5"],
  activity: ["M3 12h4l3-8 4 16 3-8h4"],
  workflow: ["M4 4h6v6H4z", "M14 14h6v6h-6z", "M10 7h7v7", "M7 10v7h7"],
  person: ["M12 12a4 4 0 100-8 4 4 0 000 8z", "M4 21v-2a6 6 0 016-6h4a6 6 0 016 6v2"],
  sun: ["M12 8a4 4 0 100 8 4 4 0 000-8z", "M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M5 19l1.5-1.5M17.5 6.5L19 5"],
  grid: ["M4 4h6.5v6.5H4z", "M13.5 4H20v6.5h-6.5z", "M4 13.5h6.5V20H4z", "M13.5 13.5H20V20h-6.5z"],
  send: ["M3 11l17-8-7 17-2.5-7.5L3 11z"],
  globe: ["M12 3a9 9 0 100 18 9 9 0 000-18z", "M3 12h18", "M12 3c2.5 2.5 2.5 15.5 0 18", "M12 3c-2.5 2.5-2.5 15.5 0 18"],
  refresh: ["M4 12a8 8 0 0114-5.3M20 12a8 8 0 01-14 5.3", "M18 4v4h-4", "M6 20v-4h4"],
  pen: ["M4 20l4-1 11-11-3-3L5 16l-1 4z", "M14 6l3 3"],
  file: ["M7 3h7l4 4v14H7z", "M14 3v4h4"],
  chart: ["M4 20V10", "M11 20V4", "M18 20v-7"],
  book: ["M4 5a2 2 0 012-2h8v18H6a2 2 0 01-2-2z", "M14 3h4a2 2 0 012 2v16h-6"],
  check: ["M4 12l5 5 11-11"],
  sliders: ["M4 6h10M17 6h3", "M4 12h3M10 12h10", "M4 18h10M17 18h3", "M14 4v4", "M7 10v4", "M17 16v4"],
  folder: ["M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z"],
  play: ["M6 4l14 8-14 8z"],
  stop: ["M6 6h12v12H6z"],
  x: ["M5 5l14 14", "M19 5L5 19"],
  copy: ["M9 9h10v10H9z", "M5 15V5h10"],
  "chevron-down": ["M5 8l7 7 7-7"],
  "chevron-left": ["M15 5l-7 7 7 7"],
  "chevron-right": ["M9 5l7 7-7 7"],
  calendar: ["M5 5h14v16H5z", "M5 10h14", "M8 3v5", "M16 3v5", "M8 14h2", "M14 14h2", "M8 17h2"],
  "chevron-up": ["M5 16l7-7 7 7"],
  eye: ["M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z", "M12 15a3 3 0 100-6 3 3 0 000 6z"],
  "eye-off": ["M3 3l18 18", "M9.9 5.1A10.4 10.4 0 0112 5c6.5 0 10 6 10 6a16.6 16.6 0 01-3.2 3.9", "M6.1 6.9A16 16 0 002 11s3.5 6 10 6a10.3 10.3 0 004-.8", "M9.5 9.6a3 3 0 004.1 4.2"],
  external: ["M14 4h6v6", "M20 4L10 14", "M8 6H5a1 1 0 00-1 1v12a1 1 0 001 1h12a1 1 0 001-1v-3"],
  "alert-triangle": ["M12 4l9 16H3z", "M12 10v4", "M12 17.5h.01"],
  info: ["M12 3a9 9 0 100 18 9 9 0 000-18z", "M12 8h.01", "M11 11h1v6h1"],
  search: ["M10 17a7 7 0 100-14 7 7 0 000 14z", "M21 21l-4.3-4.3"],
  download: ["M12 4v12", "M7 12l5 5 5-5", "M5 20h14"],
  "arrow-up-right": ["M7 17L17 7", "M9 7h8v8"],
};

export function icon(name, className = "icon") {
  const d = PATHS[name] || PATHS.info;
  return svg("svg", { class: className, viewBox: "0 0 24 24", "aria-hidden": "true" }, d.map((p) => svg("path", { d: p })));
}
