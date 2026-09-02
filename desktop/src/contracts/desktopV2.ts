export const CONTRACT_VERSIONS = {
  componentManifest: "desktop.component-manifest.v1",
  engineControl: "desktop.engine-control.v1",
  healthReadiness: "desktop.health-readiness.v1",
  capabilities: "desktop.capabilities.v1",
  storageLayout: "desktop.storage-layout.v1",
  updateState: "desktop.update-state.v1",
} as const;

export const CAPABILITY_IDS = [
  "api",
  "database",
  "vector-store",
  "ffmpeg",
  "ai-model",
  "transcription",
  "rendering",
  "gpu",
  "native-import",
] as const;

export type CapabilityId = (typeof CAPABILITY_IDS)[number];
export type ComponentType =
  | "backend"
  | "database"
  | "vector-store"
  | "ffmpeg"
  | "model"
  | "renderer"
  | "utility";
export type ReleaseChannel = "stable" | "beta" | "nightly";
export type OperatingSystem = "windows" | "macos" | "linux";
export type Architecture = "x86" | "x86_64" | "aarch64";
export type RemediationCode =
  | "ENGINE_NOT_RUNNING"
  | "API_UNHEALTHY"
  | "DATABASE_UNAVAILABLE"
  | "VECTOR_STORE_UNAVAILABLE"
  | "FFMPEG_MISSING"
  | "MODEL_NOT_INSTALLED"
  | "MODEL_LOAD_FAILED"
  | "COMPONENT_VERSION_INCOMPATIBLE"
  | "PORT_ALLOCATION_FAILED"
  | "SESSION_AUTH_FAILED"
  | "STORAGE_NOT_WRITABLE"
  | "MIGRATION_REQUIRED"
  | "UPDATE_ROLLBACK_AVAILABLE"
  | "RESTART_REQUIRED"
  | "DISK_SPACE_LOW";

export interface ComponentManifest {
  schemaVersion: typeof CONTRACT_VERSIONS.componentManifest;
  component: ComponentIdentity;
  target: Target;
  requirements: Requirements;
  artifact: Artifact;
  signature: DetachedSignature;
  archive: Archive;
  install: InstallLayout;
  entrypoint: Entrypoint;
  dependencies: Dependency[];
  capabilities: CapabilityId[];
  metadata: ComponentMetadata;
  files: FileInventoryEntry[];
  selfTest: SelfTest;
  health: HealthContract;
  rollback: RollbackMetadata;
}

export interface ComponentIdentity {
  id: string;
  type: ComponentType;
  version: string;
  channel: ReleaseChannel;
}

export interface Target {
  operatingSystems: OperatingSystem[];
  architectures: Architecture[];
}

export interface Requirements {
  minimumShellVersion: string;
  requiresElevation?: boolean;
}

export interface Artifact {
  url: string;
  byteSize: number;
  sha256: string;
}

export interface DetachedSignature {
  algorithm: "ed25519";
  value: string;
  keyId: string;
}

export interface Archive {
  format: "zip" | "tar.gz";
  rootDirectory: string;
}

export interface InstallLayout {
  rootKind: "program-data-components";
  relativePath: string;
  immutable: true;
  activation: ActivationLayout;
}

export interface ActivationLayout {
  strategy: "stage-then-atomic-rename";
  activePath: string;
  stagingPath: string;
  metadataPath: string;
  atomicCommit: true;
}

export interface Entrypoint {
  kind: "executable" | "script";
  relativePath: string;
  arguments: string[];
  workingDirectory?: string;
}

export interface Dependency {
  id: string;
  versionConstraint: string;
  optional: boolean;
}

export interface ComponentMetadata {
  displayName: string;
  publisher: string;
  license: LicenseMetadata;
  source: SourceMetadata;
}

export interface LicenseMetadata {
  spdxId: string;
  noticeFile: string;
}

export interface SourceMetadata {
  repositoryUrl: string;
  releaseUrl: string;
}

export interface FileInventoryEntry {
  path: string;
  kind: "file" | "directory";
  byteSize: number;
  sha256: string;
  executable: boolean;
}

export interface SelfTest {
  command: string[];
  timeoutMs: number;
  expectedExitCode: 0;
}

export interface HealthContract {
  probe: "http";
  path: string;
  method: "GET";
  timeoutMs: number;
  readinessSchemaVersion: typeof CONTRACT_VERSIONS.healthReadiness;
  requiresBearerToken: true;
}

export interface RollbackMetadata {
  strategy: "retain-previous-active";
  retentionCount: number;
  metadataPath: string;
  onActivationFailure: "rollback-automatically" | "mark-failed";
}

export interface StoragePathDescriptor {
  pathTemplate: string;
  scope: "machine" | "user" | "user-selected";
  owner: "machine-installer" | "machine-update-service" | "user";
  writer: "installer" | "update-service" | "user-runtime";
  runtimeWritable: boolean;
  purpose: string;
}

export type StoragePathKey =
  | "shellInstall"
  | "sharedComponents"
  | "activationMetadata"
  | "downloadStaging"
  | "userConfig"
  | "userCache"
  | "userLogs"
  | "userState"
  | "projects"
  | "exports";

export interface StorageLayout {
  schemaVersion: typeof CONTRACT_VERSIONS.storageLayout;
  platform: "windows";
  programFilesRuntimeWritable: false;
  paths: Record<StoragePathKey, StoragePathDescriptor>;
}

export const CANONICAL_WINDOWS_PATHS: Record<StoragePathKey, string> = {
  shellInstall: "%ProgramFiles%\\AI Video Editor Desktop V2\\Shell",
  sharedComponents: "%ProgramData%\\AI Video Editor\\Components",
  activationMetadata: "%ProgramData%\\AI Video Editor\\Activation",
  downloadStaging: "%ProgramData%\\AI Video Editor\\Downloads\\Staging",
  userConfig: "%LocalAppData%\\AI Video Editor\\Config",
  userCache: "%LocalAppData%\\AI Video Editor\\Cache",
  userLogs: "%LocalAppData%\\AI Video Editor\\Logs",
  userState: "%LocalAppData%\\AI Video Editor\\State",
  projects: "%USERPROFILE%\\Documents\\AI Video Editor\\Projects",
  exports: "%USERPROFILE%\\Documents\\AI Video Editor\\Exports",
};

