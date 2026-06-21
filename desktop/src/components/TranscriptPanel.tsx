import { useRef, useEffect, useMemo, useState } from "react";
import type { Segment, TranscriptCutDecision, TranscriptTimeline, TranscriptTimelineWord } from "../types/api";
import { Check, Loader2, MessageCircle, RotateCcw, Scissors, SlidersHorizontal, Trash2, User, X } from "lucide-react";

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
  onRestoreTranscriptCutWord: (decisionId: string, wordIndex: number) => Promise<void>;
  onUpdateTranscriptCutTrim: (
    decisionId: string,
    update: { start_time: number; end_time: number; pre_roll_seconds: number; post_roll_seconds: number },
  ) => Promise<void>;
}

interface WordSelection {
  anchorIndex: number;
  focusIndex: number;
}

interface TrimDraft {
  start_time: string;
  end_time: string;
  pre_roll_seconds: string;
  post_roll_seconds: string;
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
  onRestoreTranscriptCutWord,
  onUpdateTranscriptCutTrim,
}: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef<HTMLDivElement>(null);
  const selectionArmTimerRef = useRef<number | null>(null);
  const followResumeTimerRef = useRef<number | null>(null);
  const [selection, setSelection] = useState<WordSelection | null>(null);
  const [followPlayback, setFollowPlayback] = useState(true);
  const [manualScrollLocked, setManualScrollLocked] = useState(false);
  const [isSelecting, setIsSelecting] = useState(false);
  const [selectionActionArmed, setSelectionActionArmed] = useState(false);
  const [isSavingCut, setIsSavingCut] = useState(false);
  const [deletingCutId, setDeletingCutId] = useState<string | null>(null);
  const [restoringCutWordKey, setRestoringCutWordKey] = useState<string | null>(null);
  const [savingTrimId, setSavingTrimId] = useState<string | null>(null);
  const [trimDrafts, setTrimDrafts] = useState<Record<string, TrimDraft>>({});

  useEffect(() => {
    if (followPlayback && !manualScrollLocked && activeRef.current && scrollRef.current) {
      const container = scrollRef.current;
      const el = activeRef.current;
      const top = el.offsetTop - container.offsetTop - container.clientHeight / 3;
      container.scrollTo({ top, behavior: "smooth" });
    }
  }, [currentTime, followPlayback, manualScrollLocked]);

  const pauseAutoFollow = () => {
    if (!followPlayback) return;
    setManualScrollLocked(true);
    if (followResumeTimerRef.current !== null) {
      window.clearTimeout(followResumeTimerRef.current);
    }
    followResumeTimerRef.current = window.setTimeout(() => {
      setManualScrollLocked(false);
      followResumeTimerRef.current = null;
    }, 5000);
  };

  useEffect(() => {
    const stopSelecting = () => {
      setIsSelecting(false);
      if (selectionArmTimerRef.current !== null) {
        window.clearTimeout(selectionArmTimerRef.current);
      }
      selectionArmTimerRef.current = window.setTimeout(() => {
        setSelectionActionArmed(true);
        selectionArmTimerRef.current = null;
      }, 150);
    };
    window.addEventListener("pointerup", stopSelecting);
    return () => {
      window.removeEventListener("pointerup", stopSelecting);
      if (selectionArmTimerRef.current !== null) {
        window.clearTimeout(selectionArmTimerRef.current);
      }
      if (followResumeTimerRef.current !== null) {
        window.clearTimeout(followResumeTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    setTrimDrafts(Object.fromEntries(
      cutDecisions.map(decision => [decision.id, decisionToTrimDraft(decision)]),
    ));
  }, [cutDecisions]);

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
  const activeCutCount = useMemo(() => {
    return new Set(cutDecisions.map(decision => decision.id)).size;
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
  const selectedSingleWord = selectedRange && selectedRange.start === selectedRange.end
    ? timeline?.words[selectedRange.start] ?? null
    : null;
  const selectedCutDecision = selectedSingleWord ? cutWordIndexes.get(selectedSingleWord.word_index) ?? null : null;
  const hasWordTimeline = Boolean(timeline?.words.length);

  const handleWordPointerDown = (word: TranscriptTimelineWord) => {
    if (selectionArmTimerRef.current !== null) {
      window.clearTimeout(selectionArmTimerRef.current);
      selectionArmTimerRef.current = null;
    }
    setSelection({ anchorIndex: word.word_index, focusIndex: word.word_index });
    setSelectionActionArmed(false);
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
      setSelectionActionArmed(false);
    } finally {
      setIsSavingCut(false);
    }
  };

  const handleDeleteCut = async (decisionId: string) => {
    setDeletingCutId(decisionId);
    try {
      await onDeleteTranscriptCut(decisionId);
      setSelection(null);
      setSelectionActionArmed(false);
    } finally {
      setDeletingCutId(null);
    }
  };

  const handleRestoreSelectedCutWord = async () => {
    if (!selectedSingleWord || !selectedCutDecision) return;
    const key = `${selectedCutDecision.id}:${selectedSingleWord.word_index}`;
    setRestoringCutWordKey(key);
    try {
      await onRestoreTranscriptCutWord(selectedCutDecision.id, selectedSingleWord.word_index);
      setSelection(null);
      setSelectionActionArmed(false);
    } finally {
      setRestoringCutWordKey(null);
    }
  };

  const handleTrimDraftChange = (decision: TranscriptCutDecision, field: keyof TrimDraft, value: string) => {
    setTrimDrafts(prev => ({
      ...prev,
      [decision.id]: nextTrimDraft(decision, prev[decision.id] ?? decisionToTrimDraft(decision), field, value),
    }));
  };

  const handleResetTrimDraft = (decision: TranscriptCutDecision) => {
    const wordStart = decision.word_start_time ?? decision.start_time;
    const wordEnd = decision.word_end_time ?? decision.end_time;
    setTrimDrafts(prev => ({
      ...prev,
      [decision.id]: {
        start_time: formatNumberInput(wordStart),
        end_time: formatNumberInput(wordEnd),
        pre_roll_seconds: "0.00",
        post_roll_seconds: "0.00",
      },
    }));
  };

  const handleApplyTrim = async (decision: TranscriptCutDecision) => {
    const draft = trimDrafts[decision.id] ?? decisionToTrimDraft(decision);
    const startTime = parseDraftNumber(draft.start_time);
    const endTime = parseDraftNumber(draft.end_time);
    const preRoll = parseDraftNumber(draft.pre_roll_seconds);
    const postRoll = parseDraftNumber(draft.post_roll_seconds);

    if (startTime === null || endTime === null || preRoll === null || postRoll === null) {
      alert("Trim values must be valid numbers.");
      return;
    }
    if (endTime <= startTime) {
      alert("Cut end must be after cut start.");
      return;
    }

    setSavingTrimId(decision.id);
    try {
      await onUpdateTranscriptCutTrim(decision.id, {
        start_time: startTime,
        end_time: endTime,
        pre_roll_seconds: preRoll,
        post_roll_seconds: postRoll,
      });
    } finally {
      setSavingTrimId(null);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-surface-border px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0 text-xs text-gray-500">
            {hasWordTimeline ? `${timeline?.word_count ?? 0} timed words` : "Segment transcript"}
            {activeCutCount > 0 && (
              <span className="ml-2 text-red-300">{activeCutCount} text cuts</span>
            )}
            {selectedRange && (
              <span className="ml-2 text-accent">{selectedWords.length} selected</span>
            )}
            {manualScrollLocked && (
              <span className="ml-2 text-yellow-300">manual scroll</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setFollowPlayback(value => !value);
                setManualScrollLocked(false);
              }}
              className={`rounded px-2 py-1 text-[11px] font-semibold transition-colors ${
                followPlayback ? "bg-accent/15 text-accent" : "bg-surface-overlay text-gray-400 hover:text-gray-200"
              }`}
            >
              {followPlayback ? "Following" : "Follow"}
            </button>
            {cutsLoading && <Loader2 className="h-3.5 w-3.5 animate-spin text-gray-500" />}
          </div>
        </div>

        {selectedRange && (
          <div className="mt-2 rounded-md border border-red-500/30 bg-red-500/10 p-2">
            <div className="mb-2 flex items-start justify-between gap-2">
              <p className="line-clamp-2 min-w-0 text-xs text-red-100">{selectedText || "Selected transcript words"}</p>
              <button
                type="button"
                onClick={() => {
                  setSelection(null);
                  setSelectionActionArmed(false);
                }}
                className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-red-200 hover:bg-red-500/20"
                aria-label="Clear transcript selection"
                title="Clear selection"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
            {selectedCutDecision && selectedSingleWord ? (
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={handleRestoreSelectedCutWord}
                  disabled={restoringCutWordKey === `${selectedCutDecision.id}:${selectedSingleWord.word_index}`}
                  className="flex items-center justify-center gap-1.5 rounded-md bg-emerald-600 px-2 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {restoringCutWordKey === `${selectedCutDecision.id}:${selectedSingleWord.word_index}` ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <RotateCcw className="h-3.5 w-3.5" />
                  )}
                  Restore word
                </button>
                <button
                  type="button"
                  onClick={() => handleDeleteCut(selectedCutDecision.id)}
                  disabled={deletingCutId === selectedCutDecision.id}
                  className="flex items-center justify-center gap-1.5 rounded-md bg-red-600 px-2 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {deletingCutId === selectedCutDecision.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                  Remove cut
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={handleCutSelection}
                disabled={isSavingCut || !selectionActionArmed}
                className="flex w-full items-center justify-center gap-1.5 rounded-md bg-red-600 px-2 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isSavingCut ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Scissors className="h-3.5 w-3.5" />}
                Cut selected text
              </button>
            )}
          </div>
        )}
      </div>

      <div
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-y-auto space-y-1 p-2"
        onWheel={pauseAutoFollow}
        onPointerDown={pauseAutoFollow}
      >
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
                        onClick={(event) => {
                          event.stopPropagation();
                          if (cutDecision) {
                            void onRestoreTranscriptCutWord(cutDecision.id, word.word_index);
                            setSelection(null);
                            setSelectionActionArmed(false);
                          }
                        }}
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

        {activeCutCount > 0 && (
          <div className="space-y-2 px-1 pt-2">
            <p className="px-2 text-[11px] font-semibold uppercase tracking-wider text-gray-500">Text Cut Decisions</p>
            {cutDecisions.map(decision => {
              const draft = trimDrafts[decision.id] ?? decisionToTrimDraft(decision);
              const wordStart = decision.word_start_time ?? decision.start_time;
              const wordEnd = decision.word_end_time ?? decision.end_time;

              return (
              <div key={decision.id} className="rounded-md border border-red-500/20 bg-red-500/10 p-2">
                <div className="flex items-start gap-2">
                  <Scissors className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-300" />
                  <div className="min-w-0 flex-1">
                    <p className="line-clamp-2 text-xs text-red-100">{decision.text}</p>
                    <p className="mt-1 text-[11px] text-red-200/70">
                      {formatPreciseTime(decision.start_time)} - {formatPreciseTime(decision.end_time)}
                      <span className="ml-1 text-red-200/45">
                        base {formatPreciseTime(wordStart)} - {formatPreciseTime(wordEnd)}
                      </span>
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
                <div className="mt-2 border-t border-red-300/10 pt-2">
                  <div className="mb-1.5 flex items-center justify-between gap-2 text-[11px] text-red-100/80">
                    <span className="inline-flex items-center gap-1 font-semibold">
                      <SlidersHorizontal className="h-3 w-3" />
                      Manual trim
                    </span>
                    <span>{formatPreciseDuration(decision.duration)} cut</span>
                  </div>
                  <div className="grid grid-cols-2 gap-1.5">
                    <TrimNumberInput
                      label="Start"
                      value={draft.start_time}
                      onChange={(value) => handleTrimDraftChange(decision, "start_time", value)}
                    />
                    <TrimNumberInput
                      label="End"
                      value={draft.end_time}
                      onChange={(value) => handleTrimDraftChange(decision, "end_time", value)}
                    />
                    <TrimNumberInput
                      label="Pre-roll"
                      value={draft.pre_roll_seconds}
                      onChange={(value) => handleTrimDraftChange(decision, "pre_roll_seconds", value)}
                    />
                    <TrimNumberInput
                      label="Post-roll"
                      value={draft.post_roll_seconds}
                      onChange={(value) => handleTrimDraftChange(decision, "post_roll_seconds", value)}
                    />
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-2">
                    <button
                      type="button"
                      onClick={() => handleResetTrimDraft(decision)}
                      className="flex h-7 w-7 items-center justify-center rounded text-red-200 hover:bg-red-500/20"
                      aria-label="Reset cut trim to transcript word boundaries"
                      title="Reset to word boundaries"
                    >
                      <RotateCcw className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => handleApplyTrim(decision)}
                      disabled={savingTrimId === decision.id}
                      className="flex items-center gap-1.5 rounded bg-red-600/70 px-2 py-1.5 text-[11px] font-semibold text-white transition-colors hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {savingTrimId === decision.id ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Check className="h-3.5 w-3.5" />
                      )}
                      Apply trim
                    </button>
                  </div>
                </div>
              </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function TrimNumberInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="min-w-0 text-[11px] text-red-100/70">
      <span className="mb-0.5 block truncate">{label}</span>
      <input
        type="number"
        min="0"
        max={label.includes("roll") ? 5 : undefined}
        step="0.05"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-7 w-full rounded border border-red-300/15 bg-black/20 px-1.5 text-xs text-red-50 outline-none transition-colors focus:border-red-300/50"
      />
    </label>
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

function formatPreciseTime(seconds: number): string {
  const safeSeconds = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  const m = Math.floor(safeSeconds / 60);
  const s = safeSeconds % 60;
  return `${m}:${s.toFixed(2).padStart(5, "0")}`;
}

function formatPreciseDuration(seconds: number): string {
  return `${(Number.isFinite(seconds) ? seconds : 0).toFixed(2)}s`;
}

function decisionToTrimDraft(decision: TranscriptCutDecision): TrimDraft {
  return {
    start_time: formatNumberInput(decision.start_time),
    end_time: formatNumberInput(decision.end_time),
    pre_roll_seconds: formatNumberInput(decision.pre_roll_seconds ?? 0),
    post_roll_seconds: formatNumberInput(decision.post_roll_seconds ?? 0),
  };
}

function nextTrimDraft(
  decision: TranscriptCutDecision,
  current: TrimDraft,
  field: keyof TrimDraft,
  value: string,
): TrimDraft {
  const next = { ...current, [field]: value };
  const parsedValue = parseDraftNumber(value);
  if (parsedValue === null) return next;

  if (field === "pre_roll_seconds") {
    const wordStart = decision.word_start_time ?? decision.start_time;
    next.start_time = formatNumberInput(Math.max(0, wordStart - parsedValue));
  }

  if (field === "post_roll_seconds") {
    const wordEnd = decision.word_end_time ?? decision.end_time;
    next.end_time = formatNumberInput(wordEnd + parsedValue);
  }

  return next;
}

function formatNumberInput(value: number | null | undefined): string {
  return Number.isFinite(value) ? Number(value).toFixed(2) : "0.00";
}

function parseDraftNumber(value: string): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}
