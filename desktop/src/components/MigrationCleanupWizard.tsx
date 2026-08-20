import { useMemo, useState } from "react";
import { Archive, ArrowRight, CheckCircle2, Database, FileWarning, HardDrive, ShieldCheck, Trash2 } from "lucide-react";
import {
  FULL_WIPE_CONFIRMATION,
  formatMigrationBytes,
  migrationCategoryLabel,
  migrationClient,
  redactMigrationText,
  type LegacyInventory,
  type MigrationOptions,
  type MigrationReport,
} from "../migration";

export function MigrationCleanupWizard({
  inventory,
  onContinue,
}: {
  inventory: LegacyInventory;
  onContinue: () => void;
}) {
  const [report, setReport] = useState<MigrationReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [backup, setBackup] = useState(true);
  const [keepOldCopy, setKeepOldCopy] = useState(true);
  const [cleanupApproved, setCleanupApproved] = useState(false);
  const [fullWipeText, setFullWipeText] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const valuableBytes = useMemo(() => inventory.totals.valuableBytes, [inventory.totals.valuableBytes]);
  const cleanupBytes = useMemo(() => inventory.totals.cleanupBytes, [inventory.totals.cleanupBytes]);
  const options: MigrationOptions = {
    action: "recommended-migrate",
    backupBeforeMigrate: backup,
    keepOldCopy,
    cleanupAfterMigrate: false,
    cleanupApproved,
  };

  const preview = async () => {
    setBusy(true);
    setError(null);
    try {
      setReport(await migrationClient.preview(undefined, options));
      setMessage("Preflight complete. Review the paths and choose an explicit action.");
    } catch (operationError) {
      setError(redactMigrationText(String(operationError)));
    } finally {
      setBusy(false);
    }
  };

  const migrate = async () => {
    setBusy(true);
    setError(null);
    try {
      const nextReport = report ?? await migrationClient.preview(undefined, options);
      if (!nextReport.preflight.passed) {
        setReport(nextReport);
        setError("Migration is blocked by preflight findings. Resolve disk, lock, or boundary warnings first.");
        return;
      }
      const completed = await migrationClient.execute(nextReport, options);
      setReport(completed);
      setMessage(keepOldCopy
        ? "Supported settings and content were migrated. The old copy remains until you approve cleanup."
        : "Supported settings and content were migrated. Review the cleanup report before removing legacy runtime files.");
    } catch (operationError) {
      setError(redactMigrationText(String(operationError)));
    } finally {
      setBusy(false);
    }
  };

  const cleanup = async () => {
    setBusy(true);
    setError(null);
    try {
      const cleanupReport = await migrationClient.cleanup(inventory, {
        approved: true,
        dryRun: false,
        scheduleRebootCleanup: true,
      });
      setMessage(cleanupReport.lockedLeftovers.length > 0
        ? "Disposable legacy state was cleaned where safe; locked leftovers were reported for close/reboot cleanup."
        : "Approved disposable legacy runtime, cache, logs, staging, and stale shortcuts were cleaned.");
      onContinue();
    } catch (operationError) {
      setError(redactMigrationText(String(operationError)));
    } finally {
      setBusy(false);
    }
  };

  const fullWipe = async () => {
    setBusy(true);
    setError(null);
    try {
      const cleanupReport = await migrationClient.cleanup(inventory, {
        approved: true,
        fullWipeConfirmed: true,
        confirmation: FULL_WIPE_CONFIRMATION,
        dryRun: false,
        scheduleRebootCleanup: true,
      });
      setMessage(cleanupReport.lockedLeftovers.length > 0
        ? "The separately confirmed full wipe removed safe paths; locked leftovers were reported for close/reboot cleanup."
        : "The separately confirmed full wipe removed the detected legacy state within the allowlisted roots.");
      onContinue();
    } catch (operationError) {
      setError(redactMigrationText(String(operationError)));
    } finally {
      setBusy(false);
    }
  };

  const fullWipeReady = fullWipeText === FULL_WIPE_CONFIRMATION;

  return (
    <section className="mt-6 overflow-hidden rounded-2xl border border-amber-400/30 bg-surface-raised shadow-xl shadow-black/10" aria-labelledby="migration-wizard-title">
      <div className="border-b border-amber-400/20 bg-amber-500/5 px-5 py-5 sm:px-7">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-400/15 text-amber-200 ring-1 ring-amber-300/30"><Archive className="h-5 w-5" aria-hidden="true" /></div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-amber-200">Migration &amp; Cleanup</p>
            <h2 id="migration-wizard-title" className="mt-2 text-2xl font-semibold tracking-tight text-white">We found an older local installation</h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-300">The scan is read-only. Application runtime/cache is separate from valuable projects, uploads, exports, models, and databases. Nothing is deleted until you approve a cleanup choice.</p>
          </div>
        </div>
        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <SummaryTile label="Detected items" value={`${inventory.totals.itemCount}`} detail={inventory.oldInstallIdentities.map(identity => `${identity.productName} ${identity.version ?? "unknown"}`).join(" · ") || "Known legacy layout"} />
          <SummaryTile label="Valuable data" value={formatMigrationBytes(valuableBytes)} detail="Preserved by default" />
          <SummaryTile label="Disposable runtime" value={formatMigrationBytes(cleanupBytes)} detail="Cleanup needs approval" />
        </div>
      </div>

      <div className="grid gap-6 p-5 sm:p-7 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0">
          {error ? <div role="alert" className="mb-4 rounded-lg border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-100">{error}</div> : null}
          {message ? <div role="status" className="mb-4 rounded-lg border border-emerald-400/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100">{message}</div> : null}
          <div className="rounded-xl border border-surface-border bg-surface-overlay p-4">
            <div className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-accent" aria-hidden="true" /><h3 className="text-sm font-semibold text-white">Recommended choice</h3></div>
            <p className="mt-2 text-sm leading-6 text-gray-400">Back up the supported settings and user data, copy them transactionally into the V2 layout, validate each switch, and keep the old copy until you review the result.</p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <label className="flex items-start gap-3 rounded-lg border border-surface-border bg-surface-raised p-3 text-sm text-gray-300"><input type="checkbox" checked={backup} onChange={event => setBackup(event.target.checked)} className="mt-0.5 h-4 w-4 accent-accent" /><span><span className="block font-semibold text-white">Create a backup/export</span><span className="mt-1 block text-xs leading-5 text-gray-500">Protected secret values are never copied into this backup as plaintext.</span></span></label>
              <label className="flex items-start gap-3 rounded-lg border border-surface-border bg-surface-raised p-3 text-sm text-gray-300"><input type="checkbox" checked={keepOldCopy} onChange={event => setKeepOldCopy(event.target.checked)} className="mt-0.5 h-4 w-4 accent-accent" /><span><span className="block font-semibold text-white">Keep the old copy</span><span className="mt-1 block text-xs leading-5 text-gray-500">Recommended. Cleanup remains a separate, explicit decision.</span></span></label>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <button type="button" disabled={busy} onClick={() => void preview()} className="inline-flex items-center gap-2 rounded-lg border border-surface-border px-3 py-2 text-xs font-medium text-gray-200 hover:border-accent disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-accent/70"><HardDrive className="h-3.5 w-3.5" aria-hidden="true" /> Preview preflight</button>
              <button type="button" disabled={busy} onClick={() => void migrate()} className="inline-flex items-center gap-2 rounded-lg bg-accent px-3 py-2 text-xs font-medium text-white hover:bg-accent-hover disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-accent/70">Migrate supported data <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" /></button>
            </div>
          </div>

          <div className="mt-4 rounded-xl border border-surface-border bg-surface-overlay p-4">
            <div className="flex items-center gap-2"><Database className="h-4 w-4 text-accent" aria-hidden="true" /><h3 className="text-sm font-semibold text-white">What will happen to detected paths</h3></div>
            <div className="mt-4 space-y-2">
              {inventory.items.slice(0, 24).map(item => (
                <div key={item.itemId} className="flex flex-col gap-2 rounded-lg border border-surface-border bg-surface-raised px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0"><p className="truncate text-xs font-semibold text-gray-200">{migrationCategoryLabel(item)}</p><p className="mt-1 truncate text-[11px] text-gray-500">{item.sourcePath}</p></div>
                  <div className="flex shrink-0 items-center gap-2 text-[11px] text-gray-500"><span>{formatMigrationBytes(item.sizeBytes)}</span>{item.locked ? <span className="rounded bg-amber-500/10 px-2 py-1 text-amber-200">Locked</span> : null}{item.reparsePoint ? <span className="rounded bg-red-500/10 px-2 py-1 text-red-200">Reparse refused</span> : null}</div>
                </div>
              ))}
            </div>
            {inventory.items.length > 24 ? <p className="mt-3 text-xs text-gray-500">Showing the first 24 items; the machine-readable report contains all {inventory.items.length} items.</p> : null}
            {inventory.items.some(item => item.exportImportRequired) ? <div className="mt-4 flex gap-2 rounded-lg border border-amber-400/30 bg-amber-500/10 p-3 text-xs leading-5 text-amber-100"><FileWarning className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" /><span>PostgreSQL/Qdrant state is not silently copied. Use an application-level export/import flow after V2 is ready.</span></div> : null}
            {inventory.items.some(item => item.secretDetected) ? <p className="mt-3 text-xs leading-5 text-gray-500">Provider secret keys detected: {inventory.items.flatMap(item => item.secretNames).join(", ") || "names redacted"}. Secret values are not shown.</p> : null}
          </div>

          {report ? <div className="mt-4 rounded-xl border border-surface-border bg-surface-overlay p-4" aria-live="polite"><div className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-emerald-300" aria-hidden="true" /><h3 className="text-sm font-semibold text-white">Preflight / migration report</h3></div><p className="mt-2 text-xs text-gray-400">Status: <span className="text-gray-200">{report.status}</span> · {report.preflight.passed ? "safe to proceed" : "blocked until findings are resolved"}</p>{report.journalPath ? <p className="mt-1 break-all text-[11px] text-gray-500">Journal: {report.journalPath}</p> : null}{report.preflight.warnings.map(warning => <p key={warning} className="mt-2 text-xs text-amber-200">{warning}</p>)}</div> : null}
        </div>

        <aside className="space-y-4">
          <div className="rounded-xl border border-surface-border bg-surface-overlay p-4 text-xs leading-5 text-gray-400"><p className="font-semibold text-white">Safe boundaries</p><p className="mt-2">The scanner uses known LocalAppData, Program Files, ProgramData, Documents, shortcut, and redirected registry roots only. Reparse points, path escapes, locked files, and arbitrary drives are refused.</p></div>
          <div className="rounded-xl border border-surface-border bg-surface-overlay p-4 text-xs leading-5 text-gray-400"><p className="font-semibold text-white">Keep old copy</p><p className="mt-2">Choose this when you want to compare or export manually. It does not delete anything and does not block the V2 shell from continuing.</p><button type="button" onClick={onContinue} className="mt-4 inline-flex items-center gap-2 rounded-lg border border-surface-border px-3 py-2 text-xs font-medium text-gray-200 hover:border-accent focus:outline-none focus:ring-2 focus:ring-accent/70">Continue with old copy <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" /></button></div>
          <div className="rounded-xl border border-rose-400/25 bg-rose-500/5 p-4"><div className="flex items-center gap-2"><Trash2 className="h-4 w-4 text-rose-200" aria-hidden="true" /><p className="text-sm font-semibold text-white">Approved cleanup</p></div><p className="mt-2 text-xs leading-5 text-gray-400">This removes only disposable legacy runtime, cache, temp, logs, stale PID/port files, obsolete shortcuts, and old installer records. Valuable content stays.</p><label className="mt-3 flex items-start gap-2 text-xs text-gray-300"><input type="checkbox" checked={cleanupApproved} onChange={event => setCleanupApproved(event.target.checked)} className="mt-0.5 h-4 w-4 accent-accent" /><span>I explicitly approve disposable legacy cleanup.</span></label><button type="button" disabled={busy || !cleanupApproved} onClick={() => void cleanup()} className="mt-3 inline-flex items-center gap-2 rounded-lg border border-rose-400/30 px-3 py-2 text-xs font-medium text-rose-100 hover:bg-rose-500/10 disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-accent/70"><Trash2 className="h-3.5 w-3.5" aria-hidden="true" /> Clean approved disposable state</button></div>
          <div className="rounded-xl border border-red-400/25 bg-red-500/5 p-4"><p className="text-sm font-semibold text-white">Full wipe is separate</p><p className="mt-2 text-xs leading-5 text-gray-400">Removing all user data is never part of detection, migration, default cleanup, or default uninstall. Type the exact phrase to unlock this separately confirmed action.</p><label className="mt-3 block text-xs text-gray-300"><span className="sr-only">Full wipe confirmation</span><input value={fullWipeText} onChange={event => setFullWipeText(event.target.value)} placeholder={FULL_WIPE_CONFIRMATION} className="mt-1 w-full rounded-lg border border-surface-border bg-surface-raised px-3 py-2 text-[11px] text-gray-100 outline-none focus:border-red-300" /></label><p className={`mt-2 text-[11px] ${fullWipeReady ? "text-emerald-300" : "text-gray-500"}`}>{fullWipeReady ? "Full-wipe confirmation accepted." : "No full wipe is armed."}</p><button type="button" disabled={busy || !fullWipeReady} onClick={() => void fullWipe()} className="mt-3 inline-flex items-center gap-2 rounded-lg border border-red-400/40 px-3 py-2 text-xs font-medium text-red-100 hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-red-300/70"><Trash2 className="h-3.5 w-3.5" aria-hidden="true" /> Remove all detected legacy data</button></div>
        </aside>
      </div>
    </section>
  );
}

function SummaryTile({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="rounded-lg border border-surface-border bg-surface-overlay p-3"><p className="text-[10px] uppercase tracking-wide text-gray-500">{label}</p><p className="mt-1 text-lg font-semibold text-white">{value}</p><p className="mt-1 line-clamp-2 text-[11px] leading-5 text-gray-500">{detail}</p></div>;
}
