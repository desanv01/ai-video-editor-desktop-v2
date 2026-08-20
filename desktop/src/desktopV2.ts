import { canonicalWindowsStorageLayout, type RemediationCode, type StorageLayout } from "./contracts/desktopV2.ts";

export const DESKTOP_V2_PRODUCT_NAME = "AI Video Editor Desktop V2";
export const DESKTOP_V2_PRODUCT_LINE = "Desktop V2";
export const DESKTOP_V2_IDENTIFIER = "com.fyp.ai-video-editor.desktop-v2";
export const DESKTOP_V2_STATE_VERSION = "desktop.shell-state.v1";

export type DesktopBootState =
  | "starting"
  | "shell-ready"
  | "setup-required"
  | "engine-available"
  | "recoverable-error";

export type ComponentInstallationState = "available" | "not-installed" | "unavailable";
export type ActivationStatus = "missing" | "available" | "invalid" | "unreadable";

export interface ShellInfo {
  productName: string;
  productLine: string;
  shellVersion: string;
  identifier: string;
  launchMode: string;
  bootstrapPolicy: string;
  storageLayoutVersion: string;
  shellInstallPath: string;
  userStatePath: string;
}

export interface ResolvedDesktopPaths {
  schemaVersion: string;
  platform: string;
  programFilesRoot: string;
  programDataRoot: string;
  localAppDataRoot: string;
  userProfileRoot: string;
  storageLayout: StorageLayout;
  shellInstall: string;
  sharedComponents: string;
  activationMetadata: string;
  activationMetadataFile: string;
  downloadStaging: string;
  userRoot: string;
  userConfig: string;
  userCache: string;
  userLogs: string;
  userState: string;
  shellStateFile: string;
  projects: string;
  exports: string;
}

export interface ActivationMetadataInspection {
  status: ActivationStatus;
  metadataPath: string;
  present: boolean;
  componentId: string | null;
  componentVersion: string | null;
  activePath: string | null;
  detailCode: string;
  detail: string;
  remediationCodes: string[];
}

export interface ComponentStatus {
  id: string;
  displayName: string;
  state: ComponentInstallationState;
  required: boolean;
  detail: string;
  remediationCodes: string[];
}

export interface ShellRemediation {
  code: string;
  title: string;
  action: string;
}

export interface ShellBootstrapError {
  code: string;
  message: string;
  remediationCodes: string[];
}

export interface DesktopV2BootstrapResult {
  shellInfo: ShellInfo;
  paths: ResolvedDesktopPaths;
  bootState: DesktopBootState;
  engineReady: boolean;
  setupRequired: boolean;
  componentStatus: ComponentStatus[];
  activation: ActivationMetadataInspection;
  remediation: ShellRemediation[];
  persistedStatePath: string;
  error: ShellBootstrapError | null;
}

export interface SafeLogDirectoryResult {
  available: boolean;
  path: string;
  created: boolean;
  detail: string;
  remediationCodes: string[];
}

export interface DiagnosticSnapshotResult {
  created: boolean;
  diagnosticId: string;
  path: string | null;
  detail: string;
  remediationCodes: string[];
}

export type BootEvent =
  | { type: "shell-ready" }
  | { type: "component-scan"; componentState: ComponentInstallationState | "invalid" }
  | { type: "supervisor-ready" }
  | { type: "recoverable-error" };

export function initialBootState(): DesktopBootState {
  return "starting";
}

export function transitionBootState(state: DesktopBootState, event: BootEvent): DesktopBootState {
  if (event.type === "recoverable-error") return "recoverable-error";

  if (state === "starting" && event.type === "shell-ready") return "shell-ready";
  if (state === "shell-ready" && event.type === "component-scan") {
    if (event.componentState === "available") return "engine-available";
    if (event.componentState === "not-installed") return "setup-required";
    return "recoverable-error";
  }
  if (state === "engine-available" && event.type === "supervisor-ready") return "engine-available";
  return state;
}

export function deriveBootState(componentState: ComponentInstallationState | "invalid"): DesktopBootState {
  let state = transitionBootState(initialBootState(), { type: "shell-ready" });
  return transitionBootState(state, { type: "component-scan", componentState });
}

export function engineViewsEnabled(result: Pick<DesktopV2BootstrapResult, "bootState" | "engineReady">): boolean {
  return result.bootState === "engine-available" && result.engineReady;
}

export type AppRoute = "browser-editor" | "desktop-v2-shell";

export function resolveAppRoute(isTauriRuntime: boolean): AppRoute {
  return isTauriRuntime ? "desktop-v2-shell" : "browser-editor";
}

export function storagePathInvariantsHold(layout: StorageLayout = canonicalWindowsStorageLayout()): boolean {
  const pathEntries = Object.values(layout.paths);
  const shell = layout.paths.shellInstall;
  const machineComponentPaths = [layout.paths.sharedComponents, layout.paths.activationMetadata, layout.paths.downloadStaging];
  const userPaths = [layout.paths.userConfig, layout.paths.userCache, layout.paths.userLogs, layout.paths.userState];

  return layout.platform === "windows"
    && layout.programFilesRuntimeWritable === false
    && shell.runtimeWritable === false
    && shell.pathTemplate.startsWith("%ProgramFiles%\\")
    && machineComponentPaths.every(path => path.pathTemplate.startsWith("%ProgramData%\\") && !path.runtimeWritable)
    && userPaths.every(path => path.pathTemplate.startsWith("%LocalAppData%\\") && path.runtimeWritable)
    && pathEntries.length === 10;
}

export function redactDiagnosticText(input: string): string {
  let output = input.slice(0, 2048);
  output = output.replace(/((?:password|passwd|secret|token|api[_-]?key|authorization)\s*[:=]\s*)[^\s,;&]+/gi, "$1[REDACTED]");
  output = output.replace(/\bBearer\s+[^\s,;&]+/gi, "Bearer [REDACTED]");
  output = output.replace(/\b(?:sk|pk)-[A-Za-z0-9_-]{12,}\b/g, "[REDACTED_TOKEN]");
  output = output.replace(/\bghp_[A-Za-z0-9_-]{12,}\b/g, "[REDACTED_TOKEN]");
  return output;
}

export function normalizeShellFailure(_error: unknown): ShellBootstrapError {
  return {
    code: "SHELL_BOOTSTRAP_FAILED",
    message: "Desktop V2 could not finish its local readiness check. Open Diagnostics for technical details.",
    remediationCodes: ["STORAGE_NOT_WRITABLE" as RemediationCode],
  };
}
