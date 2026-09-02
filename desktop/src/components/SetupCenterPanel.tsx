import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  ClipboardCopy,
  CloudDownload,
  Cpu,
  Download,
  FileCheck2,
  FileKey2,
  FileSearch,
  HardDrive,
  Info,
  LockKeyhole,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Trash2,
  Upload,
  Wrench,
  XCircle,
} from "lucide-react";
import {
  componentManager,
  type ComponentProgress,
  type ComponentStatusResult,
} from "../componentManager.ts";
import type { DesktopV2BootstrapResult, SupervisorStatus } from "../desktopV2.ts";
import { ProviderOnboardingPanel } from "./ProviderOnboardingPanel";
import * as api from "../lib/api";
import { provisioningClient } from "../provisioning";
import {
  aggregateProgress,
  canLaunchEditor,
  catalogEntryFor,
  catalogEntryIsInstallable,
  DEFAULT_COMPONENT_CARDS,
  normalizeSetupError,
  optionalComponentIsSelected,
  REQUIRED_COMPONENT_IDS,
  setupClient,
  systemChecksAreCurrentAndHealthy,
  setupStepIndex,
  setupStepLabel,
  type SetupCatalog,
  type SetupCatalogEntry,
  type SetupCatalogInfo,
  type BundledCatalogDiscovery,
  type SetupError,
  type SetupStage,
  type SetupState,
  type SetupSystemCheck,
  type SetupSystemChecksResult,
} from "../setupCenter.ts";

type ComponentTarget = { version: string; operationId: string };

export interface SetupCenterPanelProps {
  bootstrap: DesktopV2BootstrapResult | null;
  supervisor: SupervisorStatus | null;
  initialStatuses: ComponentStatusResult[];
  initialState: SetupState;
  initialCatalog: SetupCatalogInfo | null;
  setupRequired: boolean;
  initialStage?: SetupStage;
  onSupervisorStatus: (status: SupervisorStatus) => void;
  onSetupComplete: (status: SupervisorStatus, state: SetupState) => void;
  onLaunchEditor: () => void;
  onOpenDiagnostics: () => void;
}

