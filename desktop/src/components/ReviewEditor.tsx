import { forwardRef, useState, useEffect, useCallback, useMemo } from "react";
import type { CSSProperties, VideoHTMLAttributes } from "react";
import { useSegments, usePlaybackSync, useProcessingStatus } from "../hooks/useApi";
import { useCommandShortcuts } from "../hooks/useCommandShortcuts";
import { EditorialTimeline, Timeline } from "./Timeline";
import { TranscriptPanel } from "./TranscriptPanel";
import { CommandPalette, type CommandPaletteCommand } from "./CommandPalette";
import {
  DEFAULT_LAYOUT_PREVIEW_SETTINGS,
  GUIDED_WORKFLOW_STEPS,
  GuidedWorkflowPanel,
  GuidedWorkflowStepper,
  layoutCueAtTime,
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
  CleanApplyResult,
  SegmentAction,
  RevalidationResult,
  EditDecisionSync,
  TranscriptCutDecision,
  TranscriptCutDecisionRequest,
  TranscriptCutTrimUpdateRequest,
  TranscriptTimeline,
  ProjectAsset,
  SemanticRenderPlan,
  EditorialBlock,
  Video,
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

type GeneratedSlidePreview = {
  enabled: boolean;
  title: string;
  subtitle: string;
  sourceName: string;
  bullets: string[];
  imageUrl?: string | null;
};

export function ReviewEditor({ videoId, videoFilename, onOpenSettings }: Props) {
  const { segments, loading, reload: reloadSegments, applySegmentOverride, acceptAllHighConfidence } = useSegments(videoId);
  const { currentTime, setCurrentTime, isPlaying, setIsPlaying, videoRef, seekTo, togglePlay } = usePlaybackSync();
  const [selectedSegment, setSelectedSegment] = useState<Segment | null>(null);
  const [activeWorkflowStep, setActiveWorkflowStep] = useState<GuidedWorkflowStepId>("transcribe");
  const [completedWorkflowSteps, setCompletedWorkflowSteps] = useState<Set<GuidedWorkflowStepId>>(() => new Set());
  const [layoutPreviewSettings, setLayoutPreviewSettings] = useState<LayoutPreviewSettings>(DEFAULT_LAYOUT_PREVIEW_SETTINGS);
  const [layoutDraftDirty, setLayoutDraftDirty] = useState(false);
  const [layoutDraftBlockId, setLayoutDraftBlockId] = useState<string | null>(null);
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
  const [semanticRenderPlan, setSemanticRenderPlan] = useState<SemanticRenderPlan | null>(null);
  const [videoDetail, setVideoDetail] = useState<Video | null>(null);
  const [projectAssets, setProjectAssets] = useState<ProjectAsset[]>([]);
  const [transcriptCutsLoading, setTranscriptCutsLoading] = useState(false);
  const [undoStack, setUndoStack] = useState<EditHistoryEntry[]>([]);
  const [redoStack, setRedoStack] = useState<EditHistoryEntry[]>([]);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [approving, setApproving] = useState(false);
  const [renderCancelling, setRenderCancelling] = useState(false);
  const [renderPollVersion, setRenderPollVersion] = useState(0);
  const [duration, setDuration] = useState(0);
  const { status: processingStatus } = useProcessingStatus(videoId, 1500, renderPollVersion);

  useEffect(() => {
    api.getEditPlan(videoId).then(setPlan).catch(() => {});
  }, [videoId]);

  const refreshSemanticRenderPlan = useCallback(async () => {
    try {
      const renderPlan = await api.regenerateSemanticRenderPlan(videoId);
      setSemanticRenderPlan(renderPlan);
    } catch {
      setSemanticRenderPlan(null);
    }
  }, [videoId]);

  useEffect(() => {
    void refreshSemanticRenderPlan();
  }, [refreshSemanticRenderPlan]);

  useEffect(() => {
    let cancelled = false;
    api.getVideo(videoId)
      .then(video => {
        if (cancelled) return;
        setVideoDetail(video);
        if (!video.project_id) {
          setProjectAssets([]);
          return;
        }
        api.listProjectAssets(video.project_id)
          .then(assets => {
            if (!cancelled) setProjectAssets(assets);
          })
          .catch(() => {
            if (!cancelled) setProjectAssets([]);
          });
      })
      .catch(() => {
        if (!cancelled) {
          setVideoDetail(null);
          setProjectAssets([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [videoId]);

  useEffect(() => {
    if (activeWorkflowStep === "layout" && layoutDraftDirty) return;
    setLayoutPreviewSettings(layoutPreviewSettingsFromCue(layoutCueAtTime(plan?.layout_cues ?? [], currentTime) ?? plan?.layout_cues[0]));
  }, [activeWorkflowStep, currentTime, layoutDraftDirty, plan?.layout_cues]);

  useEffect(() => {
    setUndoStack([]);
    setRedoStack([]);
  }, [videoId]);

  useEffect(() => {
    if (videoDetail?.status === "rendering" || processingStatus?.current_step === "rendering") {
      setActiveWorkflowStep("export");
    }
  }, [processingStatus?.current_step, videoDetail?.status]);

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
  const visibleTranscriptCuts = useMemo(() => dedupeTranscriptCuts(transcriptCuts), [transcriptCuts]);
  const annotations = useMemo(() => annotationsFromPlan(plan), [plan]);
  const educationalOverlays = useMemo(() => educationalOverlaysFromPlan(plan), [plan]);
  const endCards = useMemo(() => endCardsFromPlan(plan), [plan]);
  const enabledEndCardDuration = endCards.reduce((total, card) => total + (card.enabled ? card.duration_seconds : 0), 0);
  const contentDuration = duration || plan?.original_duration || 0;
  const effectiveDuration = contentDuration + enabledEndCardDuration;
  const activeLayoutCue = layoutCueAtTime(plan?.layout_cues ?? [], currentTime) ?? plan?.layout_cues?.[0] ?? null;
  const editorialBlocks = plan?.editorial_blocks ?? [];
  const activeEditorialBlock = (
    layoutDraftDirty && layoutDraftBlockId
      ? editorialBlocks.find((block) => block.id === layoutDraftBlockId)
      : null
  ) ?? editorialBlocks.find(
    (block) => currentTime >= block.start_time && currentTime < block.end_time,
  ) ?? editorialBlocks[0] ?? null;
  const activeRenderScene = useMemo(
    () => activeRenderSceneAtTime(semanticRenderPlan, currentTime),
    [currentTime, semanticRenderPlan],
  );
  const slidePreview = useMemo(
    () => buildSemanticSlidePreview(semanticRenderPlan, activeRenderScene) ?? buildGeneratedSlidePreview({
      cue: activeLayoutCue,
      currentTime,
      segments,
      chapters,
      projectAssets,
    }),
    [activeLayoutCue, activeRenderScene, chapters, currentTime, projectAssets, segments, semanticRenderPlan],
  );
  const previewLayoutSettings = useMemo(
    () => layoutSettingsFromRenderScene(layoutPreviewSettings, activeRenderScene),
    [activeRenderScene, layoutPreviewSettings],
  );

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
    setUndoStack(prev => {
      const next = [...prev, entry];
      if (prev.length === 50) {
        console.warn("Undo stack limit reached (50). Oldest entry dropped.");
      }
      return next.slice(-50);
    });
    setRedoStack([]);
  }, []);

  const refreshEditWarnings = useCallback(async () => {
    try {
      const result = await api.revalidatePlan(videoId);
      setWarnings(result);
    } catch {
      console.warn("Revalidation failed (non-fatal), editing continues");
    }
  }, [videoId]);

  const refreshEditPlan = useCallback(async () => {
    try {
      const updatedPlan = await api.getEditPlan(videoId);
      setPlan(updatedPlan);
      void refreshSemanticRenderPlan();
    } catch {
      // Plan stats are secondary UI context; the edit operation already completed.
    }
  }, [refreshSemanticRenderPlan, videoId]);

  const handlePlanUpdated = useCallback((updatedPlan: EditPlan) => {
    setPlan(updatedPlan);
    void refreshSemanticRenderPlan();
  }, [refreshSemanticRenderPlan]);

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
    if (!segment) {
      console.error("handleUpdateAction: segment not found in local state", segId);
      alert("Cannot update: segment not found");
      return;
    }
    const before = snapshotSegmentOverride(segment);
    const after: SegmentOverrideSnapshot = {
      ...before,
      teacher_action: action,
      teacher_note: note || null,
      is_teacher_modified: true,
    };

    try {
      await applySegmentOverride(segId, action, note || null, true);

      if (!sameSegmentOverrideSnapshot(before, after)) {
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
    } catch (err) {
      console.error("handleUpdateAction: failed to persist segment change", err);
      // Error already surfaced by applySegmentOverride; avoid duplicate alert
    }
  }, [applySegmentOverride, pushHistory, refreshEditDecisionSync, refreshEditWarnings, segments]);

  const handleCreateTranscriptCut = useCallback(async (wordStartIndex: number, wordEndIndex: number) => {
    const request: TranscriptCutDecisionRequest = {
      word_start_index: wordStartIndex,
      word_end_index: wordEndIndex,
      teacher_note: "Marked for cut from transcript text selection",
    };
    try {
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
    } catch (err) {
      console.error("handleCreateTranscriptCut: API call failed", err);
      alert(`Failed to create transcript cut: ${err}`);
    }
  }, [pushHistory, refreshEditDecisionSync, refreshEditPlan, videoId]);

  const handleDeleteTranscriptCut = useCallback(async (decisionId: string) => {
    const decision = transcriptCuts.find(candidate => candidate.id === decisionId);
    try {
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
    } catch (err) {
      console.error("handleDeleteTranscriptCut: API call failed", err);
      alert(`Failed to delete transcript cut: ${err}`);
    }
  }, [pushHistory, refreshEditDecisionSync, refreshEditPlan, transcriptCuts, videoId]);

  const handleRestoreTranscriptCutWord = useCallback(async (decisionId: string, wordIndex: number) => {
    const decision = transcriptCuts.find(candidate => candidate.id === decisionId);
    try {
      const nextCuts = await api.restoreTranscriptCutWord(videoId, decisionId, {
        word_index: wordIndex,
        teacher_note: "Restored one word from transcript cut",
      });
      setTranscriptCuts(nextCuts);
      if (decision) {
        pushHistory({
          id: createHistoryId(),
          kind: "transcript_cut_delete",
          label: "Restore one cut word",
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
    } catch (err) {
      console.error("handleRestoreTranscriptCutWord: API call failed", err);
      alert(`Failed to restore cut word: ${err}`);
    }
  }, [pushHistory, refreshEditDecisionSync, refreshEditPlan, transcriptCuts, videoId]);

  const handleUpdateTranscriptCutTrim = useCallback(async (
    decisionId: string,
    update: Required<Pick<TranscriptCutTrimUpdateRequest, "start_time" | "end_time" | "pre_roll_seconds" | "post_roll_seconds">>,
  ) => {
    const before = transcriptCuts.find(candidate => candidate.id === decisionId) ?? null;
    try {
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
    } catch (err) {
      console.error("handleUpdateTranscriptCutTrim: API call failed", err);
      alert(`Failed to update cut trim: ${err}`);
    }
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

    try {
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
    } catch (err) {
      console.error("handleAcceptAll: API call failed", err);
      // Error already surfaced by acceptAllHighConfidence; avoid duplicate alert
    }
  }, [acceptAllHighConfidence, pushHistory, refreshEditDecisionSync, refreshEditWarnings, segments]);

  const handleCleanApplied = useCallback(async (result?: CleanApplyResult) => {
    if (result) {
      const updatedSegmentIds = new Set(result.updated_segments.map(update => update.segment_id));
      const before = segments
        .filter(segment => updatedSegmentIds.has(segment.id))
        .map(snapshotSegmentOverride);
      const updatesById = new Map(result.updated_segments.map(update => [update.segment_id, update]));
      const after = before.map(snapshot => {
        const update = updatesById.get(snapshot.segment_id);
        return {
          ...snapshot,
          teacher_action: normalizeSegmentAction(update?.teacher_action) ?? snapshot.teacher_action,
          teacher_note: update?.teacher_note ?? null,
          is_teacher_modified: true,
        };
      });

      if (before.length > 0) {
        pushHistory({
          id: createHistoryId(),
          kind: "bulk_segment_override",
          label: `Auto-clean ${before.length} segments`,
          before,
          after,
        });
      }

      for (const decision of result.created_transcript_cuts) {
        pushHistory({
          id: createHistoryId(),
          kind: "transcript_cut_create",
          label: `Auto-clean transcript cut: ${truncateHistoryLabel(decision.text || "cut")}`,
          decision,
          request: transcriptCutRequestFromDecision(decision),
        });
      }
    }

    await Promise.all([
      reloadSegments(),
      loadTranscriptEditingData(),
      refreshEditPlan(),
      refreshEditWarnings(),
    ]);
  }, [loadTranscriptEditingData, pushHistory, refreshEditPlan, refreshEditWarnings, reloadSegments, segments]);

  const handleApprove = useCallback(async (exportPresetId?: string) => {
    setApproving(true);
    try {
      await api.approvePlan(videoId, undefined, exportPresetId);
      setRenderPollVersion(value => value + 1);
      const updatedPlan = await api.getEditPlan(videoId);
      setPlan(updatedPlan);
      setCompletedWorkflowSteps(prev => new Set(prev).add("export"));
    } catch (e) {
      try {
        const [status, updatedPlan] = await Promise.all([
          api.getProcessingStatus(videoId),
          api.getEditPlan(videoId),
        ]);
        const renderAccepted = Boolean(
          status.render_job && ["queued", "running", "cancel_requested"].includes(status.render_job.status),
        );
        if (renderAccepted) {
          setPlan(updatedPlan);
          setRenderPollVersion(value => value + 1);
          setCompletedWorkflowSteps(prev => new Set(prev).add("export"));
          return;
        }
      } catch {
        // Preserve the original approval error when status reconciliation also fails.
      }
      alert(`Approval failed: ${e}`);
    } finally {
      setApproving(false);
    }
  }, [videoId]);

  const handleCancelRender = useCallback(async () => {
    setRenderCancelling(true);
    try {
      await api.cancelRender(videoId);
      setRenderPollVersion(value => value + 1);
    } catch (e) {
      alert(`Cancel failed: ${e}`);
    } finally {
      setRenderCancelling(false);
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
  const sourceName = videoFilename || videoDetail?.original_filename || "Lecture source";

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface text-gray-100">
      <GuidedWorkflowStepper
        activeStep={activeWorkflowStep}
        completedStepIds={completedWorkflowSteps}
        onStepChange={setActiveWorkflowStep}
      />

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(300px,400px)_minmax(480px,1fr)_minmax(360px,460px)] grid-rows-[minmax(0,1fr)_118px] overflow-hidden xl:grid-cols-[minmax(340px,430px)_minmax(620px,1fr)_minmax(390px,480px)] xl:grid-rows-[minmax(0,1fr)_128px]">
        <div className="contents">
          <aside className="row-span-2 flex min-h-0 min-w-0 flex-col border-r border-surface-border bg-surface-raised">
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
                  cutDecisions={visibleTranscriptCuts}
                  cutsLoading={transcriptCutsLoading}
                  currentTime={currentTime}
                  onSeek={seekTo}
                  selectedSegmentId={selectedSegment?.id ?? null}
                  onSelectSegment={handleSelectSegment}
                  onCreateTranscriptCut={handleCreateTranscriptCut}
                  onDeleteTranscriptCut={handleDeleteTranscriptCut}
                  onRestoreTranscriptCutWord={handleRestoreTranscriptCutWord}
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

          <main className="col-start-2 row-start-1 flex min-h-0 min-w-0 flex-col border-b border-surface-border bg-[#15151f]">
            <div className="flex items-center justify-between gap-4 border-b border-surface-border bg-surface-raised px-4 py-2">
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

            <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-black px-4 py-3 xl:px-5 xl:py-4">
              <div className="absolute left-4 top-4 z-10 rounded bg-black/65 px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-gray-300">
                Program preview
              </div>
              <LayoutProgramPreview
                ref={videoRef}
                src={videoSrc}
                settings={previewLayoutSettings}
                generatedSlidePreview={slidePreview}
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

          <aside className="col-start-3 row-span-2 row-start-1 min-h-0 min-w-0 overflow-hidden border-l border-surface-border bg-surface-raised">
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
              renderStatus={processingStatus}
              renderCancelling={renderCancelling}
              onLayoutSettingsChange={setLayoutPreviewSettings}
              onLayoutDraftDirtyChange={(dirty, blockId) => {
                setLayoutDraftDirty(dirty);
                setLayoutDraftBlockId(dirty ? blockId ?? activeEditorialBlock?.id ?? null : null);
              }}
              onPolishPlanUpdated={handlePlanUpdated}
              onSelectedAnnotationChange={setSelectedAnnotationId}
              onSelectedEducationalOverlayChange={setSelectedEducationalOverlayId}
              onAcceptAll={handleAcceptAll}
              onCleanApplied={handleCleanApplied}
              onApprove={handleApprove}
              onCancelRender={handleCancelRender}
              onRefreshChapters={() => void loadChapters()}
              onSeekToTime={seekTo}
              onUpdateAction={handleUpdateAction}
              onCompleteStep={handleCompleteWorkflowStep}
              onNextStep={handleNextWorkflowStep}
              onPreviousStep={handlePreviousWorkflowStep}
            />
          </aside>
        </div>

        <footer className="col-start-2 row-start-2 flex min-h-0 flex-col bg-surface-raised">
          <div className="flex items-center justify-between gap-4 border-b border-surface-border px-4 py-2">
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-white">
                {activeWorkflowStep === "layout" ? "Content Layout Timeline" : "Review Timeline"}
              </h2>
              <p className="text-xs text-gray-500">
                {activeWorkflowStep === "layout"
                  ? "The same AI teaching blocks shown in Content Layout Decisions"
                  : "Segment decisions, current playhead, and teacher review status"}
              </p>
            </div>
            <div className="flex items-center gap-3 text-xs">
              {activeWorkflowStep !== "layout" && <button
                onClick={handleAcceptAll}
                className="flex items-center gap-1.5 rounded-md bg-green-600/20 px-3 py-1.5 font-semibold text-green-300 transition-all hover:bg-green-600/30"
              >
                <CheckSquare className="h-3.5 w-3.5" /> Accept All High-Confidence
              </button>}
              {warningCount > 0 && (
                <span className="flex items-center gap-1 rounded bg-yellow-500/10 px-2 py-1 text-yellow-300">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  {warningCount} warnings
                </span>
              )}
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-hidden px-4 py-2">
            {activeWorkflowStep === "layout" && editorialBlocks.length > 0 ? (
              <EditorialTimeline
                blocks={editorialBlocks}
                duration={contentDuration}
                currentTime={currentTime}
                selectedBlockId={activeEditorialBlock?.id ?? null}
                onSeek={seekTo}
                onSelectBlock={(block: EditorialBlock) => {
                  if (layoutDraftDirty) return;
                  seekTo(Math.min(block.end_time - 0.001, block.start_time + 0.001));
                }}
              />
            ) : (
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
            )}
            <div className="mt-2 flex items-center justify-between text-xs text-gray-500">
              <span>{activeWorkflowStep === "layout" ? `${editorialBlocks.length} teaching blocks` : `${segments.length} transcript segments`}</span>
              <span>
                {syncedExportPlan?.transcript_cut_count ?? visibleTranscriptCuts.length} transcript cuts synced to preview, timeline, and export
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
  generatedSlidePreview: GeneratedSlidePreview;
  annotations: AnnotationAction[];
  educationalOverlays: EducationalOverlayAction[];
  endCards: EndCardAction[];
  currentTime: number;
  contentDuration: number;
};

const LayoutProgramPreview = forwardRef<HTMLVideoElement, LayoutProgramPreviewProps>(function LayoutProgramPreview(
  { src, settings, generatedSlidePreview, annotations, educationalOverlays, endCards, currentTime, contentDuration, ...videoProps },
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
      className="h-full w-full bg-black object-contain"
      {...videoProps}
    />
  );
  const slideSurface = (
    <GeneratedSlidePreviewSurface preview={generatedSlidePreview} />
  );
  const shouldUseSlideScreen = generatedSlidePreview.enabled && settings.layout !== "full_camera_source";
  const playbackOnlyVideo = shouldUseSlideScreen && settings.layout === "full_screen_source";

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
            {shouldUseSlideScreen ? slideSurface : video}
          </div>
          <div
            className="relative min-w-0 bg-black transition-all ease-out"
            style={{ transitionDuration: `${settings.transitionDurationSeconds}s` }}
          >
            {shouldUseSlideScreen ? video : <CameraPreviewSurface settings={settings} variant="panel" />}
          </div>
        </div>
      ) : (
        <div
          className="absolute inset-0 bg-black transition-all ease-out"
          style={{ transitionDuration: `${settings.transitionDurationSeconds}s` }}
        >
          {playbackOnlyVideo ? <div className="pointer-events-none absolute h-px w-px opacity-0">{video}</div> : shouldUseSlideScreen ? slideSurface : video}
          {settings.layout === "picture_in_picture" && (
            shouldUseSlideScreen ? (
              <div
                className={`absolute z-10 overflow-hidden border border-white/25 bg-black shadow-xl ${cameraShapeClass(settings.cameraShape)}`}
                style={{
                  ...cameraInsetStyle(settings),
                  transition: `all ${settings.transitionDurationSeconds}s ease-out`,
                }}
              >
                {video}
              </div>
            ) : (
              <CameraPreviewSurface settings={settings} variant="inset" />
            )
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

function GeneratedSlidePreviewSurface({ preview }: { preview: GeneratedSlidePreview }) {
  if (preview.imageUrl) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-black">
        <img src={preview.imageUrl} alt={preview.title || "Lecture slide"} className="h-full w-full object-contain" />
      </div>
    );
  }
  const bullets = preview.bullets.length > 0 ? preview.bullets : [preview.subtitle].filter(Boolean);
  return (
    <div className="flex h-full w-full flex-col justify-between bg-[#f8fafc] px-[6%] py-[5%] text-[#111827]">
      <div className="min-w-0">
        <div className="mb-3 inline-flex max-w-full items-center gap-2 rounded bg-[#2563eb]/10 px-3 py-1 text-[clamp(10px,1.2vw,14px)] font-semibold uppercase text-[#1d4ed8]">
          <span className="h-2 w-2 rounded-full bg-[#2563eb]" />
          <span className="truncate">{preview.sourceName}</span>
        </div>
        <h3 className="max-w-[88%] text-[clamp(22px,3vw,46px)] font-bold leading-tight text-[#111827]">
          {preview.title}
        </h3>
        {preview.subtitle && (
          <p className="mt-3 max-w-[78%] text-[clamp(13px,1.45vw,22px)] leading-snug text-[#475569]">
            {preview.subtitle}
          </p>
        )}
      </div>
      <div className="grid max-w-[82%] gap-3">
        {bullets.slice(0, 4).map((bullet, index) => (
          <div key={`${bullet}-${index}`} className="flex items-start gap-3 rounded border border-[#cbd5e1] bg-white/80 px-4 py-3 shadow-sm">
            <span className="mt-1 h-2.5 w-2.5 flex-none rounded-full bg-[#f59e0b]" />
            <span className="text-[clamp(12px,1.35vw,20px)] font-medium leading-snug text-[#1f2937]">{compactPreviewText(bullet, 150)}</span>
          </div>
        ))}
      </div>
      <div className="h-1.5 w-32 rounded-full bg-[#7c3aed]" />
    </div>
  );
}

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

function transcriptCutRequestFromDecision(decision: TranscriptCutDecision): TranscriptCutDecisionRequest {
  return {
    word_start_index: decision.word_start_index,
    word_end_index: decision.word_end_index,
    teacher_note: decision.teacher_note,
  };
}

function normalizeSegmentAction(value: SegmentAction | string | undefined): SegmentAction | null {
  if (value === "keep" || value === "cut" || value === "shorten" || value === "highlight") {
    return value;
  }
  return null;
}

function truncateHistoryLabel(value: string): string {
  const text = value.trim().replace(/\s+/g, " ");
  return text.length > 34 ? `${text.slice(0, 31)}...` : text;
}

function dedupeTranscriptCuts(decisions: TranscriptCutDecision[]): TranscriptCutDecision[] {
  const seen = new Set<string>();
  return decisions.filter(decision => {
    const key = decision.id || `${decision.word_start_index}-${decision.word_end_index}-${decision.start_time}-${decision.end_time}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}


function activeRenderSceneAtTime(renderPlan: SemanticRenderPlan | null, currentTime: number): SemanticRenderPlan["scenes"][number] | null {
  if (!renderPlan?.scenes?.length) return null;
  return renderPlan.scenes.find(
    (scene) => currentTime >= scene.source_start_time && currentTime < scene.source_end_time,
  ) ?? renderPlan.scenes.find(
    (scene) => currentTime >= scene.start_time && currentTime < scene.end_time,
  ) ?? renderPlan.scenes[0] ?? null;
}

function buildSemanticSlidePreview(
  renderPlan: SemanticRenderPlan | null,
  scene: SemanticRenderPlan["scenes"][number] | null,
): GeneratedSlidePreview | null {
  if (!renderPlan || !scene) return null;
  const slide = renderPlan.slides.find((item) => item.id === scene.slide_id);
  if (!slide) return null;
  return {
    enabled: true,
    title: compactPreviewText(slide.title || scene.slide_title || "Teaching slide", 72),
    subtitle: compactPreviewText(slide.body || scene.caption_text || scene.topic_label, 220),
    sourceName: compactPreviewText(slide.source_filename || "AI teaching slide", 70),
    imageUrl: slide.image_url,
    bullets: (slide.bullets?.length ? slide.bullets : [scene.caption_text])
      .filter((item): item is string => Boolean(item && item.trim()))
      .map((item) => compactPreviewText(item, 150))
      .slice(0, 4),
  };
}

function layoutSettingsFromRenderScene(
  current: LayoutPreviewSettings,
  scene: SemanticRenderPlan["scenes"][number] | null,
): LayoutPreviewSettings {
  if (!scene) return current;
  const layout = normalizePreviewLayout(scene.layout, current.layout);
  return {
    ...current,
    layout,
    cameraShape: scene.camera.shape === "circle" ? "circle" : current.cameraShape,
    cameraCorner: normalizeCameraCorner(scene.camera.corner, current.cameraCorner),
    transitionPreset: scene.transition.type || current.transitionPreset,
    transitionDurationSeconds: normalizePreviewTransitionDuration(scene.transition.duration_seconds, current.transitionDurationSeconds),
  };
}

function normalizePreviewLayout(value: unknown, fallback: LayoutPreviewSettings["layout"]): LayoutPreviewSettings["layout"] {
  if (value === "picture_in_picture" || value === "side_by_side" || value === "full_screen_source" || value === "full_camera_source") {
    return value;
  }
  return fallback;
}

function normalizeCameraCorner(value: unknown, fallback: LayoutPreviewSettings["cameraCorner"]): LayoutPreviewSettings["cameraCorner"] {
  if (value === "top_left" || value === "top_right" || value === "bottom_left" || value === "bottom_right") {
    return value;
  }
  return fallback;
}

function normalizePreviewTransitionDuration(value: unknown, fallback: number): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return fallback;
  return Math.min(2, Math.max(0, Math.round(value * 100) / 100));
}

function buildGeneratedSlidePreview({
  cue,
  currentTime,
  segments,
  chapters,
  projectAssets,
}: {
  cue: EditPlan["layout_cues"][number] | null;
  currentTime: number;
  segments: Segment[];
  chapters: Chapter[];
  projectAssets: ProjectAsset[];
}): GeneratedSlidePreview {
  const structureAssets = projectAssets.filter((asset) =>
    asset.role === "slides" ||
    asset.role === "notes" ||
    asset.role === "supporting_material" ||
    asset.kind === "slide_deck" ||
    asset.kind === "pdf_notes" ||
    asset.kind === "course_material",
  );
  const hasGeneratedSlideCue = cue?.sources?.screen?.track === "generated_slides" || cue?.sources?.screen?.asset_id === "generated_slides";
  const enabled = hasGeneratedSlideCue || structureAssets.length > 0;
  const activeSegment = segments.find((segment) => currentTime >= segment.start_time && currentTime <= segment.end_time) ?? segments[0] ?? null;
  const activeChapter = chapters.find((chapter, index) => {
    const next = chapters[index + 1];
    const end = next?.timestamp ?? Number.POSITIVE_INFINITY;
    return currentTime >= chapter.timestamp && currentTime < end;
  }) ?? chapters[0] ?? null;
  const sourceName = structureAssets[0]?.original_filename || structureAssets[0]?.filename || "Generated lecture slides";
  const title = compactPreviewText(
    activeSegment?.topic_label || activeChapter?.label || structureAssets[0]?.original_filename || "Teaching slide",
    72,
  );
  const subtitle = compactPreviewText(activeSegment?.summary || activeSegment?.text || activeChapter?.label || "", 180);
  const bullets = [
    activeSegment?.summary,
    activeSegment?.text,
    activeChapter?.label,
    ...structureAssets.slice(0, 2).map((asset) => asset.original_filename || asset.filename),
  ]
    .filter((item): item is string => Boolean(item && item.trim()))
    .map((item) => compactPreviewText(item, 150));

  return {
    enabled,
    title,
    subtitle,
    sourceName: compactPreviewText(sourceName, 70),
    bullets: Array.from(new Set(bullets)).slice(0, 4),
  };
}

function compactPreviewText(value: string | null | undefined, limit = 120): string {
  const text = (value || "").trim().replace(/\s+/g, " ");
  if (text.length <= limit) return text;
  return `${text.slice(0, Math.max(0, limit - 3)).trim()}...`;
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
