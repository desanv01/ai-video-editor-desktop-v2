import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export const COMPONENT_PROGRESS_EVENT = "component-operation-progress";

export interface ComponentManagerError {
  code: string;
  message: string;
  retryable: boolean;
  remediationCodes: string[];
}

export interface ManifestIntakeResult {
  componentId: string;
  componentVersion: string;
  signatureKeyId: string;
  artifactBytes: number;
  catalogPath: string;
}

export interface DependencyPlanItem {
  id: string;
  versionConstraint: string;
  resolvedVersion: string | null;
  optional: boolean;
}

export interface InstallationPlan {
  componentId: string;
  targetVersion: string;
  artifactBytes: number;
  requiresElevation: boolean;
  dependencies: DependencyPlanItem[];
}

export type ComponentOperationState =
  | "downloading"
  | "paused"
  | "cancelled"
  | "downloaded"
  | "verifying"
  | "verified"
  | "staged"
  | "published"
  | "active"
  | "rolled-back"
  | "failed";

export interface ComponentStatusResult {
  id: string;
  displayName: string | null;
  version: string | null;
  state: string;
  activePath: string | null;
  downloadedBytes: number;
  detail: string;
  remediationCodes: string[];
}

export interface ComponentProgress {
  operationId: string;
  componentId: string;
  componentVersion: string;
  operation: "download" | "stage" | "activate" | "rollback";
  state: ComponentOperationState;
  bytesDownloaded: number;
  totalBytes: number;
  percent: number;
  message: string;
}

export interface DownloadResult {
  operationId: string;
  componentId: string;
  componentVersion: string;
  archivePath: string;
  bytesDownloaded: number;
  resumed: boolean;
  state: "downloaded";
}

export interface VerificationResult {
  componentId: string;
  componentVersion: string;
  artifactBytes: number;
  artifactSha256: string;
  signatureKeyId: string;
  inventoryEntries: number;
  state: "verified";
}

export interface StageResult {
  componentId: string;
  componentVersion: string;
  operationId: string;
  stagePath: string;
  inventoryEntries: number;
  state: "staged";
}

export interface ActivationResult {
  componentId: string;
  componentVersion: string;
  activePath: string;
  previousVersion: string | null;
  state: "active" | "rolled-back";
}

export interface RecoveryResult {
  recoveredJournals: number;
  cleanedStagingDirectories: number;
  resumableDownloads: number;
}

export interface RepairResult {
  componentId: string;
  state: "healthy" | "rolled-back";
  detail: string;
}

export interface UninstallResult {
  componentId: string;
  removedPaths: string[];
  preservedUserData: boolean;
}

export interface ComponentManagerClient {
  intakeManifest(manifestJson: string, allowTestSources?: boolean): Promise<ManifestIntakeResult>;
  resolvePlan(componentId: string, targetVersion?: string, allowTestSources?: boolean): Promise<InstallationPlan>;
  status(componentId?: string): Promise<ComponentStatusResult[]>;
  download(
    componentId: string,
    componentVersion: string,
    operationId?: string,
    allowTestSources?: boolean,
  ): Promise<DownloadResult>;
  pause(operationId: string): Promise<boolean>;
  cancel(operationId: string): Promise<boolean>;
  retry(
    componentId: string,
    componentVersion: string,
    operationId?: string,
    allowTestSources?: boolean,
  ): Promise<DownloadResult>;
  verify(componentId: string, componentVersion: string, allowTestSources?: boolean): Promise<VerificationResult>;
  stage(
    componentId: string,
    componentVersion: string,
    operationId?: string,
    allowTestSources?: boolean,
  ): Promise<StageResult>;
  activate(
    componentId: string,
    componentVersion: string,
    operationId?: string,
    allowTestSources?: boolean,
  ): Promise<ActivationResult>;
  rollback(componentId: string, allowTestSources?: boolean): Promise<ActivationResult>;
  repair(componentId: string, allowTestSources?: boolean): Promise<RepairResult>;
  uninstall(componentId: string): Promise<UninstallResult>;
  recover(): Promise<RecoveryResult>;
  onProgress(handler: (progress: ComponentProgress) => void): Promise<UnlistenFn>;
}

const testPolicy = (allowTestSources: boolean): { allowTestSources: boolean } => ({
  allowTestSources,
});

export const componentManager: ComponentManagerClient = {
  intakeManifest: (manifestJson, allowTestSources = false) =>
    invoke<ManifestIntakeResult>("component_intake_manifest", {
      manifestJson,
      ...testPolicy(allowTestSources),
    }),
  resolvePlan: (componentId, targetVersion, allowTestSources = false) =>
    invoke<InstallationPlan>("component_resolve_plan", {
      componentId,
      targetVersion,
      ...testPolicy(allowTestSources),
    }),
  status: (componentId) => invoke<ComponentStatusResult[]>("component_status", { componentId }),
  download: (componentId, componentVersion, operationId, allowTestSources = false) =>
    invoke<DownloadResult>("component_download", {
      componentId,
      componentVersion,
      operationId,
      ...testPolicy(allowTestSources),
    }),
  pause: (operationId) => invoke<boolean>("component_pause", { operationId }),
  cancel: (operationId) => invoke<boolean>("component_cancel", { operationId }),
  retry: (componentId, componentVersion, operationId, allowTestSources = false) =>
    invoke<DownloadResult>("component_retry", {
      componentId,
      componentVersion,
      operationId,
      ...testPolicy(allowTestSources),
    }),
  verify: (componentId, componentVersion, allowTestSources = false) =>
    invoke<VerificationResult>("component_verify", {
      componentId,
      componentVersion,
      ...testPolicy(allowTestSources),
    }),
  stage: (componentId, componentVersion, operationId, allowTestSources = false) =>
    invoke<StageResult>("component_stage", {
      componentId,
      componentVersion,
      operationId,
      ...testPolicy(allowTestSources),
    }),
  activate: (componentId, componentVersion, operationId, allowTestSources = false) =>
    invoke<ActivationResult>("component_activate", {
      componentId,
      componentVersion,
      operationId,
      ...testPolicy(allowTestSources),
    }),
  rollback: (componentId, allowTestSources = false) =>
    invoke<ActivationResult>("component_rollback", {
      componentId,
      ...testPolicy(allowTestSources),
    }),
  repair: (componentId, allowTestSources = false) =>
    invoke<RepairResult>("component_repair", {
      componentId,
      ...testPolicy(allowTestSources),
    }),
  uninstall: (componentId) => invoke<UninstallResult>("component_uninstall", { componentId }),
  recover: () => invoke<RecoveryResult>("component_recover"),
  onProgress: (handler) =>
    listen<ComponentProgress>(COMPONENT_PROGRESS_EVENT, (event) => handler(event.payload)),
};
