import { invoke } from "@tauri-apps/api/core";

export const MIGRATION_INVENTORY_SCHEMA = "desktop.migration-inventory.v1" as const;
export const MIGRATION_REPORT_SCHEMA = "desktop.migration-report.v1" as const;
export const FULL_WIPE_CONFIRMATION = "REMOVE ALL AI VIDEO EDITOR USER DATA";

export interface MigrationRoots {
  localAppData: string;
  programFiles: string;
  programFilesX86?: string | null;
  programData: string;
  userProfile: string;
  desktop?: string | null;
  startMenu?: string | null;
  registry?: string | null;
}

export interface LegacyInstallIdentity {
  identityId: string;
  productName: string;
  identifier: string | null;
  version: string | null;
  installScope: string;
  installPath: string;
  evidencePaths: string[];
  isCurrentV2: boolean;
}

export interface InventoryItem {
  itemId: string;
  category: string;
  classification: string;
  sourcePath: string;
  rootScope: string;
  exists: boolean;
  isDirectory: boolean;
  fileCount: number;
  sizeBytes: number;
  reparsePoint: boolean;
  locked: boolean;
  safeBoundary: boolean;
  oldIdentityId: string | null;
  detectedVersion: string | null;
  databaseKind: string | null;
  compatibleForMigration: boolean;
  exportImportRequired: boolean;
  secretDetected: boolean;
  secretNames: string[];
  conflict: boolean;
  recommendedAction: string;
  rationale: string;
  notes: string[];
}

export interface LegacyInventory {
  schemaVersion: typeof MIGRATION_INVENTORY_SCHEMA;
  generatedAtEpochMs: number;
  roots: MigrationRoots;
  oldInstallIdentities: LegacyInstallIdentity[];
  items: InventoryItem[];
  processes: Array<{ sourcePath: string; pid: number | null; port: number | null; ownedByProduct: boolean; stale: boolean; detail: string }>;
  shortcuts: Array<{ sourcePath: string; location: string; targetHint: string | null; oldIdentityId: string | null; stale: boolean; safeToRemove: boolean; detail: string }>;
  registryUninstallRecords: Array<{ sourcePath: string; displayName: string | null; displayVersion: string | null; identifier: string | null; uninstallCommandPresent: boolean; oldIdentityId: string | null; stale: boolean; safeToRemove: boolean }>;
  conflicts: string[];
  warnings: string[];
  totals: { itemCount: number; totalBytes: number; valuableBytes: number; migratableBytes: number; cleanupBytes: number; unsupportedDatabaseBytes: number };
  hasLegacyState: boolean;
  scanComplete: boolean;
  recommendedAction: string;
  redactionPolicy: string;
}

export interface MigrationOptions {
  action?: string;
  backupBeforeMigrate?: boolean;
  keepOldCopy?: boolean;
  cleanupAfterMigrate?: boolean;
  cleanupApproved?: boolean;
  dryRun?: boolean;
  availableSpaceOverrideBytes?: number | null;
  failureAfterSteps?: number | null;
}

export interface MigrationPlanItem {
  itemId: string;
  action: string;
  sourcePath: string;
  destinationPath: string | null;
  stagingPath: string | null;
  bytes: number;
  conflictStrategy: string;
  supported: boolean;
  warning: string | null;
}

export interface MigrationReport {
  schemaVersion: typeof MIGRATION_REPORT_SCHEMA;
  migrationId: string;
  generatedAtEpochMs: number;
  inventory: LegacyInventory;
  targets: {
    userRoot: string;
    config: string;
    cache: string;
    temp: string;
    logs: string;
    state: string;
    uploads: string;
    projects: string;
    exports: string;
    backupRoot: string;
    programDataProductRoot: string;
  };
  plan: MigrationPlanItem[];
  preflight: {
    passed: boolean;
    requiredBytes: number;
    availableBytes: number | null;
    diskSpaceOk: boolean;
    safeBoundariesOk: boolean;
    lockedItems: string[];
    reparseItems: string[];
    conflicts: string[];
    warnings: string[];
  };
  status: string;
  journalPath: string | null;
  completedItemIds: string[];
  warnings: string[];
  redactedSecretNames: string[];
  recommendedNextAction: string;
}

export interface CleanupOptions {
  approved?: boolean;
  fullWipeConfirmed?: boolean;
  confirmation?: string | null;
  dryRun?: boolean;
  scheduleRebootCleanup?: boolean;
}

export interface CleanupReport {
  schemaVersion: string;
  generatedAtEpochMs: number;
  dryRun: boolean;
  approved: boolean;
  fullWipe: boolean;
  removedPaths: string[];
  preservedPaths: string[];
  lockedLeftovers: string[];
  unsafePaths: string[];
  warnings: string[];
  restartRequired: boolean;
  recommendedNextAction: string;
}

export interface RepairOptions {
  restoreShortcuts?: boolean;
  resetDisposableCache?: boolean;
  recoverActivationJournal?: boolean;
  runComponentSelfTests?: boolean;
  dryRun?: boolean;
}

