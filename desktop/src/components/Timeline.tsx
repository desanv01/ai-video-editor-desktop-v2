import { useCallback, useMemo, useRef, useState } from "react";
import type { AnnotationAction, EditorialBlock, EducationalOverlayAction, EndCardAction, Segment, SegmentAction, TranscriptCutInterval } from "../types/api";

interface Props {
  segments: Segment[];
  duration: number;
  currentTime: number;
  onSeek: (time: number) => void;
  onSelectSegment: (seg: Segment) => void;
  selectedSegmentId: string | null;
  cutIntervals?: TranscriptCutInterval[];
  annotations?: AnnotationAction[];
  educationalOverlays?: EducationalOverlayAction[];
  endCards?: EndCardAction[];
  onSelectAnnotation?: (annotation: AnnotationAction) => void;
  onSelectEducationalOverlay?: (overlay: EducationalOverlayAction) => void;
}

const ACTION_COLORS: Record<SegmentAction, string> = {
  keep: "timeline-keep",
  cut: "timeline-cut",
  shorten: "timeline-shorten",
  highlight: "timeline-highlight",
};

export function Timeline({
  segments,
  duration,
  currentTime,
  onSeek,
  onSelectSegment,
  selectedSegmentId,
  cutIntervals = [],
  annotations = [],
  educationalOverlays = [],
  endCards = [],
  onSelectAnnotation,
  onSelectEducationalOverlay,
}: Props) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [isScrubbing, setIsScrubbing] = useState(false);
  const playheadPct = duration > 0 ? (currentTime / duration) * 100 : 0;

  const seekFromClientX = useCallback((clientX: number) => {
    const track = trackRef.current;
    if (!track || duration <= 0) return;
    const rect = track.getBoundingClientRect();
    const pct = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    onSeek(pct * duration);
  }, [duration, onSeek]);

  const segBars = useMemo(() => {
    if (!duration || duration === 0) return [];
    return segments.map(seg => {
      const action = seg.is_teacher_modified && seg.teacher_action ? seg.teacher_action : seg.action;
      const left = (seg.start_time / duration) * 100;
      const width = Math.max(((seg.end_time - seg.start_time) / duration) * 100, 0.3);
      return { seg, action, left, width };
    });
  }, [segments, duration]);

  const cutBars = useMemo(() => {
    if (!duration || duration === 0) return [];
    return cutIntervals.map((interval, index) => {
      const left = (interval.start_time / duration) * 100;
      const width = Math.max(((interval.end_time - interval.start_time) / duration) * 100, 0.35);
      return { interval, index, left, width };
    });
  }, [cutIntervals, duration]);

  const annotationBars = useMemo(() => {
    if (!duration || duration === 0) return [];
    return annotations.map((annotation) => {
      const left = (annotation.start_time / duration) * 100;
      const width = Math.max(((annotation.end_time - annotation.start_time) / duration) * 100, 0.5);
      return { annotation, left, width };
    });
  }, [annotations, duration]);

  const educationalOverlayBars = useMemo(() => {
    if (!duration || duration === 0) return [];
    return educationalOverlays.map((overlay) => {
      const left = (overlay.start_time / duration) * 100;
      const width = Math.max(((overlay.end_time - overlay.start_time) / duration) * 100, 0.5);
      return { overlay, left, width };
    });
  }, [educationalOverlays, duration]);

  const endCardBars = useMemo(() => {
    if (!duration || duration === 0) return [];
    const enabled = endCards.filter((card) => card.enabled);
    const totalEndCardDuration = enabled.reduce((total, card) => total + card.duration_seconds, 0);
    let cursor = Math.max(0, duration - totalEndCardDuration);
    return enabled.map((card) => {
      const left = (cursor / duration) * 100;
      const width = Math.max((card.duration_seconds / duration) * 100, 0.8);
      cursor += card.duration_seconds;
      return { card, left, width };
    });
  }, [endCards, duration]);

  return (
    <div className="w-full space-y-1">
      {/* ── Timeline Bar ── */}
      <div
        ref={trackRef}
        className="relative h-10 overflow-hidden rounded-lg bg-surface-overlay cursor-ew-resize touch-none"
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId);
          setIsScrubbing(true);
          seekFromClientX(event.clientX);
        }}
        onPointerMove={(event) => {
          if (isScrubbing) seekFromClientX(event.clientX);
        }}
        onPointerUp={(event) => {
          setIsScrubbing(false);
          event.currentTarget.releasePointerCapture(event.pointerId);
        }}
        onPointerCancel={() => {
          setIsScrubbing(false);
        }}
      >
        {/* Segment bars */}
        {segBars.map(({ seg, action, left, width }) => (
          <div
            key={seg.id}
            className={`absolute top-0 h-full timeline-bar ${ACTION_COLORS[action]} ${
              selectedSegmentId === seg.id ? "ring-2 ring-white ring-inset" : ""
            }`}
            style={{ left: `${left}%`, width: `${width}%` }}
            title={`${seg.topic_label || "Segment"} (${action})`}
            onPointerDown={(e) => {
              onSelectSegment(seg);
              seekFromClientX(e.clientX);
            }}
          />
        ))}

        {cutBars.map(({ interval, index, left, width }) => (
          <div
            key={`${interval.start_time}-${interval.end_time}-${index}`}
            className="absolute bottom-0 z-[5] h-3 border-x border-red-200/40 bg-red-500/70"
            style={{ left: `${left}%`, width: `${width}%` }}
            title={`Transcript cut ${formatTime(interval.start_time)} - ${formatTime(interval.end_time)}`}
          />
        ))}

        {annotationBars.map(({ annotation, left, width }) => (
          <button
            key={annotation.id}
            type="button"
            className="absolute top-1 z-[6] h-3 rounded-sm border border-sky-200/50 bg-sky-400/80"
            style={{ left: `${left}%`, width: `${width}%` }}
            title={`${annotation.annotation_type}: ${annotation.text}`}
            onClick={(e) => {
              e.stopPropagation();
              onSelectAnnotation?.(annotation);
            }}
          />
        ))}

        {educationalOverlayBars.map(({ overlay, left, width }) => (
          <button
            key={overlay.id}
            type="button"
            className="absolute top-5 z-[6] h-3 rounded-sm border border-amber-100/60 bg-amber-300/85"
            style={{ left: `${left}%`, width: `${width}%` }}
            title={`${overlay.overlay_type}: ${overlay.title}`}
            onClick={(e) => {
              e.stopPropagation();
              onSelectEducationalOverlay?.(overlay);
            }}
          />
        ))}

        {endCardBars.map(({ card, left, width }) => (
          <div
            key={card.id}
            className="absolute bottom-1 z-[6] h-3 rounded-sm border border-cyan-100/60 bg-cyan-300/85"
            style={{ left: `${left}%`, width: `${width}%` }}
            title={`${card.card_type}: ${card.title}`}
          />
        ))}

        <div
          className="pointer-events-none absolute top-0 z-20 h-full w-0.5 bg-white shadow-[0_0_12px_rgba(255,255,255,0.55)]"
          style={{ left: `${playheadPct}%` }}
        >
          <div className="absolute -left-2 top-1 h-4 w-4 rounded-full border border-white bg-surface shadow-lg" />
        </div>
      </div>

      {/* ── Time Labels ── */}
      <div className="flex justify-between text-xs text-gray-500 px-1">
        <span>{formatTime(currentTime)}</span>
        <div className="flex gap-4">
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-action-keep inline-block" /> Keep</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-action-cut inline-block" /> Cut</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-action-shorten inline-block" /> Shorten</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-action-highlight inline-block" /> Highlight</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-sky-400 inline-block" /> Callout</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-amber-300 inline-block" /> Edu label</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-cyan-300 inline-block" /> End card</span>
        </div>
        <span>{formatTime(duration)}</span>
      </div>
    </div>
  );
}

