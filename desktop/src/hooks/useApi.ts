/**
 * React hooks for the desktop app.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import * as api from "../lib/api";
import type { ProcessingStatus, Segment, SegmentAction } from "../types/api";

/**
 * Poll processing status every N seconds.
 * Stops polling when status is terminal (awaiting_review, completed, failed).
 */
export function useProcessingStatus(videoId: string | null, intervalMs = 2500, pollKey = 0) {
  const [status, setStatus] = useState<ProcessingStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!videoId) return;

    let active = true;

    const poll = async () => {
      try {
        const s = await api.getProcessingStatus(videoId);
        if (active) {
          setStatus(s);
          setError(null);
        }

        const renderJobActive = s.render_job && ["queued", "running", "cancel_requested"].includes(s.render_job.status);
        // Stop polling on terminal states
        const terminal = ["awaiting_review", "completed", "failed"];
        if (terminal.includes(s.status) && !renderJobActive) return;

        // Continue polling
        if (active) setTimeout(poll, intervalMs);
      } catch (e) {
        if (active) setError(String(e));
        if (active) setTimeout(poll, intervalMs * 2); // slower retry on error
      }
    };

    poll();
    return () => { active = false; };
  }, [videoId, intervalMs, pollKey]);

  return { status, error };
}

/**
 * Manage segments for a video — load, update, bulk actions.
 */
export function useSegments(videoId: string | null) {
  const [segments, setSegments] = useState<Segment[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!videoId) return;
    setLoading(true);
    try {
      const segs = await api.getSegments(videoId);
      setSegments(segs);
    } finally {
      setLoading(false);
    }
  }, [videoId]);

  useEffect(() => { load(); }, [load]);

  const updateAction = useCallback(async (
    segmentId: string,
    action: SegmentAction,
    note?: string,
  ) => {
    if (!videoId) {
      console.error("updateAction: videoId is null, cannot persist segment change");
      alert("Cannot save: no video selected");
      return;
    }
    if (!segmentId) {
      console.error("updateAction: segmentId is empty");
      alert("Cannot save: invalid segment");
      return;
    }
    try {
      await api.updateSegment(videoId, segmentId, action, note, true);

      setSegments(prev =>
        prev.map(s =>
          s.id === segmentId
            ? { ...s, teacher_action: action, teacher_note: note || null, is_teacher_modified: true }
            : s
        )
      );
    } catch (err) {
      console.error("updateAction: API call failed", err);
      alert(`Failed to save segment change: ${err}`);
      throw err; // re-throw so callers like undo/redo can surface the error
    }
  }, [videoId]);

  const applySegmentOverride = useCallback(async (
    segmentId: string,
    teacherAction: SegmentAction | null,
    teacherNote: string | null,
    isTeacherModified: boolean,
  ) => {
    if (!videoId) {
      console.error("applySegmentOverride: videoId is null");
      alert("Cannot save: no video selected");
      return;
    }
    if (!segmentId) {
      console.error("applySegmentOverride: segmentId is empty");
      alert("Cannot save: invalid segment");
      return;
    }
    try {
      await api.updateSegment(videoId, segmentId, teacherAction, teacherNote, isTeacherModified);

      setSegments(prev =>
        prev.map(s =>
          s.id === segmentId
            ? {
                ...s,
                teacher_action: teacherAction,
                teacher_note: teacherNote,
                is_teacher_modified: isTeacherModified,
              }
            : s
        )
      );
    } catch (err) {
      console.error("applySegmentOverride: API call failed", err);
      alert(`Failed to save segment override: ${err}`);
      throw err;
    }
  }, [videoId]);

  const acceptAllHighConfidence = useCallback(async (threshold = 0.85) => {
    if (!videoId) {
      console.error("acceptAllHighConfidence: videoId is null");
      alert("Cannot accept: no video selected");
      return 0;
    }
    const updates = segments
      .filter(s => (s.action_confidence ?? 0) >= threshold && !s.is_teacher_modified)
      .map(s => ({
        segment_id: s.id,
        teacher_action: s.action,
        teacher_note: "Auto-accepted (high confidence)",
      }));

    if (updates.length > 0) {
      try {
        await api.bulkUpdateSegments(videoId, updates);
        await load(); // Reload after bulk update
      } catch (err) {
        console.error("acceptAllHighConfidence: bulk update API call failed", err);
        alert(`Failed to auto-accept segments: ${err}`);
        throw err;
      }
    }

    return updates.length;
  }, [videoId, segments, load]);

  return { segments, loading, reload: load, updateAction, applySegmentOverride, acceptAllHighConfidence };
}

/**
 * Track current playback time for syncing transcript + timeline.
 */
export function usePlaybackSync() {
  const [currentTime, setCurrentTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const seekTo = useCallback((time: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = time;
      setCurrentTime(time);
    }
  }, []);

  const togglePlay = useCallback(async () => {
    const video = videoRef.current;
    if (!video) return;

    if (video.paused) {
      try {
        await video.play();
        setIsPlaying(!video.paused);
      } catch {
        setIsPlaying(false);
      }
      return;
    }

    video.pause();
    setIsPlaying(false);
  }, []);

  return { currentTime, setCurrentTime, isPlaying, setIsPlaying, videoRef, seekTo, togglePlay };
}
