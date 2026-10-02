import { net } from 'electron';
import fs from 'node:fs/promises';
import path from 'node:path';
import type { Endpoint } from './supervisor';
import { confined } from './util';
export const CSP = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self' data:; connect-src 'self'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'self'";
const requestHeaders=new Set(['accept','accept-language','content-type','range','if-range','if-none-match','if-modified-since']);
const responseHeaders=new Set(['content-type','content-length','content-range','accept-ranges','content-disposition','etag','last-modified','cache-control']);
const types:Record<string,string>={'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css','.json':'application/json','.svg':'image/svg+xml','.png':'image/png','.jpg':'image/jpeg','.woff2':'font/woff2','.ico':'image/x-icon'};
export function apiPath(value: unknown): value is string {
 if(typeof value!=='string'||value.length>4096||!value.startsWith('/api/v1/')||value.includes(String.fromCharCode(92))||value.includes('#')) return false;
 try {
  // URL construction removes dot segments, so inspect the unnormalized path first.
  const rawPath=value.split('?',1)[0];
  const decoded=decodeURIComponent(rawPath);
  if(/%2f|%5c|%00/i.test(rawPath)||/%2e|%2f|%5c|%00/i.test(decoded)||decoded.includes(String.fromCharCode(92))||decoded.includes('\0')||decoded.split('/').some(segment=>segment==='.'||segment==='..')) return false;
  const parsed=new URL(value,'aive://app');
  return parsed.protocol==='aive:' && parsed.hostname==='app' && !parsed.port && !parsed.username && !parsed.password && parsed.pathname.startsWith('/api/v1/');
 } catch { return false; }
}
export async function proxy(request: Request, endpoint: Endpoint): Promise<Response> {
 const url=new URL(request.url); if(url.hostname!=='app'||url.username||url.password||url.port||!apiPath(url.pathname+url.search)||!['GET','HEAD','POST','PUT','PATCH','DELETE','OPTIONS'].includes(request.method)) return new Response('Invalid request',{status:400});
 const headers=new Headers(); request.headers.forEach((value,key) => { if(requestHeaders.has(key.toLowerCase())) headers.set(key,value); }); headers.set('Accept-Encoding','identity'); headers.set('Authorization',`Bearer ${endpoint.token}`);
 const body=['GET','HEAD'].includes(request.method)?undefined:request.body;
 const upstream=await net.fetch(endpoint.url+url.pathname+url.search,{method:request.method,headers,body,redirect:'error',signal:AbortSignal.any([request.signal,endpoint.signal]),...(body?{duplex:'half'}:{})} as RequestInit);
 const output=new Headers(); upstream.headers.forEach((value,key) => { if(responseHeaders.has(key.toLowerCase())) output.set(key,value); }); output.set('Content-Security-Policy',CSP); output.set('X-Content-Type-Options','nosniff');
 return new Response(upstream.body,{status:upstream.status,statusText:upstream.statusText,headers:output});
}
export async function handle(request: Request, root: string, endpoint: () => Endpoint): Promise<Response> {
 try { const url=new URL(request.url); if(url.protocol!=='aive:'||url.hostname!=='app'||url.username||url.password||url.port) return new Response('Unknown origin',{status:403});
  if(url.pathname.startsWith('/api/')) return await proxy(request,endpoint());
  if(!['GET','HEAD'].includes(request.method)) return new Response('Method not allowed',{status:405});
  const decoded=decodeURIComponent(url.pathname); const asset=decoded==='/'?'index.html':decoded.slice(1); const file=confined(root,asset); const stat=await fs.stat(file); if(!stat.isFile()) return new Response('Not found',{status:404});
  const response=await net.fetch(new URL('file:///'+file.replace(/\\/g,'/')).href,{method:request.method,signal:request.signal});
  const headers=new Headers(response.headers); headers.set('Content-Type',types[path.extname(file)]??'application/octet-stream'); headers.set('Content-Security-Policy',CSP); headers.set('X-Content-Type-Options','nosniff'); return new Response(response.body,{status:response.status,headers});
 } catch { return new Response(JSON.stringify({code:'DESKTOP_RESOURCE_UNAVAILABLE',message:'The resource or local engine is unavailable.'}),{status:503,headers:{'Content-Type':'application/json'}}); }
}




