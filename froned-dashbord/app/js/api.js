/** Same-origin fetch wrapper. The dashboard Python server serves both the UI and
 * the existing project APIs on port 8100; no second proxy process is required. */

import { sentence } from "./format.js";
import { queryClient, queryKey, invalidateReads } from './query-client.js';

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
async function request(path, body, { onOnline, signal } = {}) {
  const options =
    body === undefined
      ? { signal:AbortSignal.any([signal,AbortSignal.timeout(20_000)].filter(Boolean)) }
      : { signal:AbortSignal.timeout(20_000),method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  let reply;
  try {
    const initial=body===undefined && window.__orbitInitialRequests?.get(path);
    if(initial) window.__orbitInitialRequests.delete(path);
    reply = await (initial || fetch(path, options));
  } catch (error) {
    if(error.name==='AbortError') throw error;
    if(error.name==='TimeoutError')throw new ApiError(body===undefined?'The server is taking too long. Try again.':'The server did not confirm the result. Check Activity or reload the saved file before retrying.',0);
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

export async function api(path, body, { onOnline, fresh=false } = {}) {
  if(body!==undefined){
    const data=await request(path,body,{onOnline});
    if(new URL(path,window.location.origin).pathname!=='/api/preview')await invalidateReads();
    return data;
  }
  const url=new URL(path,window.location.origin);
  // Live controls and editable source files must never be served from stale memory.
  if(['/api/run','/api/status','/api/file'].includes(url.pathname))return request(path,body,{onOnline});
  const key=queryKey(path);
  if(fresh)await queryClient.invalidateQueries({queryKey:key,exact:true,refetchType:'none'});
  const data=await queryClient.fetchQuery({queryKey:key,queryFn:({signal})=>request(path,undefined,{signal,onOnline}),
    staleTime:url.pathname==='/api/meta'?300_000:30_000,
    retry:(count,error)=>count<1 && (!error.status || error.status>=500)});
  onOnline?.(true);
  return data;
}
