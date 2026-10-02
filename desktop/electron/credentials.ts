import path from 'node:path';
import fs from 'node:fs/promises';
import { safeStorage } from 'electron';
import { atomic } from './util';
const credentialProviders = new Set(['mistral', 'openai', 'deepseek', 'alibaba']);
export type CredentialSnapshot = Partial<Record<'mistral'|'openai'|'deepseek'|'alibaba', string>>;
const controls = /[\x00-\x1f\x7f-\x9f]/;
export class Credentials {
 private queue = Promise.resolve();
 constructor(private root: string) {}
 private provider(value: unknown): asserts value is keyof CredentialSnapshot { if (typeof value !== 'string' || !credentialProviders.has(value)) throw new Error('INVALID_PROVIDER'); }
 private valid(value: unknown): value is string { return typeof value === 'string' && value.length >= 1 && value.length <= 8192 && !controls.test(value); }
 private async entries(): Promise<Record<string,string>> {
  let values: unknown;
  try {
   const contents = await fs.readFile(path.join(this.root,'credentials.json'),'utf8');
   try { values = JSON.parse(contents); } catch { throw new Error('CREDENTIAL_READ_FAILED'); }
  } catch (error) {
   if ((error as NodeJS.ErrnoException).code === 'ENOENT') values = {};
   else throw new Error('CREDENTIAL_READ_FAILED');
  }
  if (!values || typeof values !== 'object' || Array.isArray(values)) throw new Error('CREDENTIAL_READ_FAILED');
  for (const [provider, value] of Object.entries(values)) {
   if (!credentialProviders.has(provider) || typeof value !== 'string' || !value || value.length > 65536 || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value) || Buffer.from(value,'base64').toString('base64') !== value) throw new Error('CREDENTIAL_READ_FAILED');
  }
  return values as Record<string,string>;
 }
 // Main-process only: this method is never registered as an IPC action.
 async snapshot(): Promise<CredentialSnapshot> {
  await this.queue;
  try {
   const entries = await this.entries();
   if (Object.keys(entries).length && !safeStorage.isEncryptionAvailable()) throw new Error('unavailable');
   const snapshot: CredentialSnapshot = {};
   for (const [provider, encrypted] of Object.entries(entries)) {
    const value = safeStorage.decryptString(Buffer.from(encrypted,'base64'));
    if (!this.valid(value)) throw new Error('invalid');
    snapshot[provider as keyof CredentialSnapshot] = value;
   }
   return snapshot;
  } catch { throw new Error('CREDENTIAL_READ_FAILED'); }
 }
 async metadata() { return Object.keys(await this.snapshot()).map(provider => ({provider,configured:true})); }
 set(provider: unknown, value: unknown) { this.provider(provider); if (!this.valid(value)) throw new Error('INVALID_CREDENTIAL'); return this.write(provider,value); }
 remove(provider: unknown) { this.provider(provider); return this.write(provider,null); }
 private write(provider: string, value: string | null): Promise<void> {
  const operation = this.queue.then(async () => {
   try {
    if (!safeStorage.isEncryptionAvailable()) throw new Error('CREDENTIAL_ENCRYPTION_UNAVAILABLE');
    const values = await this.entries();
    if (value === null) delete values[provider]; else values[provider] = safeStorage.encryptString(value).toString('base64');
    await atomic(path.join(this.root,'credentials.json'),values);
   } catch { throw new Error('CREDENTIAL_WRITE_FAILED'); }
  });
  this.queue = operation.catch(() => {}); return operation;
 }
}
