import { invoke } from "@tauri-apps/api/core";
import type { ComponentStatusResult } from "./componentManager";
import type { DesktopBootState, SupervisorStatus } from "./desktopV2";

export type DesktopHydrationRoute =
  | "booting"
  | "needs-core-setup"
  | "resumable-setup"
  | "starting-engine"
  | "needs-optional-ai-choice"
  | "ready"
  | "repair-required";

export type ProvisioningOperationKind =
  | "core-setup"
  | "local-transcription-runtime"
  | "local-transcription-model";

export type ProvisioningState =
  | "running"
  | "cancelling"
  | "cancelled"
  | "interrupted"
  | "failed"
  | "completed";

export type ProvisioningCheckpoint =
  | "discovered"
  | "catalog-reconciled"
  | "downloading"
  | "downloaded"
  | "verified"
  | "staged"
  | "activated"
  | "complete";

export interface ProvisioningJournal {
  schemaVersion: "desktop.provisioning-journal.v1";
  operationId: string;
  operationKind: ProvisioningOperationKind;
  targetId: string;
  state: ProvisioningState;
  checkpoint: ProvisioningCheckpoint;
  phaseLabel: string;
  bytesDownloaded: number;
  totalBytes: number;
  percent: number;
  cancelRequested: boolean;
  inAtomicSection: boolean;
  retryCount: number;
  lastErrorCode: string | null;
  updatedAtEpochMs: number;
}

export interface FirstLaunchState {
  schemaVersion: "desktop.first-launch.v1";
  optionalAiChoice: "local" | "cloud" | "decide-later" | null;
  completed: boolean;
  updatedAtEpochMs: number;
}

export interface DesktopBootSnapshot {
  schemaVersion: "desktop.boot-snapshot.v1";
  hydrationComplete: true;
  reconciled: true;
  route: DesktopHydrationRoute;
  generatedAtEpochMs: number;
  shellBootState: DesktopBootState;
  coreComponents: ComponentStatusResult[];
  catalog: {
    available: boolean;
    trusted: boolean;
    autoDiscovered: boolean;
    source: string | null;
    detail: string;
  };
  provisioning: ProvisioningJournal | null;
  supervisor: SupervisorStatus;
  firstLaunch: FirstLaunchState;
  friendlyTitle: string;
  friendlyDetail: string;
  remediationCodes: string[];
}

export const provisioningClient = {
  hydrate: () => invoke<DesktopBootSnapshot>("desktop_boot_snapshot"),
  hydrateAlias: () => invoke<DesktopBootSnapshot>("desktop_hydrate"),
  status: () => invoke<ProvisioningJournal | null>("provisioning_status"),
  begin: (operationKind: ProvisioningOperationKind, targetId: string, totalBytes = 0) =>
    invoke<ProvisioningJournal>("provisioning_begin", { operationKind, targetId, totalBytes }),
  retry: () => invoke<ProvisioningJournal>("provisioning_retry"),
  cancel: () => invoke<ProvisioningJournal>("provisioning_cancel"),
  complete: () => invoke<ProvisioningJournal>("provisioning_complete"),
  fail: (errorCode: string) => invoke<ProvisioningJournal>("provisioning_fail", { errorCode }),
  checkpoint: (checkpoint: ProvisioningCheckpoint, bytesDownloaded: number) =>
    invoke<ProvisioningJournal>("provisioning_checkpoint", { checkpoint, bytesDownloaded }),
  setAtomicSection: (active: boolean) =>
    invoke<ProvisioningJournal>("provisioning_set_atomic_section", { active }),
  completeOptionalAiChoice: (choice: FirstLaunchState["optionalAiChoice"]) => {
    if (choice === null) return Promise.reject(new Error("Choose an AI preference."));
    return invoke<FirstLaunchState>("desktop_complete_optional_ai_choice", { choice });
  },
};

export function routeNeedsSetup(route: DesktopHydrationRoute): boolean {
  return route === "needs-core-setup" || route === "resumable-setup" || route === "repair-required";
}

export function formatProvisioningProgress(journal: ProvisioningJournal): string {
  if (journal.state === "cancelling") return "Finishing this safe step before stopping…";
  if (journal.state === "interrupted") return `Continue from ${journal.phaseLabel.toLowerCase()} (${journal.percent}%).`;
  return `${journal.phaseLabel} · ${journal.percent}%`;
}
