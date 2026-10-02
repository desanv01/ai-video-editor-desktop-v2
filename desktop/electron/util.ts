import path from 'node:path';
import fs from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
export const RELEASE = '2.1.0-rebuild.1';
export function relative(value: unknown): value is string { return typeof value === 'string' && value.length > 0 && value.length < 512 && !value.includes('\\') && !value.includes(':') && !value.includes('\0') && !value.startsWith('/') && value.split('/').every(p => p !== '..' && p !== '.' && p !== ''); }
export function confined(root: string, value: string): string { if (!relative(value)) throw new Error('UNSAFE_PATH'); const result = path.resolve(root, value); if (!result.startsWith(path.resolve(root) + path.sep)) throw new Error('UNSAFE_PATH'); return result; }
export async function atomic(file: string, value: unknown): Promise<void> { const temp = file + '.' + randomUUID() + '.tmp'; const handle = await fs.open(temp, 'wx'); try { await handle.writeFile(JSON.stringify(value)); await handle.sync(); } finally { await handle.close(); } await fs.rename(temp, file); }
export async function readJson<T>(file: string, fallback: T): Promise<T> { try { return JSON.parse(await fs.readFile(file,'utf8')) as T; } catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return fallback; throw error; } }
export interface Paths { root: string; data: string; components: string; state: string; cache: string; logs: string }
export async function paths(root: string): Promise<Paths> { const result = { root, data:path.join(root,'Data'), components:path.join(root,'Components'), state:path.join(root,'State'), cache:path.join(root,'Cache'), logs:path.join(root,'Logs') }; await Promise.all(Object.values(result).map(p => fs.mkdir(p,{recursive:true}))); return result; }
