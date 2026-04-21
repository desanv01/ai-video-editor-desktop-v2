import { useState, useEffect, useCallback, useRef } from "react";
import { useSegments, usePlaybackSync } from "../hooks/useApi";
import { Timeline } from "./Timeline";
import { TranscriptPanel } from "./TranscriptPanel";
import { SegmentDetail } from "./SegmentDetail";
import { StatsPanel } from "./StatsPanel";
import * as api from "../lib/api";
import type { Segment, EditPlan, SegmentAction, RevalidationResult } from "../types/api";
import { AlertTriangle, BarChart3, FileText, CheckSquare, Loader2 } from "lucide-react";

type RightPanel = "detail" | "stats";

interface Props {
  videoId: string;
}

export function ReviewEditor({ videoId }: Props) {
  const { segments, loading, reload, updateAction, acceptAllHighConfidence } = useSegments(videoId);
  const { currentTime, setCurrentTime, isPlaying, videoRef, seekTo, togglePlay } = usePlaybackSync();
  const [selectedSegment, setSelectedSegment] = useState<Segment | null>(null);
  const [rightPanel, setRightPanel] = useState<RightPanel>("stats");
  const [plan, setPlan] = useState<EditPlan | null>(null);
  const [warnings, setWarnings] = useState<RevalidationResult | null>(null);
  const [approving, setApproving] = useState(false);
  const [duration, setDuration] = useState(0);

  // Load edit plan
  useEffect(() => {
    api.getEditPlan(videoId).then(setPlan).catch(() => {});
  }, [videoId]);

  // Video source URL (original uploaded video for preview)
  const videoSrc = api.getVideoStreamUrl(videoId);

  // Handle video time updates
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

  // Handle segment selection
  const handleSelectSegment = useCallback((seg: Segment) => {
    setSelectedSegment(seg);
    setRightPanel("detail");
  }, []);

  // Handle teacher action update + revalidation
  const handleUpdateAction = useCallback(async (segId: string, action: SegmentAction, note?: string) => {
    await updateAction(segId, action, note);
    // Revalidate after every change
    try {
      const result = await api.revalidatePlan(videoId);
      setWarnings(result);
    } catch {
      // Non-fatal
    }
  }, [videoId, updateAction]);

  // Bulk accept high confidence
  const handleAcceptAll = useCallback(async () => {
    const count = await acceptAllHighConfidence(0.85);
    if (count && count > 0) {
      alert(`Auto-accepted ${count} high-confidence segments`);
    } else {
      alert("No segments to auto-accept (all already reviewed or below threshold)");
    }
  }, [acceptAllHighConfidence]);

  // Approve plan
  const handleApprove = useCallback(async () => {
    setApproving(true);
    try {
      await api.approvePlan(videoId);
      const updatedPlan = await api.getEditPlan(videoId);
      setPlan(updatedPlan);
    } catch (e) {
      alert(`Approval failed: ${e}`);
    } finally {
      setApproving(false);
    }
  }, [videoId]);

  // Keyboard shortcuts
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
      {/* ── Top: Video + Timeline ── */}
      <div className="shrink-0 border-b border-surface-border">
        {/* Video Player */}
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

        {/* Timeline */}
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

        {/* Toolbar */}
        <div className="flex items-center justify-between px-4 py-1.5 bg-surface-raised border-t border-surface-border text-xs">
          <div className="flex items-center gap-3">
            <button
              onClick={handleAcceptAll}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600/20 text-green-400 hover:bg-green-600/30 rounded-md transition-all"
            >
              <CheckSquare className="w-3 h-3" /> Accept All High-Confidence
            </button>
            <span className="text-gray-500">
              {segments.length} segments | Keyboard: Space=play, J/L=±5s
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

      {/* ── Bottom: Transcript + Detail/Stats ── */}
      <div className="flex-1 flex overflow-hidden">
        {/* Transcript (left) */}
        <div className="flex-1 border-r border-surface-border overflow-hidden">
          <TranscriptPanel
            segments={segments}
            currentTime={currentTime}
            onSeek={seekTo}
            selectedSegmentId={selectedSegment?.id ?? null}
            onSelectSegment={handleSelectSegment}
          />
        </div>

        {/* Right Panel */}
        <div className="w-80 shrink-0 bg-surface-raised flex flex-col overflow-hidden">
          {/* Tab switcher */}
          <div className="flex border-b border-surface-border shrink-0">
            <button
              onClick={() => setRightPanel("stats")}
              className={`flex-1 py-2 text-xs font-medium flex items-center justify-center gap-1.5 transition-all ${
                rightPanel === "stats" ? "text-accent border-b-2 border-accent" : "text-gray-400 hover:text-gray-200"
              }`}
            >
              <BarChart3 className="w-3 h-3" /> Stats & Export
            </button>
            <button
              onClick={() => setRightPanel("detail")}
              className={`flex-1 py-2 text-xs font-medium flex items-center justify-center gap-1.5 transition-all ${
                rightPanel === "detail" ? "text-accent border-b-2 border-accent" : "text-gray-400 hover:text-gray-200"
              }`}
            >
              <FileText className="w-3 h-3" /> Segment Detail
            </button>
          </div>

          {/* Panel content */}
          <div className="flex-1 overflow-hidden">
            {rightPanel === "stats" && (
              <StatsPanel
                videoId={videoId}
                plan={plan}
                onApprove={handleApprove}
                approving={approving}
              />
            )}
            {rightPanel === "detail" && selectedSegment && (
              <SegmentDetail
                segment={selectedSegment}
                onUpdateAction={handleUpdateAction}
              />
            )}
            {rightPanel === "detail" && !selectedSegment && (
              <div className="h-full flex items-center justify-center text-gray-500 text-sm p-4 text-center">
                Click a segment in the transcript or timeline to see its details
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
