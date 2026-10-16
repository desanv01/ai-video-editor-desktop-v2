import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import type { BigIntStats } from 'node:fs';

export interface EngineLaunch { executable: string; cwd: string }
const CMD_META = /[%!^&|<>()"\r\n]/;
const QUERY_FLAGS = ['/d', '/u', '/e:on', '/v:off', '/s', '/c'];
// Entire scripts are constants. No path, credential or caller filename enters shell text.
const SAME_DIRECTORY = 'for %I in (aive-engine.exe) do @for %J in (.) do @echo %~fsI^|%~fsJ';
const PARENT_DIRECTORY = 'for %I in (aive-engine.exe) do @for %J in (..) do @echo %~fsI^|%~fsJ';
class QueryUnavailable extends Error {}
const equalPath = (left: string, right: string): boolean => path.resolve(left).toLowerCase() === path.resolve(right).toLowerCase();
const sameId = (left: BigIntStats, right: BigIntStats): boolean => left.ino > 0n && left.dev > 0n && left.ino === right.ino && left.dev === right.dev;

async function noLinks(value: string): Promise<void> {
  for(let current = value;; current = path.dirname(current)) {
    if((await fs.lstat(current)).isSymbolicLink()) throw new Error('ENGINE_LAUNCH_REPARSE_PATH');
    if(path.dirname(current) === current) break;
  }
}
async function original(value: string, directory: boolean): Promise<BigIntStats> {
  const claimed = value.replace(/\//g, path.sep);
  if(!path.isAbsolute(value) || path.resolve(value).toLowerCase() !== claimed.toLowerCase()) throw new Error('ENGINE_LAUNCH_CANONICAL_PATH');
  await noLinks(value);
  if(!equalPath(await fs.realpath(value), value)) throw new Error('ENGINE_LAUNCH_REALPATH_CONFLICT');
  const info = await fs.stat(value, {bigint: true});
  if(!(directory ? info.isDirectory() : info.isFile()) || info.ino <= 0n || info.dev <= 0n) throw new Error('ENGINE_LAUNCH_FILE_IDENTITY');
  return info;
}
async function alias(value: string, canonical: string, before: BigIntStats, directory: boolean): Promise<void> {
  await noLinks(value);
  if(!equalPath(await fs.realpath(value), canonical)) throw new Error('ENGINE_LAUNCH_ALIAS_REALPATH');
  const info = await fs.stat(value, {bigint: true});
  if(!(directory ? info.isDirectory() : info.isFile()) || !sameId(info, before)) throw new Error('ENGINE_LAUNCH_ALIAS_IDENTITY');
  if(!sameId(await original(canonical, directory), before)) throw new Error('ENGINE_LAUNCH_ORIGINAL_CHANGED');
}

function query(command: string, directory: string, script: string, systemRoot: string, signal: AbortSignal): Promise<[string, string]> {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    let child: ReturnType<typeof spawn>;
    try {
      child = spawn(command, [...QUERY_FLAGS, script], {cwd: directory, shell: false, windowsHide: true,
        stdio: ['ignore', 'pipe', 'pipe'], env: {SystemRoot: systemRoot, WINDIR: systemRoot}});
    } catch(error) { reject(new QueryUnavailable(String(error))); return; }
    let failure: Error | null = null; let received = 0; const chunks: Buffer[] = [];
    const stop = (error: Error) => {
      if(failure) return; failure = error;
      if(child.pid && child.exitCode === null && child.signalCode === null) {
        try { child.kill('SIGKILL'); } catch { /* Keep ownership until close, even if termination fails. */ }
      }
    };
    const abort = () => stop(new Error('ENGINE_LAUNCH_QUERY_CANCELLED'));
    const timer = setTimeout(() => stop(new QueryUnavailable('ENGINE_LAUNCH_QUERY_TIMEOUT')), 2000);
    signal.addEventListener('abort', abort, {once: true});
    const collect = (chunk: Buffer, stdout: boolean) => {
      received += chunk.length;
      if(received > 8192) { stop(new Error('ENGINE_LAUNCH_QUERY_OUTPUT_LIMIT')); return; }
      if(stdout) chunks.push(chunk);
    };
    child.stdout!.on('data', (chunk: Buffer) => collect(chunk, true));
    child.stderr!.on('data', (chunk: Buffer) => collect(chunk, false));
    child.stdout!.once('error', error => stop(error)); child.stderr!.once('error', error => stop(error));
    child.once('error', error => stop(new QueryUnavailable(String(error))));
    // Never fallback/reject at exit/timeout/abort: close drains this exact query child and its pipes.
    child.once('close', code => {
      clearTimeout(timer); signal.removeEventListener('abort', abort);
      if(signal.aborted) { reject(signal.reason ?? new Error('ENGINE_LAUNCH_QUERY_CANCELLED')); return; }
      if(failure) { reject(failure); return; }
      if(code !== 0) { reject(new QueryUnavailable('ENGINE_LAUNCH_QUERY_FAILED')); return; }
      const bytes = Buffer.concat(chunks);
      if(bytes.length % 2) { reject(new Error('ENGINE_LAUNCH_QUERY_ENCODING')); return; }
      const line = bytes.toString('utf16le').replace(/^\uFEFF/, '').replace(/\r?\n$/, '');
      const lines = line.split('|');
      if(lines.length !== 2 || lines.some(line => !path.isAbsolute(line) || /[\x00-\x1f"]/.test(line))) {
        reject(new Error('ENGINE_LAUNCH_QUERY_OUTPUT')); return;
      }
      resolve([lines[0], lines[1]]);
    });
    if(signal.aborted) abort();
  });
}

/** Choose only a proved existing Windows spelling; callers keep canonical confinement/activation checks. */
export async function resolveEngineLaunch(executable: string, cwd: string, signal: AbortSignal): Promise<EngineLaunch> {
  signal.throwIfAborted();
  const canonical = {executable, cwd};
  if(process.platform !== 'win32' || path.basename(executable) !== 'aive-engine.exe') return canonical;
  const exeInfo = await original(executable, false), cwdInfo = await original(cwd, true);
  const unchanged = async (): Promise<EngineLaunch> => {
    if(!sameId(await original(executable, false), exeInfo) || !sameId(await original(cwd, true), cwdInfo)) throw new Error('ENGINE_LAUNCH_ORIGINAL_CHANGED');
    signal.throwIfAborted(); return canonical;
  };
  // for-variable expansion can emit path metacharacters even without command interpolation.
  // Such valid paths keep their previous direct launch; never send them through cmd.
  if(CMD_META.test(executable) || CMD_META.test(cwd)) return unchanged();
  const directory = path.dirname(executable);
  const script = equalPath(cwd, directory) ? SAME_DIRECTORY : equalPath(cwd, path.dirname(directory)) ? PARENT_DIRECTORY : undefined;
  const systemRoot = process.env.SystemRoot;
  if(!script || !systemRoot || !path.isAbsolute(systemRoot)) return unchanged();
  const command = path.join(systemRoot, 'System32', 'cmd.exe');
  try { await original(command, false); }
  catch(error) { if((error as NodeJS.ErrnoException).code === 'ENOENT') return unchanged(); throw error; }
  signal.throwIfAborted();
  let selected: [string, string];
  try { selected = await query(command, directory, script, systemRoot, signal); }
  catch(error) { signal.throwIfAborted(); if(error instanceof QueryUnavailable) return unchanged(); throw error; }
  // Identity errors/malformed output never enter the unavailable-query fallback.
  await alias(selected[0], executable, exeInfo, false);
  await alias(selected[1], cwd, cwdInfo, true);
  signal.throwIfAborted();
  return {executable: selected[0].length < executable.length ? selected[0] : executable,
    cwd: selected[1].length < cwd.length ? selected[1] : cwd};
}
