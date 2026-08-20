import { Component, useEffect, useMemo, useState, type ErrorInfo, type ReactNode } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  Cog,
  FileSearch,
  FolderOpen,
  Info,
  LockKeyhole,
  RefreshCw,
  ServerOff,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import {
  DESKTOP_V2_PRODUCT_LINE,
  DESKTOP_V2_PRODUCT_NAME,
  type ComponentStatus,
  type DesktopV2BootstrapResult,
  type ShellInfo,
  normalizeShellFailure,
} from "../desktopV2";
import * as api from "../lib/api";

type ShellPanel = "setup" | "diagnostics";

type ErrorBoundaryProps = { children: ReactNode };
type ErrorBoundaryState = { hasError: boolean };

export class DesktopV2ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(_error: Error, _info: ErrorInfo) {
    // Keep render failures generic in the UI. Technical details belong in the
    // explicit redacted diagnostics flow rather than an error overlay.
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-screen items-center justify-center bg-surface px-6 text-gray-100">
          <div className="max-w-lg rounded-2xl border border-amber-400/30 bg-surface-raised p-6 text-center">
            <AlertTriangle className="mx-auto h-8 w-8 text-amber-300" />
            <h1 className="mt-4 text-xl font-semibold text-white">Desktop shell needs recovery</h1>
            <p className="mt-2 text-sm leading-6 text-gray-400">The shell UI encountered a recoverable rendering error. Restart the shell and generate a redacted diagnostic snapshot if the problem continues.</p>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export function DesktopV2Shell() {
  const [shellInfo, setShellInfo] = useState<ShellInfo | null>(null);
  const [bootstrap, setBootstrap] = useState<DesktopV2BootstrapResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<ReturnType<typeof normalizeShellFailure> | null>(null);
  const [panel, setPanel] = useState<ShellPanel>("setup");
  const [diagnosticMessage, setDiagnosticMessage] = useState<string | null>(null);

  const loadShell = async () => {
    setLoading(true);
    setFailure(null);
    setDiagnosticMessage(null);

    try {
      const info = await api.getShellInfo();
      setShellInfo(info);
    } catch (error) {
      setFailure(normalizeShellFailure(error));
    }

    try {
      const result = await api.bootstrapDesktopV2Shell();
      setBootstrap(result);
      if (result.bootState === "recoverable-error") setPanel("diagnostics");
    } catch (error) {
      setFailure(normalizeShellFailure(error));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadShell();
  }, []);

  const displayInfo = shellInfo ?? bootstrap?.shellInfo ?? null;
  const componentStatuses = bootstrap?.componentStatus ?? [
    {
      id: "desktop-v2-shell",
      displayName: "Desktop V2 shell",
      state: "available",
      required: true,
      detail: "The offline-safe shell is running.",
      remediationCodes: [],
    },
    {
      id: "aive-engine",
      displayName: "Core engine",
      state: "not-installed",
      required: true,
      detail: "Core engine not installed.",
      remediationCodes: ["ENGINE_NOT_RUNNING"],
    },
  ] satisfies ComponentStatus[];

  const bootLabel = useMemo(() => {
    if (loading) return "Starting shell";
    if (failure) return "Recoverable shell error";
    switch (bootstrap?.bootState) {
      case "engine-available":
        return "Engine component available";
      case "recoverable-error":
        return "Diagnostics needed";
      case "setup-required":
        return "Setup required";
      case "shell-ready":
        return "Shell ready";
      default:
        return "Starting shell";
    }
  }, [bootstrap?.bootState, failure, loading]);

  const handleDiagnostics = async () => {
    setPanel("diagnostics");
    setDiagnosticMessage(null);
    try {
      const result = await api.generateDesktopDiagnosticSnapshot();
      setDiagnosticMessage(result.created
        ? `Snapshot created at ${result.path ?? "the per-user Logs directory"}.`
        : result.detail);
    } catch {
      setDiagnosticMessage("Diagnostics could not be generated. Check the per-user LocalAppData permissions and try again.");
    }
  };

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-surface text-gray-100">
      <header className="flex shrink-0 items-center justify-between border-b border-surface-border bg-surface-raised px-5 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent/20 text-accent ring-1 ring-accent/40">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div>
            <div className="text-sm font-semibold tracking-wide text-white">{displayInfo?.productName ?? DESKTOP_V2_PRODUCT_NAME}</div>
            <div className="text-[11px] uppercase tracking-[0.18em] text-gray-500">{displayInfo?.productLine ?? DESKTOP_V2_PRODUCT_LINE} · offline-safe shell</div>
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-400">
          <span className="rounded-full border border-surface-border bg-surface-overlay px-3 py-1">
            v{displayInfo?.shellVersion ?? "2.0.0"}
          </span>
          <span className="hidden rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-emerald-300 sm:inline-flex">
            {bootLabel}
          </span>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-64 shrink-0 border-r border-surface-border bg-surface-raised p-4 md:block">
          <p className="px-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-gray-500">Desktop control</p>
          <nav className="mt-3 space-y-1">
            <ShellNavButton
              active={panel === "setup"}
              icon={<Wrench className="h-4 w-4" />}
              label="Setup Center"
              onClick={() => setPanel("setup")}
            />
            <ShellNavButton
              active={panel === "diagnostics"}
              icon={<FileSearch className="h-4 w-4" />}
              label="Diagnostics"
              onClick={() => void handleDiagnostics()}
            />
          </nav>
          <div className="mt-8 rounded-xl border border-surface-border bg-surface-overlay p-3 text-xs leading-5 text-gray-400">
            <LockKeyhole className="mb-2 h-4 w-4 text-accent" />
            Shell launch is local-only. Backend, Docker, downloads, and engine processes are gated until a later supervisor is ready.
          </div>
        </aside>

        <main className="min-h-0 flex-1 overflow-auto">
          <div className="mx-auto max-w-6xl px-5 py-6 lg:px-8 lg:py-8">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-accent">Desktop V2 base shell</p>
                <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">A useful starting point, even before setup.</h1>
                <p className="mt-3 max-w-2xl text-sm leading-6 text-gray-400">
                  The shell is installed independently from the engine. It can show status, storage boundaries, and recovery guidance without contacting localhost or starting external services.
                </p>
              </div>
              <button
                type="button"
                onClick={() => void loadShell()}
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-surface-border bg-surface-raised px-3 py-2 text-xs font-medium text-gray-200 transition-colors hover:border-accent hover:text-white"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Refresh shell status
              </button>
            </div>

            <div className="mt-7 grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
              <section className="rounded-2xl border border-surface-border bg-surface-raised p-5 shadow-xl shadow-black/10">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Boot state</p>
                    <h2 className="mt-2 text-xl font-semibold text-white">{bootLabel}</h2>
                  </div>
                  <BootStateIcon state={loading ? "starting" : failure ? "recoverable-error" : bootstrap?.bootState ?? "starting"} />
                </div>
                {loading ? (
                  <p className="mt-5 rounded-xl border border-accent/30 bg-accent/10 p-4 text-sm leading-6 text-accent-100">
                    Reading local shell paths and activation metadata. No backend or engine startup is performed.
                  </p>
                ) : failure ? (
                  <div className="mt-5 rounded-xl border border-amber-400/30 bg-amber-500/10 p-4">
                    <p className="text-sm font-semibold text-amber-100">{failure.message}</p>
                    <p className="mt-2 text-xs leading-5 text-amber-100/70">{failure.code} · technical details stay in Diagnostics.</p>
                    <button
                      type="button"
                      onClick={() => void handleDiagnostics()}
                      className="mt-4 inline-flex items-center gap-2 rounded-md border border-amber-300/30 px-3 py-1.5 text-xs font-medium text-amber-100 hover:bg-amber-500/10"
                    >
                      <FileSearch className="h-3.5 w-3.5" />
                      Open Diagnostics
                    </button>
                  </div>
                ) : (
                  <BootStateMessage bootstrap={bootstrap} onSetup={() => setPanel("setup")} onDiagnostics={() => void handleDiagnostics()} />
                )}
              </section>

              <section className="rounded-2xl border border-surface-border bg-surface-raised p-5">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Component status</p>
                    <h2 className="mt-2 text-xl font-semibold text-white">Shell inventory</h2>
                  </div>
                  <ClipboardCheck className="h-5 w-5 text-accent" />
                </div>
                <div className="mt-5 space-y-3">
                  {componentStatuses.map(status => <ComponentStatusCard key={status.id} status={status} />)}
                </div>
              </section>
            </div>

            <div className="mt-4 grid gap-4 lg:grid-cols-3">
              <ActionCard
                icon={<Wrench className="h-5 w-5" />}
                title="Setup Center"
                detail="Review what the future component installer will provide. Phase 2 does not download or activate runtimes."
                action="Open Setup Center"
                onClick={() => setPanel("setup")}
              />
              <ActionCard
                icon={<FileSearch className="h-5 w-5" />}
                title="Diagnostics"
                detail="Create a redacted local snapshot with shell, path-boundary, and activation metadata status."
                action="Generate snapshot"
                onClick={() => void handleDiagnostics()}
              />
              <ActionCard
                icon={<ServerOff className="h-5 w-5" />}
                title="Engine-dependent views"
                detail="Editor, API, uploads, and rendering remain gated until a later supervisor marks the engine ready."
                action="Currently unavailable"
                disabled
              />
            </div>

            {panel === "setup" ? (
              <SetupCenter bootstrap={bootstrap} />
            ) : (
              <DiagnosticsPanel bootstrap={bootstrap} message={diagnosticMessage} onGenerate={() => void handleDiagnostics()} />
            )}
          </div>
        </main>
      </div>
    </div>
  );
}

