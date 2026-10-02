import path from 'node:path';
import { safeStorage } from 'electron';
import { atomic, readJson } from './util';
// Credential namespaces from backend/app/services/app_settings.py API_KEY_ENV_VARS.
// Registry wiring maps Voxtral/Mistral, Whisper/OpenAI, DeepSeek and Qwen/Alibaba to these providers.
const credentialProviders = new Set(['mistral', 'openai', 'deepseek', 'alibaba']);
export class Credentials {
 private queue = Promise.resolve();
 constructor(private root: string) {}
 private provider(value: unknown): asserts value is string { if (typeof value !== 'string' || !credentialProviders.has(value)) throw new Error('INVALID_PROVIDER'); }
 async metadata() { const values = await readJson<Record<string,string>>(path.join(this.root,'credentials.json'),{}); return Object.keys(values).filter(provider => credentialProviders.has(provider)).map(provider => ({ provider, configured:true })); }
 set(provider: unknown, value: unknown) { this.provider(provider); if (typeof value !== 'string' || value.length < 1 || value.length > 8192) throw new Error('INVALID_CREDENTIAL'); return this.write(provider, value); }
 remove(provider: unknown) { this.provider(provider); return this.write(provider,null); }
 private write(provider: string, value: string | null): Promise<void> { const operation = this.queue.then(async () => { if (!safeStorage.isEncryptionAvailable()) throw new Error('CREDENTIAL_ENCRYPTION_UNAVAILABLE'); const file = path.join(this.root,'credentials.json'); const values = await readJson<Record<string,string>>(file,{}); if(value === null) delete values[provider]; else values[provider] = safeStorage.encryptString(value).toString('base64'); await atomic(file,values); }); this.queue = operation.catch(() => {}); return operation; }
}


