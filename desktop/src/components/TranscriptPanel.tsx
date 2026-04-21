import { useRef, useEffect } from "react";
import type { Segment } from "../types/api";
import { User, MessageCircle } from "lucide-react";

interface Props {
  segments: Segment[];
  currentTime: number;
  onSeek: (time: number) => void;
  selectedSegmentId: string | null;
  onSelectSegment: (seg: Segment) => void;
}

const ACTION_BADGES: Record<string, string> = {
  keep: "action-keep",
  cut: "action-cut",
  shorten: "action-shorten",
  highlight: "action-highlight",
};

export function TranscriptPanel({ segments, currentTime, onSeek, selectedSegmentId, onSelectSegment }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to active segment
  useEffect(() => {
    if (activeRef.current && scrollRef.current) {
      const container = scrollRef.current;
      const el = activeRef.current;
      const top = el.offsetTop - container.offsetTop - container.clientHeight / 3;
      container.scrollTo({ top, behavior: "smooth" });
    }
  }, [currentTime]);

  return (
    <div ref={scrollRef} className="h-full overflow-y-auto space-y-1 p-2">
      {segments.map(seg => {
        const action = seg.is_teacher_modified && seg.teacher_action ? seg.teacher_action : seg.action;
        const isActive = currentTime >= seg.start_time && currentTime < seg.end_time;
        const isSelected = selectedSegmentId === seg.id;

        return (
          <div
            key={seg.id}
            ref={isActive ? activeRef : undefined}
            className={`px-3 py-2 rounded-lg text-sm cursor-pointer transition-all ${
              isActive ? "transcript-active" :
              isSelected ? "bg-surface-overlay border border-accent/30" :
              "hover:bg-surface-overlay/50"
            } ${action === "cut" ? "opacity-40 line-through" : ""}`}
            onClick={() => { onSeek(seg.start_time); onSelectSegment(seg); }}
          >
            {/* ── Header: time + speaker + action badge ── */}
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-2 text-xs text-gray-400">
                <span>{formatTime(seg.start_time)}</span>
                {seg.speaker && (
                  <span className="flex items-center gap-1 text-accent/70">
                    <User className="w-3 h-3" />
                    {seg.speaker}
                  </span>
                )}
                {seg.segment_type === "qa" && (
                  <span className="flex items-center gap-1 text-yellow-400">
                    <MessageCircle className="w-3 h-3" /> Q&A
                  </span>
                )}
              </div>
              <span className={`action-pill ${ACTION_BADGES[action] || ""}`}>
                {action}
              </span>
            </div>

            {/* ── Text ── */}
            <p className="text-gray-200 leading-relaxed">
              {seg.text || "(no text)"}
            </p>

            {/* ── Metadata bar ── */}
            <div className="flex items-center gap-3 mt-1.5 text-xs text-gray-500">
              {seg.topic_label && <span>{seg.topic_label}</span>}
              {seg.importance_score !== null && (
                <ImportanceBar score={seg.importance_score} />
              )}
              {(seg.filler_count ?? 0) > 0 && (
                <span className="text-orange-400">
                  {seg.filler_count} fillers
                </span>
              )}
              {seg.has_slide_change && (
                <span className="text-blue-400">📊 slide</span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ImportanceBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color = score >= 0.7 ? "bg-green-500" : score >= 0.4 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-1">
      <div className="w-12 h-1.5 bg-surface-overlay rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span>{pct}%</span>
    </div>
  );
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
