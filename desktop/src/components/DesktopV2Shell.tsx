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
  normalizeShellFailure,
  type DesktopV2BootstrapResult,
  type ShellInfo,
  type SupervisorStatus,
  supervisorStateLabel,
} from "../desktopV2";
import { componentManager, type ComponentStatusResult } from "../componentManager.ts";
import {
  defaultSetupState,
  canLaunchEditor,
  requiredComponentsReady,
  setupClient,
  type SetupCatalogInfo,
  type SetupState,
} from "../setupCenter.ts";
import * as api from "../lib/api";
import { SetupCenterPanel } from "./SetupCenterPanel";
import { MigrationCleanupWizard } from "./MigrationCleanupWizard";
import { migrationClient, type LegacyInventory } from "../migration";

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
  const [statuses, setStatuses] = useState<ComponentStatusResult[]>([]);
  const [setupState, setSetupState] = useState<SetupState>(() => defaultSetupState());
  const [catalogInfo, setCatalogInfo] = useState<SetupCatalogInfo | null>(null);
  const [setupRequired, setSetupRequired] = useState(true);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<ReturnType<typeof normalizeShellFailure> | null>(null);
  const [panel, setPanel] = useState<ShellPanel>("setup");
  const [diagnosticMessage, setDiagnosticMessage] = useState<string | null>(null);
  const [migrationInventory, setMigrationInventory] = useState<LegacyInventory | null>(null);

  const loadShell = useCallback(async () => {
    setLoading(true);
    setFailure(null);
    setDiagnosticMessage(null);
    let nextBootstrap: DesktopV2BootstrapResult | null = null;
    let nextSetupState = setupState;
    let nextStatuses: ComponentStatusResult[] = [];

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
    const bootstrapHealthy = nextBootstrap?.bootState !== "recoverable-error";
    const shouldSetup = !requiredReady || !bootstrapHealthy;
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
      if (requiredReady && bootstrapHealthy) {
        if (status.state === "stopped" || status.state === "repair-required" || status.state === "fatal") {
          status = await api.startSupervisor();
        }
        setSupervisor(status);
        if (persistedHealthyState.onboardingCompleted && canLaunchEditor(status)) onEngineReady();
      } else {
        setSupervisor(status);
      }
    } catch {
      setSupervisor(null);
    } finally {
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
          if (event.payload.engineReady && setupState.onboardingCompleted) onEngineReady();
        });
        if (cancelled) stopListening();
        else unlisten = stopListening;
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
  };

  const handleLaunchEditor = () => {
    if (canLaunchEditor(supervisor)) onEngineReady();
  };

  return (
    <div className="flex h-screen min-h-[700px] flex-col overflow-hidden bg-surface text-gray-100">
      <header className="flex shrink-0 items-center justify-between border-b border-surface-border bg-surface-raised px-5 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent/20 text-accent ring-1 ring-accent/40"><ShieldCheck className="h-5 w-5" aria-hidden="true" /></div>
          <div><div className="text-sm font-semibold tracking-wide text-white">{displayInfo?.productName ?? DESKTOP_V2_PRODUCT_NAME}</div><div className="text-[11px] uppercase tracking-[0.18em] text-gray-500">{displayInfo?.productLine ?? DESKTOP_V2_PRODUCT_LINE} · offline-safe shell</div></div>
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-400"><span className="rounded-full border border-surface-border bg-surface-overlay px-3 py-1">v{displayInfo?.shellVersion ?? "2.0.0"}</span><span className={`hidden rounded-full border px-3 py-1 sm:inline-flex ${setupRequired ? "border-amber-400/30 bg-amber-500/10 text-amber-200" : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"}`}>{bootLabel}</span></div>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-64 shrink-0 border-r border-surface-border bg-surface-raised p-4 md:block">
          <p className="px-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-gray-500">Desktop control</p>
          <nav className="mt-3 space-y-1" aria-label="Desktop control">
            <ShellNavButton active={panel === "setup"} icon={<Wrench className="h-4 w-4" />} label="Setup Center" onClick={() => setPanel("setup")} />
            {migrationInventory ? <ShellNavButton active={panel === "migration"} icon={<ArchiveIcon />} label="Migration & Cleanup" onClick={() => setPanel("migration")} /> : null}
            <ShellNavButton active={panel === "diagnostics"} icon={<FileSearch className="h-4 w-4" />} label="Diagnostics" onClick={() => void handleDiagnostics()} />
          </nav>
          <div className="mt-8 rounded-xl border border-surface-border bg-surface-overlay p-3 text-xs leading-5 text-gray-400"><LockKeyhole className="mb-2 h-4 w-4 text-accent" aria-hidden="true" />The shell is local-only. Backend, Docker, downloads, and engine processes remain gated until the authenticated supervisor is ready.</div>
          <div className="mt-3 rounded-xl border border-surface-border bg-surface-overlay p-3 text-xs leading-5 text-gray-500"><Settings2 className="mb-2 h-4 w-4 text-gray-400" aria-hidden="true" />Component management remains available after setup for update channel, version, health, repair, rollback, and optional removal.</div>
        </aside>

        <main className="min-h-0 flex-1 overflow-auto">
          <div className="mx-auto max-w-6xl px-5 py-6 lg:px-8 lg:py-8">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between"><div><p className="text-xs font-semibold uppercase tracking-[0.2em] text-accent">Desktop V2 base shell</p><h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">{setupRequired ? "Finish local setup with confidence." : "Your local workspace is ready."}</h1><p className="mt-3 max-w-2xl text-sm leading-6 text-gray-400">{setupRequired ? "Install and verify the native components from inside the app, then launch only after the supervisor proves authenticated readiness." : "The shell has bypassed onboarding because the required components are active. Use Setup Center any time to manage the installation."}</p></div><button type="button" onClick={() => void loadShell()} className="inline-flex items-center justify-center gap-2 rounded-lg border border-surface-border bg-surface-raised px-3 py-2 text-xs font-medium text-gray-200 hover:border-accent hover:text-white focus:outline-none focus:ring-2 focus:ring-accent/70"><RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} aria-hidden="true" /> Refresh shell status</button></div>
            {failure ? <ShellFailure failure={failure} onDiagnostics={() => void handleDiagnostics()} /> : null}
            {panel === "setup" ? <SetupCenterPanel bootstrap={bootstrap} supervisor={supervisor} initialStatuses={statuses} initialState={setupState} initialCatalog={catalogInfo} setupRequired={setupRequired} onSupervisorStatus={setSupervisor} onSetupComplete={handleSetupComplete} onLaunchEditor={handleLaunchEditor} onOpenDiagnostics={() => void handleDiagnostics()} /> : panel === "migration" && migrationInventory ? <MigrationCleanupWizard inventory={migrationInventory} onContinue={() => setPanel("setup")} /> : <DiagnosticsPanel bootstrap={bootstrap} supervisor={supervisor} message={diagnosticMessage} onGenerate={() => void handleDiagnostics()} />}
          </div>
        </main>
      </div>
    </div>
  );
}

function ShellFailure({ failure, onDiagnostics }: { failure: ReturnType<typeof normalizeShellFailure>; onDiagnostics: () => void }) {
  return <div className="mt-5 rounded-xl border border-amber-400/30 bg-amber-500/10 p-4"><div className="flex items-start gap-3"><FileWarning className="mt-0.5 h-5 w-5 shrink-0 text-amber-200" aria-hidden="true" /><div><p className="text-sm font-semibold text-amber-50">{failure.message}</p><p className="mt-1 text-xs text-amber-100/70">{failure.code} · technical details stay in Diagnostics.</p><button type="button" onClick={onDiagnostics} className="mt-3 inline-flex items-center gap-2 rounded-md border border-amber-300/30 px-3 py-1.5 text-xs font-medium text-amber-100 hover:bg-amber-500/10 focus:outline-none focus:ring-2 focus:ring-accent/70"><FileSearch className="h-3.5 w-3.5" aria-hidden="true" /> Open Diagnostics</button></div></div></div>;
}

function DiagnosticsPanel({ bootstrap, supervisor, message, onGenerate }: { bootstrap: DesktopV2BootstrapResult | null; supervisor: SupervisorStatus | null; message: string | null; onGenerate: () => void }) {
  return <section className="mt-6 rounded-2xl border border-surface-border bg-surface-raised p-5 sm:p-7" aria-labelledby="diagnostics-title"><div className="flex items-start gap-3"><FileSearch className="mt-0.5 h-5 w-5 text-accent" aria-hidden="true" /><div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">Diagnostics</p><h2 id="diagnostics-title" className="mt-2 text-2xl font-semibold text-white">Redacted recovery details</h2><p className="mt-2 max-w-2xl text-sm leading-6 text-gray-400">Generate a local snapshot with shell state, storage boundary checks, component status, supervisor readiness, and redacted technical details. Tokens and provider secrets are never persisted.</p></div></div><div className="mt-6 grid gap-3 sm:grid-cols-3"><DiagnosticTile label="Shell boot" value={bootstrap?.bootState ?? "Unavailable"} /><DiagnosticTile label="Supervisor" value={supervisorStateLabel(supervisor)} /><DiagnosticTile label="Engine gate" value={supervisor?.engineReady ? "Authenticated" : "Locked"} /></div>{message ? <p role="status" className="mt-5 rounded-lg border border-emerald-400/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100">{message}</p> : null}<button type="button" onClick={onGenerate} className="mt-6 inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white hover:bg-accent-hover focus:outline-none focus:ring-2 focus:ring-accent/70"><FileSearch className="h-4 w-4" aria-hidden="true" /> Generate redacted snapshot</button></section>;
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