export interface RepairReport {
  schemaVersion: string;
  generatedAtEpochMs: number;
  dryRun: boolean;
  installerIdentityValid: boolean;
  componentStoreValid: boolean;
  stateRecovered: boolean;
  shortcutsRestored: string[];
  cacheReset: string[];
  actions: string[];
  warnings: string[];
  preservedUserData: string[];
  recommendedNextAction: string;
}

export interface UninstallPath {
  path: string;
  classification: string;
  removeByDefault: boolean;
  preserveByDefault: boolean;
  safeBoundary: boolean;
  exists: boolean;
  reason: string;
}

export interface UninstallPlan {
  schemaVersion: string;
  generatedAtEpochMs: number;
  roots: MigrationRoots;
  removeByDefault: UninstallPath[];
  preserveByDefault: UninstallPath[];
  fullWipePaths: UninstallPath[];
  ownedProcesses: Array<{ pid: number | null; port: number | null; markerPath: string; owner: string | null; stopAllowed: boolean; reason: string }>;
  warnings: string[];
  defaultChoice: string;
  fullWipeConfirmation: string;
}

export interface UninstallOptions {
  approved?: boolean;
  removeAllUserData?: boolean;
  confirmation?: string | null;
  dryRun?: boolean;
  scheduleRebootCleanup?: boolean;
}

export interface UninstallReport {
  schemaVersion: string;
  generatedAtEpochMs: number;
  dryRun: boolean;
  removeAllUserData: boolean;
  removedPaths: string[];
  preservedPaths: string[];
  lockedLeftovers: string[];
  unsafePaths: string[];
  warnings: string[];
  restartRequired: boolean;
  ownedProcessesNotStopped: UninstallPlan["ownedProcesses"];
  recommendedNextAction: string;
}

export interface MigrationBridgeTransport {
  invoke<T>(command: string, args?: Record<string, unknown>): Promise<T>;
}

export interface MigrationClient {
  scan: (roots?: MigrationRoots) => Promise<LegacyInventory>;
  preview: (roots: MigrationRoots | undefined, options?: MigrationOptions) => Promise<MigrationReport>;
  execute: (report: MigrationReport, options?: MigrationOptions) => Promise<MigrationReport>;
  rollback: (report: MigrationReport) => Promise<MigrationReport>;
  recover: (roots?: MigrationRoots) => Promise<MigrationReport | null>;
  cleanup: (inventory: LegacyInventory, options?: CleanupOptions) => Promise<CleanupReport>;
  repair: (roots: MigrationRoots | undefined, options?: RepairOptions) => Promise<RepairReport>;
  uninstallPlan: (roots?: MigrationRoots) => Promise<UninstallPlan>;
  uninstall: (plan: UninstallPlan, options?: UninstallOptions) => Promise<UninstallReport>;
}

export function createMigrationClient(transport: MigrationBridgeTransport): MigrationClient {
  return {
    scan: roots => transport.invoke<LegacyInventory>("migration_scan_legacy", roots ? { roots } : undefined),
    preview: (roots, options = {}) => transport.invoke<MigrationReport>("migration_preview", { roots, options }),
    execute: (report, options = {}) => transport.invoke<MigrationReport>("migration_execute", { report, options }),
    rollback: report => transport.invoke<MigrationReport>("migration_rollback", { report }),
    recover: roots => transport.invoke<MigrationReport | null>("migration_recover", roots ? { roots } : undefined),
    cleanup: (inventory, options = {}) => transport.invoke<CleanupReport>("migration_cleanup", { inventory, options }),
    repair: (roots, options = {}) => transport.invoke<RepairReport>("migration_repair", { roots, options }),
    uninstallPlan: roots => transport.invoke<UninstallPlan>("migration_uninstall_plan", roots ? { roots } : undefined),
    uninstall: (plan, options = {}) => transport.invoke<UninstallReport>("migration_uninstall_execute", { plan, options }),
  };
}

export const migrationClient: MigrationClient = createMigrationClient({ invoke });

export function formatMigrationBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value >= 10 || index === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[index]}`;
}

export function migrationCategoryLabel(item: Pick<InventoryItem, "category" | "classification"> & { exportImportRequired?: boolean }): string {
  if (item.exportImportRequired || item.classification === "postgresql" || item.classification === "qdrant") return "Export/import required";
  switch (item.category) {
    case "application-runtime": return "Application runtime (safe to clean after approval)";
    case "config": return "Settings (secrets protected or re-entered)";
    case "projects": return "Projects (valuable user data)";
    case "uploads": return "Uploads/media (valuable user data)";
    case "exports": return "Exports (valuable user data)";
    case "models": return "Models (preserved by default)";
    case "database": return "Database (preserved/exported before removal)";
    case "shortcut": return "Legacy shortcut";
    default: return item.category;
  }
}

export function redactMigrationText(value: string): string {
  return value
    .slice(0, 1200)
    .replace(/((?:password|passwd|secret|token|api[_-]?key|authorization)\s*[:=]\s*)[^\s,;&]+/gi, "$1[REDACTED]")
    .replace(/\bBearer\s+[^\s,;&]+/gi, "Bearer [REDACTED]")
    .replace(/\b(?:sk|pk)-[A-Za-z0-9_-]{12,}\b/g, "[REDACTED_TOKEN]");
}
