import { forwardRef, useState, useEffect, useCallback, useMemo } from "react";
import type { CSSProperties, VideoHTMLAttributes } from "react";
import { useSegments, usePlaybackSync } from "../hooks/useApi";
import { useCommandShortcuts } from "../hooks/useCommandShortcuts";
import { Timeline } from "./Timeline";
import { TranscriptPanel } from "./TranscriptPanel";
import { CommandPalette, type CommandPaletteCommand } from "./CommandPalette";
import {
  DEFAULT_LAYOUT_PREVIEW_SETTINGS,
  GUIDED_WORKFLOW_STEPS,
  GuidedWorkflowPanel,
  GuidedWorkflowStepper,
  layoutPreviewSettingsFromCue,
  type LayoutPreviewSettings,
  type GuidedWorkflowStepId,
} from "./GuidedWorkflow";
import * as api from "../lib/api";
import type {
  Chapter,
  Segment,
  AnnotationAction,
  AnimationSettings,
  EducationalOverlayAction,
  EndCardAction,
  EditPlan,
  SegmentAction,
  RevalidationResult,
  EditDecisionSync,
  TranscriptCutDecision,
  TranscriptCutDecisionRequest,
  TranscriptCutTrimUpdateRequest,
  TranscriptTimeline,
} from "../types/api";
import {
  Activity,
  AlertTriangle,
  CheckSquare,
  Clock3,
  Download,
  Film,
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

type SegmentOverrideSnapshot = {
  segment_id: string;
  segment_index: number;
  teacher_action: SegmentAction | null;
  teacher_note: string | null;
  is_teacher_modified: boolean;
};

type SegmentHistoryEntry = {
  id: string;
  kind: "segment_override";
  label: string;
  before: SegmentOverrideSnapshot;
  after: SegmentOverrideSnapshot;
};

type BulkSegmentHistoryEntry = {
  id: string;
  kind: "bulk_segment_override";
  label: string;
  before: SegmentOverrideSnapshot[];
  after: SegmentOverrideSnapshot[];
};

type TranscriptCutHistoryEntry = {
  id: string;
  kind: "transcript_cut_create" | "transcript_cut_delete";
  label: string;
  decision: TranscriptCutDecision;
  request: TranscriptCutDecisionRequest;
};

type TranscriptCutTrimHistoryEntry = {
  id: string;
  kind: "transcript_cut_trim_update";
  label: string;
  before: TranscriptCutDecision;
  after: TranscriptCutDecision;
};

type EditHistoryEntry =
  | SegmentHistoryEntry
  | BulkSegmentHistoryEntry
  | TranscriptCutHistoryEntry
  | TranscriptCutTrimHistoryEntry;
type HistoryDirection = "undo" | "redo";

export function ReviewEditor({ videoId, videoFilename, onOpenSettings }: Props) {
  const { segments, loading, reload: reloadSegments, applySegmentOverride, acceptAllHighConfidence } = useSegments(videoId);
  const { currentTime, setCurrentTime, isPlaying, setIsPlaying, videoRef, seekTo, togglePlay } = usePlaybackSync();
  const [selectedSegment, setSelectedSegment] = useState<Segment | null>(null);
  const [activeWorkflowStep, setActiveWorkflowStep] = useState<GuidedWorkflowStepId>("transcribe");
  const [completedWorkflowSteps, setCompletedWorkflowSteps] = useState<Set<GuidedWorkflowStepId>>(() => new Set());
  const [layoutPreviewSettings, setLayoutPreviewSettings] = useState<LayoutPreviewSettings>(DEFAULT_LAYOUT_PREVIEW_SETTINGS);
  const [leftPanelTab, setLeftPanelTab] = useState<LeftPanelTab>("transcript");
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [plan, setPlan] = useState<EditPlan | null>(null);
  const [selectedAnnotationId, setSelectedAnnotationId] = useState<string | null>(null);
  const [selectedEducationalOverlayId, setSelectedEducationalOverlayId] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<RevalidationResult | null>(null);
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [chaptersLoading, setChaptersLoading] = useState(false);
  const [transcriptTimeline, setTranscriptTimeline] = useState<TranscriptTimeline | null>(null);
  const [transcriptCuts, setTranscriptCuts] = useState<TranscriptCutDecision[]>([]);
  const [editDecisionSync, setEditDecisionSync] = useState<EditDecisionSync | null>(null);
  const [transcriptCutsLoading, setTranscriptCutsLoading] = useState(false);
  const [undoStack, setUndoStack] = useState<EditHistoryEntry[]>([]);
  const [redoStack, setRedoStack] = useState<EditHistoryEntry[]>([]);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [approving, setApproving] = useState(false);
  const [duration, setDuration] = useState(0);

  useEffect(() => {
    api.getEditPlan(videoId).then(setPlan).catch(() => {});
  }, [videoId]);

  useEffect(() => {
    setLayoutPreviewSettings(layoutPreviewSettingsFromCue(plan?.layout_cues[0]));
  }, [plan?.layout_cues]);

  useEffect(() => {
    setUndoStack([]);
    setRedoStack([]);
  }, [videoId]);

  useEffect(() => {
    setSelectedSegment(prev => {
      if (!prev) return prev;
      return segments.find(segment => segment.id === prev.id) ?? null;
    });
  }, [segments]);

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
      const [timelineResult, cutsResult, syncResult] = await Promise.all([
        api.getTranscriptTimeline(videoId),
        api.getTranscriptCutDecisions(videoId),
        api.getEditDecisionSync(videoId),
      ]);
      setTranscriptTimeline(timelineResult);
      setTranscriptCuts(cutsResult);
      setEditDecisionSync(syncResult);
    } catch {
      setTranscriptTimeline(null);
      setTranscriptCuts([]);
      setEditDecisionSync(null);
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
  const syncedCutIntervals = editDecisionSync?.cut_intervals ?? [];
  const syncedExportPlan = editDecisionSync?.export_plan ?? null;
  const annotations = useMemo(() => annotationsFromPlan(plan), [plan]);
  const educationalOverlays = useMemo(() => educationalOverlaysFromPlan(plan), [plan]);
  const endCards = useMemo(() => endCardsFromPlan(plan), [plan]);
  const enabledEndCardDuration = endCards.reduce((total, card) => total + (card.enabled ? card.duration_seconds : 0), 0);
  const contentDuration = duration || plan?.original_duration || 0;
  const effectiveDuration = contentDuration + enabledEndCardDuration;

  const handleTimeUpdate = useCallback(() => {
    if (videoRef.current) {
      setCurrentTime(videoRef.current.currentTime);
    }
  }, [videoRef, setCurrentTime]);

  useEffect(() => {
    if (!isPlaying || !videoRef.current || syncedCutIntervals.length === 0) return;
    const activeCut = syncedCutIntervals.find(
      interval => currentTime >= interval.start_time && currentTime < interval.end_time,
    );
    if (!activeCut) return;

    const nextTime = Math.min(activeCut.end_time + 0.03, effectiveDuration || activeCut.end_time);
    videoRef.current.currentTime = nextTime;
    setCurrentTime(nextTime);
  }, [currentTime, effectiveDuration, isPlaying, setCurrentTime, syncedCutIntervals, videoRef]);

  const handleLoadedMetadata = useCallback(() => {
    if (videoRef.current) {
      setDuration(videoRef.current.duration || plan?.original_duration || 0);
    }
  }, [videoRef, plan]);

  const handleSelectSegment = useCallback((seg: Segment) => {
    setSelectedSegment(seg);
    setActiveWorkflowStep("clean");
  }, []);

  const handleSelectAnnotation = useCallback((annotation: AnnotationAction) => {
    setSelectedAnnotationId(annotation.id);
    setSelectedEducationalOverlayId(null);
    setActiveWorkflowStep("polish");
    seekTo(annotation.start_time);
  }, [seekTo]);

  const handleSelectEducationalOverlay = useCallback((overlay: EducationalOverlayAction) => {
    setSelectedEducationalOverlayId(overlay.id);
    setSelectedAnnotationId(null);
    setActiveWorkflowStep("polish");
    seekTo(overlay.start_time);
  }, [seekTo]);

  const pushHistory = useCallback((entry: EditHistoryEntry) => {
    setUndoStack(prev => [...prev, entry].slice(-50));
    setRedoStack([]);
  }, []);

  const refreshEditWarnings = useCallback(async () => {
    try {
      const result = await api.revalidatePlan(videoId);
      setWarnings(result);
    } catch {
      // Revalidation is helpful context, but editing should continue if it fails.
    }
  }, [videoId]);

  const refreshEditPlan = useCallback(async () => {
    try {
      const updatedPlan = await api.getEditPlan(videoId);
      setPlan(updatedPlan);
    } catch {
      // Plan stats are secondary UI context; the edit operation already completed.
    }
  }, [videoId]);

  const refreshEditDecisionSync = useCallback(async () => {
    try {
      const sync = await api.getEditDecisionSync(videoId);
      setEditDecisionSync(sync);
    } catch {
      setEditDecisionSync(null);
    }
  }, [videoId]);

  const applySegmentSnapshot = useCallback(async (snapshot: SegmentOverrideSnapshot) => {
    await applySegmentOverride(
      snapshot.segment_id,
      snapshot.teacher_action,
      snapshot.teacher_note,
      snapshot.is_teacher_modified,
    );
  }, [applySegmentOverride]);

  const applySegmentSnapshots = useCallback(async (snapshots: SegmentOverrideSnapshot[]) => {
    for (const snapshot of snapshots) {
      await applySegmentSnapshot(snapshot);
    }
  }, [applySegmentSnapshot]);

  const handleUpdateAction = useCallback(async (segId: string, action: SegmentAction, note?: string) => {
    const segment = segments.find(candidate => candidate.id === segId);
    const before = segment ? snapshotSegmentOverride(segment) : null;
    const after: SegmentOverrideSnapshot | null = before
      ? {
          ...before,
          teacher_action: action,
          teacher_note: note || null,
          is_teacher_modified: true,
        }
      : null;

    await applySegmentOverride(segId, action, note || null, true);

    if (before && after && !sameSegmentOverrideSnapshot(before, after)) {
      pushHistory({
        id: createHistoryId(),
        kind: "segment_override",
        label: `Segment ${before.segment_index} ${action}`,
        before,
        after,
      });
    }
    await refreshEditWarnings();
    await refreshEditDecisionSync();
  }, [applySegmentOverride, pushHistory, refreshEditDecisionSync, refreshEditWarnings, segments]);

  const handleCreateTranscriptCut = useCallback(async (wordStartIndex: number, wordEndIndex: number) => {
    const request: TranscriptCutDecisionRequest = {
      word_start_index: wordStartIndex,
      word_end_index: wordEndIndex,
      teacher_note: "Marked for cut from transcript text selection",
    };
    const decision = await api.createTranscriptCutDecision(videoId, request);
    setTranscriptCuts(prev => [...prev, decision]);
    pushHistory({
      id: createHistoryId(),
      kind: "transcript_cut_create",
      label: "Transcript text cut",
      decision,
      request,
    });
    setActiveWorkflowStep("clean");
    await refreshEditPlan();
    await refreshEditDecisionSync();
  }, [pushHistory, refreshEditDecisionSync, refreshEditPlan, videoId]);

  const handleDeleteTranscriptCut = useCallback(async (decisionId: string) => {
    const decision = transcriptCuts.find(candidate => candidate.id === decisionId);
    await api.deleteTranscriptCutDecision(videoId, decisionId);
    setTranscriptCuts(prev => prev.filter(decision => decision.id !== decisionId));
    if (decision) {
      pushHistory({
        id: createHistoryId(),
        kind: "transcript_cut_delete",
        label: "Remove transcript cut",
        decision,
        request: {
          word_start_index: decision.word_start_index,
          word_end_index: decision.word_end_index,
          teacher_note: decision.teacher_note,
        },
      });
    }
    await refreshEditPlan();
    await refreshEditDecisionSync();
  }, [pushHistory, refreshEditDecisionSync, refreshEditPlan, transcriptCuts, videoId]);

  const handleUpdateTranscriptCutTrim = useCallback(async (
    decisionId: string,
    update: Required<Pick<TranscriptCutTrimUpdateRequest, "start_time" | "end_time" | "pre_roll_seconds" | "post_roll_seconds">>,
  ) => {
    const before = transcriptCuts.find(candidate => candidate.id === decisionId) ?? null;
    const updated = await api.updateTranscriptCutTrim(videoId, decisionId, update);
    setTranscriptCuts(prev => prev.map(decision => decision.id === decisionId ? updated : decision));
    if (before && !sameTranscriptCutTiming(before, updated)) {
      pushHistory({
        id: createHistoryId(),
        kind: "transcript_cut_trim_update",
        label: "Adjust transcript cut trim",
        before,
        after: updated,
      });
    }
    setActiveWorkflowStep("clean");
    await refreshEditPlan();
    await refreshEditDecisionSync();
  }, [pushHistory, refreshEditDecisionSync, refreshEditPlan, transcriptCuts, videoId]);

  const handleAcceptAll = useCallback(async () => {
    const candidates = segments.filter(segment => (segment.action_confidence ?? 0) >= 0.85 && !segment.is_teacher_modified);
    const before = candidates.map(snapshotSegmentOverride);
    const after = candidates.map(segment => ({
      ...snapshotSegmentOverride(segment),
      teacher_action: segment.action,
      teacher_note: "Auto-accepted (high confidence)",
      is_teacher_modified: true,
    }));

    const count = await acceptAllHighConfidence(0.85);
    if (count && count > 0) {
      pushHistory({
        id: createHistoryId(),
        kind: "bulk_segment_override",
        label: `Auto-accept ${count} segments`,
        before,
        after,
      });
      setCompletedWorkflowSteps(prev => new Set(prev).add("clean"));
      await refreshEditWarnings();
      await refreshEditDecisionSync();
      alert(`Auto-accepted ${count} high-confidence segments`);
    } else {
      alert("No segments to auto-accept (all already reviewed or below threshold)");
    }
  }, [acceptAllHighConfidence, pushHistory, refreshEditDecisionSync, refreshEditWarnings, segments]);

  const handleCleanApplied = useCallback(async () => {
    await Promise.all([
      reloadSegments(),
      loadTranscriptEditingData(),
      refreshEditPlan(),
      refreshEditWarnings(),
    ]);
  }, [loadTranscriptEditingData, refreshEditPlan, refreshEditWarnings, reloadSegments]);

  const handleApprove = useCallback(async (exportPresetId?: string) => {
    setApproving(true);
    try {
      await api.approvePlan(videoId, undefined, exportPresetId);
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

  const applyHistoryEntry = useCallback(async (
    entry: EditHistoryEntry,
    direction: HistoryDirection,
  ): Promise<EditHistoryEntry> => {
    if (entry.kind === "segment_override") {
      await applySegmentSnapshot(direction === "undo" ? entry.before : entry.after);
      await refreshEditWarnings();
      await refreshEditDecisionSync();
      return entry;
    }

    if (entry.kind === "bulk_segment_override") {
      await applySegmentSnapshots(direction === "undo" ? entry.before : entry.after);
      await refreshEditWarnings();
      await refreshEditDecisionSync();
      return entry;
    }

    if (entry.kind === "transcript_cut_create") {
      if (direction === "undo") {
        await api.deleteTranscriptCutDecision(videoId, entry.decision.id);
        setTranscriptCuts(prev => prev.filter(decision => decision.id !== entry.decision.id));
        await refreshEditPlan();
        await refreshEditDecisionSync();
        return entry;
      }

      const decision = await api.createTranscriptCutDecision(videoId, entry.request);
      setTranscriptCuts(prev => [...prev, decision]);
      await refreshEditPlan();
      await refreshEditDecisionSync();
      return { ...entry, decision };
    }

    if (entry.kind === "transcript_cut_trim_update") {
      const target = direction === "undo" ? entry.before : entry.after;
      const updated = await api.updateTranscriptCutTrim(videoId, target.id, transcriptCutTrimRequest(target));
      setTranscriptCuts(prev => prev.map(decision => decision.id === target.id ? updated : decision));
      await refreshEditPlan();
      await refreshEditDecisionSync();
      return direction === "undo" ? { ...entry, before: updated } : { ...entry, after: updated };
    }

    if (direction === "undo") {
      const decision = await api.createTranscriptCutDecision(videoId, entry.request);
      setTranscriptCuts(prev => [...prev, decision]);
      await refreshEditPlan();
      await refreshEditDecisionSync();
      return { ...entry, decision };
    }

    await api.deleteTranscriptCutDecision(videoId, entry.decision.id);
    setTranscriptCuts(prev => prev.filter(decision => decision.id !== entry.decision.id));
    await refreshEditPlan();
    await refreshEditDecisionSync();
    return entry;
  }, [applySegmentSnapshot, applySegmentSnapshots, refreshEditDecisionSync, refreshEditPlan, refreshEditWarnings, videoId]);

  const handleUndo = useCallback(async () => {
    const entry = undoStack[undoStack.length - 1];
    if (!entry || historyBusy) return;

    setHistoryBusy(true);
    try {
      const updatedEntry = await applyHistoryEntry(entry, "undo");
      setUndoStack(prev => prev.slice(0, -1));
      setRedoStack(prev => [...prev, updatedEntry].slice(-50));
    } catch (error) {
      alert(`Undo failed: ${error}`);
    } finally {
      setHistoryBusy(false);
    }
  }, [applyHistoryEntry, historyBusy, undoStack]);

  const handleRedo = useCallback(async () => {
    const entry = redoStack[redoStack.length - 1];
    if (!entry || historyBusy) return;

    setHistoryBusy(true);
    try {
      const updatedEntry = await applyHistoryEntry(entry, "redo");
      setRedoStack(prev => prev.slice(0, -1));
      setUndoStack(prev => [...prev, updatedEntry].slice(-50));
    } catch (error) {
      alert(`Redo failed: ${error}`);
    } finally {
      setHistoryBusy(false);
    }
  }, [applyHistoryEntry, historyBusy, redoStack]);

  const nextUndoEntry = undoStack[undoStack.length - 1] ?? null;
  const nextRedoEntry = redoStack[redoStack.length - 1] ?? null;
  const canUndo = Boolean(nextUndoEntry) && !historyBusy;
  const canRedo = Boolean(nextRedoEntry) && !historyBusy;

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
      label: nextUndoEntry ? `Undo ${nextUndoEntry.label}` : "Undo",
      category: "Editing",
      bindings: [{ key: "z", label: "Ctrl+Z", ctrlOrMeta: true }],
      disabledReason: canUndo ? undefined : historyBusy ? "Applying edit history" : "Nothing to undo",
      icon: Undo2,
      run: handleUndo,
    },
    {
      id: "redo",
      label: nextRedoEntry ? `Redo ${nextRedoEntry.label}` : "Redo",
      category: "Editing",
      bindings: [
        { key: "z", label: "Ctrl+Shift+Z", ctrlOrMeta: true, shift: true },
        { key: "y", label: "Ctrl+Y", ctrlOrMeta: true },
      ],
      disabledReason: canRedo ? undefined : historyBusy ? "Applying edit history" : "Nothing to redo",
      icon: Redo2,
      run: handleRedo,
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
    canRedo,
    canUndo,
    effectiveDuration,
    handleUpdateAction,
    handleRedo,
    handleUndo,
    historyBusy,
    isPlaying,
    nextRedoEntry,
    nextUndoEntry,
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
                  onUpdateTranscriptCutTrim={handleUpdateTranscriptCutTrim}
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
                  onClick={handleUndo}
                  disabled={!canUndo}
                  className="flex h-7 w-7 items-center justify-center rounded-md bg-surface-overlay text-gray-300 transition-colors hover:bg-surface-border disabled:cursor-not-allowed disabled:opacity-40"
                  aria-label={nextUndoEntry ? `Undo ${nextUndoEntry.label}` : "Undo"}
                  title={nextUndoEntry ? `Undo ${nextUndoEntry.label} (Ctrl+Z)` : "Nothing to undo"}
                >
                  <Undo2 className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  onClick={handleRedo}
                  disabled={!canRedo}
                  className="flex h-7 w-7 items-center justify-center rounded-md bg-surface-overlay text-gray-300 transition-colors hover:bg-surface-border disabled:cursor-not-allowed disabled:opacity-40"
                  aria-label={nextRedoEntry ? `Redo ${nextRedoEntry.label}` : "Redo"}
                  title={nextRedoEntry ? `Redo ${nextRedoEntry.label} (Ctrl+Shift+Z)` : "Nothing to redo"}
                >
                  <Redo2 className="h-3.5 w-3.5" />
                </button>
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
              <LayoutProgramPreview
                ref={videoRef}
                src={videoSrc}
                settings={layoutPreviewSettings}
                annotations={annotations}
                educationalOverlays={educationalOverlays}
                endCards={endCards}
                currentTime={currentTime}
                contentDuration={duration || plan?.original_duration || 0}
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
              <PreviewMetric
                icon={<MonitorPlay className="h-3.5 w-3.5" />}
                label="Output"
                value={formatDuration(syncedExportPlan?.estimated_output_duration_seconds ?? plan?.estimated_duration ?? effectiveDuration)}
              />
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
              selectedAnnotationId={selectedAnnotationId}
              selectedEducationalOverlayId={selectedEducationalOverlayId}
              plan={plan}
              currentTime={currentTime}
              layoutSettings={layoutPreviewSettings}
              warnings={warnings}
              chapters={chapters}
              chaptersLoading={chaptersLoading}
              approving={approving}
              onLayoutSettingsChange={setLayoutPreviewSettings}
              onPolishPlanUpdated={setPlan}
              onSelectedAnnotationChange={setSelectedAnnotationId}
              onSelectedEducationalOverlayChange={setSelectedEducationalOverlayId}
              onAcceptAll={handleAcceptAll}
              onCleanApplied={handleCleanApplied}
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
              cutIntervals={syncedCutIntervals}
              annotations={annotations}
              educationalOverlays={educationalOverlays}
              endCards={endCards}
              onSelectAnnotation={handleSelectAnnotation}
              onSelectEducationalOverlay={handleSelectEducationalOverlay}
            />
            <div className="mt-2 flex items-center justify-between text-xs text-gray-500">
              <span>{segments.length} transcript segments</span>
              <span>
                {syncedExportPlan?.transcript_cut_count ?? 0} transcript cuts synced to preview, timeline, and export
                {enabledEndCardDuration > 0 ? `, plus ${formatDuration(enabledEndCardDuration)} end card` : ""}
              </span>
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

type LayoutProgramPreviewProps = Pick<
  VideoHTMLAttributes<HTMLVideoElement>,
  "onTimeUpdate" | "onLoadedMetadata" | "onPlay" | "onPause" | "onClick"
> & {
  src: string;
  settings: LayoutPreviewSettings;
  annotations: AnnotationAction[];
  educationalOverlays: EducationalOverlayAction[];
  endCards: EndCardAction[];
  currentTime: number;
  contentDuration: number;
};

const LayoutProgramPreview = forwardRef<HTMLVideoElement, LayoutProgramPreviewProps>(function LayoutProgramPreview(
  { src, settings, annotations, educationalOverlays, endCards, currentTime, contentDuration, ...videoProps },
  ref,
) {
  const activeAnnotations = annotations.filter(
    (annotation) => currentTime >= annotation.start_time && currentTime <= annotation.end_time,
  );
  const activeEducationalOverlays = educationalOverlays.filter(
    (overlay) => currentTime >= overlay.start_time && currentTime <= overlay.end_time,
  );
  const activeEndCard = activeEndCardAtTime(endCards, currentTime, contentDuration);
  const video = (
    <video
      ref={ref}
      src={src}
      className={settings.layout === "full_camera_source" ? "h-full w-full bg-black object-cover" : "h-full w-full bg-black object-contain"}
      {...videoProps}
    />
  );

  return (
    <div
      className="relative flex max-h-full max-w-full overflow-hidden bg-[#08080d] shadow-2xl ring-1 ring-white/10"
      style={{
        aspectRatio: previewAspectRatio(settings.aspectRatio),
        width: "100%",
        transition: `all ${settings.transitionDurationSeconds}s ease-out`,
      }}
    >
      {settings.layout === "side_by_side" ? (
        <div className="absolute inset-0 grid grid-cols-2 gap-px bg-surface-border">
          <div
            className="relative min-w-0 bg-black transition-all ease-out"
            style={{ transitionDuration: `${settings.transitionDurationSeconds}s` }}
          >
            {video}
          </div>
          <CameraPreviewSurface settings={settings} variant="panel" />
        </div>
      ) : (
        <div
          className="absolute inset-0 bg-black transition-all ease-out"
          style={{ transitionDuration: `${settings.transitionDurationSeconds}s` }}
        >
          {video}
          {settings.layout === "picture_in_picture" && (
            <CameraPreviewSurface settings={settings} variant="inset" />
          )}
        </div>
      )}
      {activeAnnotations.map((annotation) => (
        <AnnotationPreviewOverlay key={annotation.id} annotation={annotation} />
      ))}
      {activeEducationalOverlays.map((overlay) => (
        <EducationalOverlayPreview key={overlay.id} overlay={overlay} />
      ))}
      {activeEndCard && <EndCardPreview card={activeEndCard} />}
    </div>
  );
});

function AnnotationPreviewOverlay({ annotation }: { annotation: AnnotationAction }) {
  const style = annotation.style;
  return (
    <div
      className="pointer-events-none absolute z-20 max-w-[42%] rounded border px-3 py-2 text-left font-semibold leading-tight shadow-xl"
      style={{
        left: `${annotation.x_percent}%`,
        top: `${annotation.y_percent}%`,
        transform: annotationPreviewTransform(annotation.position),
        color: style.text_color,
        backgroundColor: hexWithAlpha(style.background_color, style.opacity),
        borderColor: style.border_color,
        fontSize: `${Math.max(12, Math.round(style.font_size * 0.48))}px`,
        animation: previewAnimationCss(annotation.animation),
      }}
    >
      {annotation.pointer.enabled && annotation.annotation_type === "callout" && (
        <span className="mr-1 text-current">{pointerGlyph(annotation.pointer.direction)}</span>
      )}
      {annotation.text}
    </div>
  );
}

function EducationalOverlayPreview({ overlay }: { overlay: EducationalOverlayAction }) {
  const style = overlay.style;
  const isCard = overlay.overlay_type === "intro_card" || overlay.overlay_type === "section_title_card";
  return (
    <div
      className={`pointer-events-none absolute z-30 border text-left font-semibold shadow-2xl ${
        isCard ? "w-[58%] rounded-md px-5 py-4 text-center" : "max-w-[42%] rounded px-3 py-2"
      }`}
      style={{
        left: `${overlay.x_percent}%`,
        top: `${overlay.y_percent}%`,
        transform: educationalOverlayTransform(overlay.position),
        color: style.text_color,
        backgroundColor: hexWithAlpha(style.background_color, style.opacity),
        borderColor: style.accent_color,
        fontSize: `${Math.max(12, Math.round(style.font_size * 0.48))}px`,
        animation: previewAnimationCss(overlay.animation),
      }}
    >
      <div className="mb-1 text-[0.56em] font-bold uppercase tracking-wider" style={{ color: style.accent_color }}>
        {educationalOverlayEyebrow(overlay)}
      </div>
      <div className="leading-tight">{overlay.title}</div>
      {overlay.subtitle && (
        <div className="mt-1 font-medium leading-tight" style={{ color: style.subtitle_color, fontSize: `${Math.max(10, Math.round(style.subtitle_font_size * 0.48))}px` }}>
          {overlay.subtitle}
        </div>
      )}
    </div>
  );
}

function EndCardPreview({ card }: { card: EndCardAction }) {
  const style = card.style;
  return (
    <div
      className="pointer-events-none absolute inset-0 z-40 flex items-center justify-center px-8 text-center"
      style={{
        color: style.text_color,
        backgroundColor: hexWithAlpha(style.background_color, style.opacity),
        animation: previewAnimationCss(card.animation),
      }}
    >
      <div className="w-[78%] max-w-3xl">
        <div className="mb-3 text-[11px] font-bold uppercase tracking-wider" style={{ color: style.accent_color }}>
          {endCardEyebrow(card.card_type)}
        </div>
        <div className="font-semibold leading-tight" style={{ fontSize: `${Math.max(18, Math.round(style.font_size * 0.48))}px` }}>
          {card.title}
        </div>
        {card.summary_points.length > 0 && (
          <div className="mt-3 space-y-1 text-left font-medium" style={{ color: style.body_color, fontSize: `${Math.max(11, Math.round(style.body_font_size * 0.48))}px` }}>
            {card.summary_points.slice(0, 5).map((point, index) => (
              <div key={`${point}-${index}`}>- {point}</div>
            ))}
          </div>
        )}
        {card.message && (
          <div className="mt-3 font-medium leading-snug" style={{ color: style.body_color, fontSize: `${Math.max(11, Math.round(style.body_font_size * 0.48))}px` }}>
            {card.message}
          </div>
        )}
        {card.next_topic && (
          <div className="mt-3 text-sm font-semibold" style={{ color: style.accent_color }}>
            Next: {card.next_topic}
          </div>
        )}
        {card.course_url && (
          <div className="mx-auto mt-4 inline-flex max-w-full rounded border px-3 py-1.5 text-xs font-semibold" style={{ borderColor: style.accent_color, color: style.accent_color }}>
            <span className="truncate">{card.button_text}: {card.course_url}</span>
          </div>
        )}
      </div>
    </div>
  );
}

function CameraPreviewSurface({ settings, variant }: { settings: LayoutPreviewSettings; variant: "inset" | "panel" }) {
  if (variant === "panel") {
    return (
      <div className="flex min-w-0 items-center justify-center bg-[#141421] p-5">
        <div className={`flex items-center justify-center border border-white/20 bg-surface-raised/90 ${cameraShapeClass(settings.cameraShape)} ${settings.cameraShape === "circle" ? "aspect-square h-[56%]" : "aspect-video w-full"}`}>
          <Film className="h-6 w-6 text-gray-400" />
        </div>
      </div>
    );
  }

  return (
    <div
      className={`absolute z-10 flex items-center justify-center border border-white/25 bg-surface-raised/95 shadow-xl ${cameraShapeClass(settings.cameraShape)}`}
      style={{
        ...cameraInsetStyle(settings),
        transition: `all ${settings.transitionDurationSeconds}s ease-out`,
      }}
    >
      <Film className="h-5 w-5 text-gray-300" />
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

function createHistoryId(): string {
  return `history-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function snapshotSegmentOverride(segment: Segment): SegmentOverrideSnapshot {
  return {
    segment_id: segment.id,
    segment_index: segment.segment_index,
    teacher_action: segment.teacher_action,
    teacher_note: segment.teacher_note,
    is_teacher_modified: segment.is_teacher_modified,
  };
}

function sameSegmentOverrideSnapshot(a: SegmentOverrideSnapshot, b: SegmentOverrideSnapshot): boolean {
  return (
    a.teacher_action === b.teacher_action &&
    a.teacher_note === b.teacher_note &&
    a.is_teacher_modified === b.is_teacher_modified
  );
}

function sameTranscriptCutTiming(a: TranscriptCutDecision, b: TranscriptCutDecision): boolean {
  return (
    a.start_time === b.start_time &&
    a.end_time === b.end_time &&
    (a.pre_roll_seconds ?? 0) === (b.pre_roll_seconds ?? 0) &&
    (a.post_roll_seconds ?? 0) === (b.post_roll_seconds ?? 0)
  );
}

function transcriptCutTrimRequest(decision: TranscriptCutDecision): TranscriptCutTrimUpdateRequest {
  return {
    start_time: decision.start_time,
    end_time: decision.end_time,
    pre_roll_seconds: decision.pre_roll_seconds ?? 0,
    post_roll_seconds: decision.post_roll_seconds ?? 0,
    teacher_note: decision.teacher_note,
  };
}

function annotationsFromPlan(plan: EditPlan | null): AnnotationAction[] {
  return (plan?.polish_actions ?? []).filter((item): item is AnnotationAction => {
    return typeof item === "object" && item != null && "kind" in item && item.kind === "annotation";
  });
}

function educationalOverlaysFromPlan(plan: EditPlan | null): EducationalOverlayAction[] {
  return (plan?.polish_actions ?? []).filter((item): item is EducationalOverlayAction => {
    return typeof item === "object" && item != null && "kind" in item && item.kind === "educational_overlay";
  });
}

function endCardsFromPlan(plan: EditPlan | null): EndCardAction[] {
  return (plan?.polish_actions ?? []).filter((item): item is EndCardAction => {
    return typeof item === "object" && item != null && "kind" in item && item.kind === "end_card";
  }).filter((card) => card.enabled);
}

function activeEndCardAtTime(cards: EndCardAction[], currentTime: number, contentDuration: number): EndCardAction | null {
  let cursor = contentDuration;
  for (const card of cards) {
    const end = cursor + card.duration_seconds;
    if (currentTime >= cursor && currentTime <= end) {
      return card;
    }
    cursor = end;
  }
  return null;
}

function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "0:00";
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.round(seconds % 60);
  return `${minutes}:${remainingSeconds.toString().padStart(2, "0")}`;
}

function previewAspectRatio(value: LayoutPreviewSettings["aspectRatio"]): string {
  if (value === "4:3") return "4 / 3";
  if (value === "1:1") return "1 / 1";
  if (value === "9:16") return "9 / 16";
  return "16 / 9";
}

function cameraShapeClass(shape: LayoutPreviewSettings["cameraShape"]): string {
  if (shape === "circle") return "rounded-full";
  if (shape === "rectangle") return "rounded";
  return "rounded-xl";
}

function cameraInsetStyle(settings: LayoutPreviewSettings): CSSProperties {
  const margin = `${settings.cameraMarginPercent}%`;
  const width = settings.cameraSize === "small" ? "18%" : settings.cameraSize === "large" ? "31%" : "24%";
  const style: CSSProperties = {
    width,
    aspectRatio: settings.cameraShape === "circle" ? "1 / 1" : "16 / 9",
  };

  if (settings.cameraCorner.includes("top")) {
    style.top = margin;
  } else {
    style.bottom = margin;
  }

  if (settings.cameraCorner.includes("left")) {
    style.left = margin;
  } else {
    style.right = margin;
  }

  return style;
}

function annotationPreviewTransform(position: string): string {
  if (position.includes("center")) return "translate(-50%, 0)";
  if (position.includes("right")) return "translate(-100%, 0)";
  return "translate(0, 0)";
}

function educationalOverlayTransform(position: string): string {
  if (position === "center") return "translate(-50%, -50%)";
  if (position.includes("center")) return "translate(-50%, 0)";
  if (position.includes("right")) return "translate(-100%, 0)";
  return "translate(0, 0)";
}

function educationalOverlayEyebrow(overlay: EducationalOverlayAction): string {
  if (overlay.overlay_type === "step_label" && overlay.step_number) return `Step ${overlay.step_number}`;
  if (overlay.overlay_type === "chapter_label" && overlay.chapter_index != null) return `Chapter ${overlay.chapter_index + 1}`;
  if (overlay.overlay_type === "section_title_card") return "Section";
  if (overlay.overlay_type === "intro_card") return "Intro";
  return "Label";
}

function endCardEyebrow(cardType: string): string {
  if (cardType === "next_topic") return "Next Topic";
  if (cardType === "course_link") return "Course Link";
  if (cardType === "custom_message") return "Closing";
  return "Summary";
}

function previewAnimationCss(animation: AnimationSettings | undefined): string | undefined {
  if (!animation || animation.preset === "none") return undefined;
  let name: string | null = null;
  if (animation.preset === "fade") name = "ave-fade-in";
  if (animation.preset === "pop") name = "ave-pop-in";
  if (animation.preset === "zoom") name = "ave-zoom-in";
  if (animation.preset === "slide_up") name = "ave-slide-up";
  if (animation.preset === "slide_down") name = "ave-slide-down";
  if (animation.preset === "slide_left") name = "ave-slide-left";
  if (animation.preset === "slide_right") name = "ave-slide-right";
  if (!name) return undefined;
  const duration = Math.min(2, Math.max(0.08, animation.duration_seconds || 0.35));
  return `${name} ${duration}s ease-out both`;
}

function hexWithAlpha(hex: string, opacity: number): string {
  const value = hex?.startsWith("#") ? hex : "#111827";
  const alpha = Math.round(Math.min(1, Math.max(0.2, opacity || 0.88)) * 255).toString(16).padStart(2, "0");
  return `${value}${alpha}`;
}

function pointerGlyph(direction: string): string {
  if (direction === "right") return "->";
  if (direction === "up") return "^";
  if (direction === "down") return "v";
  if (direction === "left") return "<-";
  return "";
}
