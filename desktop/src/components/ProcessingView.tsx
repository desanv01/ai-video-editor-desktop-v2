import { useEffect } from "react";
import { useProcessingStatus } from "../hooks/useApi";
import { Loader2, CheckCircle2, XCircle, Clock } from "lucide-react";

interface Props {
  videoId: string;
  onComplete: () => void;
}

const STEP_ORDER = [
  { key: "transcribing", label: "Transcribing speech", icon: "🎙️" },
  { key: "embedding_transcript", label: "Building knowledge base", icon: "🧠" },
  { key: "analyzing_content", label: "Analyzing content (Agent 2)", icon: "📝" },
  { key: "analyzing_fluency", label: "Detecting fillers (Agent 3)", icon: "🗣️" },
  { key: "analyzing_visual", label: "Detecting slides (Agent 4)", icon: "🎬" },
  { key: "planning_edits", label: "Generating edit plan (Agent 5)", icon: "✂️" },
  { key: "awaiting_review", label: "Ready for review", icon: "✅" },
];

export function ProcessingView({ videoId, onComplete }: Props) {
  const { status, error } = useProcessingStatus(videoId, 2000);

  // Auto-transition to review when ready
  useEffect(() => {
    if (status?.status === "awaiting_review") {
      const timer = setTimeout(onComplete, 1500);
      return () => clearTimeout(timer);
    }
  }, [status?.status, onComplete]);

  const completedSteps = status?.steps_completed ?? [];
  const currentStep = status?.current_step ?? "queued";
  const progressPct = status?.progress_percent ?? 0;
  const timing = status?.steps_timing ?? {};
  const isFailed = status?.status === "failed";

  return (
    <div className="h-full flex items-center justify-center p-8">
      <div className="max-w-lg w-full space-y-8">
        {/* ── Header ── */}
        <div className="text-center space-y-2">
          {isFailed ? (
            <XCircle className="w-12 h-12 text-red-400 mx-auto" />
          ) : currentStep === "awaiting_review" ? (
            <CheckCircle2 className="w-12 h-12 text-green-400 mx-auto" />
          ) : (
            <Loader2 className="w-12 h-12 text-accent animate-spin mx-auto" />
          )}
          <h2 className="text-xl font-semibold">
            {isFailed ? "Processing Failed" : currentStep === "awaiting_review" ? "Processing Complete!" : "Processing Video..."}
          </h2>
          {status?.current_step_label && (
            <p className="text-sm text-gray-400">{status.current_step_label}</p>
          )}
        </div>

        {/* ── Progress Bar ── */}
        <div className="space-y-2">
          <div className="flex justify-between text-xs text-gray-400">
            <span>{Math.round(progressPct)}%</span>
            {status?.total_elapsed_seconds ? (
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {formatDuration(status.total_elapsed_seconds)}
              </span>
            ) : null}
          </div>
          <div className="h-2 bg-surface-overlay rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-700 ${isFailed ? "bg-red-500" : "bg-accent"}`}
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>

        {/* ── Step List ── */}
        <div className="space-y-1">
          {STEP_ORDER.map(step => {
            const isCompleted = completedSteps.includes(step.key);
            const isCurrent = currentStep === step.key && !isCompleted;
            const stepTiming = timing[step.key];
            const elapsed = stepTiming?.elapsed_seconds;

            return (
              <div
                key={step.key}
                className={`flex items-center justify-between px-4 py-2.5 rounded-lg text-sm transition-all ${
                  isCompleted ? "bg-surface-raised text-gray-200" :
                  isCurrent ? "bg-accent/10 text-white border border-accent/30" :
                  "text-gray-500"
                }`}
              >
                <div className="flex items-center gap-3">
                  <span className="w-5 text-center">
                    {isCompleted ? "✓" : isCurrent ? step.icon : "○"}
                  </span>
                  <span>{step.label}</span>
                </div>
                <div className="flex items-center gap-2 text-xs">
                  {elapsed !== undefined && (
                    <span className="text-gray-400">{elapsed.toFixed(1)}s</span>
                  )}
                  {isCurrent && !isCompleted && (
                    <Loader2 className="w-3 h-3 animate-spin text-accent" />
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* ── Error Message ── */}
        {(isFailed || error) && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-sm text-red-300">
            {status?.error_message || error || "An unknown error occurred."}
          </div>
        )}
      </div>
    </div>
  );
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}
