import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  ArrowLeft,
  ArrowRight,
  Captions,
  CheckCircle2,
  Circle,
  Download,
  FileText,
  Film,
  Layers,
  ListChecks,
  Loader2,
  MessageSquareOff,
  MonitorPlay,
  Palette,
  RefreshCw,
  Scissors,
  SlidersHorizontal,
  Sparkles,
  SplitSquareHorizontal,
  TextSelect,
  Wand2,
  Volume2,
} from "lucide-react";
import { SegmentDetail } from "./SegmentDetail";
import * as api from "../lib/api";
import type { Chapter, CleanAnalyzeResult, CleanProfileId, EditPlan, RevalidationResult, Segment } from "../types/api";

export type GuidedWorkflowStepId = "transcribe" | "clean" | "sections" | "layout" | "polish" | "export";

export type GuidedWorkflowStep = {
  id: GuidedWorkflowStepId;
  label: string;
  shortLabel: string;
  eyebrow: string;
  description: string;
  icon: LucideIcon;
};

export const GUIDED_WORKFLOW_STEPS: GuidedWorkflowStep[] = [
  {
    id: "transcribe",
    label: "Transcribe",
    shortLabel: "Transcript",
    eyebrow: "Speech to text",
    description: "Confirm the generated transcript and timing are ready for editing.",
    icon: TextSelect,
  },
  {
    id: "clean",
    label: "Clean",
    shortLabel: "Cleanup",
    eyebrow: "Decision review",
    description: "Review cuts, filler words, silence, and teacher overrides.",
    icon: Scissors,
  },
  {
    id: "sections",
    label: "Sections",
    shortLabel: "Sections",
    eyebrow: "Lecture structure",
    description: "Check generated chapters and the teaching flow before layout work.",
    icon: ListChecks,
  },
  {
    id: "layout",
    label: "Layout",
    shortLabel: "Layout",
    eyebrow: "Composition",
    description: "Choose the intended screen, camera, and slide framing direction.",
    icon: SplitSquareHorizontal,
  },
  {
    id: "polish",
    label: "Polish",
    shortLabel: "Polish",
    eyebrow: "Presentation",
    description: "Prepare captions, labels, cards, transitions, and review polish.",
    icon: Sparkles,
  },
  {
    id: "export",
    label: "Export",
    shortLabel: "Export",
    eyebrow: "Delivery",
    description: "Approve the edit and download video, subtitle, chapter, and plan files.",
    icon: Download,
  },
];

type StepperProps = {
  activeStep: GuidedWorkflowStepId;
  completedStepIds: Set<GuidedWorkflowStepId>;
  onStepChange: (step: GuidedWorkflowStepId) => void;
};

type PanelProps = StepperProps & {
  videoId: string;
  segments: Segment[];
  selectedSegment: Segment | null;
  plan: EditPlan | null;
  warnings: RevalidationResult | null;
  chapters: Chapter[];
  chaptersLoading: boolean;
  approving: boolean;
  onAcceptAll: () => void;
  onCleanApplied: () => Promise<void> | void;
  onApprove: () => void;
  onRefreshChapters: () => void;
  onSeekToTime: (time: number) => void;
  onUpdateAction: (segId: string, action: Segment["action"], note?: string) => void;
  onCompleteStep: (step: GuidedWorkflowStepId) => void;
  onNextStep: () => void;
  onPreviousStep: () => void;
};

