import { useRef, useEffect, useMemo, useState } from "react";
import type { Segment, TranscriptCutDecision, TranscriptTimeline, TranscriptTimelineWord } from "../types/api";
import { Loader2, MessageCircle, Scissors, Trash2, User, X } from "lucide-react";

interface Props {
  segments: Segment[];
  timeline: TranscriptTimeline | null;
  cutDecisions: TranscriptCutDecision[];
  cutsLoading: boolean;
  currentTime: number;
  onSeek: (time: number) => void;
  selectedSegmentId: string | null;
  onSelectSegment: (seg: Segment) => void;
  onCreateTranscriptCut: (wordStartIndex: number, wordEndIndex: number) => Promise<void>;
  onDeleteTranscriptCut: (decisionId: string) => Promise<void>;
}

interface WordSelection {
  anchorIndex: number;
  focusIndex: number;
}

const ACTION_BADGES: Record<string, string> = {
  keep: "action-keep",
  cut: "action-cut",
  shorten: "action-shorten",
  highlight: "action-highlight",
};

export function TranscriptPanel({
  segments,
  timeline,
  cutDecisions,
  cutsLoading,
  currentTime,
  onSeek,
  selectedSegmentId,
  onSelectSegment,
  onCreateTranscriptCut,
  onDeleteTranscriptCut,
}: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef<HTMLDivElement>(null);
  const [selection, setSelection] = useState<WordSelection | null>(null);
  const [isSelecting, setIsSelecting] = useState(false);
  const [isSavingCut, setIsSavingCut] = useState(false);
  const [deletingCutId, setDeletingCutId] = useState<string | null>(null);

  useEffect(() => {
    if (activeRef.current && scrollRef.current) {
      const container = scrollRef.current;
      const el = activeRef.current;
      const top = el.offsetTop - container.offsetTop - container.clientHeight / 3;
      container.scrollTo({ top, behavior: "smooth" });
    }
  }, [currentTime]);

  useEffect(() => {
    const stopSelecting = () => setIsSelecting(false);
    window.addEventListener("pointerup", stopSelecting);
    return () => window.removeEventListener("pointerup", stopSelecting);
  }, []);

  const segmentById = useMemo(() => new Map(segments.map(segment => [segment.id, segment])), [segments]);
  const wordsBySegmentId = useMemo(() => {
    const grouped = new Map<string, TranscriptTimelineWord[]>();
    for (const word of timeline?.words ?? []) {
      if (!word.segment_id) continue;
      const words = grouped.get(word.segment_id) ?? [];
      words.push(word);
      grouped.set(word.segment_id, words);
    }
    return grouped;
  }, [timeline?.words]);

  const cutWordIndexes = useMemo(() => {
    const indexes = new Map<number, TranscriptCutDecision>();
    for (const decision of cutDecisions) {
      for (let index = decision.word_start_index; index <= decision.word_end_index; index += 1) {
        if (!indexes.has(index)) indexes.set(index, decision);
      }
    }
    return indexes;
  }, [cutDecisions]);

  const selectedRange = selection
    ? {
        start: Math.min(selection.anchorIndex, selection.focusIndex),
        end: Math.max(selection.anchorIndex, selection.focusIndex),
      }
    : null;

  const selectedWords = useMemo(() => {
    if (!selectedRange || !timeline) return [];
    return timeline.words.slice(selectedRange.start, selectedRange.end + 1);
  }, [selectedRange, timeline]);

  const selectedText = selectedWords.map(word => word.text).join(" ");
  const hasWordTimeline = Boolean(timeline?.words.length);

  const handleWordPointerDown = (word: TranscriptTimelineWord) => {
    setSelection({ anchorIndex: word.word_index, focusIndex: word.word_index });
    setIsSelecting(true);
    onSeek(word.start_time);
    const segment = word.segment_id ? segmentById.get(word.segment_id) : null;
    if (segment) onSelectSegment(segment);
  };

  const handleWordPointerEnter = (word: TranscriptTimelineWord) => {
    if (!isSelecting) return;
    setSelection(prev => prev ? { ...prev, focusIndex: word.word_index } : prev);
  };

  const handleCutSelection = async () => {
    if (!selectedRange) return;
    setIsSavingCut(true);
    try {
      await onCreateTranscriptCut(selectedRange.start, selectedRange.end);
      setSelection(null);
    } finally {
      setIsSavingCut(false);
    }
  };

  const handleDeleteCut = async (decisionId: string) => {
    setDeletingCutId(decisionId);
    try {
      await onDeleteTranscriptCut(decisionId);
    } finally {
      setDeletingCutId(null);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-surface-border px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0 text-xs text-gray-500">
            {hasWordTimeline ? `${timeline?.word_count ?? 0} timed words` : "Segment transcript"}
            {cutDecisions.length > 0 && (
              <span className="ml-2 text-red-300">{cutDecisions.length} text cuts</span>
            )}
          </div>
          {cutsLoading && <Loader2 className="h-3.5 w-3.5 animate-spin text-gray-500" />}
        </div>

        {selectedRange && (
          <div className="mt-2 rounded-md border border-red-500/30 bg-red-500/10 p-2">
            <div className="mb-2 flex items-start justify-between gap-2">
              <p className="line-clamp-2 min-w-0 text-xs text-red-100">{selectedText || "Selected transcript words"}</p>
              <button
                type="button"
                onClick={() => setSelection(null)}
                className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-red-200 hover:bg-red-500/20"
                aria-label="Clear transcript selection"
                title="Clear selection"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
            <button
              type="button"
              onClick={handleCutSelection}
              disabled={isSavingCut}
              className="flex w-full items-center justify-center gap-1.5 rounded-md bg-red-600 px-2 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isSavingCut ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Scissors className="h-3.5 w-3.5" />}
              Cut selected text
            </button>
          </div>
        )}
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto space-y-1 p-2">
        {segments.map(seg => {
          const action = seg.is_teacher_modified && seg.teacher_action ? seg.teacher_action : seg.action;
          const isActive = currentTime >= seg.start_time && currentTime < seg.end_time;
          const isSelected = selectedSegmentId === seg.id;
          const segmentWords = wordsBySegmentId.get(seg.id) ?? [];

          return (
            <div
              key={seg.id}
              ref={isActive ? activeRef : undefined}
              className={`px-3 py-2 rounded-lg text-sm transition-all ${
                isActive ? "transcript-active" :
                isSelected ? "bg-surface-overlay border border-accent/30" :
                "hover:bg-surface-overlay/50"
              } ${action === "cut" ? "opacity-40" : ""}`}
              onClick={() => { onSeek(seg.start_time); onSelectSegment(seg); }}
            >
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

              {segmentWords.length > 0 ? (
                <p className="select-none text-gray-200 leading-7">
                  {segmentWords.map(word => {
                    const isInSelection = Boolean(
                      selectedRange && word.word_index >= selectedRange.start && word.word_index <= selectedRange.end,
                    );
                    const cutDecision = cutWordIndexes.get(word.word_index);
                    const isCurrent = currentTime >= word.start_time && currentTime < word.end_time;

                    return (
                      <button
                        key={word.word_index}
                        type="button"
                        onPointerDown={(event) => {
                          event.stopPropagation();
                          handleWordPointerDown(word);
                        }}
                        onPointerEnter={() => handleWordPointerEnter(word)}
                        onClick={(event) => event.stopPropagation()}
                        className={`mr-1 rounded px-1 py-0.5 text-left transition-colors ${
                          cutDecision
                            ? "bg-red-500/20 text-red-200 line-through decoration-red-300 decoration-2"
                            : isInSelection
                              ? "bg-red-500/35 text-white"
                              : isCurrent
                                ? "bg-accent/25 text-white"
                                : "hover:bg-surface-overlay"
                        }`}
                        title={`${formatTime(word.start_time)} - ${formatTime(word.end_time)}`}
                      >
                        {word.text}
                      </button>
                    );
                  })}
                </p>
              ) : (
                <p className={`text-gray-200 leading-relaxed ${action === "cut" ? "line-through" : ""}`}>
                  {seg.text || "(no text)"}
                </p>
              )}

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
                  <span className="text-blue-400">slide</span>
                )}
              </div>
            </div>
          );
        })}

        {cutDecisions.length > 0 && (
          <div className="space-y-2 px-1 pt-2">
            <p className="px-2 text-[11px] font-semibold uppercase tracking-wider text-gray-500">Text Cut Decisions</p>
            {cutDecisions.map(decision => (
              <div key={decision.id} className="rounded-md border border-red-500/20 bg-red-500/10 p-2">
                <div className="flex items-start gap-2">
                  <Scissors className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-300" />
                  <div className="min-w-0 flex-1">
                    <p className="line-clamp-2 text-xs text-red-100">{decision.text}</p>
                    <p className="mt-1 text-[11px] text-red-200/70">
                      {formatTime(decision.start_time)} - {formatTime(decision.end_time)}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleDeleteCut(decision.id)}
                    disabled={deletingCutId === decision.id}
                    className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-red-200 hover:bg-red-500/20 disabled:opacity-50"
                    aria-label="Remove transcript cut"
                    title="Remove cut"
                  >
                    {deletingCutId === decision.id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Trash2 className="h-3.5 w-3.5" />
                    )}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
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