export function canonicalWindowsStorageLayout(): StorageLayout {
  return {
    schemaVersion: CONTRACT_VERSIONS.storageLayout,
    platform: "windows",
    programFilesRuntimeWritable: false,
    paths: {
      shellInstall: {
        pathTemplate: CANONICAL_WINDOWS_PATHS.shellInstall,
        scope: "machine",
        owner: "machine-installer",
        writer: "installer",
        runtimeWritable: false,
        purpose: "Versioned thin shell binaries and static resources.",
      },
      sharedComponents: {
        pathTemplate: CANONICAL_WINDOWS_PATHS.sharedComponents,
        scope: "machine",
        owner: "machine-update-service",
        writer: "update-service",
        runtimeWritable: false,
        purpose: "Verified immutable component versions selected by activation metadata.",
      },
      activationMetadata: {
        pathTemplate: CANONICAL_WINDOWS_PATHS.activationMetadata,
        scope: "machine",
        owner: "machine-update-service",
        writer: "update-service",
        runtimeWritable: false,
        purpose: "Atomic active-version pointers, update journals and rollback records.",
      },
      downloadStaging: {
        pathTemplate: CANONICAL_WINDOWS_PATHS.downloadStaging,
        scope: "machine",
        owner: "machine-update-service",
        writer: "update-service",
        runtimeWritable: false,
        purpose: "Resumable temporary downloads before digest, signature and inventory verification.",
      },
      userConfig: {
        pathTemplate: CANONICAL_WINDOWS_PATHS.userConfig,
        scope: "user",
        owner: "user",
        writer: "user-runtime",
        runtimeWritable: true,
        purpose: "Per-user settings and non-secret preferences.",
      },
      userCache: {
        pathTemplate: CANONICAL_WINDOWS_PATHS.userCache,
        scope: "user",
        owner: "user",
        writer: "user-runtime",
        runtimeWritable: true,
        purpose: "Rebuildable per-user caches and indexes.",
      },
      userLogs: {
        pathTemplate: CANONICAL_WINDOWS_PATHS.userLogs,
        scope: "user",
        owner: "user",
        writer: "user-runtime",
        runtimeWritable: true,
        purpose: "Redacted per-user shell and engine logs.",
      },
      userState: {
        pathTemplate: CANONICAL_WINDOWS_PATHS.userState,
        scope: "user",
        owner: "user",
        writer: "user-runtime",
        runtimeWritable: true,
        purpose: "Per-user resumable operation state and local metadata.",
      },
      projects: {
        pathTemplate: CANONICAL_WINDOWS_PATHS.projects,
        scope: "user-selected",
        owner: "user",
        writer: "user-runtime",
        runtimeWritable: true,
        purpose: "User projects under Documents by default or an explicitly selected folder.",
      },
      exports: {
        pathTemplate: CANONICAL_WINDOWS_PATHS.exports,
        scope: "user-selected",
        owner: "user",
        writer: "user-runtime",
        runtimeWritable: true,
        purpose: "User-selected export destination, Documents by default.",
      },
    },
  };
}

export interface EngineControlMessage {
  schemaVersion: typeof CONTRACT_VERSIONS.engineControl;
  messageType: "start" | "ready" | "shutdown" | "shutdown-ack";
  session: SessionIdentity;
  engine: EngineIdentity;
  process: ProcessIdentity;
  loopback: LoopbackAllocation;
  storagePaths: EngineStoragePaths;
  installedComponents: InstalledComponent[];
  requestedCapabilities: CapabilityId[];
  logPath: string;
  startupDeadlineMs: number;
  shutdownPolicy: ShutdownPolicy;
  shutdown?: ShutdownState;
  readiness?: ReadinessReference;
}

export interface SessionIdentity {
  sessionId: string;
  bearerToken: string;
}

export interface EngineIdentity {
  id: "aive-engine";
  version: string;
}

export interface ProcessIdentity {
  componentId: string;
  componentVersion: string;
  pid?: number;
  executablePath: string;
  entrypoint: string;
  arguments: string[];
  startedAt?: string;
}

export interface LoopbackAllocation {
  host: "127.0.0.1";
  allocation: "dynamic";
  requestedPort: 0;
  assignedPort?: number;
}

export interface EngineStoragePaths {
  layoutVersion: typeof CONTRACT_VERSIONS.storageLayout;
  shellInstallRoot: string;
  sharedComponentsRoot: string;
  activationMetadataRoot: string;
  downloadStagingRoot: string;
  userConfigRoot: string;
  userCacheRoot: string;
  userLogsRoot: string;
  userStateRoot: string;
  projectsRoot: string;
  exportsRoot: string;
  programFilesRuntimeWritable: false;
}

export interface InstalledComponent {
  id: string;
  version: string;
  path: string;
  active: boolean;
  capabilities: CapabilityId[];
}

export interface ShutdownPolicy {
  mode: "graceful";
  gracePeriodMs: number;
  escalation: "terminate" | "leave-running";
}

export interface ShutdownState {
  reason: string;
  requestedAt: string;
  status: "requested" | "completed" | "timed-out" | "rejected";
}

export interface ReadinessReference {
  schemaVersion: typeof CONTRACT_VERSIONS.healthReadiness;
  endpoint: string;
  overallState: HealthOverallState;
}

export type HealthOverallState = "starting" | "ready" | "degraded" | "fatal";
export type HealthCheckState = "healthy" | "ready" | "degraded" | "not-ready" | "not-configured" | "fatal";

export interface HealthReadinessPayload {
  schemaVersion: typeof CONTRACT_VERSIONS.healthReadiness;
  generatedAt: string;
  overallState: HealthOverallState;
  process: ProcessHealth;
  checks: HealthChecks;
  capabilities: HealthCapabilities;
  remediationCodes: RemediationCode[];
  fatalError?: FatalError;
}

export interface ProcessHealth {
  alive: boolean;
  pid: number;
  componentId: string;
  componentVersion: string;
}

export interface HealthChecks {
  api: HealthCheck;
  database: HealthCheck;
  vectorStore: HealthCheck;
  ffmpeg: HealthCheck;
  nativeImport: HealthCheck;
  aiModel?: HealthCheck;
}

export interface HealthCheck {
  state: HealthCheckState;
  required: boolean;
  detail: string;
  remediationCodes: RemediationCode[];
}

export interface HealthCapabilities {
  available: CapabilityId[];
  degraded: CapabilityId[];
  unavailable: CapabilityId[];
}

export interface FatalError {
  code: string;
  message: string;
  retryable: boolean;
}

export interface CapabilitiesPayload {
  schemaVersion: typeof CONTRACT_VERSIONS.capabilities;
  componentId: string;
  componentVersion: string;
  generatedAt: string;
  requested: CapabilityId[];
  items: CapabilityItem[];
}

export interface CapabilityItem {
  id: CapabilityId;
  state: "available" | "degraded" | "unavailable";
  source: "component" | "backend" | "model" | "host";
  version?: string;
  detail?: string;
  remediationCodes?: RemediationCode[];
}

export type UpdateStateName =
  | "idle"
  | "checking"
  | "downloading"
  | "paused"
  | "downloaded"
  | "verifying"
  | "staged"
  | "activating"
  | "active"
  | "interrupted"
  | "rolling-back"
  | "rolled-back"
  | "failed";

export interface UpdateState {
  schemaVersion: typeof CONTRACT_VERSIONS.updateState;
  operationId: string;
  componentId: string;
  targetVersion: string;
  channel: ReleaseChannel;
  state: UpdateStateName;
  download: DownloadState;
  activation: UpdateActivation;
  rollback: UpdateRollback;
  error?: UpdateError;
  updatedAt: string;
}

export interface DownloadState {
  url: string;
  expectedBytes: number;
  bytesDownloaded: number;
  sha256: string;
  tempPath: string;
  resumable: boolean;
  recovery: DownloadRecovery;
}

export interface DownloadRecovery {
  status: "none" | "resume-available" | "restart-required" | "discarded";
  resumeFromByte: number;
  lastVerifiedByte: number;
  etag?: string;
}

export interface UpdateActivation {
  strategy: "stage-then-atomic-rename";
  stagePath: string;
  activePath: string;
  metadataPath: string;
  currentVersion: string;
  targetVersion: string;
  checkpoint: "none" | "downloaded" | "verified" | "staged" | "active" | "rolled-back";
  atomicCommit: boolean;
}

export interface UpdateRollback {
  available: boolean;
  previousVersion?: string;
  previousPath?: string;
  automatic: boolean;
  attemptCount: number;
  maxAttempts: number;
  reason?: string;
}

export interface UpdateError {
  code: string;
  message: string;
  retryable: boolean;
}

type UnknownRecord = Record<string, unknown>;

