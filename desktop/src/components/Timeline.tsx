import { useMemo } from "react";
import type { AnnotationAction, EducationalOverlayAction, EndCardAction, Segment, SegmentAction, TranscriptCutInterval } from "../types/api";

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
  const playheadPct = duration > 0 ? (currentTime / duration) * 100 : 0;

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
        className="relative h-10 bg-surface-overlay rounded-lg overflow-hidden cursor-pointer"
        onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const pct = (e.clientX - rect.left) / rect.width;
          onSeek(pct * duration);
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
            onClick={(e) => { e.stopPropagation(); onSelectSegment(seg); }}
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

        {/* Playhead */}
        <div
          className="absolute top-0 w-0.5 h-full bg-white z-10 pointer-events-none"
          style={{ left: `${playheadPct}%` }}
        />
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

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
