import type { Segment, SegmentAction } from "../types/api";
import { Check, Scissors, Minimize2, Star, AlertTriangle } from "lucide-react";

interface Props {
  segment: Segment;
  onUpdateAction: (segId: string, action: SegmentAction, note?: string) => void;
}

const ACTIONS: { action: SegmentAction; label: string; icon: React.ReactNode; color: string }[] = [
  { action: "keep", label: "Keep", icon: <Check className="w-4 h-4" />, color: "bg-action-keep hover:bg-action-keep-dark" },
  { action: "cut", label: "Cut", icon: <Scissors className="w-4 h-4" />, color: "bg-action-cut hover:bg-action-cut-dark" },
  { action: "shorten", label: "Shorten", icon: <Minimize2 className="w-4 h-4" />, color: "bg-action-shorten hover:bg-action-shorten-dark" },
  { action: "highlight", label: "Highlight", icon: <Star className="w-4 h-4" />, color: "bg-action-highlight hover:bg-action-highlight-dark" },
];

export function SegmentDetail({ segment: seg, onUpdateAction }: Props) {
  const currentAction = seg.is_teacher_modified && seg.teacher_action ? seg.teacher_action : seg.action;

  return (
    <div className="h-full overflow-y-auto p-4 space-y-5 text-sm">
      {/* ── Header ── */}
      <div>
        <h3 className="text-base font-semibold">
          Segment {seg.segment_index}
        </h3>
        <p className="text-xs text-gray-400 mt-1">
          {formatTime(seg.start_time)} — {formatTime(seg.end_time)}
          {seg.duration ? ` (${seg.duration.toFixed(1)}s)` : ""}
        </p>
      </div>

      {/* ── Action Buttons ── */}
      <div className="grid grid-cols-4 gap-1.5">
        {ACTIONS.map(({ action, label, icon, color }) => (
          <button
            key={action}
            onClick={() => onUpdateAction(seg.id, action)}
            className={`flex flex-col items-center gap-1 py-2 rounded-lg text-white text-xs font-medium transition-all ${
              currentAction === action
                ? `${color} ring-2 ring-white ring-offset-1 ring-offset-surface`
                : "bg-surface-overlay hover:bg-surface-border"
            }`}
          >
            {icon}
            {label}
          </button>
        ))}
      </div>

      {/* ── Teacher modified indicator ── */}
      {seg.is_teacher_modified && (
        <div className="bg-accent/10 border border-accent/30 rounded-lg px-3 py-2 text-xs text-accent">
          You changed this from <strong>{seg.action}</strong> to <strong>{seg.teacher_action}</strong>
        </div>
      )}

      {/* ── AI Analysis ── */}
      <Section title="Content Analysis (Agent 2)">
        <Row label="Topic" value={seg.topic_label} />
        <Row label="Type" value={seg.segment_type} />
        <Row label="Importance">
          <ScoreBar score={seg.importance_score ?? 0} />
        </Row>
        {seg.summary && <Row label="Summary" value={seg.summary} />}
        {seg.speaker && <Row label="Speaker" value={seg.speaker} />}
      </Section>

      <Section title="Delivery Analysis (Agent 3)">
        <Row label="Fluency">
          <ScoreBar score={seg.fluency_score ?? 1} />
        </Row>
        <Row label="Filler words" value={`${seg.filler_count ?? 0}`} />
        {seg.filler_words && seg.filler_words.length > 0 && (
          <Row label="Found">
            <div className="flex flex-wrap gap-1">
              {seg.filler_words.map((w, i) => (
                <span key={i} className="bg-orange-500/20 text-orange-300 px-1.5 py-0.5 rounded text-xs">{w}</span>
              ))}
            </div>
          </Row>
        )}
        <Row label="Pause time" value={`${(seg.pause_duration_total ?? 0).toFixed(1)}s`} />
        {seg.has_repetition && (
          <Row label="Repetition">
            <span className="text-orange-400 flex items-center gap-1">
              <AlertTriangle className="w-3 h-3" /> Detected
            </span>
          </Row>
        )}
      </Section>

      <Section title="Visual Structure (Agent 4)">
        <Row label="Slide change" value={seg.has_slide_change ? `Yes (#${seg.slide_index})` : "No"} />
      </Section>

      <Section title="AI Decision (Agent 5)">
        <Row label="Action" value={seg.action} />
        <Row label="Confidence" value={seg.action_confidence ? `${Math.round(seg.action_confidence * 100)}%` : "N/A"} />
        {seg.action_reason && <Row label="Reason" value={seg.action_reason} />}
      </Section>

      {/* ── Teacher Note ── */}
      <div>
        <label className="text-xs text-gray-400 block mb-1">Teacher Note</label>
        <textarea
          className="w-full bg-surface-overlay border border-surface-border rounded-lg px-3 py-2 text-sm text-gray-200 resize-none focus:outline-none focus:border-accent"
          rows={2}
          placeholder="Add a note about your decision..."
          defaultValue={seg.teacher_note || ""}
          onBlur={(e) => {
            if (e.target.value !== (seg.teacher_note || "")) {
              onUpdateAction(seg.id, currentAction, e.target.value);
            }
          }}
        />
      </div>
    </div>
  );
}

// ── Sub-components ──

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">{title}</h4>
      <div className="space-y-1.5 pl-1">{children}</div>
    </div>
  );
}

function Row({ label, value, children }: { label: string; value?: string | null; children?: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-2">
      <span className="text-gray-500 shrink-0">{label}</span>
      {children || <span className="text-gray-200 text-right">{value ?? "—"}</span>}
    </div>
  );
}

function ScoreBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color = score >= 0.7 ? "bg-green-500" : score >= 0.4 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 h-2 bg-surface-overlay rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-gray-200">{pct}%</span>
    </div>
  );
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