function BootStateMessage({
  bootstrap,
  onSetup,
  onDiagnostics,
}: {
  bootstrap: DesktopV2BootstrapResult | null;
  onSetup: () => void;
  onDiagnostics: () => void;
}) {
  if (!bootstrap) return null;
  if (bootstrap.bootState === "setup-required") {
    return (
      <div className="mt-5 rounded-xl border border-amber-400/30 bg-amber-500/10 p-4">
        <p className="text-sm font-semibold text-amber-100">Core engine not installed</p>
        <p className="mt-2 text-sm leading-6 text-amber-100/75">The shell is ready and no required component was found. You can inspect the planned setup boundary without starting a backend.</p>
        <button type="button" onClick={onSetup} className="mt-4 inline-flex items-center gap-2 rounded-md bg-accent px-3 py-2 text-xs font-medium text-white hover:bg-accent-hover">
          <Wrench className="h-3.5 w-3.5" />
          Open Setup Center
        </button>
      </div>
    );
  }
  if (bootstrap.bootState === "engine-available") {
    return (
      <div className="mt-5 rounded-xl border border-blue-400/30 bg-blue-500/10 p-4">
        <p className="text-sm font-semibold text-blue-100">Engine component found, but not started</p>
        <p className="mt-2 text-sm leading-6 text-blue-100/75">The Phase 2 shell only discovers activation metadata. API-dependent views stay locked until a later supervisor sends an authenticated ready state.</p>
      </div>
    );
  }
  if (bootstrap.bootState === "recoverable-error") {
    return (
      <div className="mt-5 rounded-xl border border-amber-400/30 bg-amber-500/10 p-4">
        <p className="text-sm font-semibold text-amber-100">Shell recovery is required</p>
        <p className="mt-2 text-sm leading-6 text-amber-100/75">The local metadata could not be treated as a verified active component. Review a redacted diagnostic snapshot before taking action.</p>
        <button type="button" onClick={onDiagnostics} className="mt-4 inline-flex items-center gap-2 rounded-md border border-amber-300/30 px-3 py-2 text-xs font-medium text-amber-100 hover:bg-amber-500/10">
          <FileSearch className="h-3.5 w-3.5" />
          Open Diagnostics
        </button>
      </div>
    );
  }
  return <p className="mt-5 text-sm text-gray-400">The shell is ready to inspect local Desktop V2 state.</p>;
}