export function SetupCenterPanel({
  bootstrap,
  supervisor,
  initialStatuses,
  initialState,
  initialCatalog,
  setupRequired,
  initialStage,
  onSupervisorStatus,
  onSetupComplete,
  onLaunchEditor,
  onOpenDiagnostics,
}: SetupCenterPanelProps) {
  const [stage, setStage] = useState<SetupStage>(initialStage ?? (initialState.onboardingCompleted && !setupRequired ? "complete" : "welcome"));
  const [state, setState] = useState(initialState);
  const [catalogInfo, setCatalogInfo] = useState(initialCatalog);
  const [bundledCatalog, setBundledCatalog] = useState<BundledCatalogDiscovery | null>(null);
  const [statuses, setStatuses] = useState(initialStatuses);
  const [checks, setChecks] = useState<SetupSystemChecksResult | null>(null);
  const [progressByOperation, setProgressByOperation] = useState<Record<string, ComponentProgress>>({});
  const [transferMetrics, setTransferMetrics] = useState<Record<string, { speedBytesPerSecond: number; etaSeconds: number | null }>>({});
  const [error, setError] = useState<SetupError | null>(null);
  const [busy, setBusy] = useState(false);
  const [licenseAccepted, setLicenseAccepted] = useState(false);
  const [technicalOpen, setTechnicalOpen] = useState(false);
  const [resumeAvailable, setResumeAvailable] = useState(Object.keys(initialState.incompleteOperationIds).length > 0);
  const [selectedStatus, setSelectedStatus] = useState<ComponentStatusResult | null>(null);
  const [copyMessage, setCopyMessage] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);
  const [cancelRequested, setCancelRequested] = useState(false);
  const targetsRef = useRef<Record<string, ComponentTarget>>({});
  const stateRef = useRef(initialState);
  const currentComponentRef = useRef<string | null>(null);
  const operationStageRef = useRef<SetupStage>("download");
  const progressSamplesRef = useRef<Record<string, { bytes: number; at: number }>>({});
  const cancelRequestedRef = useRef(false);
  const supervisorStartedRef = useRef(false);

  const selectedOptionalIds = state.selectedOptionalPacks;
  const selectedIds = useMemo(
    () => [...REQUIRED_COMPONENT_IDS, ...selectedOptionalIds],
    [selectedOptionalIds],
  );
  const installableSelectedIds = useMemo(
    () => selectedIds.filter(id => catalogEntryIsInstallable(catalogEntryFor(catalogInfo?.catalog ?? null, id))),
    [catalogInfo, selectedIds],
  );
  const progress = useMemo(
    () => aggregateProgress(installableSelectedIds, progressByOperation),
    [installableSelectedIds, progressByOperation],
  );
  const hasRequiredCatalog = REQUIRED_COMPONENT_IDS.every(id => catalogEntryIsInstallable(catalogEntryFor(catalogInfo?.catalog ?? null, id)));
  const checksHealthy = systemChecksAreCurrentAndHealthy(checks);
  const reviewReady = hasRequiredCatalog && checksHealthy && !error;
  const engineReady = canLaunchEditor(supervisor);

  useEffect(() => {
    let disposed = false;
    let unlisten: (() => void) | undefined;
    void componentManager.onProgress(next => {
      if (disposed) return;
      setProgressByOperation(current => {
        const updated = { ...current, [next.operationId]: next };
        const downloaded = Object.values(updated).reduce((sum, item) => sum + item.bytesDownloaded, 0);
        void provisioningClient.checkpoint("downloading", downloaded).catch(() => undefined);
        return updated;
      });
      setPaused(next.state === "paused");
      const now = performance.now();
      const previous = progressSamplesRef.current[next.componentId];
      const elapsedSeconds = previous ? Math.max((now - previous.at) / 1000, 0.001) : 0;
      const speedBytesPerSecond = previous && next.bytesDownloaded > previous.bytes
        ? (next.bytesDownloaded - previous.bytes) / elapsedSeconds
        : 0;
      const etaSeconds = speedBytesPerSecond > 0 && next.totalBytes > next.bytesDownloaded
        ? (next.totalBytes - next.bytesDownloaded) / speedBytesPerSecond
        : null;
      progressSamplesRef.current[next.componentId] = { bytes: next.bytesDownloaded, at: now };
      setTransferMetrics(current => ({ ...current, [next.componentId]: { speedBytesPerSecond, etaSeconds } }));
    }).then(dispose => {
      if (disposed) dispose();
      else unlisten = dispose;
    });
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, []);

  useEffect(() => {
    let disposed = false;
    void setupClient.discoverBundledCatalog().then(discovery => {
      if (!disposed) setBundledCatalog(discovery);
    }).catch(() => {
      if (!disposed) setBundledCatalog(null);
    });
    return () => { disposed = true; };
  }, []);

  useEffect(() => {
    if (engineReady && state.onboardingCompleted && stage === "welcome") setStage("complete");
  }, [engineReady, stage, state.onboardingCompleted]);

  const refreshStatuses = async () => {
    const next = await componentManager.status();
    setStatuses(next);
    return next;
  };

  const saveNextState = async (next: SetupState) => {
    const saved = await setupClient.saveState(next);
    stateRef.current = saved;
    setState(saved);
    return saved;
  };

  const runChecks = async () => {
    setBusy(true);
    setError(null);
    try {
      setChecks(await setupClient.runSystemChecks(true));
      setStage("system-check");
    } catch (operationError) {
      setError(normalizeSetupError(operationError));
    } finally {
      setBusy(false);
    }
  };

  const refreshChecks = async () => {
    const next = await setupClient.runSystemChecks(true);
    setChecks(next);
    return next;
  };

  const importCatalog = async () => {
    setBusy(true);
    setError(null);
    try {
      let selected: string | null;
      try {
        const { open } = await import("@tauri-apps/plugin-dialog");
        const result = await open({
          multiple: false,
          directory: false,
          title: "Select one signed Desktop V2 catalog JSON file",
          filters: [{ name: "Setup catalog JSON", extensions: ["json"] }],
        });
        selected = typeof result === "string" ? result : null;
      } catch (dialogError) {
        throw { code: "DIALOG_OPEN_FAILED", message: String(dialogError), retryable: true };
      }
      if (typeof selected !== "string") return;
      const result = await setupClient.importCatalogFile(selected);
      setCatalogInfo(result.catalog);
      await saveNextState({ ...stateRef.current, catalogChannel: result.catalog.catalog.channel });
      await refreshStatuses();
      await refreshChecks();
      setStage("choose-components");
    } catch (operationError) {
      setError(normalizeSetupError(operationError));
    } finally {
      setBusy(false);
    }
  };

  const importBundledCatalog = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await setupClient.importBundledCatalog();
      setCatalogInfo(result.catalog);
      await saveNextState({ ...stateRef.current, catalogChannel: result.catalog.catalog.channel });
      await refreshStatuses();
      await refreshChecks();
      setStage("choose-components");
    } catch (operationError) {
      setError(normalizeSetupError(operationError));
    } finally {
      setBusy(false);
    }
  };

  const refreshProductionCatalog = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await setupClient.refreshCatalog();
      setCatalogInfo(result.catalog);
      await refreshStatuses();
      await refreshChecks();
      setStage("choose-components");
    } catch (operationError) {
      setError(normalizeSetupError(operationError));
    } finally {
      setBusy(false);
    }
  };

  const toggleOptional = (entry: SetupCatalogEntry) => {
    if (!catalogEntryIsInstallable(entry)) return;
    const selected = new Set(stateRef.current.selectedOptionalPacks);
    if (selected.has(entry.componentId)) selected.delete(entry.componentId);
    else selected.add(entry.componentId);
    const next = { ...stateRef.current, selectedOptionalPacks: [...selected] };
    void saveNextState(next).catch(operationError => setError(normalizeSetupError(operationError)));
  };

  const throwIfCancellationRequested = () => {
    if (cancelRequestedRef.current) {
      throw {
        code: "SETUP_CANCELLED",
        message: "Setup cancellation was requested at a safe boundary.",
        retryable: true,
        remediationCodes: ["RESUME_SETUP"],
      };
    }
  };

  const stopSupervisorForCancellation = async () => {
    if (!supervisorStartedRef.current) return;
    let next = await api.stopSupervisor();
    onSupervisorStatus(next);
    for (let attempt = 0; attempt < 40 && !["stopped", "cancelled-stopped"].includes(next.state); attempt += 1) {
      await new Promise(resolve => window.setTimeout(resolve, 100));
      next = await api.getSupervisorStatus();
      onSupervisorStatus(next);
    }
  };

  const finishComponent = async (componentId: string, target: ComponentTarget, allowTestSources: boolean) => {
    throwIfCancellationRequested();
    operationStageRef.current = "verify";
    setStage("verify");
    await componentManager.verify(componentId, target.version, allowTestSources);
    throwIfCancellationRequested();
    operationStageRef.current = "activate";
    setStage("activate");
    await componentManager.stage(componentId, target.version, target.operationId, allowTestSources);
    throwIfCancellationRequested();
    await provisioningClient.setAtomicSection(true);
    try {
      await componentManager.activate(componentId, target.version, target.operationId, allowTestSources);
    } finally {
      await provisioningClient.setAtomicSection(false).catch(() => undefined);
    }
    // Activation is an atomic safe checkpoint.  If cancellation arrived while
    // it was committing, leave the active version intact and stop before the
    // next component/readiness phase.
    throwIfCancellationRequested();
  };

  const installComponent = async (componentId: string, resume = false) => {
    const entry = catalogEntryFor(catalogInfo?.catalog ?? null, componentId);
    if (!catalogEntryIsInstallable(entry)) {
      throw { code: "CATALOG_MANIFEST_MISSING", message: "The selected component has no verified artifact." };
    }
    currentComponentRef.current = componentId;
    throwIfCancellationRequested();
    operationStageRef.current = "download";
    const allowTestSources = catalogInfo?.source === "offline-import";
    let target = targetsRef.current[componentId];
    if (!target) {
      const plan = await componentManager.resolvePlan(componentId, undefined, allowTestSources);
      target = {
        version: plan.targetVersion,
        operationId: stateRef.current.incompleteOperationIds[componentId] ?? `setup-${componentId}-${Date.now()}`,
      };
      targetsRef.current[componentId] = target;
    }
    await saveNextState({
      ...stateRef.current,
      incompleteOperationIds: { ...stateRef.current.incompleteOperationIds, [componentId]: target.operationId },
    });
    if (resume) {
      setStage("download");
      setPaused(false);
      await componentManager.retry(componentId, target.version, target.operationId, allowTestSources);
    } else {
      setStage("download");
      await componentManager.download(componentId, target.version, target.operationId, allowTestSources);
    }
    throwIfCancellationRequested();
    await finishComponent(componentId, target, allowTestSources);
    const incompleteOperationIds = { ...stateRef.current.incompleteOperationIds };
    delete incompleteOperationIds[componentId];
    await saveNextState({ ...stateRef.current, incompleteOperationIds });
  };

  const installSelected = async (resume = false) => {
    setBusy(true);
    setError(null);
    setResumeAvailable(false);
    cancelRequestedRef.current = false;
    setCancelRequested(false);
    const currentState = stateRef.current;
    let currentChecks = checks;
    if (!currentChecks) {
      try {
        currentChecks = await refreshChecks();
      } catch (operationError) {
        setError(normalizeSetupError(operationError));
        setBusy(false);
        return;
      }
    }
    const selectedLicensesReady = selectedIds.every(id => {
      const entry = catalogEntryFor(catalogInfo?.catalog ?? null, id);
      return !entry?.licenseVersion || stateRef.current.acceptedLicenseVersions[id] === entry.licenseVersion;
    });
    if (!catalogInfo || !hasRequiredCatalog || !systemChecksAreCurrentAndHealthy(currentChecks) || (!licenseAccepted && !selectedLicensesReady)) {
      if (resume && !licenseAccepted && !selectedLicensesReady) setStage("review");
      setError(normalizeSetupError({
        code: "SETUP_NOT_READY",
        message: "Select a verified catalog, pass the current activation-writer check, and accept the component licenses before installing.",
        retryable: true,
      }));
      setBusy(false);
      return;
    }
    const acceptedLicenseVersions = Object.fromEntries(
      selectedIds
        .map(id => catalogEntryFor(catalogInfo?.catalog ?? null, id))
        .filter((entry): entry is SetupCatalogEntry => Boolean(entry?.licenseVersion))
        .map(entry => [entry.componentId, entry.licenseVersion]),
    );
    const ordered = [...installableSelectedIds].sort((left, right) => (left === "ffmpeg" ? -1 : right === "ffmpeg" ? 1 : 0));
    try {
      const totalBytes = ordered.reduce((sum, id) => sum + (catalogEntryFor(catalogInfo.catalog, id)?.artifactBytes ?? 0), 0);
      let journal = await provisioningClient.status();
      if (journal && ["running", "cancelling"].includes(journal.state) && journal.operationKind !== "core-setup") {
        throw { code: "PROVISIONING_BUSY", message: "Finish the current optional AI operation before core setup." };
      }
      if (resume && journal && ["interrupted", "failed", "cancelled"].includes(journal.state)) {
        journal = await provisioningClient.retry();
      } else if (!journal || !["running", "cancelling"].includes(journal.state)) {
        journal = await provisioningClient.begin("core-setup", "desktop-core", totalBytes);
      }
      if (journal.checkpoint === "discovered") {
        await provisioningClient.checkpoint("catalog-reconciled", 0);
      }
      await saveNextState({ ...currentState, acceptedLicenseVersions: { ...currentState.acceptedLicenseVersions, ...acceptedLicenseVersions } });
      for (const componentId of ordered) {
        throwIfCancellationRequested();
        await installComponent(componentId, resume && Boolean(stateRef.current.incompleteOperationIds[componentId]));
      }
      await provisioningClient.checkpoint("activated", totalBytes);
      throwIfCancellationRequested();
      setStage("readiness");
      operationStageRef.current = "readiness";
      supervisorStartedRef.current = true;
      const starting = await api.startSupervisor();
      onSupervisorStatus(starting);
      let ready = starting;
      for (let attempt = 0; attempt < 80 && !canLaunchEditor(ready); attempt += 1) {
        throwIfCancellationRequested();
        await new Promise(resolve => window.setTimeout(resolve, 250));
        ready = await api.getSupervisorStatus();
        onSupervisorStatus(ready);
        if (["setup-required", "component-repair-required", "repair-required", "storage-blocked", "launch-blocked", "protocol-incompatible", "session-auth-failed", "fatal-shell-failure", "fatal", "cancelled-stopped"].includes(ready.state)) break;
      }
      throwIfCancellationRequested();
      if (!canLaunchEditor(ready)) {
        const code = ready.lastError?.split(":", 1)[0] || "ENGINE_NOT_READY";
        throw { code, message: ready.detail, remediationCodes: ready.remediationCodes };
      }
      const completed = await saveNextState({
        ...stateRef.current,
        onboardingCompleted: true,
        lastSuccessfulSetup: new Date().toISOString(),
        incompleteOperationIds: {},
      });
      await refreshStatuses();
      await provisioningClient.complete();
      setStage("complete");
      onSetupComplete(ready, completed);
    } catch (operationError) {
      const nextError = normalizeSetupError(operationError);
      try {
        const journal = await provisioningClient.status();
        if (journal?.operationKind === "core-setup" && journal.state !== "completed") {
          await provisioningClient.fail(nextError.code);
        }
      } catch { /* setup may have failed before coordination began */ }
      setError(nextError);
      setStage(nextError.code === "ENGINE_NOT_READY" ? "readiness" : operationStageRef.current);
      setResumeAvailable(true);
    } finally {
      supervisorStartedRef.current = false;
      cancelRequestedRef.current = false;
      setCancelRequested(false);
      setBusy(false);
    }
  };

  const pauseCurrent = async () => {
    if (operationStageRef.current !== "download" || cancelRequestedRef.current) return;
    const componentId = currentComponentRef.current;
    const target = componentId ? targetsRef.current[componentId] : null;
    if (!target) return;
    try {
      await componentManager.pause(target.operationId);
      setPaused(true);
    } catch (operationError) {
      setError(normalizeSetupError(operationError));
    }
  };

  const cancelCurrent = async () => {
    if (!busy || cancelRequestedRef.current) return;
    cancelRequestedRef.current = true;
    setCancelRequested(true);
    setPaused(false);
    const componentId = currentComponentRef.current;
    const target = componentId ? targetsRef.current[componentId] : null;
    try {
      try { await provisioningClient.cancel(); } catch { /* no active provisioning journal */ }
      if (operationStageRef.current === "download" && target) {
        await componentManager.cancel(target.operationId);
      } else if (operationStageRef.current === "readiness") {
        await stopSupervisorForCancellation();
      }
    } catch (operationError) {
      const nextError = normalizeSetupError(operationError);
      if (nextError.code !== "OPERATION_NOT_FOUND") setError(nextError);
    }
  };

  const retryCurrent = async () => {
    setPaused(false);
    await installSelected(true);
  };

  const copyDiagnostics = async () => {
    const payload = JSON.stringify({
      stage,
      error,
      checks,
      statuses: statuses.map(status => ({ id: status.id, state: status.state, version: status.version, detail: status.detail })),
      supervisor: supervisor ? { state: supervisor.state, engineReady: supervisor.engineReady, componentId: supervisor.componentId, componentVersion: supervisor.componentVersion, detail: supervisor.detail, lastError: supervisor.lastError, lastExitCode: supervisor.lastExitCode, handshakeAtEpochMs: supervisor.handshakeAtEpochMs, readinessAtEpochMs: supervisor.readinessAtEpochMs, lastProbeStatus: supervisor.lastProbeStatus, capabilitiesAtEpochMs: supervisor.capabilitiesAtEpochMs, lastCapabilitiesStatus: supervisor.lastCapabilitiesStatus, verificationPolicy: supervisor.verificationPolicy, remediationCodes: supervisor.remediationCodes } : null,
    }, null, 2);
    try {
      await navigator.clipboard.writeText(payload);
      setCopyMessage("Redacted setup details copied");
    } catch {
      setCopyMessage("Clipboard access is unavailable; use Generate diagnostics");
    }
    window.setTimeout(() => setCopyMessage(null), 2500);
  };

  const openManagement = () => {
    setStage("management");
    setError(null);
    void refreshStatuses().catch(operationError => setError(normalizeSetupError(operationError)));
  };

  if (stage === "management") {
    return (
      <ManagementView
        catalog={catalogInfo?.catalog ?? null}
        statuses={statuses}
        supervisor={supervisor}
        error={error}
        onBack={() => setStage(state.onboardingCompleted ? "complete" : "welcome")}
        onRefresh={() => void refreshStatuses()}
        onError={setError}
        onChannelChange={channel => void saveNextState({ ...state, catalogChannel: channel })}
        onSelectedStatus={setSelectedStatus}
      />
    );
  }

  return (
    <section className="mt-6 overflow-hidden rounded-2xl border border-surface-border bg-surface-raised shadow-xl shadow-black/10" aria-labelledby="setup-center-title">
      <div className="border-b border-surface-border px-5 py-5 sm:px-7">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent/15 text-accent ring-1 ring-accent/30">
              <Wrench className="h-5 w-5" aria-hidden="true" />
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">Setup Center</p>
              <h2 id="setup-center-title" className="mt-2 text-2xl font-semibold tracking-tight text-white">
                {stage === "complete" ? "Your local engine is ready" : "Install the pieces this app needs"}
              </h2>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-400">
                {stage === "complete"
                  ? "Components are verified in the machine component store and the authenticated supervisor is ready. You can manage versions from this page at any time."
                  : "The base shell is already installed. Setup Center adds signed, versioned components without placing runtime files in Program Files or silently falling back to AppData."}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={openManagement} className="inline-flex items-center gap-2 rounded-lg border border-surface-border px-3 py-2 text-xs font-medium text-gray-200 hover:border-accent hover:text-white focus:outline-none focus:ring-2 focus:ring-accent/70">
              <Cpu className="h-3.5 w-3.5" aria-hidden="true" /> Manage components
            </button>
            <button type="button" onClick={onOpenDiagnostics} className="inline-flex items-center gap-2 rounded-lg border border-surface-border px-3 py-2 text-xs font-medium text-gray-200 hover:border-accent hover:text-white focus:outline-none focus:ring-2 focus:ring-accent/70">
              <FileSearch className="h-3.5 w-3.5" aria-hidden="true" /> Diagnostics
            </button>
          </div>
        </div>
        <SetupStepper stage={stage} />
      </div>

      <div className="grid gap-6 p-5 sm:p-7 xl:grid-cols-[minmax(0,1fr)_300px]">
        <div className="min-w-0">
          {stage === "welcome" && (
            <WelcomeStep
              setupRequired={setupRequired}
              engineReady={engineReady}
              resumeAvailable={resumeAvailable}
              busy={busy}
              onContinue={() => void runChecks()}
              onResume={() => void installSelected(true)}
              onManage={openManagement}
            />
          )}
          {stage === "system-check" && (
            <SystemCheckStep checks={checks} busy={busy} onRun={() => void runChecks()} onContinue={() => setStage("choose-components")} />
          )}
          {stage === "choose-components" && (
            <ChooseComponentsStep
              catalog={catalogInfo?.catalog ?? null}
              state={state}
              busy={busy}
              hasRequiredCatalog={hasRequiredCatalog}
              checksHealthy={checksHealthy}
              reviewReady={reviewReady}
              bundledCatalog={bundledCatalog}
              onToggle={toggleOptional}
              onImport={importCatalog}
              onUseBundled={importBundledCatalog}
              onRefresh={() => void refreshProductionCatalog()}
              onContinue={() => setStage("review")}
            />
          )}
          {stage === "review" && (
            <ReviewStep
              catalog={catalogInfo?.catalog ?? null}
              selectedIds={selectedIds}
              licenseAccepted={licenseAccepted}
              ready={reviewReady}
              busy={busy}
              onLicenseAccepted={setLicenseAccepted}
              onBack={() => setStage("choose-components")}
              onInstall={() => void installSelected(false)}
            />
          )}
          {(stage === "download" || stage === "verify" || stage === "activate") && (
            <OperationStep
              stage={stage}
              progress={progress}
              progressByOperation={progressByOperation}
              transferMetrics={transferMetrics}
              paused={paused}
              cancelRequested={cancelRequested}
              selectedIds={installableSelectedIds}
              busy={busy}
              error={error}
              onPause={() => void pauseCurrent()}
              onResume={() => void retryCurrent()}
              onCancel={() => void cancelCurrent()}
              onRetry={() => void retryCurrent()}
              onDiagnostics={onOpenDiagnostics}
            />
          )}
          {stage === "readiness" && (
            <ReadinessStep supervisor={supervisor} busy={busy} cancelRequested={cancelRequested} error={error} onCancel={() => void cancelCurrent()} onRetry={() => void installSelected(true)} onDiagnostics={onOpenDiagnostics} />
          )}
          {stage === "complete" && (
            <CompletionStep supervisor={supervisor} statuses={statuses} engineReady={engineReady} onLaunchEditor={onLaunchEditor} onManage={openManagement} />
          )}
          {error && !["download", "verify", "activate", "readiness"].includes(stage) ? (
            <ErrorCallout error={error} technicalOpen={technicalOpen} onToggleTechnical={() => setTechnicalOpen(value => !value)} onRetry={() => void retryCurrent()} onDiagnostics={onOpenDiagnostics} />
          ) : null}
        </div>

        <aside className="space-y-4" aria-label="Setup context">
          <ProgressSummary stage={stage} progress={progress} selectedCount={installableSelectedIds.length} />
          <details className="rounded-xl border border-surface-border bg-surface-overlay p-4"><summary className="cursor-pointer text-xs font-medium text-gray-300">Setup details</summary><div className="mt-4 space-y-4"><StorageBoundaryCard bootstrap={bootstrap} /><CatalogCard catalogInfo={catalogInfo} bundledCatalog={bundledCatalog} onImport={importCatalog} onUseBundled={importBundledCatalog} onRefresh={() => void refreshProductionCatalog()} busy={busy} /></div></details>
          {selectedStatus ? <StatusDetail status={selectedStatus} onClose={() => setSelectedStatus(null)} /> : null}
          {copyMessage ? <p role="status" className="rounded-lg border border-emerald-400/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-100">{copyMessage}</p> : null}
          <button type="button" onClick={() => void copyDiagnostics()} className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-surface-border px-3 py-2 text-xs font-medium text-gray-300 hover:border-accent hover:text-white focus:outline-none focus:ring-2 focus:ring-accent/70">
            <ClipboardCopy className="h-3.5 w-3.5" aria-hidden="true" /> Copy redacted setup details
          </button>
        </aside>
      </div>
    </section>
  );
}

