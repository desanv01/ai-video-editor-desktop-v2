const { contextBridge, ipcRenderer } = require('electron');
const invoke = (name: string, ...args: unknown[]) => ipcRenderer.invoke('aive:' + name, ...args);
contextBridge.exposeInMainWorld('aiveDesktop', Object.freeze({
  getState: () => invoke('getState'),
  onState: (listener: (state: unknown) => void) => { const handler = (_event: unknown, state: unknown) => listener(state); ipcRenderer.on('aive:state', handler); return () => ipcRenderer.removeListener('aive:state', handler); },
  prepare: () => invoke('prepare'), cancel: () => invoke('cancel'), retry: () => invoke('retry'), restartEngine: () => invoke('restartEngine'),
  pickMedia: () => invoke('pickMedia'), saveResource: (path: string, name: string) => invoke('saveResource', path, name),
  openDiagnostics: () => invoke('openDiagnostics'), setCredential: (provider: string, value: string) => invoke('setCredential', provider, value),
  removeCredential: (provider: string) => invoke('removeCredential', provider), openExternal: (url: string) => invoke('openExternal', url),
}));
