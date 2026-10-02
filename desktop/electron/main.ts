import { randomUUID } from 'node:crypto';
import { app, BrowserWindow, protocol, ipcMain, dialog, shell, net } from 'electron';
import { autoUpdater } from 'electron-updater';
import path from 'node:path';
import fs from 'node:fs/promises';
import { createWriteStream } from 'node:fs';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import type { DesktopState } from '../../contracts/rebuild/desktop';
import { paths, RELEASE, type Paths } from './util';
import { Credentials } from './credentials';
import { Components } from './components';
import { Supervisor } from './supervisor';
import { handle, proxy, apiPath } from './protocol';
protocol.registerSchemesAsPrivileged([{scheme:'aive',privileges:{standard:true,secure:true,supportFetchAPI:true,stream:true}}]);
const base=path.join(process.env.LOCALAPPDATA ?? app.getPath('appData'),'AIVE','Desktop');
app.setPath('userData',path.join(base,'Shell'));
const developerUrl=!app.isPackaged && process.env.AIVE_DEVELOPER_MODE==='1' && process.env.AIVE_DEV_URL==='http://localhost:1420' ? process.env.AIVE_DEV_URL : null;
autoUpdater.autoDownload=false; autoUpdater.autoInstallOnAppQuit=false;
let window:BrowserWindow|null=null;let owned:Paths;let components:Components;let supervisor:Supervisor;let credentials:Credentials;let quitting=false;let preparing=false;let restarting=false;
let lastLog='';
let state:DesktopState={schemaVersion:'aive.desktop-state.v1',releaseVersion:RELEASE,phase:'checking',setupComplete:false,engineState:'stopped',components:[],capabilities:{localTranscription:{state:'unavailable',reason:'A verified runtime and compatible model with a joint transcription probe are required.'},updates:{state:'unavailable',reason:'Publishing and signing metadata are not configured.'},providers:{state:'unavailable',reason:'Secure storage is available through the shell; backend credential routing is not connected.',providerRequired:true}},progress:{operationId:null,selected:[],totalBytes:0,acquiredBytes:0,completedWork:0,totalWork:0},error:null,canCancel:false,canRetry:false,credentials:[]};
function publish(patch:Partial<DesktopState>):void {state={...state,...patch};window?.webContents.send('aive:state',state);if(owned){const errorCode=state.error?.code && /^[A-Z0-9_]{1,80}$/.test(state.error.code)?state.error.code:null;const line=JSON.stringify({release:RELEASE,phase:state.phase,engine:state.engineState,error:errorCode,components:state.components.map(c=>({id:c.id,version:c.version,phase:c.phase}))});if(line!==lastLog){lastLog=line;void fs.appendFile(path.join(owned.logs,'controller.log'),line+'\n').catch(()=>{});}}}
function failure(code:string):void {const safe=/^[A-Z0-9_]{1,80}$/.test(code)?code:'DESKTOP_OPERATION_FAILED';publish({phase:'error',setupComplete:false,canRetry:true,canCancel:false,error:{code:safe,message:safe==='PACKS_UNCONFIGURED'?'Runtime packs are not configured in this engineering build. A release with verified packs is required.':'The desktop operation could not complete. Retry or open diagnostics.',retryable:true}});}
function validateSender(event:Electron.IpcMainInvokeEvent):void {const frame=event.senderFrame; if(!window||window.isDestroyed()||event.sender.isDestroyed()||!frame||frame.isDestroyed()||frame.detached||window.webContents.isDestroyed()||event.sender!==window.webContents||frame!==window.webContents.mainFrame)throw new Error('IPC_SENDER_REJECTED');const url=new URL(frame.url);if(developerUrl){if(url.origin!==developerUrl)throw new Error('IPC_ORIGIN_REJECTED');}else if(url.protocol!=='aive:'||url.hostname!=='app'||url.port||url.username||url.password)throw new Error('IPC_ORIGIN_REJECTED');}
function register(name:string,count:number,action:(...args:unknown[])=>unknown):void {ipcMain.handle('aive:'+name,async(event,...args:unknown[])=>{validateSender(event);if(args.length!==count)throw new Error('IPC_ARGUMENTS_REJECTED');return action(...args);});}
async function start():Promise<void> {if(state.engineState==='starting')throw new Error('ENGINE_START_BUSY');if(!await components.allRequiredInstalled())throw new Error('REQUIRED_COMPONENTS_MISSING');const active=await components.engine();publish({phase:'starting',setupComplete:false,error:null});await supervisor.start(active.engine,active.root,active.ffmpegRoot,active.documentsRoot,active.libreofficeBinary);await components.markReady();if(await components.localTranscriptionReady()) publish({capabilities:{...state.capabilities,localTranscription:{state:'ready'}}});}
async function prepare():Promise<void>{if(preparing||restarting)throw new Error('PREPARATION_BUSY');preparing=true;try{await supervisor.stop();await components.prepare();await start();}catch(error){if(state.phase!=='cancelled')failure(error instanceof Error?error.message:'PREPARATION_FAILED');}finally{preparing=false;}}
async function saveResource(value:unknown,name:unknown):Promise<boolean> {if(!apiPath(value)||typeof name!=='string'||name.length>180||!name||/[\\/:*?"<>|\x00-\x1f]/.test(name)||name==='.'||name==='..')throw new Error('SAVE_ARGUMENTS_REJECTED');const selected=await dialog.showSaveDialog(window!,{defaultPath:name});if(selected.canceled||!selected.filePath)return false;const response=await proxy(new Request('aive://app'+value),supervisor.getEndpoint());if(!response.ok||!response.body)throw new Error('SAVE_RESOURCE_FAILED');const temp=selected.filePath+'.'+randomUUID()+'.aive-part';try{await pipeline(Readable.fromWeb(response.body as import('node:stream/web').ReadableStream),createWriteStream(temp,{flags:'wx'}),{signal:supervisor.getEndpoint().signal});await fs.rename(temp,selected.filePath);return true;}catch(error){await fs.rm(temp,{force:true});throw error;}}
function ipc():void {
 register('getState',0,()=>state);register('prepare',0,prepare);register('retry',0,prepare);register('cancel',0,()=>{if(state.canCancel)components.cancel();});
 register('restartEngine',0,async()=>{if(preparing||restarting)throw new Error('ENGINE_RESTART_BUSY');restarting=true;try{await supervisor.stop();await start();}catch(error){failure(error instanceof Error?error.message:'ENGINE_RESTART_FAILED');}finally{restarting=false;}});
 register('pickMedia',0,async()=>{const result=await dialog.showOpenDialog(window!,{properties:['openFile','multiSelections'],filters:[{name:'Media',extensions:['mp4','mov','mkv','avi','webm','mp3','wav','m4a']}]});return result.canceled?[]:result.filePaths;});
 register('saveResource',2,saveResource);register('openDiagnostics',0,async()=>{await shell.openPath(owned.logs);});
 register('setCredential',2,async(provider,value)=>{await credentials.set(provider,value);publish({credentials:await credentials.metadata()});});register('removeCredential',1,async(provider)=>{await credentials.remove(provider);publish({credentials:await credentials.metadata()});});
 register('openExternal',1,async(value)=>{if(typeof value!=='string'||value.length>2048)throw new Error('EXTERNAL_URL_REJECTED');const url=new URL(value);if(url.protocol!=='https:'||url.username||url.password||url.port||!['github.com','www.aive.dev','aive.dev'].includes(url.hostname))throw new Error('EXTERNAL_URL_REJECTED');await shell.openExternal(url.href);});
}
function createWindow():void {window=new BrowserWindow({width:1280,height:820,minWidth:800,minHeight:600,show:false,backgroundColor:'#17171c',title:'AIVE Desktop',webPreferences:{preload:path.join(__dirname,'preload.js'),contextIsolation:true,sandbox:true,nodeIntegration:false,webSecurity:true}});window.once('ready-to-show',()=>window?.show());window.on('closed',()=>{window=null;});window.webContents.setWindowOpenHandler(()=>({action:'deny'}));window.webContents.on('will-navigate',(event,url)=>{try{const target=new URL(url);const allowed=developerUrl?target.origin===developerUrl:target.protocol==='aive:'&&target.hostname==='app'&&!target.port&&!target.username&&!target.password;if(!allowed)event.preventDefault();}catch{event.preventDefault();}});window.webContents.on('will-attach-webview',event=>event.preventDefault());window.webContents.session.setPermissionRequestHandler((_webContents,_permission,callback)=>callback(false));window.webContents.session.setPermissionCheckHandler(()=>false);window.webContents.session.on('will-download',event=>event.preventDefault());void window.loadURL(developerUrl??'aive://app/');}
if(!app.requestSingleInstanceLock())app.quit();else{
 app.on('second-instance',()=>{if(window?.isMinimized())window.restore();window?.focus();});
 app.on('window-all-closed',()=>app.quit());
 app.on('before-quit',event=>{if(quitting)return;event.preventDefault();quitting=true;components?.cancel();void supervisor?.stop().finally(()=>app.quit());});
 void app.whenReady().then(async()=>{owned=await paths(base);credentials=new Credentials(owned.state);supervisor=new Supervisor(owned,(engineState,code)=>{publish({engineState,setupComplete:engineState==='ready',...(engineState==='ready'?{phase:'ready',error:null,canRetry:false,capabilities:{...state.capabilities,api:{state:'ready'},database:{state:'ready'},requiredComponents:{state:'ready'}}}:engineState==='failed'?{phase:'error',canRetry:true,error:{code:code??'ENGINE_FAILED',message:'The private engine stopped. Restart it to continue.',retryable:true}}:{})});});
  const manifestFile=app.isPackaged?path.join(process.resourcesPath,'rebuild','components.json'):path.resolve(__dirname,'../../../../contracts/rebuild/components.json');
  components=new Components(owned,manifestFile,[path.join(process.resourcesPath,'offline-components'),path.join(path.dirname(app.getPath('exe')),'offline-components')],publish);
  protocol.handle('aive',request=>handle(request,path.resolve(__dirname,'../../../dist'),()=>supervisor.getEndpoint()));ipc();createWindow();
  try{publish({credentials:await credentials.metadata()});await components.initialize();if(await components.allRequiredInstalled())await start();}catch(error){failure(error instanceof Error?error.message:'DESKTOP_INITIALIZATION_FAILED');}
 }).catch(()=>{app.quit();});
}