function SetupStepper({ stage }: { stage: SetupStage }) {
  const labels = ["Welcome", "Check this PC", "Install Core", "Install Media Tools", "Verify and Start", "Optional AI Setup", "Ready"];
  const index = stage === "welcome" ? 0
    : stage === "system-check" ? 1
      : ["choose-components", "review"].includes(stage) ? 2
        : stage === "download" ? 3
          : ["verify", "activate", "readiness"].includes(stage) ? 4
            : stage === "complete" ? 6 : Math.min(6, setupStepIndex(stage));
  return (
    <ol className="mt-6 grid grid-cols-3 gap-2 sm:grid-cols-9" aria-label="Setup progress">
      {labels.map((label, itemIndex) => (
        <li key={label} className="min-w-0">
          <div className={`flex items-center gap-1.5 text-[10px] font-medium ${itemIndex <= index ? "text-accent-100" : "text-gray-500"}`}>
            <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[10px] ${itemIndex < index ? "border-accent bg-accent text-white" : itemIndex === index ? "border-accent text-accent" : "border-surface-border text-gray-500"}`} aria-hidden="true">
              {itemIndex < index ? <Check className="h-3 w-3" /> : itemIndex + 1}
            </span>
            <span className="truncate">{label}</span>
          </div>
        </li>
      ))}
    </ol>
  );
}

function WelcomeStep({ setupRequired, engineReady, resumeAvailable, busy, onContinue, onResume, onManage }: {
  setupRequired: boolean;
  engineReady: boolean;
  resumeAvailable: boolean;
  busy: boolean;
  onContinue: () => void;
  onResume: () => void;
  onManage: () => void;
}) {
  return (
    <div>
      <div className="rounded-xl border border-accent/30 bg-accent/10 p-5">
        <div className="flex items-start gap-3">
          <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-accent" aria-hidden="true" />
          <div>
            <h3 className="text-lg font-semibold text-white">A small, guided setup</h3>
            <p className="mt-2 text-sm leading-6 text-gray-300">
              {engineReady ? "Your editing tools are ready. You can review them or open the editor." : setupRequired ? "We’ll check this PC, install the included core and media tools, and verify everything before you begin." : "Setup found a saved step and will check it before making changes."}
            </p>
          </div>
        </div>
      </div>
      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        <Feature icon={<FileKey2 className="h-4 w-4" />} title="Verified" detail="Every included app tool is checked before it can run." />
        <Feature icon={<HardDrive className="h-4 w-4" />} title="Local" detail="Core editing and media tools are installed on this PC." />
        <Feature icon={<LockKeyhole className="h-4 w-4" />} title="Private" detail="Optional online AI stays off until you choose it." />
      </div>
      <div className="mt-6 flex flex-wrap gap-3">
        <button type="button" autoFocus onClick={onContinue} disabled={busy} className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white hover:bg-accent-hover disabled:cursor-wait disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-accent/70">
          {busy ? <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" /> : <ArrowRight className="h-4 w-4" aria-hidden="true" />}
          {busy ? "Checking system…" : "Start system check"}
        </button>
        {resumeAvailable ? <button type="button" onClick={onResume} disabled={busy} className="inline-flex items-center gap-2 rounded-lg border border-amber-400/40 px-4 py-2.5 text-sm font-medium text-amber-100 hover:bg-amber-500/10 disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-accent/70"><RotateCcw className="h-4 w-4" aria-hidden="true" /> Resume saved setup</button> : null}
        {!setupRequired && !engineReady ? <button type="button" onClick={onManage} className="inline-flex items-center gap-2 rounded-lg border border-surface-border px-4 py-2.5 text-sm font-medium text-gray-200 hover:border-accent focus:outline-none focus:ring-2 focus:ring-accent/70"><Cpu className="h-4 w-4" aria-hidden="true" /> Review components</button> : null}
      </div>
    </div>
  );
}

function SystemCheckStep({ checks, busy, onRun, onContinue }: { checks: SetupSystemChecksResult | null; busy: boolean; onRun: () => void; onContinue: () => void }) {
  const blocking = checks?.checks.some(check => check.severity === "error") ?? false;
  return (
    <div>
      <StepHeading icon={<ClipboardCopy className="h-5 w-5" />} title="Check this PC" detail="We’ll make sure Windows, free space, and app permissions are ready before installing anything." />
      {!checks ? <button type="button" onClick={onRun} disabled={busy} className="mt-6 inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white hover:bg-accent-hover focus:outline-none focus:ring-2 focus:ring-accent/70"><RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} aria-hidden="true" /> Run checks</button> : <>
        <div className="mt-5 space-y-2" role="status" aria-live="polite">
          {checks.checks.map(check => <CheckRow key={check.id} check={check} />)}
        </div>
        <div className="mt-6 flex flex-wrap gap-3">
          <button type="button" onClick={onRun} disabled={busy} className="inline-flex items-center gap-2 rounded-lg border border-surface-border px-4 py-2.5 text-sm font-medium text-gray-200 hover:border-accent focus:outline-none focus:ring-2 focus:ring-accent/70"><RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} aria-hidden="true" /> Re-run checks</button>
          <button type="button" onClick={onContinue} disabled={blocking} className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-accent/70">Continue to components <ArrowRight className="h-4 w-4" aria-hidden="true" /></button>
        </div>
        {blocking ? <p className="mt-3 text-xs text-amber-200">Resolve the blocking checks above, then run the check again. Warnings can be continued with the offline path.</p> : null}
      </>}
    </div>
  );
}

function ChooseComponentsStep({ catalog, state, busy, hasRequiredCatalog, checksHealthy, reviewReady, bundledCatalog, onToggle, onImport, onUseBundled, onRefresh, onContinue }: {
  catalog: SetupCatalog | null;
  state: SetupState;
  busy: boolean;
  hasRequiredCatalog: boolean;
  checksHealthy: boolean;
  reviewReady: boolean;
  bundledCatalog: BundledCatalogDiscovery | null;
  onToggle: (entry: SetupCatalogEntry) => void;
  onImport: () => void;
  onUseBundled: () => void;
  onRefresh: () => void;
  onContinue: () => void;
}) {
  const entries = DEFAULT_COMPONENT_CARDS.map(card => catalogEntryFor(catalog, card.componentId) ?? {
    ...card,
    availability: "catalog-only" as const,
    artifactBytes: 0,
    licenseVersion: "",
    licenseName: "",
    sourceUrl: null,
    unavailableReason: "Import a signed catalog to see whether this component is available.",
    manifest: null,
  });
  return (
    <div>
      <StepHeading icon={<Cpu className="h-5 w-5" />} title="Choose components" detail="Core engine and FFmpeg are required. Optional packs are selectable only when a signed artifact is present; catalog-only entries never appear installed." />
      <div className="mt-5 space-y-3">
        {entries.map(entry => <ComponentChoice key={entry.componentId} entry={entry} selected={entry.required || optionalComponentIsSelected(state, entry.componentId)} onToggle={() => onToggle(entry)} />)}
      </div>
      {!hasRequiredCatalog ? <div className="mt-5 rounded-xl border border-amber-400/30 bg-amber-500/10 p-4 text-sm text-amber-100"><div className="flex items-start gap-2"><CircleHelp className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" /><div><p className="font-semibold">A signed catalog is needed before install</p><p className="mt-1 text-xs leading-5 text-amber-100/75">Use the bundled lecturer catalog or import one approved offline catalog. The selected file is signature-checked before any manifest reaches the component manager.</p></div></div></div> : !checksHealthy ? <div className="mt-5 rounded-xl border border-rose-400/30 bg-rose-500/10 p-4 text-sm text-rose-100"><div className="flex items-start gap-2"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" /><div><p className="font-semibold">Run the current activation check before review</p><p className="mt-1 text-xs leading-5 text-rose-100/75">The exact machine writer transaction or its bounded repair helper is not ready. Re-run the system check after Repair completes.</p></div></div></div> : !reviewReady ? <div className="mt-5 rounded-xl border border-amber-400/30 bg-amber-500/10 p-4 text-sm text-amber-100"><div className="flex items-start gap-2"><CircleHelp className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" /><div><p className="font-semibold">Review is paused until the current catalog is valid</p><p className="mt-1 text-xs leading-5 text-amber-100/75">The last catalog attempt was rejected. Import the bundled lecturer catalog or another approved signed JSON file to clear the error.</p></div></div></div> : null}
      <div className="mt-6 flex flex-wrap gap-3">
        <button type="button" onClick={() => void onImport()} disabled={busy} className="inline-flex items-center gap-2 rounded-lg border border-surface-border px-4 py-2.5 text-sm font-medium text-gray-200 hover:border-accent focus:outline-none focus:ring-2 focus:ring-accent/70"><Upload className="h-4 w-4" aria-hidden="true" /> Import signed catalog</button>
        {bundledCatalog?.available ? <button type="button" onClick={onUseBundled} disabled={busy} className="inline-flex items-center gap-2 rounded-lg border border-emerald-400/30 bg-emerald-500/10 px-4 py-2.5 text-sm font-medium text-emerald-100 hover:bg-emerald-500/20 focus:outline-none focus:ring-2 focus:ring-accent/70"><ShieldCheck className="h-4 w-4" aria-hidden="true" /> Use bundled lecturer catalog</button> : null}
        <button type="button" onClick={onRefresh} disabled={busy} className="inline-flex items-center gap-2 rounded-lg border border-surface-border px-4 py-2.5 text-sm font-medium text-gray-200 hover:border-accent disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-accent/70"><CloudDownload className="h-4 w-4" aria-hidden="true" /> Refresh production catalog</button>
        <button type="button" onClick={onContinue} disabled={!reviewReady || busy} className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-accent/70">Review setup <ArrowRight className="h-4 w-4" aria-hidden="true" /></button>
      </div>
    </div>
  );
}

function ReviewStep({ catalog, selectedIds, licenseAccepted, ready, busy, onLicenseAccepted, onBack, onInstall }: {
  catalog: SetupCatalog | null;
  selectedIds: string[];
  licenseAccepted: boolean;
  ready: boolean;
  busy: boolean;
  onLicenseAccepted: (value: boolean) => void;
  onBack: () => void;
  onInstall: () => void;
}) {
  const entries = selectedIds.map(id => catalogEntryFor(catalog, id)).filter((entry): entry is SetupCatalogEntry => Boolean(entry));
  const totalBytes = entries.reduce((sum, entry) => sum + entry.artifactBytes, 0);
  const licenses = entries.filter(entry => entry.licenseVersion);
  return (
    <div>
      <StepHeading icon={<FileCheck2 className="h-5 w-5" />} title="Review what will be installed" detail="Setup verifies each included tool, tests it, and keeps your current working version safe during updates." />
      <div className="mt-5 grid gap-3 sm:grid-cols-3"><ReviewStat label="Components" value={`${entries.length}`} /><ReviewStat label="Download" value={formatBytes(totalBytes)} /><ReviewStat label="Rollback" value="Previous version retained" /></div>
      <div className="mt-5 space-y-2">{entries.map(entry => <div key={entry.componentId} className="flex items-center justify-between gap-3 rounded-lg border border-surface-border bg-surface-overlay px-3 py-3 text-sm"><span className="font-medium text-white">{entry.displayName}{entry.required ? <span className="ml-2 text-[10px] uppercase tracking-wide text-accent">Required</span> : null}</span><span className="text-xs text-gray-400">{formatBytes(entry.artifactBytes)} · {entry.licenseName || "License in manifest"}</span></div>)}</div>
      <label className="mt-5 flex items-start gap-3 rounded-xl border border-surface-border bg-surface-overlay p-4 text-sm text-gray-300"><input type="checkbox" checked={licenseAccepted} onChange={event => onLicenseAccepted(event.target.checked)} className="mt-0.5 h-4 w-4 rounded border-gray-500 bg-surface accent-accent" /><span>I have reviewed the component source and license information for this catalog. I understand that setup installs only signed artifacts from the selected channel.</span></label>
      {licenses.length > 0 ? <p className="mt-3 text-xs text-gray-500">License versions recorded: {licenses.map(entry => `${entry.componentId} ${entry.licenseVersion}`).join(" · ")}</p> : null}
      <div className="mt-6 flex flex-wrap gap-3"><button type="button" onClick={onBack} className="inline-flex items-center gap-2 rounded-lg border border-surface-border px-4 py-2.5 text-sm font-medium text-gray-200 hover:border-accent focus:outline-none focus:ring-2 focus:ring-accent/70"><ArrowLeft className="h-4 w-4" aria-hidden="true" /> Back</button><button type="button" onClick={onInstall} disabled={!licenseAccepted || !ready || busy} title={!ready ? "Run checks again after importing a verified catalog and repairing the writer if needed" : undefined} className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-accent/70"><Download className="h-4 w-4" aria-hidden="true" /> Install selected components</button></div>
    </div>
  );
}

function OperationStep({ stage, progress, progressByOperation, transferMetrics, paused, cancelRequested, selectedIds, busy, error, onPause, onResume, onCancel, onRetry, onDiagnostics }: {
  stage: SetupStage;
  progress: ReturnType<typeof aggregateProgress>;
  progressByOperation: Record<string, ComponentProgress>;
  transferMetrics: Record<string, { speedBytesPerSecond: number; etaSeconds: number | null }>;
  paused: boolean;
  cancelRequested: boolean;
  selectedIds: string[];
  busy: boolean;
  error: SetupError | null;
  onPause: () => void;
  onResume: () => void;
  onCancel: () => void;
  onRetry: () => void;
  onDiagnostics: () => void;
}) {
  const metrics = Object.values(transferMetrics);
  const speed = metrics.reduce((sum, metric) => sum + metric.speedBytesPerSecond, 0);
  const eta = speed > 0 && progress.totalBytes > progress.bytesDownloaded
    ? (progress.totalBytes - progress.bytesDownloaded) / speed
    : null;
  return (
    <div>
      <StepHeading icon={stage === "download" ? <Download className="h-5 w-5" /> : stage === "verify" ? <FileCheck2 className="h-5 w-5" /> : <ShieldCheck className="h-5 w-5" />} title={stage === "download" ? "Downloading components" : stage === "verify" ? "Verifying signed artifacts" : "Installing and activating"} detail={stage === "download" ? "Downloads are resumable and stay in the ProgramData staging perimeter until verified." : stage === "verify" ? "Hashes, signatures, archive inventory, and compatibility are checked before activation." : "The manager is running the signed self-test and committing the active version atomically."} />
      <div className="mt-6" role="status" aria-live="polite"><div className="flex items-end justify-between gap-3"><span className="text-3xl font-semibold text-white">{progress.percent.toFixed(1)}%</span><span className="text-xs text-gray-400">{formatBytes(progress.bytesDownloaded)}{progress.totalBytes > 0 ? ` / ${formatBytes(progress.totalBytes)}` : ""}</span></div><div className="mt-3 h-3 overflow-hidden rounded-full bg-surface-overlay" aria-label={`Overall setup progress ${progress.percent.toFixed(1)} percent`} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress.percent}><div className="h-full rounded-full bg-accent transition-[width] duration-300 motion-reduce:transition-none" style={{ width: `${Math.min(100, progress.percent)}%` }} /></div><div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-400"><span>{progress.message}</span>{speed > 0 ? <span>{formatBytes(speed)}/s</span> : null}{eta !== null ? <span>About {formatDuration(eta)} remaining</span> : null}</div></div>
      <div className="mt-5 space-y-2">{selectedIds.map(id => { const latest = Object.values(progressByOperation).filter(item => item.componentId === id).slice(-1)[0]; return <div key={id} className="flex items-center justify-between gap-3 rounded-lg border border-surface-border bg-surface-overlay px-3 py-3 text-sm"><div className="flex min-w-0 items-center gap-2">{latest?.state === "active" ? <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" aria-hidden="true" /> : latest?.state === "failed" ? <XCircle className="h-4 w-4 shrink-0 text-rose-300" aria-hidden="true" /> : <RefreshCw className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />}<span className="truncate text-white">{displayComponentName(id)}</span></div><span className="text-xs text-gray-400">{latest ? `${latest.percent.toFixed(0)}% · ${latest.state}` : "Queued"}</span></div>; })}</div>
      {error ? <ErrorCallout error={error} technicalOpen={false} onToggleTechnical={() => undefined} onRetry={onRetry} onDiagnostics={onDiagnostics} /> : null}
      <div className="mt-6 flex flex-wrap gap-3">{busy && stage === "download" ? paused ? <button type="button" onClick={onResume} disabled={cancelRequested} className="inline-flex items-center gap-2 rounded-lg border border-accent/50 px-4 py-2.5 text-sm font-medium text-accent-100 hover:bg-accent/10 disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-accent/70"><Play className="h-4 w-4" aria-hidden="true" /> Resume download</button> : <button type="button" onClick={onPause} disabled={cancelRequested} className="inline-flex items-center gap-2 rounded-lg border border-surface-border px-4 py-2.5 text-sm font-medium text-gray-200 hover:border-accent disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-accent/70"><Pause className="h-4 w-4" aria-hidden="true" /> Pause download</button> : null}{busy ? <button type="button" onClick={onCancel} disabled={cancelRequested} className="inline-flex items-center gap-2 rounded-lg border border-amber-400/40 px-4 py-2.5 text-sm font-medium text-amber-100 hover:bg-amber-500/10 disabled:cursor-wait disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-accent/70"><XCircle className="h-4 w-4" aria-hidden="true" /> {cancelRequested ? "Finishing safely…" : "Cancel safely"}</button> : null}</div>
    </div>
  );
}

function ReadinessStep({ supervisor, busy, cancelRequested, error, onCancel, onRetry, onDiagnostics }: { supervisor: SupervisorStatus | null; busy: boolean; cancelRequested: boolean; error: SetupError | null; onCancel: () => void; onRetry: () => void; onDiagnostics: () => void }) {
  const ready = canLaunchEditor(supervisor);
  const blocked = ["setup-required", "component-repair-required", "repair-required", "storage-blocked", "launch-blocked", "protocol-incompatible", "session-auth-failed", "fatal-shell-failure", "fatal"].includes(supervisor?.state ?? "");
  return <div><StepHeading icon={<Cpu className="h-5 w-5" />} title="Verify and Start" detail="We’re doing a final local check, then your workspace will open." /><div className={`mt-6 rounded-xl border p-5 ${ready ? "border-emerald-400/30 bg-emerald-500/10" : blocked ? "border-rose-400/30 bg-rose-500/10" : "border-amber-400/30 bg-amber-500/10"}`} role="status" aria-live="polite"><div className="flex items-start gap-3">{ready ? <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-300" aria-hidden="true" /> : <RefreshCw className={`h-5 w-5 shrink-0 text-amber-200 ${busy ? "animate-spin" : ""}`} aria-hidden="true" />}<div><p className="font-semibold text-white">{ready ? "Your workspace is ready" : blocked ? "A quick repair is needed" : "Starting your workspace"}</p><p className="mt-2 text-sm leading-6 text-gray-300">{ready ? "All required editing tools passed their checks." : blocked ? "Your projects are safe. Open recovery details to continue." : "This usually takes only a moment."}</p>{blocked ? <details className="mt-3"><summary className="cursor-pointer text-xs text-gray-400">Recovery details</summary><p className="mt-2 text-xs text-amber-100">{supervisor?.detail}</p></details> : null}</div></div></div>{busy ? <button type="button" onClick={onCancel} disabled={cancelRequested} className="mt-5 inline-flex items-center gap-2 rounded-lg border border-amber-400/40 px-4 py-2.5 text-sm font-medium text-amber-100 hover:bg-amber-500/10 disabled:cursor-wait disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-accent/70"><XCircle className="h-4 w-4" aria-hidden="true" /> {cancelRequested ? "Stopping safely…" : "Cancel safely"}</button> : null}{error ? <ErrorCallout error={error} technicalOpen={false} onToggleTechnical={() => undefined} onRetry={onRetry} onDiagnostics={onDiagnostics} /> : null}</div>;
}

function CompletionStep({ supervisor, statuses, engineReady, onLaunchEditor, onManage }: { supervisor: SupervisorStatus | null; statuses: ComponentStatusResult[]; engineReady: boolean; onLaunchEditor: () => void; onManage: () => void }) {
  return <div><div className="rounded-xl border border-emerald-400/30 bg-emerald-500/10 p-5"><div className="flex items-start gap-3"><CheckCircle2 className="h-6 w-6 shrink-0 text-emerald-300" aria-hidden="true" /><div><h3 className="text-lg font-semibold text-white">Setup complete</h3><p className="mt-2 text-sm leading-6 text-emerald-50/80">The required components are active, verified, and owned by the authenticated supervisor. Optional catalog-only packs remain clearly unavailable.</p></div></div></div><div className="mt-5 grid gap-3 sm:grid-cols-2">{statuses.filter(status => REQUIRED_COMPONENT_IDS.includes(status.id as typeof REQUIRED_COMPONENT_IDS[number])).map(status => <div key={status.id} className="rounded-lg border border-surface-border bg-surface-overlay p-3"><div className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-emerald-400" aria-hidden="true" /><span className="text-sm font-medium text-white">{status.displayName ?? displayComponentName(status.id)}</span></div><p className="mt-1 text-xs text-gray-400">{status.version ? `Version ${status.version}` : status.detail}</p></div>)}</div><div className="mt-6 flex flex-wrap gap-3"><button type="button" onClick={onLaunchEditor} disabled={!engineReady} className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-accent/70"><Play className="h-4 w-4" aria-hidden="true" /> Launch editor</button><button type="button" onClick={onManage} className="inline-flex items-center gap-2 rounded-lg border border-surface-border px-4 py-2.5 text-xs font-medium text-gray-200 hover:border-accent focus:outline-none focus:ring-2 focus:ring-accent/70"><Cpu className="h-3.5 w-3.5" aria-hidden="true" /> Manage components</button></div><p className="mt-4 text-xs text-gray-500">Supervisor: {supervisor?.state ?? "not reported"} · Authenticated readiness is required each launch.</p><ProviderOnboardingPanel /></div>;
}

function ManagementView({ catalog: _catalog, statuses, supervisor, error, onBack, onRefresh, onError, onChannelChange, onSelectedStatus }: { catalog: SetupCatalog | null; statuses: ComponentStatusResult[]; supervisor: SupervisorStatus | null; error: SetupError | null; onBack: () => void; onRefresh: () => void; onError: (error: SetupError) => void; onChannelChange: (channel: "stable" | "beta" | "nightly") => void; onSelectedStatus: (status: ComponentStatusResult) => void }) {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [channel, setChannel] = useState<"stable" | "beta" | "nightly">(_catalog?.channel ?? "stable");
  const engineRunning = canLaunchEditor(supervisor);
  const perform = async (id: string, action: "repair" | "rollback" | "remove") => {
    setBusyId(id);
    try {
      if (action === "repair") await componentManager.repair(id, false);
      if (action === "rollback") await componentManager.rollback(id, false);
      if (action === "remove") {
        if (engineRunning) throw { code: "ENGINE_NOT_RUNNING", message: "Stop the authenticated engine before removing optional components." };
        await componentManager.uninstall(id);
      }
      onRefresh();
    } catch (operationError) {
      onError(normalizeSetupError(operationError));
    } finally {
      setBusyId(null);
    }
  };
  return <div className="mt-6 overflow-hidden rounded-2xl border border-surface-border bg-surface-raised p-5 sm:p-7" aria-labelledby="management-title"><div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between"><div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">Component management</p><h2 id="management-title" className="mt-2 text-2xl font-semibold text-white">Versions, health, and repair</h2><p className="mt-2 max-w-2xl text-sm leading-6 text-gray-400">Required components cannot be removed while the engine is running. Repair and rollback re-use the signed manager and never delete user projects or exports.</p></div><button type="button" onClick={onBack} className="inline-flex items-center gap-2 self-start rounded-lg border border-surface-border px-3 py-2 text-xs font-medium text-gray-200 hover:border-accent focus:outline-none focus:ring-2 focus:ring-accent/70"><ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" /> Back to Setup Center</button></div>{error ? <div role="alert" className="mt-4 rounded-lg border border-amber-400/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">{error.message}</div> : null}<div className="mt-6 flex flex-wrap items-center gap-3 rounded-xl border border-surface-border bg-surface-overlay p-4"><label className="text-xs font-medium text-gray-300" htmlFor="setup-channel">Update channel</label><select id="setup-channel" value={channel} onChange={event => { const next = event.target.value as typeof channel; setChannel(next); onChannelChange(next); }} className="rounded-lg border border-surface-border bg-surface-raised px-3 py-2 text-xs text-white focus:outline-none focus:ring-2 focus:ring-accent/70"><option value="stable">Stable</option><option value="beta">Beta</option><option value="nightly">Nightly</option></select><span className="text-xs text-gray-500">Channel changes apply to the next signed catalog refresh.</span></div><div className="mt-5 space-y-3">{statuses.length === 0 ? <p className="rounded-lg border border-surface-border bg-surface-overlay p-4 text-sm text-gray-400">No catalog status is available yet. Import a signed catalog to discover installable versions.</p> : statuses.map(status => { const required = REQUIRED_COMPONENT_IDS.includes(status.id as typeof REQUIRED_COMPONENT_IDS[number]); const hasRollback = status.remediationCodes.includes("UPDATE_ROLLBACK_AVAILABLE"); return <div key={status.id} className="rounded-xl border border-surface-border bg-surface-overlay p-4"><div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between"><button type="button" onClick={() => onSelectedStatus(status)} className="min-w-0 text-left focus:outline-none focus:ring-2 focus:ring-accent/70"><div className="flex items-center gap-2">{status.state === "active" ? <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" aria-hidden="true" /> : status.state === "repair-required" ? <AlertCircle className="h-4 w-4 shrink-0 text-amber-300" aria-hidden="true" /> : <Info className="h-4 w-4 shrink-0 text-blue-300" aria-hidden="true" />}<span className="truncate text-sm font-semibold text-white">{status.displayName ?? displayComponentName(status.id)}</span><span className="rounded-full bg-surface-raised px-2 py-0.5 text-[10px] uppercase tracking-wide text-gray-400">{required ? "Required" : "Optional"}</span></div><p className="mt-2 text-xs leading-5 text-gray-400">{status.detail}</p><p className="mt-1 text-xs text-gray-500">{status.version ? `Installed version ${status.version}` : "No active version"}{status.downloadedBytes ? ` · ${formatBytes(status.downloadedBytes)} staged` : ""}</p></button><div className="flex flex-wrap gap-2"><button type="button" disabled={busyId === status.id} onClick={() => void perform(status.id, "repair")} className="inline-flex items-center gap-1.5 rounded-lg border border-surface-border px-3 py-2 text-xs text-gray-200 hover:border-accent disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-accent/70"><Wrench className="h-3.5 w-3.5" aria-hidden="true" /> Repair</button>{hasRollback ? <button type="button" disabled={busyId === status.id} onClick={() => void perform(status.id, "rollback")} className="inline-flex items-center gap-1.5 rounded-lg border border-amber-400/30 px-3 py-2 text-xs text-amber-100 hover:bg-amber-500/10 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-accent/70"><RotateCcw className="h-3.5 w-3.5" aria-hidden="true" /> Roll back</button> : null}{!required ? <button type="button" disabled={busyId === status.id || engineRunning} title={engineRunning ? "Stop the engine before removing an optional component" : "Remove optional component"} onClick={() => void perform(status.id, "remove")} className="inline-flex items-center gap-1.5 rounded-lg border border-rose-400/30 px-3 py-2 text-xs text-rose-100 hover:bg-rose-500/10 disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-accent/70"><Trash2 className="h-3.5 w-3.5" aria-hidden="true" /> Remove</button> : null}</div></div></div>; })}</div><button type="button" onClick={onRefresh} className="mt-5 inline-flex items-center gap-2 rounded-lg border border-surface-border px-3 py-2 text-xs font-medium text-gray-200 hover:border-accent focus:outline-none focus:ring-2 focus:ring-accent/70"><RefreshCw className="h-3.5 w-3.5" aria-hidden="true" /> Refresh installed state</button></div>;
}

function CatalogCard({ catalogInfo, bundledCatalog, onImport, onUseBundled, onRefresh, busy }: { catalogInfo: SetupCatalogInfo | null; bundledCatalog: BundledCatalogDiscovery | null; onImport: () => void; onUseBundled: () => void; onRefresh: () => void; busy: boolean }) {
  return <div className="rounded-xl border border-surface-border bg-surface-overlay p-4"><div className="flex items-center gap-2"><FileKey2 className="h-4 w-4 text-accent" aria-hidden="true" /><p className="text-sm font-semibold text-white">Catalog source</p></div>{catalogInfo ? <><p className="mt-2 text-xs text-gray-300">{catalogInfo.source === "production" ? "Production HTTPS catalog" : "Signed offline import"} · {catalogInfo.catalog.channel}</p><p className="mt-1 text-[11px] text-gray-500">Verified {new Date(catalogInfo.verifiedAtEpochMs).toLocaleString()} · {catalogInfo.catalog.entries.length} entries</p></> : <p className="mt-2 text-xs leading-5 text-gray-400">No trusted catalog is loaded yet. The default is the bundled lecturer catalog when present; otherwise choose one approved offline JSON file.</p>}{bundledCatalog?.available ? <p className="mt-2 text-[11px] text-emerald-200">Bundled lecturer catalog is ready as the default.</p> : null}<div className="mt-3 flex flex-wrap gap-2"><button type="button" onClick={() => void onImport()} disabled={busy} className="inline-flex items-center gap-1.5 rounded-md border border-surface-border px-2.5 py-1.5 text-[11px] font-medium text-gray-200 hover:border-accent disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-accent/70"><Upload className="h-3 w-3" aria-hidden="true" /> Browse one JSON</button>{bundledCatalog?.available ? <button type="button" onClick={onUseBundled} disabled={busy} className="inline-flex items-center gap-1.5 rounded-md border border-emerald-400/30 px-2.5 py-1.5 text-[11px] font-medium text-emerald-100 hover:bg-emerald-500/10 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-accent/70"><ShieldCheck className="h-3 w-3" aria-hidden="true" /> Use bundled</button> : null}<button type="button" onClick={onRefresh} disabled={busy} className="inline-flex items-center gap-1.5 rounded-md border border-surface-border px-2.5 py-1.5 text-[11px] font-medium text-gray-200 hover:border-accent disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-accent/70"><RefreshCw className="h-3 w-3" aria-hidden="true" /> Refresh HTTPS</button></div></div>;
}

function ProgressSummary({ stage, progress, selectedCount }: { stage: SetupStage; progress: ReturnType<typeof aggregateProgress>; selectedCount: number }) {
  const completed = stage === "complete";
  const percent = completed ? 100 : progress.percent;
  const message = completed ? "Setup complete" : progress.message;
  return <div className="rounded-xl border border-surface-border bg-surface-overlay p-4"><div className="flex items-center justify-between gap-2"><p className="text-xs font-semibold uppercase tracking-[0.15em] text-gray-500">Current step</p><span className="text-[11px] text-accent">{setupStepLabel(stage)}</span></div><p className="mt-3 text-sm font-semibold text-white">{selectedCount > 0 ? `${selectedCount} installable component${selectedCount === 1 ? "" : "s"} selected` : completed ? "Core tools installed" : "Preparing your tools"}</p><div className="mt-3 h-2 overflow-hidden rounded-full bg-surface-raised"><div className="h-full rounded-full bg-accent motion-reduce:transition-none" style={{ width: `${percent}%` }} /></div><p className="mt-2 text-xs text-gray-400">{percent.toFixed(1)}% · {message}</p></div>;
}

function StorageBoundaryCard({ bootstrap }: { bootstrap: DesktopV2BootstrapResult | null }) {
  return <div className="rounded-xl border border-surface-border bg-surface-overlay p-4"><div className="flex items-center gap-2"><HardDrive className="h-4 w-4 text-accent" aria-hidden="true" /><p className="text-sm font-semibold text-white">Storage boundary</p></div><p className="mt-2 text-xs leading-5 text-gray-400">The shell stays immutable, verified components use the per-machine store, and projects plus settings stay with your Windows user.</p>{bootstrap?.paths ? <details className="mt-3"><summary className="cursor-pointer text-[11px] text-gray-500">Advanced path details</summary><p className="mt-2 break-all text-[10px] text-gray-500">Components: {bootstrap.paths.sharedComponents}</p></details> : null}</div>;
}

function ComponentChoice({ entry, selected, onToggle }: { entry: SetupCatalogEntry; selected: boolean; onToggle: () => void }) {
  const installable = catalogEntryIsInstallable(entry);
  return <div className={`rounded-xl border p-4 ${selected ? "border-accent/50 bg-accent/10" : "border-surface-border bg-surface-overlay"}`}><div className="flex items-start gap-3"><div className="pt-0.5">{entry.required ? <CheckCircle2 className="h-5 w-5 text-accent" aria-hidden="true" /> : <input type="checkbox" checked={selected} disabled={!installable} onChange={onToggle} aria-label={`Select ${entry.displayName}`} className="h-4 w-4 rounded border-gray-500 bg-surface accent-accent focus:ring-accent" />}</div><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><p className="text-sm font-semibold text-white">{entry.displayName}</p><span className={`rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wide ${entry.required ? "bg-accent/20 text-accent-100" : installable ? "bg-emerald-500/10 text-emerald-200" : "bg-surface-raised text-gray-400"}`}>{entry.required ? "Required" : entry.availability === "available" ? "Optional" : "Catalog only"}</span></div><p className="mt-1 text-xs leading-5 text-gray-400">{entry.description}</p>{entry.availability !== "available" ? <p className="mt-2 text-xs text-amber-200/80">{entry.unavailableReason ?? "A signed release artifact is not available yet."}</p> : <p className="mt-2 text-[11px] text-gray-500">{formatBytes(entry.artifactBytes)} · {entry.licenseName || "License details in manifest"}</p>}</div></div></div>;
}

function CheckRow({ check }: { check: SetupSystemCheck }) {
  const [open, setOpen] = useState(false);
  const icon = check.severity === "pass" ? <CheckCircle2 className="h-4 w-4 text-emerald-400" aria-hidden="true" /> : check.severity === "error" ? <XCircle className="h-4 w-4 text-rose-300" aria-hidden="true" /> : check.severity === "warning" ? <AlertCircle className="h-4 w-4 text-amber-300" aria-hidden="true" /> : <Info className="h-4 w-4 text-blue-300" aria-hidden="true" />;
  return <div className="rounded-lg border border-surface-border bg-surface-overlay p-3"><div className="flex items-start gap-3"><span className="mt-0.5">{icon}</span><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><p className="text-sm font-medium text-white">{check.label}</p><span className="rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wide text-gray-400">{check.severity}</span></div><p className="mt-1 text-xs leading-5 text-gray-400">{check.explanation}</p><p className="mt-1 text-xs text-accent-100">Next: {check.remediation}</p>{check.technicalDetail ? <button type="button" onClick={() => setOpen(value => !value)} className="mt-2 inline-flex items-center gap-1 text-[11px] text-gray-500 hover:text-gray-300 focus:outline-none focus:ring-2 focus:ring-accent/70"><ChevronDown className={`h-3 w-3 transition-transform motion-reduce:transition-none ${open ? "rotate-180" : ""}`} aria-hidden="true" /> Technical detail</button> : null}{open && check.technicalDetail ? <pre className="mt-2 overflow-auto rounded-md bg-black/20 p-2 text-[10px] leading-4 text-gray-500">{check.technicalDetail}</pre> : null}</div></div></div>;
}

function ErrorCallout({ error, technicalOpen, onToggleTechnical, onRetry, onDiagnostics }: { error: SetupError; technicalOpen: boolean; onToggleTechnical: () => void; onRetry: () => void; onDiagnostics: () => void }) {
  return <div role="alert" className="mt-5 rounded-xl border border-rose-400/35 bg-rose-500/10 p-4"><div className="flex items-start gap-3"><AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-rose-200" aria-hidden="true" /><div className="min-w-0 flex-1"><p className="text-sm font-semibold text-rose-50">{error.message}</p><p className="mt-1 text-xs leading-5 text-rose-100/70">{error.retryable ? "This step can be retried safely." : "No unverified component was activated."}</p><div className="mt-3 flex flex-wrap gap-2"><button type="button" onClick={onRetry} className="inline-flex items-center gap-1.5 rounded-md border border-rose-200/30 px-3 py-1.5 text-xs font-medium text-rose-50 hover:bg-rose-500/10 focus:outline-none focus:ring-2 focus:ring-accent/70"><RefreshCw className="h-3.5 w-3.5" aria-hidden="true" /> Retry</button><button type="button" onClick={onDiagnostics} className="inline-flex items-center gap-1.5 rounded-md border border-rose-200/30 px-3 py-1.5 text-xs font-medium text-rose-50 hover:bg-rose-500/10 focus:outline-none focus:ring-2 focus:ring-accent/70"><FileSearch className="h-3.5 w-3.5" aria-hidden="true" /> Diagnostics</button>{error.technicalDetail ? <button type="button" onClick={onToggleTechnical} className="inline-flex items-center gap-1.5 px-2 py-1.5 text-xs text-rose-100/70 hover:text-rose-50 focus:outline-none focus:ring-2 focus:ring-accent/70"><ChevronDown className={`h-3.5 w-3.5 ${technicalOpen ? "rotate-180" : ""}`} aria-hidden="true" /> Technical details</button> : null}</div>{technicalOpen && error.technicalDetail ? <pre className="mt-3 max-h-40 overflow-auto rounded-md bg-black/20 p-3 text-[10px] leading-4 text-rose-100/60">{error.code}: {error.technicalDetail}</pre> : null}</div></div></div>;
}

function StatusDetail({ status, onClose }: { status: ComponentStatusResult; onClose: () => void }) {
  return <div className="rounded-xl border border-surface-border bg-surface-overlay p-4"><div className="flex items-center justify-between gap-2"><p className="text-sm font-semibold text-white">Advanced component status</p><button type="button" onClick={onClose} aria-label="Close technical status" className="rounded p-1 text-gray-400 hover:text-white focus:outline-none focus:ring-2 focus:ring-accent/70"><XCircle className="h-4 w-4 text-gray-400 hover:text-white" aria-hidden="true" /></button></div><p className="mt-2 text-xs leading-5 text-gray-400">{status.detail}</p><details className="mt-2"><summary className="cursor-pointer text-[11px] text-gray-500">Show machine path</summary><p className="mt-2 break-all text-[10px] text-gray-500">{status.activePath ?? "No active path"}</p></details></div>;
}

function StepHeading({ icon, title, detail }: { icon: ReactNode; title: string; detail: string }) {
  return <div className="flex items-start gap-3"><span className="mt-0.5 text-accent" aria-hidden="true">{icon}</span><div><h3 className="text-lg font-semibold text-white">{title}</h3><p className="mt-2 max-w-2xl text-sm leading-6 text-gray-400">{detail}</p></div></div>;
}

function Feature({ icon, title, detail }: { icon: ReactNode; title: string; detail: string }) {
  return <div className="rounded-xl border border-surface-border bg-surface-overlay p-4"><div className="flex items-center gap-2 text-accent"><span aria-hidden="true">{icon}</span><span className="text-sm font-semibold text-white">{title}</span></div><p className="mt-2 text-xs leading-5 text-gray-400">{detail}</p></div>;
}

function ReviewStat({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border border-surface-border bg-surface-overlay p-3"><p className="text-[10px] uppercase tracking-wide text-gray-500">{label}</p><p className="mt-1 text-sm font-semibold text-white">{value}</p></div>;
}

function displayComponentName(id: string): string {
  if (id === "aive-engine") return "Core engine";
  if (id === "ffmpeg") return "FFmpeg";
  return id.replace(/[-_]/g, " ").replace(/\b\w/g, character => character.toUpperCase());
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "—";
  const units = ["B", "KiB", "MiB", "GiB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 1) return "less than a minute";
  const rounded = Math.round(seconds);
  if (rounded < 60) return `${rounded}s`;
  const minutes = Math.floor(rounded / 60);
  if (minutes < 60) return `${minutes}m`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}
