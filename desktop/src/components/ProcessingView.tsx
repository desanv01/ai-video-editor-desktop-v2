import { ArrowRight, CheckCircle2, Clock, Loader2, RefreshCw, XCircle } from "lucide-react";
import { useState } from "react";
import * as api from "../lib/api";
import { useProcessingStatus } from "../hooks/useApi";

interface Props {
  videoId: string;
  onComplete: () => void;
}

const STEP_ORDER = [
  { key: "transcribing", label: "Transcribing speech" },
  { key: "embedding_transcript", label: "Building knowledge base" },
  { key: "analyzing_content", label: "Analyzing content (Agent 2)" },
  { key: "analyzing_fluency", label: "Analyzing delivery signals (Agent 3)" },
  { key: "analyzing_visual", label: "Detecting slides (Agent 4)" },
  { key: "planning_edits", label: "Generating edit plan (Agent 5)" },
  { key: "awaiting_review", label: "Ready for review" },
];

export function ProcessingView({ videoId, onComplete }: Props) {
  const { status, error } = useProcessingStatus(videoId, 2000);
  const [retrying, setRetrying] = useState(false);

  const completedSteps = status?.steps_completed ?? [];
  const failedSteps = status?.steps_failed ?? {};
  const currentStep = status?.current_step ?? "queued";
  const progressPct = status?.progress_percent ?? 0;
  const elapsedSeconds = status?.total_elapsed_seconds ?? 0;
  const estimatedRemainingSeconds = estimateRemainingSeconds(progressPct, elapsedSeconds);
  const timing = status?.steps_timing ?? {};
  const isFailed = status?.status === "failed";
  const isReady = status?.status === "awaiting_review";
  const transcriptionSummary = timing.transcribing?.summary;
  const fluencySummary = timing.analyzing_fluency?.summary;
  const visualSummary = timing.analyzing_visual?.summary;
  const agentSummaries = [
    timing.analyzing_content?.summary,
    timing.analyzing_fluency?.summary,
    timing.analyzing_visual?.summary,
    timing.planning_edits?.summary,
  ].filter(Boolean) as Record<string, unknown>[];
  const unifiedJob = status?.job ?? null;
  const displayError = api.friendlyErrorMessage(unifiedJob?.error || status?.error_message || error || "");

  return (
    <div className="h-full overflow-y-auto p-8" aria-live="polite">
      <div className="mx-auto min-h-full w-full max-w-lg space-y-8 py-8">
        <div className="space-y-2 text-center">
          {isFailed ? (
            <XCircle className="mx-auto h-12 w-12 text-red-400" />
          ) : isReady ? (
            <CheckCircle2 className="mx-auto h-12 w-12 text-green-400" />
          ) : (
            <Loader2 className="mx-auto h-12 w-12 animate-spin text-accent" />
          )}
          <h2 className="text-xl font-semibold">
            {isFailed ? "Processing Failed" : isReady ? "Processing Complete" : "Processing Video..."}
          </h2>
          {(unifiedJob?.message || status?.current_step_label) && (
            <p className="text-sm text-gray-400">{unifiedJob?.message || status?.current_step_label}</p>
          )}
        </div>

        {unifiedJob ? (
          <div className="rounded-lg border border-surface-border bg-surface-raised p-3 text-xs text-gray-300">
            <div className="flex items-center justify-between gap-3">
              <span className="font-semibold text-gray-100">{unifiedJob.type === "analysis" ? "Analysis job" : "Workflow job"}</span>
              <span className="rounded-full border border-surface-border px-2 py-0.5 text-[11px] uppercase tracking-wide text-gray-400">{unifiedJob.state.replace(/_/g, " ")}</span>
            </div>
            <p className="mt-1 text-gray-500">Stage: {unifiedJob.stage.replace(/_/g, " ")}</p>
            {unifiedJob.retryable ? <p className="mt-1 text-amber-200">This job can be retried without removing the source.</p> : null}
          </div>
        ) : null}

        <div className="space-y-2">
          <div className="flex justify-between text-xs text-gray-400">
            <span>{Math.round(progressPct)}%</span>
            {elapsedSeconds > 0 ? (
              <span className="flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {formatDuration(elapsedSeconds)}
                {estimatedRemainingSeconds !== null ? ` / ~${formatDuration(estimatedRemainingSeconds)} left` : ""}
              </span>
            ) : null}
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-surface-overlay">
            <div
              className={`h-full rounded-full transition-all duration-700 ${isFailed ? "bg-red-500" : "bg-accent"}`}
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>

        <div className="space-y-1">
          {STEP_ORDER.map((step) => {
            const isCompleted = completedSteps.includes(step.key);
            const isCurrent = currentStep === step.key && !isCompleted;
            const stepTiming = timing[step.key];
            const failed = failedSteps[step.key] ?? (stepTiming?.error ? {
              error: stepTiming.error,
              elapsed_seconds: stepTiming.elapsed_seconds,
            } : undefined);
            const elapsed = stepTiming?.elapsed_seconds ?? failed?.elapsed_seconds;

            return (
              <div
                key={step.key}
                className={`flex items-center justify-between rounded-lg px-4 py-2.5 text-sm transition-all ${
                  failed ? "border border-red-500/30 bg-red-500/10 text-red-200" :
                  isCompleted ? "bg-surface-raised text-gray-200" :
                  isCurrent ? "border border-accent/30 bg-accent/10 text-white" :
                  "text-gray-500"
                }`}
              >
                <div className="flex min-w-0 items-center gap-3">
                  <span className="w-5 shrink-0 text-center">
                    {failed ? "x" : isCompleted ? "ok" : isCurrent ? "..." : "o"}
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate">{step.label}</span>
                    {failed?.error && (
                      <span className="mt-1 block max-w-[320px] truncate text-xs text-red-300">
                        {failed.error}
                      </span>
                    )}
                  </span>
                </div>
                <div className="flex shrink-0 items-center gap-2 text-xs">
                  {elapsed !== undefined && (
                    <span className="text-gray-400">{elapsed.toFixed(1)}s</span>
                  )}
                  {isCurrent && !isCompleted && !failed && (
                    <Loader2 className="h-3 w-3 animate-spin text-accent" />
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {(transcriptionSummary || fluencySummary || agentSummaries.length > 0) && (
          <div className="space-y-3 rounded-lg border border-surface-border bg-surface-raised p-4 text-xs text-gray-300">
            {transcriptionSummary && (
              <div>
                <div className="font-semibold text-gray-100">Transcription route</div>
                <div className="mt-1 leading-5">{formatTranscriptionRoute(transcriptionSummary)}</div>
              </div>
            )}
            {agentSummaries.length > 0 && (
              <div>
                <div className="font-semibold text-gray-100">Planning routes</div>
                <div className="mt-1 leading-5">{formatAgentRoutes(agentSummaries)}</div>
              </div>
            )}
            {fluencySummary && (
              <div>
                <div className="font-semibold text-gray-100">Delivery analysis</div>
                <div className="mt-1 leading-5">{formatFluencySummary(fluencySummary)}</div>
              </div>
            )}
            {visualSummary && (
              <div>
                <div className="font-semibold text-gray-100">Visual analysis</div>
                <div className="mt-1 leading-5">{formatVisualSummary(visualSummary)}</div>
              </div>
            )}
          </div>
        )}

        {isReady && (
          <button
            type="button"
            onClick={onComplete}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-4 py-3 text-sm font-semibold text-white transition hover:bg-accent/90"
          >
            Open Editor
            <ArrowRight className="h-4 w-4" />
          </button>
        )}

        {(isFailed || error) && (
          <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
            <p>{displayError || "An unknown error occurred."}</p>
            {unifiedJob?.remediation ? <p className="mt-2 text-xs leading-5 text-red-100">Next: {unifiedJob.remediation}</p> : null}
          </div>
        )}
        {(isFailed || error) && (
          <button
            type="button"
            onClick={() => {
              setRetrying(true);
              void api.retryVideoProcessing(videoId)
                .catch(retryError => window.alert(`Retry could not start: ${api.friendlyErrorMessage(retryError)}`))
                .finally(() => setRetrying(false));
            }}
            disabled={retrying}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-4 py-3 text-sm font-semibold text-white transition hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {retrying ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            {retrying ? "Retrying…" : "Retry Processing"}
          </button>
        )}
      </div>
    </div>
  );
}

function formatTranscriptionRoute(summary: Record<string, unknown>): string {
  const route = summary.transcription_route as Record<string, unknown> | undefined;
  if (!route) {
    return String(summary.provider ?? "Provider not reported");
  }
  const mode = String(route.mode ?? "unknown");
  const selected = String(route.selected_provider ?? summary.provider ?? "unknown");
  const attempted = Array.isArray(route.attempted_providers)
    ? route.attempted_providers.join(" -> ")
    : selected;
  const fallbackFrom = route.fallback_from ? `, fallback from ${String(route.fallback_from)}` : "";
  return `${mode.toUpperCase()}: ${attempted}; selected ${selected}${fallbackFrom}`;
}

function formatAgentRoutes(summaries: Record<string, unknown>[]): string {
  const routes = summaries
    .map((summary) => {
      const provider = summary.chat_provider ? String(summary.chat_provider) : null;
      const visionProvider = summary.vision_provider ? String(summary.vision_provider) : null;
      const model = summary.model ? String(summary.model) : null;
      if (visionProvider) return `vision: ${visionProvider}`;
      if (!provider && !model) return null;
      return [provider, model].filter(Boolean).join(" / ");
    })
    .filter(Boolean);

  return routes.length > 0 ? Array.from(new Set(routes)).join("; ") : "Provider not reported";
}

function formatFluencySummary(summary: Record<string, unknown>): string {
  const fillers = Number(summary.total_fillers ?? 0);
  const pauses = Number(summary.pauses_detected ?? 0);
  const updated = Number(summary.segments_updated ?? 0);
  const fallbackSegments = Number(summary.fallback_segments ?? 0);
  const failedBatches = Number(summary.batches_failed ?? 0);
  const diagnostics = failedBatches > 0 || fallbackSegments > 0
    ? `; fallback segments ${fallbackSegments}, failed batches ${failedBatches}`
    : "";
  return `${fillers} fillers detected, ${pauses} pause regions, ${updated} segments updated${diagnostics}`;
}

function formatVisualSummary(summary: Record<string, unknown>): string {
  const scenes = Number(summary.scenes_detected ?? 0);
  const source = String(summary.analysis_source ?? "not reported").replace(/_/g, " ");
  const structureCount = Number(summary.structure_reference_count ?? 0);
  const skipReason = summary.skip_reason ? `; ${String(summary.skip_reason)}` : "";
  return `${scenes} scene changes, ${structureCount} structure references, source: ${source}${skipReason}`;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

function estimateRemainingSeconds(progressPct: number, elapsedSeconds: number): number | null {
  if (!Number.isFinite(progressPct) || !Number.isFinite(elapsedSeconds)) return null;
  if (progressPct < 3 || progressPct >= 99 || elapsedSeconds <= 0) return null;
  const totalEstimate = elapsedSeconds / Math.max(progressPct / 100, 0.01);
  const remaining = totalEstimate - elapsedSeconds;
  if (!Number.isFinite(remaining) || remaining < 0) return null;
  return remaining;
}
