import { useState, useEffect, useCallback, useMemo } from "react";
import { useSegments, usePlaybackSync } from "../hooks/useApi";
import { useCommandShortcuts } from "../hooks/useCommandShortcuts";
import { Timeline } from "./Timeline";
import { TranscriptPanel } from "./TranscriptPanel";
import { CommandPalette, type CommandPaletteCommand } from "./CommandPalette";
import {
  GUIDED_WORKFLOW_STEPS,
  GuidedWorkflowPanel,
  GuidedWorkflowStepper,
  type GuidedWorkflowStepId,
} from "./GuidedWorkflow";
import * as api from "../lib/api";
import type { Chapter, Segment, EditPlan, SegmentAction, RevalidationResult, TranscriptCutDecision, TranscriptTimeline } from "../types/api";
import {
  Activity,
  AlertTriangle,
  CheckSquare,
  Clock3,
  Download,
  FileText,
  FolderOpen,
  Keyboard,
  Layers,
  Loader2,
  MonitorPlay,
  Pause,
  Play,
  RadioTower,
  Redo2,
  Scissors,
  Settings,
  SkipBack,
  SkipForward,
  Undo2,
} from "lucide-react";

interface Props {
  videoId: string;
  videoFilename?: string;
  onOpenSettings: () => void;
}

type LeftPanelTab = "transcript" | "assets";

