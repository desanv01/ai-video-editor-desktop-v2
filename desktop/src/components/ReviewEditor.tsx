import { useState, useEffect, useCallback } from "react";
import { useSegments, usePlaybackSync } from "../hooks/useApi";
import { Timeline } from "./Timeline";
import { TranscriptPanel } from "./TranscriptPanel";
import {
  GUIDED_WORKFLOW_STEPS,
  GuidedWorkflowPanel,
  GuidedWorkflowStepper,
  type GuidedWorkflowStepId,
} from "./GuidedWorkflow";
import * as api from "../lib/api";
import type { Chapter, Segment, EditPlan, SegmentAction, RevalidationResult } from "../types/api";
import { AlertTriangle, CheckSquare, Loader2 } from "lucide-react";

interface Props {
  videoId: string;
}

export function ReviewEditor({ videoId }: Props) {
  const { segments, loading, updateAction, acceptAllHighConfidence } = useSegments(videoId);
  const { currentTime, setCurrentTime, videoRef, seekTo, togglePlay } = usePlaybackSync();
  const [selectedSegment, setSelectedSegment] = useState<Segment | null>(null);
  const [activeWorkflowStep, setActiveWorkflowStep] = useState<GuidedWorkflowStepId>("transcribe");
  const [completedWorkflowSteps, setCompletedWorkflowSteps] = useState<Set<GuidedWorkflowStepId>>(() => new Set());
  const [plan, setPlan] = useState<EditPlan | null>(null);
  const [warnings, setWarnings] = useState<RevalidationResult | null>(null);
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [chaptersLoading, setChaptersLoading] = useState(false);
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

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement) return;

      switch (e.key) {
        case " ": e.preventDefault(); togglePlay(); break;
        case "j": seekTo(Math.max(0, currentTime - 5)); break;
        case "l": seekTo(currentTime + 5); break;
        case "k": togglePlay(); break;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [togglePlay, seekTo, currentTime]);

  if (loading && segments.length === 0) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-accent" />
      </div>
    );
  }

  const effectiveDuration = duration || plan?.original_duration || 0;

  return (
    <div className="h-full flex flex-col">
      <GuidedWorkflowStepper
        activeStep={activeWorkflowStep}
        completedStepIds={completedWorkflowSteps}
        onStepChange={setActiveWorkflowStep}
      />

      <div className="shrink-0 border-b border-surface-border">
        <div className="flex gap-0">
          <div className="flex-1 bg-black flex items-center justify-center" style={{ maxHeight: "340px" }}>
            <video
              ref={videoRef}
              src={videoSrc}
              className="max-w-full max-h-full"
              onTimeUpdate={handleTimeUpdate}
              onLoadedMetadata={handleLoadedMetadata}
              onClick={togglePlay}
            />
          </div>
        </div>

        <div className="px-4 py-2 bg-surface-raised">
          <Timeline
            segments={segments}
            duration={effectiveDuration}
            currentTime={currentTime}
            onSeek={seekTo}
            onSelectSegment={handleSelectSegment}
            selectedSegmentId={selectedSegment?.id ?? null}
          />
        </div>

        <div className="flex items-center justify-between px-4 py-1.5 bg-surface-raised border-t border-surface-border text-xs">
          <div className="flex items-center gap-3">
            <button
              onClick={handleAcceptAll}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600/20 text-green-400 hover:bg-green-600/30 rounded-md transition-all"
            >
              <CheckSquare className="w-3 h-3" /> Accept All High-Confidence
            </button>
            <span className="text-gray-500">
              {segments.length} segments | Keyboard: Space=play, J/L=+/-5s
            </span>
          </div>
          <div className="flex items-center gap-2">
            {warnings && (warnings.warnings.length > 0 || warnings.consequence_alerts.length > 0) && (
              <span className="flex items-center gap-1 text-yellow-400">
                <AlertTriangle className="w-3 h-3" />
                {warnings.warnings.length + warnings.consequence_alerts.length} warnings
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 border-r border-surface-border overflow-hidden">
          <TranscriptPanel
            segments={segments}
            currentTime={currentTime}
            onSeek={seekTo}
            selectedSegmentId={selectedSegment?.id ?? null}
            onSelectSegment={handleSelectSegment}
          />
        </div>

        <div className="w-[380px] shrink-0 overflow-hidden">
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
        </div>
      </div>
    </div>
  );
}