function ComponentStatusCard({ status }: { status: ComponentStatus }) {
  const available = status.state === "available";
  return (
    <div className="rounded-xl border border-surface-border bg-surface-overlay p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          {available ? <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" /> : <AlertTriangle className="h-4 w-4 shrink-0 text-amber-300" />}
          <p className="truncate text-sm font-medium text-white">{status.displayName}</p>
        </div>
        <span className={`rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wide ${available ? "bg-emerald-500/10 text-emerald-300" : "bg-amber-500/10 text-amber-200"}`}>
          {status.state}
        </span>
      </div>
      <p className="mt-2 text-xs leading-5 text-gray-400">{status.detail}</p>
    </div>
  );
}

function ActionCard({
  icon,
  title,
  detail,
  action,
  onClick,
  disabled = false,
}: {
  icon: ReactNode;
  title: string;
  detail: string;
  action: string;
  onClick?: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="group rounded-2xl border border-surface-border bg-surface-raised p-5 text-left transition-colors hover:border-accent disabled:cursor-not-allowed disabled:opacity-75"
    >
      <div className="flex items-center gap-3 text-accent">{icon}<span className="text-sm font-semibold text-white">{title}</span></div>
      <p className="mt-3 text-xs leading-5 text-gray-400">{detail}</p>
      <span className="mt-4 inline-flex items-center gap-1.5 text-xs font-medium text-gray-300 group-hover:text-white">{action}<span aria-hidden="true">→</span></span>
    </button>
  );
}