export function ReviewEditor({ videoId, videoFilename, onOpenSettings }: Props) {
  const { segments, loading, updateAction, acceptAllHighConfidence } = useSegments(videoId);
  const { currentTime, setCurrentTime, isPlaying, setIsPlaying, videoRef, seekTo, togglePlay } = usePlaybackSync();
  const [selectedSegment, setSelectedSegment] = useState<Segment | null>(null);
  const [activeWorkflowStep, setActiveWorkflowStep] = useState<GuidedWorkflowStepId>("transcribe");
  const [completedWorkflowSteps, setCompletedWorkflowSteps] = useState<Set<GuidedWorkflowStepId>>(() => new Set());
  const [leftPanelTab, setLeftPanelTab] = useState<LeftPanelTab>("transcript");
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [plan, setPlan] = useState<EditPlan | null>(null);
  const [warnings, setWarnings] = useState<RevalidationResult | null>(null);
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [chaptersLoading, setChaptersLoading] = useState(false);
  const [transcriptTimeline, setTranscriptTimeline] = useState<TranscriptTimeline | null>(null);
  const [transcriptCuts, setTranscriptCuts] = useState<TranscriptCutDecision[]>([]);
  const [transcriptCutsLoading, setTranscriptCutsLoading] = useState(false);
  const [approving, setApproving] = useState(false);
  const [duration, setDuration] = useState(0);

  useEffect(() => {
    api.getEditPlan(videoId).then(setPlan).catch(() => {});
  }, [videoId]);

  const loadChapters = useCallback(async () => {
    setChaptersLoading(true);
    try {
      const result = await api.getChapters(videoId);
      setChapters(result.chapters);
    } catch {
      setChapters([]);
    } finally {
      setChaptersLoading(false);
    }
  }, [videoId]);

  useEffect(() => {
    void loadChapters();
  }, [loadChapters]);

  const loadTranscriptEditingData = useCallback(async () => {
    setTranscriptCutsLoading(true);
    try {
      const [timelineResult, cutsResult] = await Promise.all([
        api.getTranscriptTimeline(videoId),
        api.getTranscriptCutDecisions(videoId),
      ]);
      setTranscriptTimeline(timelineResult);
      setTranscriptCuts(cutsResult);
    } catch {
      setTranscriptTimeline(null);
      setTranscriptCuts([]);
    } finally {
      setTranscriptCutsLoading(false);
    }
  }, [videoId]);

  useEffect(() => {
    void loadTranscriptEditingData();
  }, [loadTranscriptEditingData]);

  useEffect(() => {
    setCompletedWorkflowSteps(prev => {
      const next = new Set(prev);
      if (segments.length > 0) next.add("transcribe");
      if (plan?.is_approved) next.add("export");
      return next;
    });
  }, [segments.length, plan?.is_approved]);

  const videoSrc = api.getVideoStreamUrl(videoId);

  const handleTimeUpdate = useCallback(() => {
    if (videoRef.current) {
      setCurrentTime(videoRef.current.currentTime);
    }
  }, [videoRef, setCurrentTime]);

  const handleLoadedMetadata = useCallback(() => {
    if (videoRef.current) {
      setDuration(videoRef.current.duration || plan?.original_duration || 0);
    }
  }, [videoRef, plan]);

  const handleSelectSegment = useCallback((seg: Segment) => {
    setSelectedSegment(seg);
    setActiveWorkflowStep("clean");
  }, []);

  const handleUpdateAction = useCallback(async (segId: string, action: SegmentAction, note?: string) => {
    await updateAction(segId, action, note);
    try {
      const result = await api.revalidatePlan(videoId);
      setWarnings(result);
    } catch {
      // Revalidation is helpful context, but editing should continue if it fails.
    }
  }, [videoId, updateAction]);

  const handleCreateTranscriptCut = useCallback(async (wordStartIndex: number, wordEndIndex: number) => {
    const decision = await api.createTranscriptCutDecision(videoId, {
      word_start_index: wordStartIndex,
      word_end_index: wordEndIndex,
      teacher_note: "Marked for cut from transcript text selection",
    });
    setTranscriptCuts(prev => [...prev, decision]);
    setActiveWorkflowStep("clean");
    try {
      const updatedPlan = await api.getEditPlan(videoId);
      setPlan(updatedPlan);
    } catch {
      // The cut decision is already stored; plan stats are secondary UI context.
    }
  }, [videoId]);

  const handleDeleteTranscriptCut = useCallback(async (decisionId: string) => {
    await api.deleteTranscriptCutDecision(videoId, decisionId);
    setTranscriptCuts(prev => prev.filter(decision => decision.id !== decisionId));
    try {
      const updatedPlan = await api.getEditPlan(videoId);
      setPlan(updatedPlan);
    } catch {
      // Keep the transcript panel responsive even if stats refresh fails.
    }
  }, [videoId]);

  const handleAcceptAll = useCallback(async () => {
    const count = await acceptAllHighConfidence(0.85);
    if (count && count > 0) {
      setCompletedWorkflowSteps(prev => new Set(prev).add("clean"));
      alert(`Auto-accepted ${count} high-confidence segments`);
    } else {
      alert("No segments to auto-accept (all already reviewed or below threshold)");
    }
  }, [acceptAllHighConfidence]);

  const handleApprove = useCallback(async () => {
    setApproving(true);
    try {
      await api.approvePlan(videoId);
      const updatedPlan = await api.getEditPlan(videoId);
      setPlan(updatedPlan);
      setCompletedWorkflowSteps(prev => new Set(prev).add("export"));
    } catch (e) {
      alert(`Approval failed: ${e}`);
    } finally {
      setApproving(false);
    }
  }, [videoId]);

  const handleCompleteWorkflowStep = useCallback((step: GuidedWorkflowStepId) => {
    setCompletedWorkflowSteps(prev => new Set(prev).add(step));
  }, []);

  const handleNextWorkflowStep = useCallback(() => {
    setCompletedWorkflowSteps(prev => new Set(prev).add(activeWorkflowStep));
    const currentIndex = GUIDED_WORKFLOW_STEPS.findIndex(step => step.id === activeWorkflowStep);
    const nextStep = GUIDED_WORKFLOW_STEPS[currentIndex + 1];
    if (nextStep) setActiveWorkflowStep(nextStep.id);
  }, [activeWorkflowStep]);

  const handlePreviousWorkflowStep = useCallback(() => {
    const currentIndex = GUIDED_WORKFLOW_STEPS.findIndex(step => step.id === activeWorkflowStep);
    const previousStep = GUIDED_WORKFLOW_STEPS[currentIndex - 1];
    if (previousStep) setActiveWorkflowStep(previousStep.id);
  }, [activeWorkflowStep]);

  const effectiveDuration = duration || plan?.original_duration || 0;

  const editorCommands = useMemo<CommandPaletteCommand[]>(() => [
    {
      id: "open-command-palette",
      label: "Open command palette",
      category: "Workspace",
      bindings: [{ key: "k", label: "Ctrl+K", ctrlOrMeta: true }],
      icon: Keyboard,
      run: () => setCommandPaletteOpen(true),
    },
    {
      id: "play-pause",
      label: isPlaying ? "Pause preview" : "Play preview",
      category: "Playback",
      bindings: [
        { key: " ", label: "Space" },
        { key: "k", label: "K" },
      ],
      icon: isPlaying ? Pause : Play,
      run: togglePlay,
    },
    {
      id: "seek-backward",
      label: "Seek backward 5 seconds",
      category: "Playback",
      bindings: [
        { key: "j", label: "J" },
        { key: "ArrowLeft", label: "Left" },
      ],
      icon: SkipBack,
      run: () => seekTo(Math.max(0, currentTime - 5)),
    },
    {
      id: "seek-forward",
      label: "Seek forward 5 seconds",
      category: "Playback",
      bindings: [
        { key: "l", label: "L" },
        { key: "ArrowRight", label: "Right" },
      ],
      icon: SkipForward,
      run: () => seekTo(effectiveDuration > 0 ? Math.min(effectiveDuration, currentTime + 5) : currentTime + 5),
    },
    {
      id: "cut-selection",
      label: "Cut selected segment",
      category: "Editing",
      bindings: [{ key: "x", label: "X" }],
      disabledReason: selectedSegment ? undefined : "Select a transcript or timeline segment first",
      icon: Scissors,
      run: async () => {
        if (!selectedSegment) return;
        await handleUpdateAction(selectedSegment.id, "cut", "Marked for cut via shortcut");
        setActiveWorkflowStep("clean");
      },
    },
    {
      id: "undo",
      label: "Undo",
      category: "Editing",
      bindings: [{ key: "z", label: "Ctrl+Z", ctrlOrMeta: true }],
      disabledReason: "Undo history arrives in Phase 5",
      icon: Undo2,
      run: () => {},
    },
    {
      id: "redo",
      label: "Redo",
      category: "Editing",
      bindings: [
        { key: "z", label: "Ctrl+Shift+Z", ctrlOrMeta: true, shift: true },
        { key: "y", label: "Ctrl+Y", ctrlOrMeta: true },
      ],
      disabledReason: "Redo history arrives in Phase 5",
      icon: Redo2,
      run: () => {},
    },
    {
      id: "open-export",
      label: "Open export step",
      category: "Navigation",
      bindings: [{ key: "e", label: "Ctrl+E", ctrlOrMeta: true }],
      icon: Download,
      run: () => setActiveWorkflowStep("export"),
    },
    {
      id: "open-settings",
      label: "Open settings",
      category: "Workspace",
      bindings: [{ key: ",", label: "Ctrl+,", ctrlOrMeta: true }],
      icon: Settings,
      run: onOpenSettings,
    },
  ], [
    currentTime,
    effectiveDuration,
    handleUpdateAction,
    isPlaying,
    onOpenSettings,
    seekTo,
    selectedSegment,
    togglePlay,
  ]);

  useCommandShortcuts(editorCommands);

  const paletteCommands = useMemo(
    () => editorCommands.filter((command) => command.id !== "open-command-palette"),
    [editorCommands],
  );

  if (loading && segments.length === 0) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-accent" />
      </div>
    );
  }

  const activeWorkflowLabel = GUIDED_WORKFLOW_STEPS.find((step) => step.id === activeWorkflowStep)?.label ?? "Editor";
  const reviewedSegments = segments.filter((segment) => segment.is_teacher_modified).length;
  const warningCount = (warnings?.warnings.length ?? 0) + (warnings?.consequence_alerts.length ?? 0);
  const sourceName = videoFilename || "Lecture source";

  return (
    <div className="flex h-full flex-col bg-surface text-gray-100">
      <GuidedWorkflowStepper
        activeStep={activeWorkflowStep}
        completedStepIds={completedWorkflowSteps}
        onStepChange={setActiveWorkflowStep}
      />

      <div className="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)_178px] overflow-hidden">
        <div className="grid min-h-0 grid-cols-[minmax(280px,320px)_minmax(420px,1fr)_minmax(340px,390px)] overflow-hidden border-b border-surface-border">
          <aside className="flex min-w-0 flex-col border-r border-surface-border bg-surface-raised">
            <div className="border-b border-surface-border px-3 py-3">
              <div className="mb-3 flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-500">Source panel</p>
                  <h2 className="truncate text-sm font-semibold text-white">Transcript & Assets</h2>
                </div>
                <span className="rounded bg-surface-overlay px-2 py-1 text-[11px] text-gray-400">
                  {segments.length} clips
                </span>
              </div>
              <div className="grid grid-cols-2 gap-1 rounded-md bg-surface-overlay p-1">
                <button
                  type="button"
                  onClick={() => setLeftPanelTab("transcript")}
                  className={`flex items-center justify-center gap-1.5 rounded px-2 py-1.5 text-xs font-semibold transition-colors ${
                    leftPanelTab === "transcript" ? "bg-accent text-white" : "text-gray-400 hover:text-gray-200"
                  }`}
                >
                  <FileText className="h-3.5 w-3.5" />
                  Transcript
                </button>
                <button
                  type="button"
                  onClick={() => setLeftPanelTab("assets")}
                  className={`flex items-center justify-center gap-1.5 rounded px-2 py-1.5 text-xs font-semibold transition-colors ${
                    leftPanelTab === "assets" ? "bg-accent text-white" : "text-gray-400 hover:text-gray-200"
                  }`}
                >
                  <FolderOpen className="h-3.5 w-3.5" />
                  Assets
                </button>
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-hidden">
              {leftPanelTab === "transcript" ? (
                <TranscriptPanel
                  segments={segments}
                  timeline={transcriptTimeline}
                  cutDecisions={transcriptCuts}
                  cutsLoading={transcriptCutsLoading}
                  currentTime={currentTime}
                  onSeek={seekTo}
                  selectedSegmentId={selectedSegment?.id ?? null}
                  onSelectSegment={handleSelectSegment}
                  onCreateTranscriptCut={handleCreateTranscriptCut}
                  onDeleteTranscriptCut={handleDeleteTranscriptCut}
                />
              ) : (
                <AssetPanel
                  sourceName={sourceName}
                  segments={segments}
                  chapters={chapters}
                  plan={plan}
                  duration={effectiveDuration}
                />
              )}
            </div>
          </aside>

          <main className="flex min-w-0 flex-col bg-[#15151f]">
            <div className="flex items-center justify-between gap-4 border-b border-surface-border bg-surface-raised px-4 py-3">
              <div className="min-w-0">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-accent">{activeWorkflowLabel} workspace</p>
                <h2 className="truncate text-sm font-semibold text-white">{sourceName}</h2>
              </div>
              <div className="flex items-center gap-2 text-xs text-gray-400">
                <span className="inline-flex items-center gap-1 rounded bg-surface-overlay px-2 py-1">
                  <Clock3 className="h-3.5 w-3.5" />
                  {formatDuration(currentTime)} / {formatDuration(effectiveDuration)}
                </span>
                <button
                  type="button"
                  onClick={() => setCommandPaletteOpen(true)}
                  className="flex h-7 w-7 items-center justify-center rounded-md bg-surface-overlay text-gray-300 transition-colors hover:bg-surface-border"
                  aria-label="Open command palette"
                  title="Open command palette (Ctrl+K)"
                >
                  <Keyboard className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  onClick={togglePlay}
                  className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-accent-hover"
                >
                  {isPlaying ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                  {isPlaying ? "Pause" : "Play"}
                </button>
              </div>
            </div>

            <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-black px-6 py-5">
              <div className="absolute left-4 top-4 z-10 rounded bg-black/65 px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-gray-300">
                Program preview
              </div>
              <video
                ref={videoRef}
                src={videoSrc}
                className="max-h-full max-w-full bg-black shadow-2xl"
                onTimeUpdate={handleTimeUpdate}
                onLoadedMetadata={handleLoadedMetadata}
                onPlay={() => setIsPlaying(true)}
                onPause={() => setIsPlaying(false)}
                onClick={togglePlay}
              />
            </div>

            <div className="grid grid-cols-4 gap-px border-t border-surface-border bg-surface-border text-xs">
              <PreviewMetric icon={<Activity className="h-3.5 w-3.5" />} label="Reviewed" value={`${reviewedSegments}/${segments.length}`} />
              <PreviewMetric icon={<Layers className="h-3.5 w-3.5" />} label="Step" value={activeWorkflowLabel} />
              <PreviewMetric icon={<RadioTower className="h-3.5 w-3.5" />} label="Warnings" value={String(warningCount)} tone={warningCount > 0 ? "warn" : "good"} />
              <PreviewMetric icon={<MonitorPlay className="h-3.5 w-3.5" />} label="Duration" value={formatDuration(effectiveDuration)} />
            </div>
          </main>

          <aside className="min-w-0 overflow-hidden border-l border-surface-border bg-surface-raised">
            <GuidedWorkflowPanel
              activeStep={activeWorkflowStep}
              completedStepIds={completedWorkflowSteps}
              onStepChange={setActiveWorkflowStep}
              videoId={videoId}
              segments={segments}
              selectedSegment={selectedSegment}
              plan={plan}
              warnings={warnings}
              chapters={chapters}
              chaptersLoading={chaptersLoading}
              approving={approving}
              onAcceptAll={handleAcceptAll}
              onApprove={handleApprove}
              onRefreshChapters={() => void loadChapters()}
              onSeekToTime={seekTo}
              onUpdateAction={handleUpdateAction}
              onCompleteStep={handleCompleteWorkflowStep}
              onNextStep={handleNextWorkflowStep}
              onPreviousStep={handlePreviousWorkflowStep}
            />
          </aside>
        </div>

        <footer className="flex min-h-0 flex-col bg-surface-raised">
          <div className="flex items-center justify-between gap-4 border-b border-surface-border px-4 py-2">
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-white">Review Timeline</h2>
              <p className="text-xs text-gray-500">Segment decisions, current playhead, and teacher review status</p>
            </div>
            <div className="flex items-center gap-3 text-xs">
              <button
                onClick={handleAcceptAll}
                className="flex items-center gap-1.5 rounded-md bg-green-600/20 px-3 py-1.5 font-semibold text-green-300 transition-all hover:bg-green-600/30"
              >
                <CheckSquare className="h-3.5 w-3.5" /> Accept All High-Confidence
              </button>
              {warningCount > 0 && (
                <span className="flex items-center gap-1 rounded bg-yellow-500/10 px-2 py-1 text-yellow-300">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  {warningCount} warnings
                </span>
              )}
            </div>
          </div>

          <div className="min-h-0 flex-1 px-4 py-3">
            <Timeline
              segments={segments}
              duration={effectiveDuration}
              currentTime={currentTime}
              onSeek={seekTo}
              onSelectSegment={handleSelectSegment}
              selectedSegmentId={selectedSegment?.id ?? null}
            />
            <div className="mt-2 flex items-center justify-between text-xs text-gray-500">
              <span>{segments.length} transcript segments</span>
              <span>Ctrl+K commands, Space play/pause, J/L seek, X cut selected</span>
            </div>
          </div>
        </footer>
      </div>
      <CommandPalette
        isOpen={commandPaletteOpen}
        commands={paletteCommands}
        onClose={() => setCommandPaletteOpen(false)}
      />
    </div>
  );
}

