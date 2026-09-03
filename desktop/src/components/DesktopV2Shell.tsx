import { Component, useCallback, useEffect, useMemo, useState, type ErrorInfo, type ReactNode } from "react";
import {
  AlertTriangle,
  FileSearch,
  FileWarning,
  LockKeyhole,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import {
  DESKTOP_V2_PRODUCT_LINE,
  DESKTOP_V2_PRODUCT_NAME,
  getWebView2RuntimeStatus,
  normalizeShellFailure,
  redactDiagnosticText,
  type DesktopV2BootstrapResult,
  type ShellInfo,
  type SupervisorDiagnostics,
  type SupervisorStatus,
  type WebView2RuntimeStatus,
  supervisorStateLabel,
} from "../desktopV2";
import { componentManager, type ComponentStatusResult } from "../componentManager.ts";
import {
  defaultSetupState,
  canLaunchEditor,
  requiredComponentsReady,
  setupClient,
  type SetupImportResult,
  type SetupCatalogInfo,
  type SetupState,
} from "../setupCenter.ts";
import * as api from "../lib/api";
import { SetupCenterPanel } from "./SetupCenterPanel";
import { MigrationCleanupWizard } from "./MigrationCleanupWizard";
import { migrationClient, type LegacyInventory } from "../migration";
import { provisioningClient, routeNeedsSetup, type DesktopBootSnapshot, type FirstLaunchState } from "../provisioning";

type ShellPanel = "setup" | "diagnostics" | "migration";

type ErrorBoundaryProps = { children: ReactNode };
type ErrorBoundaryState = { hasError: boolean };

export class DesktopV2ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(_error: Error, _info: ErrorInfo) {
    // Technical details remain in the explicit redacted diagnostics flow.
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-screen items-center justify-center bg-surface px-6 text-gray-100">
          <div className="max-w-lg rounded-2xl border border-amber-400/30 bg-surface-raised p-6 text-center">
            <AlertTriangle className="mx-auto h-8 w-8 text-amber-300" aria-hidden="true" />
            <h1 className="mt-4 text-xl font-semibold text-white">Desktop shell needs recovery</h1>
            <p className="mt-2 text-sm leading-6 text-gray-400">The shell UI encountered a recoverable rendering error. Restart the shell and generate a redacted diagnostic snapshot if the problem continues.</p>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export function DesktopV2Shell({ onEngineReady }: { onEngineReady: () => void }) {
  const [shellInfo, setShellInfo] = useState<ShellInfo | null>(null);
  const [bootstrap, setBootstrap] = useState<DesktopV2BootstrapResult | null>(null);
  const [supervisor, setSupervisor] = useState<SupervisorStatus | null>(null);
  const [supervisorDiagnostics, setSupervisorDiagnostics] = useState<SupervisorDiagnostics | null>(null);
  const [statuses, setStatuses] = useState<ComponentStatusResult[]>([]);
  const [setupState, setSetupState] = useState<SetupState>(() => defaultSetupState());
  const [catalogInfo, setCatalogInfo] = useState<SetupCatalogInfo | null>(null);
  const [setupRequired, setSetupRequired] = useState(true);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<ReturnType<typeof normalizeShellFailure> | null>(null);
  const [panel, setPanel] = useState<ShellPanel>("setup");
  const [diagnosticMessage, setDiagnosticMessage] = useState<string | null>(null);
  const [migrationInventory, setMigrationInventory] = useState<LegacyInventory | null>(null);
  const [webview2, setWebview2] = useState<WebView2RuntimeStatus | null>(null);
  const [bootSnapshot, setBootSnapshot] = useState<DesktopBootSnapshot | null>(null);

  const loadShell = useCallback(async () => {
    setLoading(true);
    setFailure(null);
    setDiagnosticMessage(null);
    let nextBootstrap: DesktopV2BootstrapResult | null = null;
    let nextSetupState = setupState;
    let nextStatuses: ComponentStatusResult[] = [];
    let reconciledSnapshot: DesktopBootSnapshot;

    try {
      // This is the authority for the first render. It performs journal,
      // catalog, and component recovery before React receives any booleans.
      reconciledSnapshot = await provisioningClient.hydrate();
    } catch (error) {
      setFailure(normalizeShellFailure(error));
      setLoading(false);
      return;
    }

    try {
      const runtime = await getWebView2RuntimeStatus();
      setWebview2(runtime);
      if (!runtime.available) {
        setFailure({
          code: "WEBVIEW2_RUNTIME_REQUIRED",
          message: runtime.detail,
          remediationCodes: runtime.remediationCodes,
        });
      }
    } catch (error) {
      setFailure(normalizeShellFailure(error));
    }

    try {
      const info = await api.getShellInfo();
      setShellInfo(info);
    } catch (error) {
      setFailure(normalizeShellFailure(error));
    }

    try {
      nextBootstrap = await api.bootstrapDesktopV2Shell();
      setBootstrap(nextBootstrap);
      if (nextBootstrap.bootState === "recoverable-error") setPanel("diagnostics");
    } catch (error) {
      setFailure(normalizeShellFailure(error));
    }

    try {
      const legacy = await migrationClient.scan();
      setMigrationInventory(legacy.hasLegacyState ? legacy : null);
      if (legacy.hasLegacyState && !nextBootstrap?.bootState?.toString().includes("recoverable")) setPanel("migration");
    } catch {
      // Legacy discovery is bounded and read-only; a discovery failure never
      // blocks browser/Docker mode or the existing Setup Center.
      setMigrationInventory(null);
    }

    try {
      nextSetupState = await setupClient.getState();
      setSetupState(nextSetupState);
    } catch (error) {
      setFailure(normalizeShellFailure(error));
    }
    try {
      setCatalogInfo(await setupClient.getCatalog());
    } catch {
      // A stale or absent catalog is rendered as an actionable Setup Center
      // state; it must not prevent the base shell from opening.
      setCatalogInfo(null);
    }
    try {
      await componentManager.recover();
    } catch {
      // Recovery errors are surfaced by the status scan and Diagnostics.
    }
    try {
      const required = await Promise.all(["aive-engine", "ffmpeg"].map(id => componentManager.status(id)));
      nextStatuses = required.flat();
      setStatuses(nextStatuses);
    } catch {
      setStatuses([]);
    }

    const requiredReady = requiredComponentsReady(nextStatuses);
    const shouldSetup = routeNeedsSetup(reconciledSnapshot.route);
    setSetupRequired(shouldSetup);
    const persistedHealthyState = requiredReady && !nextSetupState.onboardingCompleted
      ? { ...nextSetupState, onboardingCompleted: true }
      : nextSetupState;
    if (persistedHealthyState !== nextSetupState) {
      try {
        nextSetupState = await setupClient.saveState(persistedHealthyState);
        setSetupState(nextSetupState);
      } catch {
        setSetupState(persistedHealthyState);
      }
    }

    try {
      let status = await api.getSupervisorStatus();
      const reconciledCoreReady = reconciledSnapshot.coreComponents.every(component => component.state === "active");
      if (reconciledCoreReady && reconciledSnapshot.shellBootState === "engine-available") {
        if ([
          "stopped",
          "cancelled-stopped",
          "component-repair-required",
          "repair-required",
          "storage-blocked",
          "launch-blocked",
          "protocol-incompatible",
          "session-auth-failed",
          "fatal-shell-failure",
          "fatal",
        ].includes(status.state)) {
          status = await api.startSupervisor();
        }
        const startupTerminalStates = [
          "setup-required",
          "component-repair-required",
          "repair-required",
          "storage-blocked",
          "launch-blocked",
          "protocol-incompatible",
          "session-auth-failed",
          "cancelled-stopped",
          "fatal-shell-failure",
          "fatal",
        ];
        // A repaired install can start quickly enough to emit readiness before
        // the post-hydration event listener subscribes. This bounded poll
        // closes that race without starting a second supervisor operation.
        for (let attempt = 0; attempt < 60 && !canLaunchEditor(status) && !startupTerminalStates.includes(status.state); attempt += 1) {
          await new Promise(resolve => window.setTimeout(resolve, 250));
          status = await api.getSupervisorStatus();
        }
        setSupervisor(status);
        try {
          setSupervisorDiagnostics(await api.getSupervisorDiagnostics());
        } catch {
          setSupervisorDiagnostics(null);
        }
        if (reconciledSnapshot.firstLaunch.completed && canLaunchEditor(status)) onEngineReady();
      } else {
        setSupervisor(status);
        try {
          setSupervisorDiagnostics(await api.getSupervisorDiagnostics());
        } catch {
          setSupervisorDiagnostics(null);
        }
      }
    } catch {
      setSupervisor(null);
      setSupervisorDiagnostics(null);
    } finally {
      try {
        const finalSnapshot = await provisioningClient.hydrate();
        setBootSnapshot(finalSnapshot);
        setSetupRequired(routeNeedsSetup(finalSnapshot.route));
        if (finalSnapshot.route === "ready") onEngineReady();
      } catch {
        setBootSnapshot(reconciledSnapshot);
      }
      setLoading(false);
    }
  }, [onEngineReady, setupState]);

  useEffect(() => {
    void loadShell();
    // Initial shell hydration intentionally runs once; later refreshes are
    // explicit so the Setup Center does not restart an active supervisor.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let cancelled = false;
    let unlisten: (() => void) | undefined;
    void (async () => {
      try {
        const { listen } = await import("@tauri-apps/api/event");
        const stopListening = await listen<SupervisorStatus>("desktop-engine-status", event => {
          if (cancelled) return;
          setSupervisor(event.payload);
          if (event.payload.engineReady) {
            void provisioningClient.hydrate().then(snapshot => {
              if (cancelled) return;
              setBootSnapshot(snapshot);
              setSetupRequired(routeNeedsSetup(snapshot.route));
              if (snapshot.route === "ready") onEngineReady();
            });
          }
        });
        if (cancelled) stopListening();
        else unlisten = stopListening;

        const stopHandoffListening = await listen<{ catalogPath: string | null; handoffRoot: string | null }>("desktop-v2-handoff-args", event => {
          const selectedCatalog = event.payload.catalogPath ?? (event.payload.handoffRoot ? `${event.payload.handoffRoot}\\Catalog\\offline-catalog.json` : null);
          if (cancelled || !selectedCatalog) return;
          void setupClient.importCatalogFile(selectedCatalog).then((result: SetupImportResult) => {
            if (!cancelled) setCatalogInfo(result.catalog);
          }).catch(() => {
            // The Setup Center exposes the redacted import error and Browse
            // fallback; a forwarded argument never bypasses its trust gate.
          });
        });
        if (cancelled) stopHandoffListening();
        else {
          const previous = unlisten;
          unlisten = () => { previous?.(); stopHandoffListening(); };
        }
      } catch {
        // Explicit refresh and the readiness poll remain available.
      }
    })();
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [onEngineReady, setupState.onboardingCompleted]);

  const displayInfo = shellInfo ?? bootstrap?.shellInfo ?? null;
  const bootLabel = useMemo(() => {
    if (loading) return "Starting shell";
    if (failure) return "Recoverable shell error";
    if (supervisor) return supervisorStateLabel(supervisor);
    return setupRequired ? "Setup required" : "Checking readiness";
  }, [failure, loading, setupRequired, supervisor]);

  const handleDiagnostics = async () => {
    setPanel("diagnostics");
    setDiagnosticMessage(null);
    try {
      try {
        setSupervisorDiagnostics(await api.getSupervisorDiagnostics());
      } catch {
        setSupervisorDiagnostics(null);
      }
      const result = await api.generateDesktopDiagnosticSnapshot();
      setDiagnosticMessage(result.created ? `Snapshot created at ${result.path ?? "the per-user Logs directory"}.` : result.detail);
    } catch {
      setDiagnosticMessage("Diagnostics could not be generated. Check the per-user LocalAppData permissions and try again.");
    }
  };

  const handleSetupComplete = (status: SupervisorStatus, state: SetupState) => {
    setSupervisor(status);
    setSetupState(state);
    setSetupRequired(false);
    void provisioningClient.hydrate().then(snapshot => {
      setBootSnapshot(snapshot);
      setSetupRequired(routeNeedsSetup(snapshot.route));
    });
  };

  const handleLaunchEditor = () => {
    if (bootSnapshot?.route === "ready" && canLaunchEditor(supervisor)) onEngineReady();
  };

  const handleOptionalAiChoice = async (choice: FirstLaunchState["optionalAiChoice"]) => {
    await provisioningClient.completeOptionalAiChoice(choice);
    const snapshot = await provisioningClient.hydrate();
    setBootSnapshot(snapshot);
    if (snapshot.route === "ready") onEngineReady();
  };

  if (!bootSnapshot) {
    return <BootHydrationScreen failure={failure} loading={loading} onRetry={() => void loadShell()} />;
  }

  return (
    <div className="flex h-screen min-h-[700px] flex-col overflow-hidden bg-surface text-gray-100">
      <header className="flex shrink-0 items-center justify-between border-b border-surface-border bg-surface-raised px-5 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent/20 text-accent ring-1 ring-accent/40"><ShieldCheck className="h-5 w-5" aria-hidden="true" /></div>
          <div><div className="text-sm font-semibold tracking-wide text-white">{displayInfo?.productName ?? DESKTOP_V2_PRODUCT_NAME}</div><div className="text-[11px] uppercase tracking-[0.18em] text-gray-500">{displayInfo?.productLine ?? DESKTOP_V2_PRODUCT_LINE} · Your creative workspace</div></div>
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-400"><span className="rounded-full border border-surface-border bg-surface-overlay px-3 py-1">v{displayInfo?.shellVersion ?? "2.0.0"}</span><span className={`hidden rounded-full border px-3 py-1 sm:inline-flex ${setupRequired ? "border-amber-400/30 bg-amber-500/10 text-amber-200" : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"}`}>{bootLabel}</span></div>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-64 shrink-0 border-r border-surface-border bg-surface-raised p-4 md:block">
          <p className="px-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-gray-500">Workspace</p>
          <nav className="mt-3 space-y-1" aria-label="Workspace">
            <ShellNavButton active={panel === "setup"} icon={<Wrench className="h-4 w-4" />} label="Setup" onClick={() => setPanel("setup")} />
            {migrationInventory ? <ShellNavButton active={panel === "migration"} icon={<ArchiveIcon />} label="Migration & Cleanup" onClick={() => setPanel("migration")} /> : null}
            <ShellNavButton active={panel === "diagnostics"} icon={<FileSearch className="h-4 w-4" />} label="Diagnostics" onClick={() => void handleDiagnostics()} />
          </nav>
          <div className="mt-8 rounded-xl border border-surface-border bg-surface-overlay p-3 text-xs leading-5 text-gray-400"><LockKeyhole className="mb-2 h-4 w-4 text-accent" aria-hidden="true" />Your local workspace and projects stay on this PC unless you choose to connect an online provider.</div>
          <div className="mt-3 rounded-xl border border-surface-border bg-surface-overlay p-3 text-xs leading-5 text-gray-500"><Settings2 className="mb-2 h-4 w-4 text-gray-400" aria-hidden="true" />You can revisit setup, optional AI, and repairs here at any time.</div>
        </aside>

        <main className="min-h-0 flex-1 overflow-auto">
          <div className="mx-auto max-w-6xl px-5 py-6 lg:px-8 lg:py-8">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between"><div><p className="text-xs font-semibold uppercase tracking-[0.2em] text-accent">AI Video Editor</p><h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">{bootSnapshot.friendlyTitle}</h1><p className="mt-3 max-w-2xl text-sm leading-6 text-gray-400">{bootSnapshot.friendlyDetail}</p></div><button type="button" onClick={() => void loadShell()} className="inline-flex items-center justify-center gap-2 rounded-lg border border-surface-border bg-surface-raised px-3 py-2 text-xs font-medium text-gray-200 hover:border-accent hover:text-white focus:outline-none focus:ring-2 focus:ring-accent/70"><RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} aria-hidden="true" /> Check again</button></div>
            {failure ? <ShellFailure failure={failure} onDiagnostics={() => void handleDiagnostics()} /> : null}
            {panel === "setup" ? bootSnapshot.route === "needs-optional-ai-choice" ? <OptionalAiChoicePanel onChoose={handleOptionalAiChoice} /> : <SetupCenterPanel bootstrap={bootstrap} supervisor={supervisor} initialStatuses={statuses} initialState={setupState} initialCatalog={catalogInfo} setupRequired={setupRequired} onSupervisorStatus={setSupervisor} onSetupComplete={handleSetupComplete} onLaunchEditor={handleLaunchEditor} onOpenDiagnostics={() => void handleDiagnostics()} /> : panel === "migration" && migrationInventory ? <MigrationCleanupWizard inventory={migrationInventory} onContinue={() => setPanel("setup")} /> : <DiagnosticsPanel bootstrap={bootstrap} supervisor={supervisor} supervisorDiagnostics={supervisorDiagnostics} webview2={webview2} message={diagnosticMessage} onGenerate={() => void handleDiagnostics()} />}
          </div>
        </main>
      </div>
    </div>
  );
}

function BootHydrationScreen({ failure, loading, onRetry }: { failure: ReturnType<typeof normalizeShellFailure> | null; loading: boolean; onRetry: () => void }) {
  return <div className="flex h-screen items-center justify-center bg-surface px-6 text-gray-100"><div className="w-full max-w-md rounded-2xl border border-surface-border bg-surface-raised p-7 text-center shadow-2xl"><div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-accent/15 text-accent"><ShieldCheck className="h-6 w-6" aria-hidden="true" /></div><p className="mt-5 text-xs font-semibold uppercase tracking-[0.2em] text-accent">AI Video Editor</p><h1 className="mt-2 text-2xl font-semibold text-white">{failure ? "We couldn’t finish opening the workspace" : "Opening your workspace"}</h1><p className="mt-3 text-sm leading-6 text-gray-400">{failure ? "Your projects are safe. Try the local readiness check again, or open recovery after the app starts." : "Checking your saved setup and local tools before anything is shown."}</p>{failure ? <button type="button" onClick={onRetry} className="mt-5 inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white"><RefreshCw className="h-4 w-4" aria-hidden="true" /> Try again</button> : <div className="mx-auto mt-6 h-1.5 w-48 overflow-hidden rounded-full bg-surface-overlay"><div className={`h-full w-1/2 rounded-full bg-accent ${loading ? "animate-pulse" : ""}`} /></div>}</div></div>;
}

function OptionalAiChoicePanel({ onChoose }: { onChoose: (choice: FirstLaunchState["optionalAiChoice"]) => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const choose = async (choice: FirstLaunchState["optionalAiChoice"]) => {
    setBusy(true);
    try { await onChoose(choice); } finally { setBusy(false); }
  };
  return <section className="mt-6 rounded-2xl border border-surface-border bg-surface-raised p-6 sm:p-8"><p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">Optional AI Setup</p><h2 className="mt-2 text-2xl font-semibold text-white">How would you like to use AI?</h2><p className="mt-2 max-w-2xl text-sm leading-6 text-gray-400">The editor is ready. This choice is optional and can be changed later in Settings.</p><div className="mt-6 grid gap-3 sm:grid-cols-3"><ChoiceCard title="Work locally" detail="Use local tools and add transcription models only when you confirm each download." onClick={() => void choose("local")} disabled={busy} /><ChoiceCard title="Connect a provider" detail="Add a supported provider later using Windows protected credential storage." onClick={() => void choose("cloud")} disabled={busy} /><ChoiceCard title="Decide later" detail="Open the editor now without configuring optional AI." onClick={() => void choose("decide-later")} disabled={busy} /></div></section>;
}

function ChoiceCard({ title, detail, onClick, disabled }: { title: string; detail: string; onClick: () => void; disabled: boolean }) {
  return <button type="button" onClick={onClick} disabled={disabled} className="rounded-xl border border-surface-border bg-surface-overlay p-4 text-left transition-colors hover:border-accent hover:bg-accent/10 disabled:opacity-50"><span className="block text-sm font-semibold text-white">{title}</span><span className="mt-2 block text-xs leading-5 text-gray-400">{detail}</span></button>;
}

function ShellFailure({ failure, onDiagnostics }: { failure: ReturnType<typeof normalizeShellFailure>; onDiagnostics: () => void }) {
  return <div className="mt-5 rounded-xl border border-amber-400/30 bg-amber-500/10 p-4"><div className="flex items-start gap-3"><FileWarning className="mt-0.5 h-5 w-5 shrink-0 text-amber-200" aria-hidden="true" /><div><p className="text-sm font-semibold text-amber-50">{failure.message}</p><p className="mt-1 text-xs text-amber-100/70">{failure.code} · technical details stay in Diagnostics.</p><button type="button" onClick={onDiagnostics} className="mt-3 inline-flex items-center gap-2 rounded-md border border-amber-300/30 px-3 py-1.5 text-xs font-medium text-amber-100 hover:bg-amber-500/10 focus:outline-none focus:ring-2 focus:ring-accent/70"><FileSearch className="h-3.5 w-3.5" aria-hidden="true" /> Open Diagnostics</button></div></div></div>;
}

function DiagnosticsPanel({ bootstrap, supervisor, supervisorDiagnostics, webview2, message, onGenerate }: { bootstrap: DesktopV2BootstrapResult | null; supervisor: SupervisorStatus | null; supervisorDiagnostics: SupervisorDiagnostics | null; webview2: WebView2RuntimeStatus | null; message: string | null; onGenerate: () => void }) {
  const lastError = supervisor?.lastError ? redactDiagnosticText(supervisor.lastError) : null;
  const remediation = supervisor?.remediationCodes.join(" · ") || "None reported";
  return <section className="mt-6 rounded-2xl border border-surface-border bg-surface-raised p-5 sm:p-7" aria-labelledby="diagnostics-title">
    <div className="flex items-start gap-3"><FileSearch className="mt-0.5 h-5 w-5 text-accent" aria-hidden="true" /><div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">Diagnostics</p><h2 id="diagnostics-title" className="mt-2 text-2xl font-semibold text-white">Redacted recovery details</h2><p className="mt-2 max-w-2xl text-sm leading-6 text-gray-400">Generate a local snapshot with shell state, storage boundary checks, component status, supervisor readiness, and redacted technical details. Tokens and provider secrets are never persisted.</p></div></div>
    <div className="mt-6 grid gap-3 sm:grid-cols-4"><DiagnosticTile label="Shell boot" value={bootstrap?.bootState ?? "Unavailable"} /><DiagnosticTile label="Supervisor" value={supervisorStateLabel(supervisor)} /><DiagnosticTile label="Engine gate" value={supervisor?.engineReady ? "Authenticated" : "Locked"} /><DiagnosticTile label="WebView2" value={webview2?.available ? webview2.version ?? "Detected" : webview2 ? "Required" : "Unknown"} /></div>
    {supervisor ? <div className={`mt-5 rounded-xl border p-4 ${supervisor.engineReady ? "border-emerald-400/30 bg-emerald-500/10" : "border-amber-400/30 bg-amber-500/10"}`} aria-live="polite"><div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-semibold text-white">Readiness detail</p><span className="rounded-full bg-black/20 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-gray-300">{supervisor.state}</span></div><p className="mt-2 text-sm leading-6 text-gray-200">{supervisor.detail}</p>{lastError ? <p className="mt-3 break-words text-xs text-amber-100"><span className="font-semibold">Last failure:</span> {lastError}</p> : null}<dl className="mt-3 grid gap-2 text-xs text-gray-400 sm:grid-cols-2"><div><dt className="text-gray-500">Component</dt><dd className="text-gray-300">{supervisor.componentId ?? "Not selected"}{supervisor.componentVersion ? ` · ${supervisor.componentVersion}` : ""}</dd></div><div><dt className="text-gray-500">Readiness probe</dt><dd className="text-gray-300">{supervisor.lastProbeStatus ? `HTTP ${supervisor.lastProbeStatus}` : "Not completed"}</dd></div><div><dt className="text-gray-500">Capabilities probe</dt><dd className="text-gray-300">{supervisor.lastCapabilitiesStatus ? `HTTP ${supervisor.lastCapabilitiesStatus}` : "Not completed"}</dd></div><div><dt className="text-gray-500">Handshake</dt><dd className="text-gray-300">{formatDiagnosticTimestamp(supervisor.handshakeAtEpochMs)}</dd></div><div><dt className="text-gray-500">Readiness</dt><dd className="text-gray-300">{formatDiagnosticTimestamp(supervisor.readinessAtEpochMs)}</dd></div><div><dt className="text-gray-500">Capabilities</dt><dd className="text-gray-300">{formatDiagnosticTimestamp(supervisor.capabilitiesAtEpochMs)}</dd></div><div><dt className="text-gray-500">Child exit</dt><dd className="text-gray-300">{supervisor.lastExitCode === null || supervisor.lastExitCode === undefined ? "Not observed" : supervisor.lastExitCode}</dd></div><div><dt className="text-gray-500">Remediation</dt><dd className="break-words text-gray-300">{remediation}</dd></div></dl>{supervisor.verificationPolicy ? <details className="mt-3"><summary className="cursor-pointer text-[11px] text-gray-500">Installed-runtime verification policy</summary><p className="mt-2 break-words text-[10px] leading-4 text-gray-500">{supervisor.verificationPolicy}</p></details> : null}{supervisorDiagnostics?.logTail.length ? <details className="mt-3"><summary className="cursor-pointer text-[11px] text-gray-500">Redacted native stdout/stderr tail</summary><pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-black/20 p-3 text-[10px] leading-4 text-gray-400">{supervisorDiagnostics.logTail.slice(-12).join("\n")}</pre></details> : null}</div> : <p className="mt-5 rounded-lg border border-amber-400/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">Supervisor status is unavailable. Refresh the shell before retrying native setup.</p>}
    {webview2 && !webview2.available ? <p role="alert" className="mt-5 rounded-lg border border-red-400/40 bg-red-500/10 px-4 py-3 text-sm text-red-100">{webview2.detail}</p> : null}{message ? <p role="status" className="mt-5 rounded-lg border border-emerald-400/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100">{message}</p> : null}<button type="button" onClick={onGenerate} className="mt-6 inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white hover:bg-accent-hover focus:outline-none focus:ring-2 focus:ring-accent/70"><FileSearch className="h-4 w-4" aria-hidden="true" /> Generate redacted snapshot</button>
  </section>;
}

function formatDiagnosticTimestamp(epochMs?: number | null): string {
  if (epochMs === null || epochMs === undefined) return "Not observed";
  const date = new Date(Number(epochMs));
  return Number.isNaN(date.getTime()) ? "Invalid timestamp" : date.toLocaleString();
}

function DiagnosticTile({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border border-surface-border bg-surface-overlay p-3"><p className="text-[10px] uppercase tracking-wide text-gray-500">{label}</p><p className="mt-1 text-sm font-medium text-white">{value}</p></div>;
}

function ShellNavButton({ active, icon, label, onClick }: { active: boolean; icon: ReactNode; label: string; onClick: () => void }) {
  return <button type="button" onClick={onClick} aria-current={active ? "page" : undefined} className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-accent/70 ${active ? "bg-accent/15 text-white ring-1 ring-accent/30" : "text-gray-400 hover:bg-surface-overlay hover:text-gray-200"}`}>{icon}<span>{label}</span></button>;
}

function ArchiveIcon() {
  return <span aria-hidden="true" className="flex h-4 w-4 items-center justify-center rounded border border-amber-300/70 text-[9px] text-amber-200">M</span>;
}