function ShellNavButton({ active, icon, label, onClick }: { active: boolean; icon: ReactNode; label: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors ${active ? "bg-accent/15 text-white ring-1 ring-accent/30" : "text-gray-400 hover:bg-surface-overlay hover:text-gray-200"}`}>
      {icon}<span>{label}</span>
    </button>
  );
}

function BootStateIcon({ state }: { state: string }) {
  if (state === "starting") return <RefreshCw className="h-6 w-6 animate-spin text-accent" />;
  if (state === "recoverable-error") return <AlertTriangle className="h-6 w-6 text-amber-300" />;
  if (state === "setup-required") return <Wrench className="h-6 w-6 text-amber-300" />;
  if (state === "engine-available") return <ServerOff className="h-6 w-6 text-blue-300" />;
  return <CheckCircle2 className="h-6 w-6 text-emerald-400" />;
}

function SetupCenter({ bootstrap }: { bootstrap: DesktopV2BootstrapResult | null }) {
  return (
    <section className="mt-6 rounded-2xl border border-surface-border bg-surface-raised p-5">
      <div className="flex items-start gap-3">
        <Cog className="mt-0.5 h-5 w-5 shrink-0 text-accent" />
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Setup Center</p>
          <h2 className="mt-2 text-xl font-semibold text-white">Component delivery is intentionally not active yet.</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-400">
            Phase 2 provides the installable shell and its storage contract. A later phase may add signed downloads, verification, staging, activation, and rollback. No component archive or runtime is bundled in this installer.
          </p>
        </div>
      </div>
      <div className="mt-5 grid gap-3 md:grid-cols-3">
        <SetupItem icon={<ShieldCheck className="h-4 w-4" />} title="Verify" detail="Ed25519 signature and SHA-256 checks are defined by the Phase 1 manifest contract." />
        <SetupItem icon={<FolderOpen className="h-4 w-4" />} title="Stage safely" detail="Future components belong under immutable ProgramData paths, never Program Files runtime state." />
        <SetupItem icon={<Info className="h-4 w-4" />} title="Current gate" detail={bootstrap?.setupRequired ? "Core engine not installed." : "No engine supervisor is active in Phase 2."} />
      </div>
    </section>
  );
}

function SetupItem({ icon, title, detail }: { icon: ReactNode; title: string; detail: string }) {
  return (
    <div className="rounded-xl border border-surface-border bg-surface-overlay p-4">
      <div className="flex items-center gap-2 text-accent"><span>{icon}</span><span className="text-sm font-semibold text-white">{title}</span></div>
      <p className="mt-2 text-xs leading-5 text-gray-400">{detail}</p>
    </div>
  );
}

function DiagnosticsPanel({ bootstrap, message, onGenerate }: { bootstrap: DesktopV2BootstrapResult | null; message: string | null; onGenerate: () => void }) {
  return (
    <section className="mt-6 rounded-2xl border border-surface-border bg-surface-raised p-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Diagnostics</p>
          <h2 className="mt-2 text-xl font-semibold text-white">Redacted local snapshot</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-400">Only shell identity, contract versions, path-boundary status, component state, and safe activation metadata summaries are included. Credentials, tokens, uploads, models, and project data are not collected.</p>
        </div>
        <button type="button" onClick={onGenerate} className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg bg-accent px-3 py-2 text-xs font-medium text-white hover:bg-accent-hover">
          <FileSearch className="h-3.5 w-3.5" />
          Generate snapshot
        </button>
      </div>
      {message ? <p className="mt-5 rounded-xl border border-emerald-400/30 bg-emerald-500/10 p-3 text-xs leading-5 text-emerald-200">{message}</p> : null}
      {bootstrap ? (
        <div className="mt-5 grid gap-3 text-xs md:grid-cols-2">
          <DiagnosticValue label="State file" value={bootstrap.persistedStatePath} />
          <DiagnosticValue label="Activation metadata" value={bootstrap.activation.metadataPath} />
          <DiagnosticValue label="Storage contract" value={bootstrap.paths.schemaVersion} />
          <DiagnosticValue label="Engine API gate" value={bootstrap.engineReady ? "ready" : "locked until supervisor ready"} />
        </div>
      ) : null}
    </section>
  );
}

function DiagnosticValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-surface-border bg-surface-overlay p-3">
      <p className="text-[10px] uppercase tracking-[0.14em] text-gray-500">{label}</p>
      <p className="mt-1 break-all text-gray-300">{value}</p>
    </div>
  );
}