function AssetPanel({
  sourceName,
  segments,
  chapters,
  plan,
  duration,
}: {
  sourceName: string;
  segments: Segment[];
  chapters: Chapter[];
  plan: EditPlan | null;
  duration: number;
}) {
  return (
    <div className="h-full overflow-y-auto p-3">
      <div className="space-y-2">
        <AssetRow icon={<MonitorPlay className="h-4 w-4 text-sky-300" />} label="Primary video" value={sourceName} detail={formatDuration(duration)} />
        <AssetRow icon={<FileText className="h-4 w-4 text-green-300" />} label="Transcript" value={`${segments.length} segments`} detail={segments.length > 0 ? "Ready for review" : "Waiting"} />
        <AssetRow icon={<Layers className="h-4 w-4 text-yellow-300" />} label="Chapters" value={`${chapters.length} markers`} detail="Generated structure" />
        <AssetRow icon={<Activity className="h-4 w-4 text-purple-300" />} label="Edit plan" value={plan ? "Loaded" : "Pending"} detail={plan?.is_approved ? "Approved" : "Draft"} />
      </div>
    </div>
  );
}

function AssetRow({ icon, label, value, detail }: { icon: React.ReactNode; label: string; value: string; detail: string }) {
  return (
    <div className="rounded-md border border-surface-border bg-surface-overlay p-3">
      <div className="flex items-start gap-3">
        <span className="mt-0.5">{icon}</span>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold uppercase tracking-wider text-gray-500">{label}</p>
          <p className="mt-1 truncate text-sm font-semibold text-gray-100">{value}</p>
          <p className="mt-1 text-xs text-gray-500">{detail}</p>
        </div>
      </div>
    </div>
  );
}

function PreviewMetric({
  icon,
  label,
  value,
  tone = "muted",
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  tone?: "muted" | "good" | "warn";
}) {
  const toneClass = {
    muted: "text-gray-100",
    good: "text-green-300",
    warn: "text-yellow-300",
  }[tone];

  return (
    <div className="min-w-0 bg-surface-raised px-3 py-2">
      <div className="mb-1 flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-gray-500">
        {icon}
        <span className="truncate">{label}</span>
      </div>
      <div className={`truncate text-sm font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}

function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "0:00";
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.round(seconds % 60);
  return `${minutes}:${remainingSeconds.toString().padStart(2, "0")}`;
}