export class ContractValidationError extends Error {
  readonly contract: string;
  readonly issues: string[];

  constructor(contract: string, issues: string[]) {
    super(`${contract} validation failed: ${issues.join("; ")}`);
    this.name = "ContractValidationError";
    this.contract = contract;
    this.issues = issues;
  }
}

const REMEDIATION_CODES: readonly RemediationCode[] = [
  "ENGINE_NOT_RUNNING",
  "API_UNHEALTHY",
  "DATABASE_UNAVAILABLE",
  "VECTOR_STORE_UNAVAILABLE",
  "FFMPEG_MISSING",
  "MODEL_NOT_INSTALLED",
  "MODEL_LOAD_FAILED",
  "COMPONENT_VERSION_INCOMPATIBLE",
  "PORT_ALLOCATION_FAILED",
  "SESSION_AUTH_FAILED",
  "STORAGE_NOT_WRITABLE",
  "MIGRATION_REQUIRED",
  "UPDATE_ROLLBACK_AVAILABLE",
  "RESTART_REQUIRED",
  "DISK_SPACE_LOW",
];
const COMPONENT_TYPES: readonly ComponentType[] = ["backend", "database", "vector-store", "ffmpeg", "model", "renderer", "utility"];
const RELEASE_CHANNELS: readonly ReleaseChannel[] = ["stable", "beta", "nightly"];
const OPERATING_SYSTEMS: readonly OperatingSystem[] = ["windows", "macos", "linux"];
const ARCHITECTURES: readonly Architecture[] = ["x86", "x86_64", "aarch64"];
const REMEDIATION_SET = new Set<string>(REMEDIATION_CODES);
const CAPABILITY_SET = new Set<string>(CAPABILITY_IDS);

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function fail(contract: string, issues: string[]): never {
  throw new ContractValidationError(contract, issues);
}

function checkObject(value: unknown, path: string, issues: string[]): UnknownRecord | undefined {
  if (!isRecord(value)) {
    issues.push(`${path} must be an object`);
    return undefined;
  }
  return value;
}

function checkKeys(value: UnknownRecord, allowed: readonly string[], path: string, issues: string[]): void {
  const allowedSet = new Set(allowed);
  for (const key of Object.keys(value)) {
    if (!allowedSet.has(key)) issues.push(`${path}.${key} is not allowed`);
  }
}

function checkString(value: unknown, path: string, issues: string[], minLength = 1): value is string {
  if (typeof value !== "string" || value.length < minLength) {
    issues.push(`${path} must be a string with at least ${minLength} character(s)`);
    return false;
  }
  return true;
}

function checkBoolean(value: unknown, path: string, issues: string[]): value is boolean {
  if (typeof value !== "boolean") {
    issues.push(`${path} must be a boolean`);
    return false;
  }
  return true;
}

function checkInteger(value: unknown, path: string, issues: string[], minimum = 0, maximum?: number): value is number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < minimum || (maximum !== undefined && value > maximum)) {
    const range = maximum === undefined ? `>= ${minimum}` : `${minimum}..${maximum}`;
    issues.push(`${path} must be an integer in ${range}`);
    return false;
  }
  return true;
}

function checkArray(value: unknown, path: string, issues: string[], minLength = 0): value is unknown[] {
  if (!Array.isArray(value) || value.length < minLength) {
    issues.push(`${path} must be an array with at least ${minLength} item(s)`);
    return false;
  }
  return true;
}

function checkEnum(value: unknown, allowed: readonly string[], path: string, issues: string[]): boolean {
  if (typeof value !== "string" || !allowed.includes(value)) {
    issues.push(`${path} must be one of ${allowed.join(", ")}`);
    return false;
  }
  return true;
}

function checkConst(value: unknown, expected: string | number | boolean, path: string, issues: string[]): boolean {
  if (value !== expected) {
    issues.push(`${path} must equal ${String(expected)}`);
    return false;
  }
  return true;
}

function checkUnique(values: unknown[], path: string, issues: string[]): void {
  const serialized = values.map((value) => JSON.stringify(value));
  if (new Set(serialized).size !== serialized.length) issues.push(`${path} must not contain duplicate items`);
}

function checkSemver(value: unknown, path: string, issues: string[]): value is string {
  if (!checkString(value, path, issues)) return false;
  if (!/^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/.test(value)) {
    issues.push(`${path} must be a semantic version`);
    return false;
  }
  return true;
}

