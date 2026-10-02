export type SetupPhase = 'checking' | 'awaiting_confirmation' | 'acquiring' | 'verifying' | 'extracting' | 'probing' | 'activating' | 'starting' | 'ready' | 'cancelled' | 'error';
export type EngineState = 'stopped' | 'starting' | 'ready' | 'failed';
export interface ComponentState { readonly id: string; readonly version: string; readonly phase: SetupPhase; readonly bytes: number; readonly installed: boolean; readonly error?: string }
export interface DesktopState {
  readonly schemaVersion: 'aive.desktop-state.v1'; readonly releaseVersion: string; readonly phase: SetupPhase;
  readonly setupComplete: boolean; readonly engineState: EngineState; readonly components: readonly ComponentState[];
  readonly capabilities: Readonly<Record<string, { readonly state: 'ready' | 'unavailable' | 'degraded'; readonly reason?: string; readonly providerRequired?: boolean }>>;
  readonly progress: { readonly operationId: string | null; readonly selected: readonly string[]; readonly totalBytes: number; readonly acquiredBytes: number; readonly completedWork: number; readonly totalWork: number };
  readonly error: { readonly code: string; readonly message: string; readonly retryable: boolean } | null;
  readonly canCancel: boolean; readonly canRetry: boolean;
  readonly credentials: readonly { readonly provider: string; readonly configured: boolean }[];
}
export interface DesktopBridge {
  getState(): Promise<DesktopState>; onState(listener: (state: DesktopState) => void): () => void;
  prepare(): Promise<void>; cancel(): Promise<void>; retry(): Promise<void>; restartEngine(): Promise<void>;
  pickMedia(): Promise<readonly string[]>; saveResource(path: string, suggestedName: string): Promise<boolean>;
  openDiagnostics(): Promise<void>; setCredential(provider: string, value: string): Promise<void>;
  removeCredential(provider: string): Promise<void>; openExternal(url: string): Promise<void>;
}
export type ProbeKind = 'engine-self-test' | 'ffmpeg-version' | 'ffprobe-version' | 'filter-codec-check' | 'whisper-runtime' | 'whisper-model' | 'document-tool-version';
export interface ComponentManifest { id: string; version: string; archive: string; sha256: string; sizeBytes: number; expandedBytes: number; required: boolean; entrypoints: Record<string,string>; probes: { kind: ProbeKind; entrypoint: string; args?: string[]; runtimeEntrypoint?: string; audioEntrypoint?: string; expectedText?: string }[]; url?: string }
export interface ReleaseManifest { schemaVersion: 'aive.components.v1'; releaseVersion: string; platform: 'win32'; architecture: 'x64'; components: ComponentManifest[] }