export function GuidedWorkflowStepper({ activeStep, completedStepIds, onStepChange }: StepperProps) {
  const completedCount = GUIDED_WORKFLOW_STEPS.filter((step) => completedStepIds.has(step.id)).length;
  const progressPercent = Math.round((completedCount / GUIDED_WORKFLOW_STEPS.length) * 100);

  return (
    <div className="border-b border-surface-border bg-surface-raised px-4 py-3">
      <div className="mb-3 flex items-center justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-white">Guided Editor Workflow</h2>
          <p className="text-xs text-gray-400">{completedCount} of {GUIDED_WORKFLOW_STEPS.length} steps complete</p>
        </div>
        <div className="w-44">
          <div className="mb-1 flex items-center justify-between text-[11px] text-gray-400">
            <span>Progress</span>
            <span>{progressPercent}%</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-surface-overlay">
            <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${progressPercent}%` }} />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-6 gap-2">
        {GUIDED_WORKFLOW_STEPS.map((step, index) => {
          const Icon = step.icon;
          const isActive = activeStep === step.id;
          const isComplete = completedStepIds.has(step.id);

          return (
            <button
              key={step.id}
              type="button"
              onClick={() => onStepChange(step.id)}
              aria-current={isActive ? "step" : undefined}
              className={`flex min-w-0 items-center gap-2 rounded-md border px-2.5 py-2 text-left transition-colors ${
                isActive
                  ? "border-accent bg-accent/15 text-white"
                  : isComplete
                    ? "border-green-500/30 bg-green-500/10 text-gray-100 hover:bg-green-500/15"
                    : "border-surface-border bg-surface-overlay text-gray-400 hover:border-gray-500 hover:text-gray-200"
              }`}
            >
              <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded ${
                isComplete ? "bg-green-500/20 text-green-300" : isActive ? "bg-accent text-white" : "bg-surface-raised"
              }`}>
                {isComplete ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Icon className="h-3.5 w-3.5" />}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-xs font-semibold">{index + 1}. {step.label}</span>
                <span className="block truncate text-[11px] text-gray-500">{step.eyebrow}</span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function GuidedWorkflowPanel({
  activeStep,
  completedStepIds,
  videoId,
  segments,
  selectedSegment,
  plan,
  warnings,
  chapters,
  chaptersLoading,
  approving,
  onAcceptAll,
  onCleanApplied,
  onApprove,
  onRefreshChapters,
  onSeekToTime,
  onUpdateAction,
  onCompleteStep,
  onNextStep,
  onPreviousStep,
  onStepChange,
}: PanelProps) {
  const [layoutPreset, setLayoutPreset] = useState("slide-pip");
  const [cleanProfile, setCleanProfile] = useState<CleanProfileId>("conservative");
  const [cleanPreview, setCleanPreview] = useState<CleanAnalyzeResult | null>(null);
  const [cleanBusy, setCleanBusy] = useState(false);
  const [cleanMessage, setCleanMessage] = useState<string | null>(null);
  const [polishOptions, setPolishOptions] = useState({
    captions: true,
    sectionLabels: true,
    titleCards: false,
    transitions: true,
  });

  const activeStepMeta = GUIDED_WORKFLOW_STEPS.find((step) => step.id === activeStep) ?? GUIDED_WORKFLOW_STEPS[0];
  const activeIndex = GUIDED_WORKFLOW_STEPS.findIndex((step) => step.id === activeStep);
  const isFirstStep = activeIndex === 0;
  const isLastStep = activeIndex === GUIDED_WORKFLOW_STEPS.length - 1;

  const actionCounts = useMemo(() => {
    return segments.reduce(
      (counts, segment) => {
        const action = segment.is_teacher_modified && segment.teacher_action ? segment.teacher_action : segment.action;
        counts[action] += 1;
        return counts;
      },
      { keep: 0, cut: 0, shorten: 0, highlight: 0 },
    );
  }, [segments]);

  const original = plan?.original_duration ?? 0;
  const estimated = plan?.estimated_duration ?? 0;
  const saved = Math.max(0, original - estimated);
  const warningCount = (warnings?.warnings.length ?? 0) + (warnings?.consequence_alerts.length ?? 0);
  const StepIcon = activeStepMeta.icon;

  const handleAnalyzeClean = async () => {
    setCleanBusy(true);
    setCleanMessage(null);
    try {
      const result = await api.analyzeCleanSuggestions(videoId, cleanProfile);
      setCleanPreview(result);
      setCleanMessage(`${result.summary.suggestions_total} suggestions found`);
    } catch (error) {
      setCleanMessage(`Clean analysis failed: ${error}`);
    } finally {
      setCleanBusy(false);
    }
  };

  const handleApplyClean = async () => {
    setCleanBusy(true);
    setCleanMessage(null);
    try {
      const result = await api.applyCleanSuggestions(videoId, cleanProfile);
      setCleanPreview({
        schema_version: result.schema_version,
        profile: result.profile,
        profiles: cleanPreview?.profiles ?? [],
        summary: result.summary,
        suggestions: result.suggestions,
      });
      await onCleanApplied();
      onCompleteStep("clean");
      setCleanMessage(
        `Applied ${result.created_transcript_cuts.length} transcript cuts and ${result.updated_segments.length} segment edits`,
      );
    } catch (error) {
      setCleanMessage(`Auto-clean failed: ${error}`);
    } finally {
      setCleanBusy(false);
    }
  };

  return (
    <aside className="flex h-full flex-col bg-surface-raised">
      <div className="border-b border-surface-border p-4">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-accent">{activeStepMeta.eyebrow}</p>
            <h3 className="mt-1 flex items-center gap-2 text-base font-semibold text-white">
              <StepIcon className="h-4 w-4" />
              {activeStepMeta.label}
            </h3>
          </div>
          <StepStatus complete={completedStepIds.has(activeStep)} />
        </div>
        <p className="text-xs leading-5 text-gray-400">{activeStepMeta.description}</p>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {activeStep === "transcribe" && (
          <PanelStack>
            <MetricGrid>
              <Metric label="Transcript segments" value={String(segments.length)} />
              <Metric label="Source duration" value={formatDuration(original)} />
              <Metric label="Timing state" value={segments.length > 0 ? "Ready" : "Waiting"} tone={segments.length > 0 ? "good" : "muted"} />
            </MetricGrid>
            <WorkflowCard title="Transcript Review" icon={<FileText className="h-4 w-4 text-sky-300" />}>
              <p className="text-xs leading-5 text-gray-400">
                Use the transcript panel to skim sentence order, timing, and speaker content. The step is marked ready once transcript segments exist.
              </p>
            </WorkflowCard>
          </PanelStack>
        )}

        {activeStep === "clean" && (
          <PanelStack>
            <WorkflowCard title="Auto-Clean" icon={<Wand2 className="h-4 w-4 text-sky-300" />}>
              <div className="space-y-3">
                <OptionGroup
                  value={cleanProfile}
                  onChange={(value) => {
                    setCleanProfile(value as CleanProfileId);
                    setCleanPreview(null);
                    setCleanMessage(null);
                  }}
                  options={[
                    { value: "conservative", label: "Conservative", icon: SlidersHorizontal },
                    { value: "aggressive", label: "Aggressive", icon: Sparkles },
                  ]}
                />
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={handleAnalyzeClean}
                    disabled={cleanBusy}
                    className="flex items-center justify-center gap-2 rounded-md bg-surface-raised px-3 py-2 text-xs font-semibold text-gray-200 transition-colors hover:bg-surface-border disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {cleanBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                    Analyze
                  </button>
                  <button
                    type="button"
                    onClick={handleApplyClean}
                    disabled={cleanBusy}
                    className="flex items-center justify-center gap-2 rounded-md bg-accent px-3 py-2 text-xs font-semibold text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {cleanBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Scissors className="h-3.5 w-3.5" />}
                    Auto-clean
                  </button>
                </div>
                {cleanPreview && (
                  <div className="grid grid-cols-2 gap-2">
                    <MiniMetric label="Fillers" value={String(cleanPreview.summary.filler_word_count)} />
                    <MiniMetric label="Dead air" value={String(cleanPreview.summary.dead_air_count)} />
                    <MiniMetric label="Bad takes" value={String(cleanPreview.summary.bad_take_count)} />
                    <MiniMetric label="Repetition" value={String(cleanPreview.summary.repetition_suggestion_count ?? 0)} />
                  </div>
                )}
                {cleanMessage && <p className="text-xs leading-5 text-gray-400">{cleanMessage}</p>}
              </div>
            </WorkflowCard>
            <button
              type="button"
              onClick={onAcceptAll}
              className="flex w-full items-center justify-center gap-2 rounded-md bg-green-600/20 px-3 py-2.5 text-sm font-semibold text-green-300 transition-colors hover:bg-green-600/30"
            >
              <CheckCircle2 className="h-4 w-4" />
              Accept All High-Confidence
            </button>
            <MetricGrid>
              <Metric label="Keep" value={String(actionCounts.keep)} tone="good" />
              <Metric label="Cut" value={String(actionCounts.cut)} tone="danger" />
              <Metric label="Shorten" value={String(actionCounts.shorten)} />
              <Metric label="Highlight" value={String(actionCounts.highlight)} tone="warn" />
            </MetricGrid>
            <WorkflowCard title="Cleaning Signals" icon={<MessageSquareOff className="h-4 w-4 text-orange-300" />}>
              <div className="space-y-2 text-xs text-gray-300">
                <IconStat icon={<MessageSquareOff className="h-3.5 w-3.5 text-orange-300" />} label="Filler words removed" value={String(plan?.filler_words_removed ?? 0)} />
                <IconStat icon={<Volume2 className="h-3.5 w-3.5 text-blue-300" />} label="Silence removed" value={`${(plan?.silence_removed_seconds ?? 0).toFixed(1)}s`} />
                <IconStat icon={<Circle className="h-3.5 w-3.5 text-yellow-300" />} label="Open warnings" value={String(warningCount)} />
              </div>
            </WorkflowCard>
            <div className="rounded-md border border-surface-border bg-surface-overlay">
              {selectedSegment ? (
                <SegmentDetail segment={selectedSegment} onUpdateAction={onUpdateAction} />
              ) : (
                <div className="p-4 text-center text-sm text-gray-500">
                  Select a transcript or timeline segment to inspect the AI decision.
                </div>
              )}
            </div>
          </PanelStack>
        )}

        {activeStep === "sections" && (
          <PanelStack>
            <div className="flex items-center justify-between gap-3">
              <div>
                <h4 className="text-sm font-semibold text-white">Generated Chapters</h4>
                <p className="text-xs text-gray-500">{chapters.length} chapter markers found</p>
              </div>
              <button
                type="button"
                onClick={onRefreshChapters}
                className="rounded-md p-2 text-gray-400 transition-colors hover:bg-surface-overlay hover:text-gray-200"
                aria-label="Refresh chapters"
              >
                {chaptersLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              </button>
            </div>
            {chapters.length > 0 ? (
              <div className="space-y-2">
                {chapters.map((chapter, index) => (
                  <button
                    key={`${chapter.timestamp}-${chapter.segment_index}-${index}`}
                    type="button"
                    onClick={() => onSeekToTime(chapter.timestamp)}
                    className="flex w-full items-start gap-3 rounded-md border border-surface-border bg-surface-overlay px-3 py-2 text-left"
                  >
                    <span className="font-mono text-xs text-accent">{chapter.formatted}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-xs text-gray-200">{chapter.label}</span>
                      <span className="mt-1 block text-[11px] leading-4 text-gray-500">
                        {[
                          chapter.segment_count ? `${chapter.segment_count} segments` : null,
                          chapter.confidence != null ? `${Math.round(chapter.confidence * 100)}% confidence` : null,
                          chapter.boundary_reason,
                        ].filter(Boolean).join(" - ")}
                      </span>
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <EmptyState title="No chapters yet" detail="Chapters appear here after the edit plan has section markers." />
            )}
          </PanelStack>
        )}

        {activeStep === "layout" && (
          <PanelStack>
            <OptionGroup
              value={layoutPreset}
              onChange={setLayoutPreset}
              options={[
                { value: "slide-pip", label: "Slides + camera", icon: MonitorPlay },
                { value: "side-by-side", label: "Side by side", icon: SplitSquareHorizontal },
                { value: "camera-full", label: "Camera focus", icon: Film },
                { value: "screen-full", label: "Screen focus", icon: Layers },
              ]}
            />
            <WorkflowCard title="Layout Intent" icon={<SplitSquareHorizontal className="h-4 w-4 text-blue-300" />}>
              <p className="text-xs leading-5 text-gray-400">
                This step captures the teacher-facing workflow position before the Phase 7 layout engine adds timed layout cues and renderer support.
              </p>
            </WorkflowCard>
          </PanelStack>
        )}

        {activeStep === "polish" && (
          <PanelStack>
            <ToggleRow
              label="Selective captions"
              detail="Prepare caption styling and burn-in decisions."
              checked={polishOptions.captions}
              icon={<Captions className="h-4 w-4 text-sky-300" />}
              onChange={(checked) => setPolishOptions((prev) => ({ ...prev, captions: checked }))}
            />
            <ToggleRow
              label="Section labels"
              detail="Show topic names at chapter starts."
              checked={polishOptions.sectionLabels}
              icon={<ListChecks className="h-4 w-4 text-green-300" />}
              onChange={(checked) => setPolishOptions((prev) => ({ ...prev, sectionLabels: checked }))}
            />
            <ToggleRow
              label="Title cards"
              detail="Reserve intro and section title cards for later polish tooling."
              checked={polishOptions.titleCards}
              icon={<Palette className="h-4 w-4 text-pink-300" />}
              onChange={(checked) => setPolishOptions((prev) => ({ ...prev, titleCards: checked }))}
            />
            <ToggleRow
              label="Gentle transitions"
              detail="Use simple changes between sections and layouts."
              checked={polishOptions.transitions}
              icon={<Sparkles className="h-4 w-4 text-yellow-300" />}
              onChange={(checked) => setPolishOptions((prev) => ({ ...prev, transitions: checked }))}
            />
          </PanelStack>
        )}

        {activeStep === "export" && (
          <PanelStack>
            <MetricGrid>
              <Metric label="Original" value={formatDuration(original)} />
              <Metric label="Estimated" value={formatDuration(estimated)} tone="good" />
              <Metric label="Saved" value={formatDuration(saved)} tone="warn" />
            </MetricGrid>
            {!plan?.is_approved ? (
              <button
                type="button"
                onClick={onApprove}
                disabled={approving || !plan}
                className="flex w-full items-center justify-center gap-2 rounded-md bg-accent px-3 py-3 text-sm font-semibold text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
              >
                {approving ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                {approving ? "Rendering..." : "Approve & Render Video"}
              </button>
            ) : (
              <div className="space-y-2">
                <DownloadLink href={api.getVideoDownloadUrl(videoId)} label="Edited Video (MP4)" primary />
                <DownloadLink href={api.getSubtitleDownloadUrl(videoId)} label="Subtitles (SRT)" />
                <DownloadLink href={api.getSubtitleVttUrl(videoId)} label="Subtitles (VTT)" />
                <DownloadLink href={api.getChaptersDownloadUrl(videoId)} label="Chapter Markers" />
                <DownloadLink href={api.getPlanExportUrl(videoId)} label="Edit Plan (JSON)" />
              </div>
            )}
          </PanelStack>
        )}
      </div>

      <div className="border-t border-surface-border p-3">
        <div className="mb-3 grid grid-cols-6 gap-1">
          {GUIDED_WORKFLOW_STEPS.map((step) => (
            <button
              key={step.id}
              type="button"
              onClick={() => onStepChange(step.id)}
              className={`h-1.5 rounded-full transition-colors ${
                activeStep === step.id || completedStepIds.has(step.id) ? "bg-accent" : "bg-surface-overlay"
              }`}
              aria-label={`Go to ${step.label}`}
            />
          ))}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onPreviousStep}
            disabled={isFirstStep}
            className="flex h-9 w-9 items-center justify-center rounded-md bg-surface-overlay text-gray-300 transition-colors hover:bg-surface-border disabled:cursor-not-allowed disabled:opacity-40"
            aria-label="Previous step"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => onCompleteStep(activeStep)}
            className="flex-1 rounded-md bg-surface-overlay px-3 py-2 text-xs font-semibold text-gray-200 transition-colors hover:bg-surface-border"
          >
            Mark {activeStepMeta.shortLabel} Complete
          </button>
          <button
            type="button"
            onClick={onNextStep}
            disabled={isLastStep}
            className="flex h-9 w-9 items-center justify-center rounded-md bg-accent text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40"
            aria-label="Next step"
          >
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      </div>
    </aside>
  );
}

function StepStatus({ complete }: { complete: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] font-semibold ${
      complete ? "bg-green-500/15 text-green-300" : "bg-surface-overlay text-gray-400"
    }`}>
      {complete ? <CheckCircle2 className="h-3 w-3" /> : <Circle className="h-3 w-3" />}
      {complete ? "Complete" : "In progress"}
    </span>
  );
}

function PanelStack({ children }: { children: ReactNode }) {
  return <div className="space-y-4">{children}</div>;
}

function WorkflowCard({ title, icon, children }: { title: string; icon: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-md border border-surface-border bg-surface-overlay p-3">
      <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold text-white">
        {icon}
        {title}
      </h4>
      {children}
    </section>
  );
}

function MetricGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-3 gap-2">{children}</div>;
}

function Metric({ label, value, tone = "muted" }: { label: string; value: string; tone?: "muted" | "good" | "warn" | "danger" }) {
  const toneClass = {
    muted: "text-gray-100",
    good: "text-green-300",
    warn: "text-yellow-300",
    danger: "text-red-300",
  }[tone];

  return (
    <div className="rounded-md border border-surface-border bg-surface-overlay px-3 py-2">
      <div className={`text-sm font-semibold ${toneClass}`}>{value}</div>
      <div className="mt-1 text-[11px] text-gray-500">{label}</div>
    </div>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-surface-border bg-surface-raised px-2 py-2">
      <div className="text-sm font-semibold text-gray-100">{value}</div>
      <div className="mt-0.5 truncate text-[11px] text-gray-500">{label}</div>
    </div>
  );
}

function IconStat({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="flex items-center gap-2 text-gray-400">{icon}{label}</span>
      <span className="font-semibold text-gray-100">{value}</span>
    </div>
  );
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="rounded-md border border-dashed border-surface-border bg-surface-overlay px-4 py-6 text-center">
      <p className="text-sm font-semibold text-gray-300">{title}</p>
      <p className="mt-1 text-xs leading-5 text-gray-500">{detail}</p>
    </div>
  );
}

type OptionGroupProps = {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string; icon: LucideIcon }[];
};

function OptionGroup({ value, onChange, options }: OptionGroupProps) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {options.map((option) => {
        const Icon = option.icon;
        const active = value === option.value;

        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            className={`flex items-center gap-2 rounded-md border px-3 py-2 text-left text-xs font-semibold transition-colors ${
              active ? "border-accent bg-accent/15 text-white" : "border-surface-border bg-surface-overlay text-gray-400 hover:text-gray-200"
            }`}
          >
            <Icon className="h-4 w-4 shrink-0" />
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

function ToggleRow({
  label,
  detail,
  checked,
  icon,
  onChange,
}: {
  label: string;
  detail: string;
  checked: boolean;
  icon: ReactNode;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-3 rounded-md border border-surface-border bg-surface-overlay p-3">
      <span className="mt-0.5">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold text-gray-100">{label}</span>
        <span className="mt-1 block text-xs leading-5 text-gray-500">{detail}</span>
      </span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-1 h-4 w-4 accent-accent"
      />
    </label>
  );
}

function DownloadLink({ href, label, primary = false }: { href: string; label: string; primary?: boolean }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className={`flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-semibold transition-colors ${
        primary ? "bg-green-600 text-white hover:bg-green-700" : "bg-surface-overlay text-gray-200 hover:bg-surface-border"
      }`}
    >
      <Download className="h-4 w-4" />
      {label}
    </a>
  );
}

function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "0:00";
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.round(seconds % 60);
  return `${minutes}:${remainingSeconds.toString().padStart(2, "0")}`;
}
