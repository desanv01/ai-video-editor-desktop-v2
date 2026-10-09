import { useCallback, useId, useLayoutEffect, useRef, useState } from "react";
import * as api from "../lib/api";
import type { ProjectAsset, ProjectSourceSyncPlan } from "../types/api";

interface Props {
  projectId: string;
  disabled?: boolean;
  onSaved?: (assets: ProjectAsset[]) => void | Promise<void>;
}

type Session = { active: boolean; read: number; revision: number; busy: boolean };

export function SourceSyncPanel(props: Props) {
  return <OwnedSourceSyncPanel key={props.projectId} {...props} />;
}

function OwnedSourceSyncPanel({ projectId, disabled = false, onSaved }: Props) {
  const idPrefix = useId();
  const sessionRef = useRef<Session | null>(null);
  const planRef = useRef<ProjectSourceSyncPlan | null>(null);
  const mutationFocusRef = useRef<{ session: Session; element: HTMLElement } | null>(null);
  const draftsRef = useRef<Record<string, string>>({});
  const [plan, setPlan] = useState<ProjectSourceSyncPlan | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const owns = (session: Session) => session.active && sessionRef.current === session;
  const hasDrafts = () => planRef.current?.assets.some(row =>
    draftsRef.current[row.asset.id] !== String(row.current_offset_seconds)) ?? false;

  const acceptPlan = (next: ProjectSourceSyncPlan) => {
    planRef.current = next;
    setPlan(next);
    const nextDrafts = Object.fromEntries(next.assets.map(row => [row.asset.id, String(row.current_offset_seconds)]));
    draftsRef.current = nextDrafts;
    setDrafts(nextDrafts);
    setErrors({});
  };

  const load = useCallback(async (session: Session) => {
    if (!session.active || sessionRef.current !== session || session.busy || hasDrafts()) return;
    const read = ++session.read;
    const revision = session.revision;
    setLoading(true);
    setError(null);
    try {
      const next = await api.getProjectSourceSyncPlan(projectId);
      if (!owns(session) || read !== session.read || revision !== session.revision || session.busy) return;
      if (next.project_id !== projectId) throw new Error("Source plan belongs to another project.");
      acceptPlan(next);
    } catch (reason) {
      if (owns(session) && read === session.read && revision === session.revision) setError(api.friendlyErrorMessage(reason));
    } finally {
      if (owns(session) && read === session.read) setLoading(false);
    }
  }, [projectId]);

  useLayoutEffect(() => {
    const session: Session = { active: true, read: 0, revision: 0, busy: false };
    sessionRef.current = session;
    void load(session);
    return () => { session.active = false; ++session.read; };
  }, [load]);

  useLayoutEffect(() => {
    if (saving !== null) return;
    const pending = mutationFocusRef.current;
    mutationFocusRef.current = null;
    if (!pending || !owns(pending.session) || !pending.element.isConnected) return;
    if (document.activeElement === document.body || document.activeElement === pending.element) pending.element.focus();
  }, [saving]);

  const notifySaved = async (session: Session, assets: ProjectAsset[]) => {
    if (!owns(session) || !onSaved) return;
    try {
      await onSaved(assets);
    } catch (reason) {
      if (owns(session)) setStatus(`Offsets saved. Related project refresh failed: ${api.friendlyErrorMessage(reason)}`);
    }
  };

  const beginMutation = (action: string) => {
    const session = sessionRef.current;
    if (!session || !owns(session) || disabled || session.busy || loading || !planRef.current) return null;
    if (document.activeElement instanceof HTMLElement) mutationFocusRef.current = { session, element: document.activeElement };
    session.busy = true;
    ++session.revision;
    ++session.read;
    setSaving(action);
    setError(null);
    setStatus(null);
    return session;
  };

  const saveOffset = async (assetId: string) => {
    const value = draftsRef.current[assetId] ?? "";
    const offset = Number(value);
    if (!value.trim() || !Number.isFinite(offset) || offset < -3600 || offset > 3600) {
      setErrors(previous => ({ ...previous, [assetId]: "Enter a finite offset between -3600 and 3600 seconds." }));
      return;
    }
    const session = beginMutation(assetId);
    if (!session) return;
    try {
      const asset = await api.updateProjectAssetSyncOffset(projectId, assetId, { sync_offset_seconds: offset });
      if (!owns(session)) return;
      if (asset.project_id !== projectId || asset.id !== assetId) throw new Error("Saved source belongs to another project.");
      const current = planRef.current!;
      const next = { ...current, assets: current.assets.map(row => row.asset.id === assetId
        ? { ...row, asset, current_offset_seconds: asset.sync_offset_seconds }
        : row) };
      planRef.current = next;
      setPlan(next);
      draftsRef.current = { ...draftsRef.current, [assetId]: String(asset.sync_offset_seconds) };
      setDrafts(draftsRef.current);
      setErrors(previous => { const nextErrors = { ...previous }; delete nextErrors[assetId]; return nextErrors; });
      setStatus(`Offset saved for ${asset.original_filename}: ${asset.sync_offset_seconds} seconds.`);
      await notifySaved(session, next.assets.map(row => row.asset));
    } catch (reason) {
      if (owns(session)) setErrors(previous => ({ ...previous, [assetId]: api.friendlyErrorMessage(reason) }));
    } finally {
      session.busy = false;
      if (owns(session)) setSaving(null);
    }
  };

  const applyMetadata = async () => {
    if (hasDrafts()) return;
    const session = beginMutation("metadata");
    if (!session) return;
    try {
      const next = await api.applyProjectSourceSyncMetadata(projectId, false);
      if (!owns(session)) return;
      if (next.project_id !== projectId) throw new Error("Source plan belongs to another project.");
      acceptPlan(next);
      setStatus("Metadata suggestions applied. Saved manual offsets are preserved.");
      await notifySaved(session, next.assets.map(row => row.asset));
    } catch (reason) {
      if (owns(session)) setError(api.friendlyErrorMessage(reason));
    } finally {
      session.busy = false;
      if (owns(session)) setSaving(null);
    }
  };

  const busy = disabled || loading || saving !== null;
  const dirty = hasDrafts();
  const reference = plan?.assets.find(row => row.asset.id === plan.reference_asset_id)?.asset;
  const buttonClass = "min-h-11 rounded-md border border-surface-border px-3 py-2 text-sm transition-colors hover:bg-surface-overlay focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-50";
  return (
    <section aria-labelledby={`${idPrefix}-heading`} aria-busy={loading || saving !== null} className="min-w-0 space-y-3 rounded-xl border border-surface-border bg-surface-raised p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id={`${idPrefix}-heading`} className="text-sm font-semibold text-gray-100">Source synchronization</h2>
          <p className="mt-1 break-words text-xs text-gray-300">Primary reference: {reference?.original_filename ?? "Not available"}</p>
        </div>
        <button type="button" className={buttonClass} disabled={busy || dirty} onClick={() => { const session = sessionRef.current; if (session) void load(session); }}>
          {error && !plan ? "Retry source synchronization" : "Refresh source synchronization"}
        </button>
      </div>
      <p id={`${idPrefix}-sign`} className="text-xs leading-5 text-gray-400">Positive offsets delay that source relative to the primary. Negative offsets move it earlier. Offsets are in seconds.</p>
      {loading && <p role="status" className="text-sm text-gray-300">Loading source synchronization…</p>}
      {error && <p role="alert" className="break-words text-sm text-red-300">{error}</p>}
      {status && <p role="status" className="break-words text-sm text-emerald-200">{status}</p>}
      {plan?.warnings.length ? <ul className="list-disc space-y-1 pl-5 text-xs text-yellow-200">{plan.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul> : null}
      {plan && !plan.assets.length && <p className="text-sm text-gray-400">No synchronization sources were returned for this project.</p>}
      {plan?.assets.map(row => {
        const asset = row.asset;
        const inputId = `${idPrefix}-${asset.id}-offset`;
        const errorId = `${inputId}-error`;
        return (
          <div key={asset.id} className="min-w-0 space-y-2 rounded-lg border border-surface-border bg-surface p-3">
            <p className="break-words text-sm font-medium text-gray-100">{asset.original_filename}</p>
            <p className="text-xs text-gray-400">Role: {asset.role.replace(/_/g, " ")} · Applied offset: {row.current_offset_seconds} seconds</p>
            <p className="break-words text-xs leading-5 text-gray-300">Suggestion: {row.recommended_offset_seconds} seconds · Method: {row.method} · Confidence: {row.confidence} · {row.needs_user_review ? "Review needed" : "No review flagged"}</p>
            {row.reason && <p className="break-words text-xs text-gray-400">{row.reason}</p>}
            <form className="flex flex-wrap items-end gap-2" noValidate onSubmit={event => { event.preventDefault(); void saveOffset(asset.id); }}>
              <label htmlFor={inputId} className="grid min-w-0 flex-1 gap-1 text-xs text-gray-300">
                Offset in seconds for {asset.original_filename}
                <input id={inputId} type="number" min={-3600} max={3600} step={0.1} value={drafts[asset.id] ?? ""} disabled={busy}
                  aria-invalid={Boolean(errors[asset.id])} aria-describedby={`${idPrefix}-sign${errors[asset.id] ? ` ${errorId}` : ""}`}
                  className="min-h-11 min-w-0 rounded-md border border-surface-border bg-surface-raised px-3 py-2 text-sm text-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
                  onChange={event => {
                    const session = sessionRef.current;
                    if (!session || session.busy) return;
                    ++session.revision;
                    draftsRef.current = { ...draftsRef.current, [asset.id]: event.target.value };
                    setDrafts(draftsRef.current);
                    setErrors(previous => { const next = { ...previous }; delete next[asset.id]; return next; });
                    setStatus(null);
                  }} />
              </label>
              <button type="submit" aria-label={`Save offset for ${asset.original_filename}`} className={buttonClass} disabled={busy}>{saving === asset.id ? "Saving offset…" : "Save offset"}</button>
            </form>
            {errors[asset.id] && <p id={errorId} role="alert" className="break-words text-xs text-red-300">{errors[asset.id]}</p>}
          </div>
        );
      })}
      {plan && <div className="space-y-2 border-t border-surface-border pt-3">
        <p className="text-xs leading-5 text-gray-400">Apply metadata suggestions without replacing saved manual offsets. This uses metadata; it does not prove waveform alignment.{dirty ? " Save your edited offsets before refreshing or applying suggestions." : ""}</p>
        <button type="button" className={buttonClass} disabled={busy || dirty} onClick={() => void applyMetadata()}>{saving === "metadata" ? "Applying suggestions…" : "Apply metadata suggestions"}</button>
      </div>}
    </section>
  );
}