function checkVersionConstraint(value: unknown, path: string, issues: string[]): void {
  if (!checkString(value, path, issues)) return;
  if (!/^(?:\*|(?:[<>=~^]*[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?)(?:\s+(?:[<>=~^]*[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?))*)$/.test(value)) {
    issues.push(`${path} must be a supported version constraint`);
  }
}

function checkId(value: unknown, path: string, issues: string[]): void {
  if (!checkString(value, path, issues)) return;
  if (!/^[a-z0-9][a-z0-9._-]{1,63}$/.test(value)) issues.push(`${path} must be a lowercase component identifier`);
}

function checkSha256(value: unknown, path: string, issues: string[]): void {
  if (!checkString(value, path, issues)) return;
  if (!/^[a-f0-9]{64}$/.test(value)) issues.push(`${path} must be 64 lowercase hexadecimal characters`);
}

function checkHttpsUrl(value: unknown, path: string, issues: string[]): void {
  if (!checkString(value, path, issues)) return;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:") issues.push(`${path} must use https`);
  } catch {
    issues.push(`${path} must be a valid URL`);
  }
}

function checkDateTime(value: unknown, path: string, issues: string[]): void {
  if (!checkString(value, path, issues)) return;
  if (Number.isNaN(Date.parse(value)) || !value.includes("T")) issues.push(`${path} must be an ISO date-time`);
}

function checkSafeRelativePath(value: unknown, path: string, issues: string[]): void {
  if (!checkString(value, path, issues)) return;
  const parts = value.split(/[\\/]/);
  if (value.startsWith("/") || value.startsWith("\\") || /^[A-Za-z]:/.test(value) || parts.includes("..") || value.includes("//") || value.includes("\\\\") || /[<>:\"|?*\u0000-\u001f]/.test(value)) {
    issues.push(`${path} must be a safe relative path`);
  }
}

function checkAbsolutePath(value: unknown, path: string, issues: string[]): void {
  if (!checkString(value, path, issues)) return;
  if (/^%ProgramFiles%/i.test(value) || /[\\/]Program Files[\\/]/i.test(value)) {
    issues.push(`${path} must not place a runtime-writable component under Program Files`);
  }
}

function checkPath(value: unknown, path: string, issues: string[]): void {
  checkString(value, path, issues);
}

function checkCapabilityArray(value: unknown, path: string, issues: string[], minLength = 0): void {
  if (!checkArray(value, path, issues, minLength)) return;
  checkUnique(value, path, issues);
  value.forEach((item, index) => {
    if (typeof item !== "string" || !CAPABILITY_SET.has(item)) issues.push(`${path}[${index}] is not a supported capability`);
  });
}

function checkRemediationCodes(value: unknown, path: string, issues: string[]): void {
  if (!checkArray(value, path, issues)) return;
  checkUnique(value, path, issues);
  value.forEach((item, index) => {
    if (typeof item !== "string" || !REMEDIATION_SET.has(item)) issues.push(`${path}[${index}] is not a supported remediation code`);
  });
}

function requireObject(parent: UnknownRecord, key: string, path: string, issues: string[]): UnknownRecord | undefined {
  if (!(key in parent)) {
    issues.push(`${path}.${key} is required`);
    return undefined;
  }
  return checkObject(parent[key], `${path}.${key}`, issues);
}

function validateComponentManifestShape(input: unknown, issues: string[]): void {
  const root = checkObject(input, "manifest", issues);
  if (!root) return;
  checkKeys(root, ["schemaVersion", "component", "target", "requirements", "artifact", "signature", "archive", "install", "entrypoint", "dependencies", "capabilities", "metadata", "files", "selfTest", "health", "rollback"], "manifest", issues);
  checkConst(root.schemaVersion, CONTRACT_VERSIONS.componentManifest, "manifest.schemaVersion", issues);

  const component = requireObject(root, "component", "manifest", issues);
  if (component) {
    checkKeys(component, ["id", "type", "version", "channel"], "manifest.component", issues);
    checkId(component.id, "manifest.component.id", issues);
    checkEnum(component.type, COMPONENT_TYPES, "manifest.component.type", issues);
    checkSemver(component.version, "manifest.component.version", issues);
    checkEnum(component.channel, RELEASE_CHANNELS, "manifest.component.channel", issues);
  }

  const target = requireObject(root, "target", "manifest", issues);
  if (target) {
    checkKeys(target, ["operatingSystems", "architectures"], "manifest.target", issues);
    if (checkArray(target.operatingSystems, "manifest.target.operatingSystems", issues, 1)) {
      checkUnique(target.operatingSystems, "manifest.target.operatingSystems", issues);
      target.operatingSystems.forEach((value, index) => checkEnum(value, OPERATING_SYSTEMS, `manifest.target.operatingSystems[${index}]`, issues));
    }
    if (checkArray(target.architectures, "manifest.target.architectures", issues, 1)) {
      checkUnique(target.architectures, "manifest.target.architectures", issues);
      target.architectures.forEach((value, index) => checkEnum(value, ARCHITECTURES, `manifest.target.architectures[${index}]`, issues));
    }
  }

  const requirements = requireObject(root, "requirements", "manifest", issues);
  if (requirements) {
    checkKeys(requirements, ["minimumShellVersion", "requiresElevation"], "manifest.requirements", issues);
    checkSemver(requirements.minimumShellVersion, "manifest.requirements.minimumShellVersion", issues);
    if ("requiresElevation" in requirements) checkBoolean(requirements.requiresElevation, "manifest.requirements.requiresElevation", issues);
  }

  const artifact = requireObject(root, "artifact", "manifest", issues);
  if (artifact) {
    checkKeys(artifact, ["url", "byteSize", "sha256"], "manifest.artifact", issues);
    checkHttpsUrl(artifact.url, "manifest.artifact.url", issues);
    checkInteger(artifact.byteSize, "manifest.artifact.byteSize", issues, 1);
    checkSha256(artifact.sha256, "manifest.artifact.sha256", issues);
  }

  const signature = requireObject(root, "signature", "manifest", issues);
  if (signature) {
    checkKeys(signature, ["algorithm", "value", "keyId"], "manifest.signature", issues);
    checkConst(signature.algorithm, "ed25519", "manifest.signature.algorithm", issues);
    if (checkString(signature.value, "manifest.signature.value", issues) && !/^[A-Za-z0-9+/]+={0,2}$/.test(signature.value)) issues.push("manifest.signature.value must be base64");
    if (checkString(signature.keyId, "manifest.signature.keyId", issues) && !/^[a-z0-9][a-z0-9._-]{2,63}$/.test(signature.keyId)) issues.push("manifest.signature.keyId is invalid");
  }

  const archive = requireObject(root, "archive", "manifest", issues);
  if (archive) {
    checkKeys(archive, ["format", "rootDirectory"], "manifest.archive", issues);
    checkEnum(archive.format, ["zip", "tar.gz"], "manifest.archive.format", issues);
    checkSafeRelativePath(archive.rootDirectory, "manifest.archive.rootDirectory", issues);
  }

  const install = requireObject(root, "install", "manifest", issues);
  if (install) {
    checkKeys(install, ["rootKind", "relativePath", "immutable", "activation"], "manifest.install", issues);
    checkConst(install.rootKind, "program-data-components", "manifest.install.rootKind", issues);
    checkSafeRelativePath(install.relativePath, "manifest.install.relativePath", issues);
    checkConst(install.immutable, true, "manifest.install.immutable", issues);
    const activation = requireObject(install, "activation", "manifest.install", issues);
    if (activation) {
      checkKeys(activation, ["strategy", "activePath", "stagingPath", "metadataPath", "atomicCommit"], "manifest.install.activation", issues);
      checkConst(activation.strategy, "stage-then-atomic-rename", "manifest.install.activation.strategy", issues);
      checkSafeRelativePath(activation.activePath, "manifest.install.activation.activePath", issues);
      checkSafeRelativePath(activation.stagingPath, "manifest.install.activation.stagingPath", issues);
      checkSafeRelativePath(activation.metadataPath, "manifest.install.activation.metadataPath", issues);
      checkConst(activation.atomicCommit, true, "manifest.install.activation.atomicCommit", issues);
    }
  }

  const entrypoint = requireObject(root, "entrypoint", "manifest", issues);
  if (entrypoint) {
    checkKeys(entrypoint, ["kind", "relativePath", "arguments", "workingDirectory"], "manifest.entrypoint", issues);
    checkEnum(entrypoint.kind, ["executable", "script"], "manifest.entrypoint.kind", issues);
    checkSafeRelativePath(entrypoint.relativePath, "manifest.entrypoint.relativePath", issues);
    if (checkArray(entrypoint.arguments, "manifest.entrypoint.arguments", issues)) entrypoint.arguments.forEach((value, index) => checkString(value, `manifest.entrypoint.arguments[${index}]`, issues, 0));
    if ("workingDirectory" in entrypoint) checkSafeRelativePath(entrypoint.workingDirectory, "manifest.entrypoint.workingDirectory", issues);
  }

  if (checkArray(root.dependencies, "manifest.dependencies", issues)) {
    checkUnique(root.dependencies, "manifest.dependencies", issues);
    root.dependencies.forEach((value, index) => {
      const dependency = checkObject(value, `manifest.dependencies[${index}]`, issues);
      if (!dependency) return;
      checkKeys(dependency, ["id", "versionConstraint", "optional"], `manifest.dependencies[${index}]`, issues);
      checkId(dependency.id, `manifest.dependencies[${index}].id`, issues);
      checkVersionConstraint(dependency.versionConstraint, `manifest.dependencies[${index}].versionConstraint`, issues);
      checkBoolean(dependency.optional, `manifest.dependencies[${index}].optional`, issues);
    });
  }

  checkCapabilityArray(root.capabilities, "manifest.capabilities", issues, 1);

  const metadata = requireObject(root, "metadata", "manifest", issues);
  if (metadata) {
    checkKeys(metadata, ["displayName", "publisher", "license", "source"], "manifest.metadata", issues);
    checkString(metadata.displayName, "manifest.metadata.displayName", issues);
    checkString(metadata.publisher, "manifest.metadata.publisher", issues);
    const license = requireObject(metadata, "license", "manifest.metadata", issues);
    if (license) {
      checkKeys(license, ["spdxId", "noticeFile"], "manifest.metadata.license", issues);
      checkString(license.spdxId, "manifest.metadata.license.spdxId", issues);
      checkSafeRelativePath(license.noticeFile, "manifest.metadata.license.noticeFile", issues);
    }
    const source = requireObject(metadata, "source", "manifest.metadata", issues);
    if (source) {
      checkKeys(source, ["repositoryUrl", "releaseUrl"], "manifest.metadata.source", issues);
      checkHttpsUrl(source.repositoryUrl, "manifest.metadata.source.repositoryUrl", issues);
      checkHttpsUrl(source.releaseUrl, "manifest.metadata.source.releaseUrl", issues);
    }
  }

  if (checkArray(root.files, "manifest.files", issues, 1)) {
    root.files.forEach((value, index) => {
      const file = checkObject(value, `manifest.files[${index}]`, issues);
      if (!file) return;
      checkKeys(file, ["path", "kind", "byteSize", "sha256", "executable"], `manifest.files[${index}]`, issues);
      checkSafeRelativePath(file.path, `manifest.files[${index}].path`, issues);
      checkEnum(file.kind, ["file", "directory"], `manifest.files[${index}].kind`, issues);
      checkInteger(file.byteSize, `manifest.files[${index}].byteSize`, issues, 0);
      checkSha256(file.sha256, `manifest.files[${index}].sha256`, issues);
      checkBoolean(file.executable, `manifest.files[${index}].executable`, issues);
    });
  }

  const selfTest = requireObject(root, "selfTest", "manifest", issues);
  if (selfTest) {
    checkKeys(selfTest, ["command", "timeoutMs", "expectedExitCode"], "manifest.selfTest", issues);
    if (checkArray(selfTest.command, "manifest.selfTest.command", issues, 1)) selfTest.command.forEach((value, index) => checkString(value, `manifest.selfTest.command[${index}]`, issues));
    checkInteger(selfTest.timeoutMs, "manifest.selfTest.timeoutMs", issues, 1000, 600000);
    checkConst(selfTest.expectedExitCode, 0, "manifest.selfTest.expectedExitCode", issues);
  }

  const health = requireObject(root, "health", "manifest", issues);
  if (health) {
    checkKeys(health, ["probe", "path", "method", "timeoutMs", "readinessSchemaVersion", "requiresBearerToken"], "manifest.health", issues);
    checkConst(health.probe, "http", "manifest.health.probe", issues);
    if (checkString(health.path, "manifest.health.path", issues) && !health.path.startsWith("/")) issues.push("manifest.health.path must start with '/'");
    checkConst(health.method, "GET", "manifest.health.method", issues);
    checkInteger(health.timeoutMs, "manifest.health.timeoutMs", issues, 100, 60000);
    checkConst(health.readinessSchemaVersion, CONTRACT_VERSIONS.healthReadiness, "manifest.health.readinessSchemaVersion", issues);
    checkConst(health.requiresBearerToken, true, "manifest.health.requiresBearerToken", issues);
  }

  const rollback = requireObject(root, "rollback", "manifest", issues);
  if (rollback) {
    checkKeys(rollback, ["strategy", "retentionCount", "metadataPath", "onActivationFailure"], "manifest.rollback", issues);
    checkConst(rollback.strategy, "retain-previous-active", "manifest.rollback.strategy", issues);
    checkInteger(rollback.retentionCount, "manifest.rollback.retentionCount", issues, 1, 5);
    checkSafeRelativePath(rollback.metadataPath, "manifest.rollback.metadataPath", issues);
    checkEnum(rollback.onActivationFailure, ["rollback-automatically", "mark-failed"], "manifest.rollback.onActivationFailure", issues);
  }
}

export function validateComponentManifest(input: unknown): ComponentManifest {
  const issues: string[] = [];
  validateComponentManifestShape(input, issues);
  if (issues.length > 0) fail(CONTRACT_VERSIONS.componentManifest, issues);
  return input as ComponentManifest;
}

function validateStoragePathDescriptor(value: unknown, path: string, issues: string[]): void {
  const descriptor = checkObject(value, path, issues);
  if (!descriptor) return;
  checkKeys(descriptor, ["pathTemplate", "scope", "owner", "writer", "runtimeWritable", "purpose"], path, issues);
  checkString(descriptor.pathTemplate, `${path}.pathTemplate`, issues);
  checkEnum(descriptor.scope, ["machine", "user", "user-selected"], `${path}.scope`, issues);
  checkEnum(descriptor.owner, ["machine-installer", "machine-update-service", "user"], `${path}.owner`, issues);
  checkEnum(descriptor.writer, ["installer", "update-service", "user-runtime"], `${path}.writer`, issues);
  checkBoolean(descriptor.runtimeWritable, `${path}.runtimeWritable`, issues);
  checkString(descriptor.purpose, `${path}.purpose`, issues);
}

export function validateStorageLayout(input: unknown): StorageLayout {
  const issues: string[] = [];
  const root = checkObject(input, "storage", issues);
  if (root) {
    checkKeys(root, ["schemaVersion", "platform", "programFilesRuntimeWritable", "paths"], "storage", issues);
    checkConst(root.schemaVersion, CONTRACT_VERSIONS.storageLayout, "storage.schemaVersion", issues);
    checkConst(root.platform, "windows", "storage.platform", issues);
    checkConst(root.programFilesRuntimeWritable, false, "storage.programFilesRuntimeWritable", issues);
    const paths = requireObject(root, "paths", "storage", issues);
    if (paths) {
      const keys = Object.keys(CANONICAL_WINDOWS_PATHS);
      checkKeys(paths, keys, "storage.paths", issues);
      for (const key of keys) validateStoragePathDescriptor(paths[key], `storage.paths.${key}`, issues);
      const shell = checkObject(paths.shellInstall, "storage.paths.shellInstall", issues);
      if (shell) {
        checkConst(shell.pathTemplate, CANONICAL_WINDOWS_PATHS.shellInstall, "storage.paths.shellInstall.pathTemplate", issues);
        checkConst(shell.runtimeWritable, false, "storage.paths.shellInstall.runtimeWritable", issues);
        checkConst(shell.scope, "machine", "storage.paths.shellInstall.scope", issues);
        checkConst(shell.owner, "machine-installer", "storage.paths.shellInstall.owner", issues);
        checkConst(shell.writer, "installer", "storage.paths.shellInstall.writer", issues);
      }
      for (const key of ["sharedComponents", "activationMetadata", "downloadStaging"] as const) {
        const machinePath = checkObject(paths[key], `storage.paths.${key}`, issues);
        if (machinePath) {
          checkConst(machinePath.runtimeWritable, false, `storage.paths.${key}.runtimeWritable`, issues);
          checkConst(machinePath.scope, "machine", `storage.paths.${key}.scope`, issues);
          checkConst(machinePath.owner, "machine-update-service", `storage.paths.${key}.owner`, issues);
          checkConst(machinePath.writer, "update-service", `storage.paths.${key}.writer`, issues);
          checkConst(machinePath.pathTemplate, CANONICAL_WINDOWS_PATHS[key], `storage.paths.${key}.pathTemplate`, issues);
        }
      }
      for (const key of ["userConfig", "userCache", "userLogs", "userState"] as const) {
        const userPath = checkObject(paths[key], `storage.paths.${key}`, issues);
        if (userPath) {
          checkConst(userPath.runtimeWritable, true, `storage.paths.${key}.runtimeWritable`, issues);
          checkConst(userPath.scope, "user", `storage.paths.${key}.scope`, issues);
          checkConst(userPath.owner, "user", `storage.paths.${key}.owner`, issues);
          checkConst(userPath.writer, "user-runtime", `storage.paths.${key}.writer`, issues);
          checkConst(userPath.pathTemplate, CANONICAL_WINDOWS_PATHS[key], `storage.paths.${key}.pathTemplate`, issues);
        }
      }
      for (const key of ["projects", "exports"] as const) {
        const userPath = checkObject(paths[key], `storage.paths.${key}`, issues);
        if (userPath) {
          checkConst(userPath.runtimeWritable, true, `storage.paths.${key}.runtimeWritable`, issues);
          checkConst(userPath.scope, "user-selected", `storage.paths.${key}.scope`, issues);
          checkConst(userPath.owner, "user", `storage.paths.${key}.owner`, issues);
          checkConst(userPath.writer, "user-runtime", `storage.paths.${key}.writer`, issues);
          checkConst(userPath.pathTemplate, CANONICAL_WINDOWS_PATHS[key], `storage.paths.${key}.pathTemplate`, issues);
        }
      }
    }
  }
  if (issues.length > 0) fail(CONTRACT_VERSIONS.storageLayout, issues);
  return input as StorageLayout;
}

function validateCheck(value: unknown, path: string, issues: string[]): void {
  const check = checkObject(value, path, issues);
  if (!check) return;
  checkKeys(check, ["state", "required", "detail", "remediationCodes"], path, issues);
  checkEnum(check.state, ["healthy", "ready", "degraded", "not-ready", "not-configured", "fatal"], `${path}.state`, issues);
  checkBoolean(check.required, `${path}.required`, issues);
  checkString(check.detail, `${path}.detail`, issues, 0);
  checkRemediationCodes(check.remediationCodes, `${path}.remediationCodes`, issues);
}

export function validateHealthReadiness(input: unknown): HealthReadinessPayload {
  const issues: string[] = [];
  const root = checkObject(input, "health", issues);
  if (root) {
    checkKeys(root, ["schemaVersion", "generatedAt", "overallState", "process", "checks", "capabilities", "remediationCodes", "fatalError"], "health", issues);
    checkConst(root.schemaVersion, CONTRACT_VERSIONS.healthReadiness, "health.schemaVersion", issues);
    checkDateTime(root.generatedAt, "health.generatedAt", issues);
    checkEnum(root.overallState, ["starting", "ready", "degraded", "fatal"], "health.overallState", issues);
    const process = requireObject(root, "process", "health", issues);
    if (process) {
      checkKeys(process, ["alive", "pid", "componentId", "componentVersion"], "health.process", issues);
      checkBoolean(process.alive, "health.process.alive", issues);
      checkInteger(process.pid, "health.process.pid", issues, 1);
      checkString(process.componentId, "health.process.componentId", issues);
      checkSemver(process.componentVersion, "health.process.componentVersion", issues);
    }
    const checks = requireObject(root, "checks", "health", issues);
    if (checks) {
      checkKeys(checks, ["api", "database", "vectorStore", "ffmpeg", "nativeImport", "aiModel"], "health.checks", issues);
      validateCheck(checks.api, "health.checks.api", issues);
      validateCheck(checks.database, "health.checks.database", issues);
      validateCheck(checks.vectorStore, "health.checks.vectorStore", issues);
      validateCheck(checks.ffmpeg, "health.checks.ffmpeg", issues);
      validateCheck(checks.nativeImport, "health.checks.nativeImport", issues);
      if ("aiModel" in checks) validateCheck(checks.aiModel, "health.checks.aiModel", issues);
    }
    const capabilities = requireObject(root, "capabilities", "health", issues);
    if (capabilities) {
      checkKeys(capabilities, ["available", "degraded", "unavailable"], "health.capabilities", issues);
      checkCapabilityArray(capabilities.available, "health.capabilities.available", issues);
      checkCapabilityArray(capabilities.degraded, "health.capabilities.degraded", issues);
      checkCapabilityArray(capabilities.unavailable, "health.capabilities.unavailable", issues);
      const groups = [capabilities.available, capabilities.degraded, capabilities.unavailable].filter(Array.isArray).flat();
      if (new Set(groups).size !== groups.length) issues.push("health.capabilities groups must not overlap");
    }
    checkRemediationCodes(root.remediationCodes, "health.remediationCodes", issues);
    if ("fatalError" in root) {
      const fatalError = checkObject(root.fatalError, "health.fatalError", issues);
      if (fatalError) {
        checkKeys(fatalError, ["code", "message", "retryable"], "health.fatalError", issues);
        if (checkString(fatalError.code, "health.fatalError.code", issues) && !/^[A-Z0-9_]{3,64}$/.test(fatalError.code)) issues.push("health.fatalError.code is invalid");
        checkString(fatalError.message, "health.fatalError.message", issues);
        checkBoolean(fatalError.retryable, "health.fatalError.retryable", issues);
      }
    }
    if (root.overallState === "fatal" && !("fatalError" in root)) issues.push("health.fatalError is required for fatal state");
    if (root.overallState === "ready" && isRecord(root.process) && root.process.alive !== true) issues.push("health.process.alive must be true for ready state");
  }
  if (issues.length > 0) fail(CONTRACT_VERSIONS.healthReadiness, issues);
  return input as HealthReadinessPayload;
}

export function validateCapabilities(input: unknown): CapabilitiesPayload {
  const issues: string[] = [];
  const root = checkObject(input, "capabilities", issues);
  if (root) {
    checkKeys(root, ["schemaVersion", "componentId", "componentVersion", "generatedAt", "requested", "items"], "capabilities", issues);
    checkConst(root.schemaVersion, CONTRACT_VERSIONS.capabilities, "capabilities.schemaVersion", issues);
    checkId(root.componentId, "capabilities.componentId", issues);
    checkSemver(root.componentVersion, "capabilities.componentVersion", issues);
    checkDateTime(root.generatedAt, "capabilities.generatedAt", issues);
    checkCapabilityArray(root.requested, "capabilities.requested", issues);
    if (checkArray(root.items, "capabilities.items", issues)) {
      checkUnique(root.items, "capabilities.items", issues);
      const ids: string[] = [];
      root.items.forEach((value, index) => {
        const item = checkObject(value, `capabilities.items[${index}]`, issues);
        if (!item) return;
        checkKeys(item, ["id", "state", "source", "version", "detail", "remediationCodes"], `capabilities.items[${index}]`, issues);
        if (typeof item.id === "string") ids.push(item.id);
        checkEnum(item.id, CAPABILITY_IDS, `capabilities.items[${index}].id`, issues);
        checkEnum(item.state, ["available", "degraded", "unavailable"], `capabilities.items[${index}].state`, issues);
        checkEnum(item.source, ["component", "backend", "model", "host"], `capabilities.items[${index}].source`, issues);
        if ("version" in item) checkSemver(item.version, `capabilities.items[${index}].version`, issues);
        if ("detail" in item) checkString(item.detail, `capabilities.items[${index}].detail`, issues, 0);
        if ("remediationCodes" in item) checkRemediationCodes(item.remediationCodes, `capabilities.items[${index}].remediationCodes`, issues);
      });
      if (new Set(ids).size !== ids.length) issues.push("capabilities.items must contain one item per capability id");
    }
  }
  if (issues.length > 0) fail(CONTRACT_VERSIONS.capabilities, issues);
  return input as CapabilitiesPayload;
}

function validateEngineStoragePaths(value: unknown, path: string, issues: string[]): void {
  const storage = checkObject(value, path, issues);
  if (!storage) return;
  const keys = ["layoutVersion", "shellInstallRoot", "sharedComponentsRoot", "activationMetadataRoot", "downloadStagingRoot", "userConfigRoot", "userCacheRoot", "userLogsRoot", "userStateRoot", "projectsRoot", "exportsRoot", "programFilesRuntimeWritable"] as const;
  checkKeys(storage, keys, path, issues);
  checkConst(storage.layoutVersion, CONTRACT_VERSIONS.storageLayout, `${path}.layoutVersion`, issues);
  for (const key of keys) {
    if (key === "shellInstallRoot") checkPath(storage[key], `${path}.${key}`, issues);
    if (key !== "layoutVersion" && key !== "programFilesRuntimeWritable" && key !== "shellInstallRoot") checkAbsolutePath(storage[key], `${path}.${key}`, issues);
  }
  checkConst(storage.programFilesRuntimeWritable, false, `${path}.programFilesRuntimeWritable`, issues);
}

export function validateEngineControl(input: unknown): EngineControlMessage {
  const issues: string[] = [];
  const root = checkObject(input, "engineControl", issues);
  if (root) {
    checkKeys(root, ["schemaVersion", "messageType", "session", "engine", "process", "loopback", "storagePaths", "installedComponents", "requestedCapabilities", "logPath", "startupDeadlineMs", "shutdownPolicy", "shutdown", "readiness"], "engineControl", issues);
    checkConst(root.schemaVersion, CONTRACT_VERSIONS.engineControl, "engineControl.schemaVersion", issues);
    checkEnum(root.messageType, ["start", "ready", "shutdown", "shutdown-ack"], "engineControl.messageType", issues);

    const session = requireObject(root, "session", "engineControl", issues);
    if (session) {
      checkKeys(session, ["sessionId", "bearerToken"], "engineControl.session", issues);
      if (checkString(session.sessionId, "engineControl.session.sessionId", issues) && !/^[A-Za-z0-9_-]{8,64}$/.test(session.sessionId)) issues.push("engineControl.session.sessionId is invalid");
      if (checkString(session.bearerToken, "engineControl.session.bearerToken", issues) && !/^[A-Za-z0-9._~-]{32,256}$/.test(session.bearerToken)) issues.push("engineControl.session.bearerToken must be an opaque bearer token");
    }

    const engine = requireObject(root, "engine", "engineControl", issues);
    if (engine) {
      checkKeys(engine, ["id", "version"], "engineControl.engine", issues);
      checkConst(engine.id, "aive-engine", "engineControl.engine.id", issues);
      checkSemver(engine.version, "engineControl.engine.version", issues);
    }

    const process = requireObject(root, "process", "engineControl", issues);
    if (process) {
      checkKeys(process, ["componentId", "componentVersion", "pid", "executablePath", "entrypoint", "arguments", "startedAt"], "engineControl.process", issues);
      checkString(process.componentId, "engineControl.process.componentId", issues);
      checkSemver(process.componentVersion, "engineControl.process.componentVersion", issues);
      if ("pid" in process) checkInteger(process.pid, "engineControl.process.pid", issues, 1);
      checkAbsolutePath(process.executablePath, "engineControl.process.executablePath", issues);
      checkString(process.entrypoint, "engineControl.process.entrypoint", issues);
      if (checkArray(process.arguments, "engineControl.process.arguments", issues)) process.arguments.forEach((value, index) => checkString(value, `engineControl.process.arguments[${index}]`, issues, 0));
      if ("startedAt" in process) checkDateTime(process.startedAt, "engineControl.process.startedAt", issues);
    }

    const loopback = requireObject(root, "loopback", "engineControl", issues);
    if (loopback) {
      checkKeys(loopback, ["host", "allocation", "requestedPort", "assignedPort"], "engineControl.loopback", issues);
      checkConst(loopback.host, "127.0.0.1", "engineControl.loopback.host", issues);
      checkConst(loopback.allocation, "dynamic", "engineControl.loopback.allocation", issues);
      checkConst(loopback.requestedPort, 0, "engineControl.loopback.requestedPort", issues);
      if ("assignedPort" in loopback) checkInteger(loopback.assignedPort, "engineControl.loopback.assignedPort", issues, 1, 65535);
    }

    validateEngineStoragePaths(root.storagePaths, "engineControl.storagePaths", issues);
    if (checkArray(root.installedComponents, "engineControl.installedComponents", issues, 1)) {
      root.installedComponents.forEach((value, index) => {
        const component = checkObject(value, `engineControl.installedComponents[${index}]`, issues);
        if (!component) return;
        checkKeys(component, ["id", "version", "path", "active", "capabilities"], `engineControl.installedComponents[${index}]`, issues);
        checkString(component.id, `engineControl.installedComponents[${index}].id`, issues);
        checkSemver(component.version, `engineControl.installedComponents[${index}].version`, issues);
        checkAbsolutePath(component.path, `engineControl.installedComponents[${index}].path`, issues);
        checkBoolean(component.active, `engineControl.installedComponents[${index}].active`, issues);
        checkCapabilityArray(component.capabilities, `engineControl.installedComponents[${index}].capabilities`, issues);
      });
    }
    checkCapabilityArray(root.requestedCapabilities, "engineControl.requestedCapabilities", issues);
    checkAbsolutePath(root.logPath, "engineControl.logPath", issues);
    checkInteger(root.startupDeadlineMs, "engineControl.startupDeadlineMs", issues, 1000, 600000);
    const policy = requireObject(root, "shutdownPolicy", "engineControl", issues);
    if (policy) {
      checkKeys(policy, ["mode", "gracePeriodMs", "escalation"], "engineControl.shutdownPolicy", issues);
      checkConst(policy.mode, "graceful", "engineControl.shutdownPolicy.mode", issues);
      checkInteger(policy.gracePeriodMs, "engineControl.shutdownPolicy.gracePeriodMs", issues, 100, 120000);
      checkEnum(policy.escalation, ["terminate", "leave-running"], "engineControl.shutdownPolicy.escalation", issues);
    }
    if ("shutdown" in root) {
      const shutdown = checkObject(root.shutdown, "engineControl.shutdown", issues);
      if (shutdown) {
        checkKeys(shutdown, ["reason", "requestedAt", "status"], "engineControl.shutdown", issues);
        checkString(shutdown.reason, "engineControl.shutdown.reason", issues);
        checkDateTime(shutdown.requestedAt, "engineControl.shutdown.requestedAt", issues);
        checkEnum(shutdown.status, ["requested", "completed", "timed-out", "rejected"], "engineControl.shutdown.status", issues);
      }
    }
    if ("readiness" in root) {
      const readiness = checkObject(root.readiness, "engineControl.readiness", issues);
      if (readiness) {
        checkKeys(readiness, ["schemaVersion", "endpoint", "overallState"], "engineControl.readiness", issues);
        checkConst(readiness.schemaVersion, CONTRACT_VERSIONS.healthReadiness, "engineControl.readiness.schemaVersion", issues);
        if (checkString(readiness.endpoint, "engineControl.readiness.endpoint", issues) && !readiness.endpoint.startsWith("/")) issues.push("engineControl.readiness.endpoint must start with '/'");
        checkEnum(readiness.overallState, ["starting", "ready", "degraded", "fatal"], "engineControl.readiness.overallState", issues);
      }
    }
    if (root.messageType === "start") {
      if ("shutdown" in root) issues.push("engineControl.shutdown is not allowed on a start message");
      if (isRecord(root.loopback) && "assignedPort" in root.loopback) issues.push("start messages must request a dynamic port before assignment");
    }
    if (root.messageType === "ready") {
      if (!isRecord(root.readiness)) issues.push("ready messages require readiness");
      if (isRecord(root.process) && !("pid" in root.process)) issues.push("ready messages require process.pid");
      if (isRecord(root.loopback) && !("assignedPort" in root.loopback)) issues.push("ready messages require loopback.assignedPort");
    }
    if ((root.messageType === "shutdown" || root.messageType === "shutdown-ack") && !isRecord(root.shutdown)) issues.push(`${String(root.messageType)} messages require shutdown state`);
  }
  if (issues.length > 0) fail(CONTRACT_VERSIONS.engineControl, issues);
  return input as EngineControlMessage;
}

function validateUpdateError(value: unknown, path: string, issues: string[]): void {
  const error = checkObject(value, path, issues);
  if (!error) return;
  checkKeys(error, ["code", "message", "retryable"], path, issues);
  if (checkString(error.code, `${path}.code`, issues) && !/^[A-Z0-9_]{3,64}$/.test(error.code)) issues.push(`${path}.code is invalid`);
  checkString(error.message, `${path}.message`, issues);
  checkBoolean(error.retryable, `${path}.retryable`, issues);
}

export function validateUpdateState(input: unknown): UpdateState {
  const issues: string[] = [];
  const root = checkObject(input, "update", issues);
  if (root) {
    checkKeys(root, ["schemaVersion", "operationId", "componentId", "targetVersion", "channel", "state", "download", "activation", "rollback", "error", "updatedAt"], "update", issues);
    checkConst(root.schemaVersion, CONTRACT_VERSIONS.updateState, "update.schemaVersion", issues);
    if (checkString(root.operationId, "update.operationId", issues) && !/^[A-Za-z0-9_-]{8,64}$/.test(root.operationId)) issues.push("update.operationId is invalid");
    checkString(root.componentId, "update.componentId", issues);
    checkSemver(root.targetVersion, "update.targetVersion", issues);
    checkEnum(root.channel, RELEASE_CHANNELS, "update.channel", issues);
    checkEnum(root.state, ["idle", "checking", "downloading", "paused", "downloaded", "verifying", "staged", "activating", "active", "interrupted", "rolling-back", "rolled-back", "failed"], "update.state", issues);
    const download = requireObject(root, "download", "update", issues);
    if (download) {
      checkKeys(download, ["url", "expectedBytes", "bytesDownloaded", "sha256", "tempPath", "resumable", "recovery"], "update.download", issues);
      checkHttpsUrl(download.url, "update.download.url", issues);
      checkInteger(download.expectedBytes, "update.download.expectedBytes", issues, 1);
      checkInteger(download.bytesDownloaded, "update.download.bytesDownloaded", issues, 0);
      checkSha256(download.sha256, "update.download.sha256", issues);
      checkAbsolutePath(download.tempPath, "update.download.tempPath", issues);
      checkBoolean(download.resumable, "update.download.resumable", issues);
      const recovery = requireObject(download, "recovery", "update.download", issues);
      if (recovery) {
        checkKeys(recovery, ["status", "resumeFromByte", "lastVerifiedByte", "etag"], "update.download.recovery", issues);
        checkEnum(recovery.status, ["none", "resume-available", "restart-required", "discarded"], "update.download.recovery.status", issues);
        checkInteger(recovery.resumeFromByte, "update.download.recovery.resumeFromByte", issues, 0);
        checkInteger(recovery.lastVerifiedByte, "update.download.recovery.lastVerifiedByte", issues, 0);
        if ("etag" in recovery) checkString(recovery.etag, "update.download.recovery.etag", issues);
      }
      if (typeof download.bytesDownloaded === "number" && typeof download.expectedBytes === "number" && download.bytesDownloaded > download.expectedBytes) issues.push("update.download.bytesDownloaded cannot exceed expectedBytes");
    }
    const activation = requireObject(root, "activation", "update", issues);
    if (activation) {
      checkKeys(activation, ["strategy", "stagePath", "activePath", "metadataPath", "currentVersion", "targetVersion", "checkpoint", "atomicCommit"], "update.activation", issues);
      checkConst(activation.strategy, "stage-then-atomic-rename", "update.activation.strategy", issues);
      checkAbsolutePath(activation.stagePath, "update.activation.stagePath", issues);
      checkAbsolutePath(activation.activePath, "update.activation.activePath", issues);
      checkAbsolutePath(activation.metadataPath, "update.activation.metadataPath", issues);
      checkSemver(activation.currentVersion, "update.activation.currentVersion", issues);
      checkSemver(activation.targetVersion, "update.activation.targetVersion", issues);
      checkEnum(activation.checkpoint, ["none", "downloaded", "verified", "staged", "active", "rolled-back"], "update.activation.checkpoint", issues);
      checkBoolean(activation.atomicCommit, "update.activation.atomicCommit", issues);
    }
    const rollback = requireObject(root, "rollback", "update", issues);
    if (rollback) {
      checkKeys(rollback, ["available", "previousVersion", "previousPath", "automatic", "attemptCount", "maxAttempts", "reason"], "update.rollback", issues);
      checkBoolean(rollback.available, "update.rollback.available", issues);
      if ("previousVersion" in rollback) checkSemver(rollback.previousVersion, "update.rollback.previousVersion", issues);
      if ("previousPath" in rollback) checkAbsolutePath(rollback.previousPath, "update.rollback.previousPath", issues);
      checkBoolean(rollback.automatic, "update.rollback.automatic", issues);
      checkInteger(rollback.attemptCount, "update.rollback.attemptCount", issues, 0);
      checkInteger(rollback.maxAttempts, "update.rollback.maxAttempts", issues, 1, 5);
      if ("reason" in rollback) checkString(rollback.reason, "update.rollback.reason", issues, 0);
      if (rollback.available === true && (!rollback.previousVersion || !rollback.previousPath)) issues.push("update.rollback previousVersion and previousPath are required when rollback is available");
    }
    if ("error" in root) validateUpdateError(root.error, "update.error", issues);
    checkDateTime(root.updatedAt, "update.updatedAt", issues);

    if (root.state === "interrupted" && isRecord(root.download) && isRecord(root.download.recovery) && !["resume-available", "restart-required"].includes(String(root.download.recovery.status))) {
      issues.push("interrupted updates require resumable recovery metadata");
    }
    if (root.state === "active" && isRecord(root.activation) && (root.activation.checkpoint !== "active" || root.activation.atomicCommit !== true)) {
      issues.push("active updates require an atomic active checkpoint");
    }
    if (root.state === "failed" && !("error" in root)) issues.push("failed updates require an error");
  }
  if (issues.length > 0) fail(CONTRACT_VERSIONS.updateState, issues);
  return input as UpdateState;
}

export function validateContract<T extends ComponentManifest | EngineControlMessage | HealthReadinessPayload | CapabilitiesPayload | StorageLayout | UpdateState>(input: unknown, schemaVersion: string): T {
  switch (schemaVersion) {
    case CONTRACT_VERSIONS.componentManifest:
      return validateComponentManifest(input) as T;
    case CONTRACT_VERSIONS.engineControl:
      return validateEngineControl(input) as T;
    case CONTRACT_VERSIONS.healthReadiness:
      return validateHealthReadiness(input) as T;
    case CONTRACT_VERSIONS.capabilities:
      return validateCapabilities(input) as T;
    case CONTRACT_VERSIONS.storageLayout:
      return validateStorageLayout(input) as T;
    case CONTRACT_VERSIONS.updateState:
      return validateUpdateState(input) as T;
    default:
      throw new ContractValidationError("desktop.contract", [`unsupported schema version ${schemaVersion}`]);
  }
}
