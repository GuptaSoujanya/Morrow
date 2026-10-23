import { QueryClient } from '@tanstack/react-query';

// Memory only: no credentials or personal data are persisted by this cache.
export const queryClient = new QueryClient({defaultOptions:{queries:{
  staleTime:30_000, gcTime:300_000, retry:1, retryDelay:600,
  refetchOnWindowFocus:false, refetchOnReconnect:true,
},mutations:{retry:false}}});

export function queryKey(path){
  const url=new URL(path,window.location.origin);
  url.searchParams.sort();
  return ['api',url.pathname,url.search];
}
export function invalidateReads(){return queryClient.invalidateQueries({queryKey:['api'],refetchType:'none'});}
export function invalidatePath(path){return queryClient.invalidateQueries({queryKey:['api',path],refetchType:'none'});}
