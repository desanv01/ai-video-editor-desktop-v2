import { spawn, type ChildProcess } from 'node:child_process';
import { createServer, type Socket } from 'node:net';
import { randomBytes, randomUUID, createHmac, timingSafeEqual } from 'node:crypto';
import { net } from 'electron';
import { confined, type Paths } from './util';
import type { ComponentManifest } from '../../contracts/rebuild/desktop';
export interface Endpoint { url: string; token: string; signal: AbortSignal }
export class Supervisor {
 private child: ChildProcess | null = null; private endpoint: Endpoint | null = null; private abort = new AbortController(); private stopping = false;
 constructor(private paths: Paths, private changed: (state: 'stopped'|'starting'|'ready'|'failed', code?: string) => void) {}
 getEndpoint(): Endpoint { if(!this.endpoint) throw new Error('ENGINE_NOT_READY'); return this.endpoint; }
 async start(engine: ComponentManifest, root: string, ffmpegRoot: string): Promise<void> {
  if(this.child) throw new Error('ENGINE_ALREADY_RUNNING'); this.changed('starting'); this.stopping=false; this.abort=new AbortController();
  const token=randomBytes(32).toString('hex'), sessionId=randomUUID(), nonce=randomBytes(32).toString('hex');
  const server=createServer(); const sockets=new Set<Socket>();
  let timer: NodeJS.Timeout | undefined;
  const handshake = new Promise<number>((resolve,reject) => {
   timer=setTimeout(() => reject(new Error('ENGINE_START_TIMEOUT')),30000);
   server.on('error',reject);
   server.on('connection',socket => { sockets.add(socket); socket.setTimeout(5000,() => socket.destroy()); let buffer=Buffer.alloc(0);
    socket.on('data',chunk => { buffer=Buffer.concat([buffer,chunk]); if(buffer.length>65536) { socket.destroy(); reject(new Error('HANDSHAKE_TOO_LARGE')); return; } const end=buffer.indexOf(10); if(end<0) return;
     try { const h=JSON.parse(buffer.subarray(0,end).toString('utf8')); const fields=[h.protocolVersion,h.sessionId,h.nonce,h.pid,h.componentId,h.componentVersion,h.host,h.assignedPort];
      if(h.type!=='aive-engine-startup'||h.protocolVersion!=='desktop.engine-handshake.v2'||h.sessionId!==sessionId||h.nonce!==nonce||h.pid!==this.child?.pid||h.componentId!==engine.id||h.componentVersion!==engine.version||h.host!=='127.0.0.1'||!Number.isInteger(h.assignedPort)||h.assignedPort<1||h.assignedPort>65535||typeof h.hmacSha256!=='string'||!/^[a-f0-9]{64}$/.test(h.hmacSha256)) throw new Error('HANDSHAKE_IDENTITY');
      const proof=createHmac('sha256',token).update(fields.join('\n')).digest(); if(!timingSafeEqual(proof,Buffer.from(h.hmacSha256,'hex'))) throw new Error('HANDSHAKE_AUTH'); resolve(h.assignedPort);
     } catch { reject(new Error('HANDSHAKE_REJECTED')); } finally { socket.destroy(); }
    }); socket.on('error',() => {}); socket.on('close',() => sockets.delete(socket));
   });
  });
  // Attach rejection handling before any asynchronous listen/spawn work.
  void handshake.catch(() => {});
  try {
   await new Promise<void>((resolve,reject) => { server.once('error',reject); server.listen(0,'127.0.0.1',resolve); });
   const address=server.address(); if(!address || typeof address==='string') throw new Error('CONTROL_BIND_FAILED');
   const executable=confined(root,engine.entrypoints.engine);
   this.child=spawn(executable,[],{cwd:root,windowsHide:true,shell:false,stdio:'ignore',env:{...process.env,AIVE_DESKTOP_DATA_ROOT:this.paths.data,AIVE_DESKTOP_COMPONENT_ROOT:this.paths.components,AIVE_FFMPEG_COMPONENT_ROOT:ffmpegRoot,AIVE_ENGINE_PORT:'0',AIVE_ENGINE_BEARER_TOKEN:token,AIVE_ENGINE_SESSION_ID:sessionId,AIVE_ENGINE_CONTROL_ADDRESS:`127.0.0.1:${address.port}`,AIVE_ENGINE_CONTROL_NONCE:nonce}});
   const child=this.child;
   const exited=new Promise<never>((_resolve,reject) => { child.once('error',() => reject(new Error('ENGINE_SPAWN_FAILED'))); child.once('exit',() => reject(new Error('ENGINE_EXITED'))); }); void exited.catch(() => {});
   child.once('exit',() => { this.endpoint=null; this.abort.abort(); if(this.child===child) this.child=null; this.changed(this.stopping?'stopped':'failed',this.stopping?undefined:'ENGINE_EXITED'); });
   const port=await Promise.race([handshake,exited]);
   const endpoint={url:`http://127.0.0.1:${port}`,token,signal:this.abort.signal};
   const response=await net.fetch(endpoint.url+'/readiness',{headers:{Authorization:`Bearer ${token}`},redirect:'error',signal:AbortSignal.any([this.abort.signal,AbortSignal.timeout(10000)])});
   const health=await response.json() as { schemaVersion?:string; process?:{alive?:boolean;pid?:number;componentId?:string;componentVersion?:string}; checks?:Record<string,{state?:string}> };
   if(!response.ok||health.schemaVersion!=='desktop.health-readiness.v1'||health.process?.alive!==true||health.process.pid!==child.pid||health.process.componentId!==engine.id||health.process.componentVersion!==engine.version||!['ready','healthy'].includes(health.checks?.api?.state??'')||!['ready','healthy'].includes(health.checks?.database?.state??'')) throw new Error('ENGINE_HEALTH_NOT_READY');
   if(this.abort.signal.aborted||this.child!==child) throw new Error('ENGINE_EXITED'); this.endpoint=endpoint; this.changed('ready');
  } catch(error) { await this.stop(); this.changed('failed',error instanceof Error?error.message:'ENGINE_START_FAILED'); throw error; }
  finally { if(timer) clearTimeout(timer); sockets.forEach(s => s.destroy()); server.close(); }
 }
 async stop(): Promise<void> {
  this.stopping=true; const child=this.child; const endpoint=this.endpoint; this.endpoint=null; this.abort.abort(); if(!child) return;
  const exit=new Promise<void>(resolve => child.once('exit',() => resolve()));
  if(endpoint) { try { await net.fetch(endpoint.url+'/engine-control/shutdown',{method:'POST',headers:{Authorization:`Bearer ${endpoint.token}`},redirect:'error',signal:AbortSignal.timeout(2000)}); } catch {} }
  let shutdownDeadline: NodeJS.Timeout | undefined;
  let exited: boolean;
  try {
   exited=await Promise.race([exit.then(() => true),new Promise<false>(resolve => { shutdownDeadline=setTimeout(() => resolve(false),10000); shutdownDeadline.unref(); })]);
  } finally { if(shutdownDeadline) clearTimeout(shutdownDeadline); }
  if(!exited && child.pid) { if(process.platform==='win32') await new Promise<void>(resolve => { const killer=spawn('taskkill.exe',['/PID',String(child.pid),'/T','/F'],{windowsHide:true,shell:false,stdio:'ignore'}); killer.once('error',() => { child.kill(); resolve(); }); killer.once('exit',() => resolve()); }); else child.kill('SIGKILL'); }
  if(this.child===child) this.child=null; this.changed('stopped');
 }
}


