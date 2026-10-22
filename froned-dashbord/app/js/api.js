/** Same-origin fetch wrapper. The dashboard Python server serves both the UI and
 * the existing project APIs on port 8100; no second proxy process is required. */

import { sentence } from "./format.js";

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** GET when `body` is omitted, POST JSON otherwise. Throws ApiError with a friendly message
 * on network failure or a non-2xx reply. `onOnline` is called with true/false so callers can
 * drive an offline banner without this module touching the DOM. */
export async function api(path, body, { onOnline } = {}) {
  const options =
    body === undefined
      ? {}
      : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  let reply;
  try {
    const initial=body===undefined && window.__orbitInitialRequests?.get(path);
    if(initial) window.__orbitInitialRequests.delete(path);
    reply = await (initial || fetch(path, options));
  } catch {
    onOnline?.(false);
    throw new ApiError("Can’t reach the site’s server.", 0);
  }
  onOnline?.(true);
  const data = await reply.json().catch(() => ({}));
  if (!reply.ok) {
    throw new ApiError(sentence(data.error || `${reply.status} ${reply.statusText}`), reply.status);
  }
  return data;
}