interface EditorialTimelineProps {
  blocks: EditorialBlock[];
  duration: number;
  currentTime: number;
  selectedBlockId: string | null;
  onSeek: (time: number) => void;
  onSelectBlock: (block: EditorialBlock) => void;
}

const EDITORIAL_COLORS = [
  "bg-sky-500",
  "bg-emerald-500",
  "bg-amber-400",
  "bg-fuchsia-500",
  "bg-cyan-400",
  "bg-violet-500",
];

export function EditorialTimeline({
  blocks,
  duration,
  currentTime,
  selectedBlockId,
  onSeek,
  onSelectBlock,
}: EditorialTimelineProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [isScrubbing, setIsScrubbing] = useState(false);
  const playheadPct = duration > 0 ? Math.min(100, Math.max(0, (currentTime / duration) * 100)) : 0;

  const seekFromClientX = useCallback((clientX: number) => {
    const track = trackRef.current;
    if (!track || duration <= 0) return;
    const rect = track.getBoundingClientRect();
    const pct = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    onSeek(pct * duration);
  }, [duration, onSeek]);

  return (
    <div className="w-full space-y-1">
      <div
        ref={trackRef}
        className="relative h-12 cursor-ew-resize touch-none overflow-hidden rounded-lg bg-surface-overlay"
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId);
          setIsScrubbing(true);
          seekFromClientX(event.clientX);
        }}
        onPointerMove={(event) => {
          if (isScrubbing) seekFromClientX(event.clientX);
        }}
        onPointerUp={(event) => {
          setIsScrubbing(false);
          event.currentTarget.releasePointerCapture(event.pointerId);
        }}
        onPointerCancel={() => setIsScrubbing(false)}
      >
        {blocks.map((block) => {
          const left = duration > 0 ? (block.start_time / duration) * 100 : 0;
          const width = duration > 0 ? Math.max(((block.end_time - block.start_time) / duration) * 100, 0.35) : 0;
          const color = block.slide_index == null
            ? "bg-slate-500"
            : EDITORIAL_COLORS[block.slide_index % EDITORIAL_COLORS.length];
          return (
            <button
              key={block.id}
              type="button"
              className={`absolute top-0 h-full border-r border-black/25 ${color} ${selectedBlockId === block.id ? "z-10 ring-2 ring-inset ring-white" : ""}`}
              style={{ left: `${left}%`, width: `${width}%` }}
              title={`${block.title}: ${block.slide_index == null ? "Lecturer only" : `Slide ${block.slide_index + 1}`} (${formatTime(block.start_time)}-${formatTime(block.end_time)})`}
              onPointerDown={(event) => {
                event.stopPropagation();
                onSelectBlock(block);
              }}
            />
          );
        })}
        <div
          className="pointer-events-none absolute top-0 z-20 h-full w-0.5 bg-white shadow-[0_0_12px_rgba(255,255,255,0.55)]"
          style={{ left: `${playheadPct}%` }}
        >
          <div className="absolute -left-2 top-1 h-4 w-4 rounded-full border border-white bg-surface shadow-lg" />
        </div>
      </div>
      <div className="flex items-center justify-between gap-3 px-1 text-xs text-gray-500">
        <span>{formatTime(currentTime)}</span>
        <span className="truncate">Colors identify lecturer-only and assigned slide blocks</span>
        <span>{formatTime(duration)}</span>
      </div>
    </div>
  );
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
