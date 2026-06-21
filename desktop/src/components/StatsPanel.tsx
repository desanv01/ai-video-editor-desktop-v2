import { useState, useEffect } from "react";
import { PieChart, Pie, Cell, ResponsiveContainer } from "recharts";
import { Clock, Scissors, MessageSquareOff, Volume2, CheckCircle2, Download } from "lucide-react";
import * as api from "../lib/api";
import type { EditPlan, Chapter } from "../types/api";

interface Props {
  videoId: string;
  plan: EditPlan | null;
  onApprove: () => void;
  approving: boolean;
}

const PIE_COLORS = ["#22c55e", "#ef4444", "#3b82f6", "#eab308"];

export function StatsPanel({ videoId, plan, onApprove, approving }: Props) {
  const [chapters, setChapters] = useState<Chapter[]>([]);

  useEffect(() => {
    api.getChapters(videoId).then(r => setChapters(r.chapters)).catch(() => {});
  }, [videoId]);

  if (!plan) return null;

  const original = plan.original_duration ?? 0;
  const estimated = plan.estimated_duration ?? 0;
  const saved = original - estimated;
  const reductionPct = original > 0 ? Math.round((saved / original) * 100) : 0;

  const pieData = [
    { name: "Keep", value: plan.segments_keep ?? 0 },
    { name: "Cut", value: plan.segments_cut ?? 0 },
    { name: "Shorten", value: plan.segments_shorten ?? 0 },
    { name: "Highlight", value: plan.segments_highlight ?? 0 },
  ].filter(d => d.value > 0);

  return (
    <div className="h-full overflow-y-auto p-4 space-y-5 text-sm">
      {/* ── Approve Button ── */}
      {!plan.is_approved && (
        <button
          onClick={onApprove}
          disabled={approving}
          className="w-full py-3 bg-accent hover:bg-accent-hover disabled:opacity-50 rounded-lg font-semibold text-white transition-all flex items-center justify-center gap-2"
        >
          <CheckCircle2 className="w-4 h-4" />
          {approving ? "Rendering..." : "Approve & Render Video"}
        </button>
      )}

      {/* ── Duration Card ── */}
      <div className="bg-surface-raised rounded-xl p-4 border border-surface-border">
        <div className="flex items-center gap-2 mb-3">
          <Clock className="w-4 h-4 text-accent" />
          <h3 className="font-semibold">Duration</h3>
        </div>
        <div className="grid grid-cols-3 gap-3 text-center">
          <Stat label="Original" value={formatDuration(original)} />
          <Stat label="Estimated" value={formatDuration(estimated)} highlight />
          <Stat label="Saved" value={`${reductionPct}%`} sub={formatDuration(saved)} />
        </div>
      </div>

      {/* ── Segments Pie Chart ── */}
      <div className="bg-surface-raised rounded-xl p-4 border border-surface-border">
        <h3 className="font-semibold mb-3">Segment Actions</h3>
        <div className="flex items-center gap-4">
          <div className="w-24 h-24">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={pieData} dataKey="value" cx="50%" cy="50%" outerRadius="90%" innerRadius="60%">
                  {pieData.map((_, i) => (
                    <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="space-y-1.5 text-xs">
            <LegendRow color="#22c55e" label="Keep" value={plan.segments_keep ?? 0} />
            <LegendRow color="#ef4444" label="Cut" value={plan.segments_cut ?? 0} />
            <LegendRow color="#eab308" label="Highlight" value={plan.segments_highlight ?? 0} />
            <div className="pt-1 border-t border-surface-border text-gray-400">
              Total: {plan.segments_total ?? 0} segments
            </div>
          </div>
        </div>
      </div>

      {/* ── Cleaning Stats ── */}
      <div className="bg-surface-raised rounded-xl p-4 border border-surface-border space-y-2">
        <h3 className="font-semibold mb-2">Cleaning Summary</h3>
        <IconStat icon={<MessageSquareOff className="w-4 h-4 text-orange-400" />}
          label="Filler words removed" value={String(plan.filler_words_removed ?? 0)} />
        <IconStat icon={<Volume2 className="w-4 h-4 text-blue-400" />}
          label="Silence removed" value={`${(plan.silence_removed_seconds ?? 0).toFixed(1)}s`} />
        <IconStat icon={<Scissors className="w-4 h-4 text-red-400" />}
          label="Segments cut" value={String(plan.segments_cut ?? 0)} />
      </div>

      {/* ── Chapters ── */}
      {chapters.length > 0 && (
        <div className="bg-surface-raised rounded-xl p-4 border border-surface-border">
          <h3 className="font-semibold mb-2">Auto Chapters ({chapters.length})</h3>
          <div className="space-y-1 text-xs">
            {chapters.map((ch, i) => (
              <div key={i} className="flex gap-2">
                <span className="text-accent font-mono shrink-0">{ch.formatted}</span>
                <span className="text-gray-300">{ch.label}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Downloads (after approval) ── */}
      {plan.is_approved && (
        <div className="space-y-2">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Downloads</h3>
          <a href={api.getVideoDownloadUrl(videoId)} target="_blank" rel="noreferrer"
            className="flex items-center gap-2 w-full py-2.5 bg-green-600 hover:bg-green-700 rounded-lg text-white text-center justify-center font-medium transition-all">
            <Download className="w-4 h-4" /> Edited Video (MP4)
          </a>
          <a href={api.getSubtitleDownloadUrl(videoId)} target="_blank" rel="noreferrer"
            className="flex items-center gap-2 w-full py-2 bg-surface-overlay hover:bg-surface-border rounded-lg text-gray-200 text-center justify-center transition-all text-sm">
            <Download className="w-3 h-3" /> Subtitles (SRT)
          </a>
          <a href={api.getSubtitleVttUrl(videoId)} target="_blank" rel="noreferrer"
            className="flex items-center gap-2 w-full py-2 bg-surface-overlay hover:bg-surface-border rounded-lg text-gray-200 text-center justify-center transition-all text-sm">
            <Download className="w-3 h-3" /> Subtitles (VTT)
          </a>
          <a href={api.getChaptersDownloadUrl(videoId)} target="_blank" rel="noreferrer"
            className="flex items-center gap-2 w-full py-2 bg-surface-overlay hover:bg-surface-border rounded-lg text-gray-200 text-center justify-center transition-all text-sm">
            <Download className="w-3 h-3" /> Chapter Markers
          </a>
          <a href={api.getPlanExportUrl(videoId)} target="_blank" rel="noreferrer"
            className="flex items-center gap-2 w-full py-2 bg-surface-overlay hover:bg-surface-border rounded-lg text-gray-200 text-center justify-center transition-all text-sm">
            <Download className="w-3 h-3" /> Edit Plan (JSON)
          </a>
          <a href={api.getQualityReportExportUrl(videoId)} target="_blank" rel="noreferrer"
            className="flex items-center gap-2 w-full py-2 bg-surface-overlay hover:bg-surface-border rounded-lg text-gray-200 text-center justify-center transition-all text-sm">
            <Download className="w-3 h-3" /> Quality Report
          </a>
          <a href={api.getModeComparisonSummaryUrl(videoId)} target="_blank" rel="noreferrer"
            className="flex items-center gap-2 w-full py-2 bg-surface-overlay hover:bg-surface-border rounded-lg text-gray-200 text-center justify-center transition-all text-sm">
            <Download className="w-3 h-3" /> Mode Comparison
          </a>
          <a href={api.getBeforeAfterComparisonUrl(videoId)} target="_blank" rel="noreferrer"
            className="flex items-center gap-2 w-full py-2 bg-surface-overlay hover:bg-surface-border rounded-lg text-gray-200 text-center justify-center transition-all text-sm">
            <Download className="w-3 h-3" /> Before/After
          </a>
          <a href={api.getTimelineDecisionsUrl(videoId)} target="_blank" rel="noreferrer"
            className="flex items-center gap-2 w-full py-2 bg-surface-overlay hover:bg-surface-border rounded-lg text-gray-200 text-center justify-center transition-all text-sm">
            <Download className="w-3 h-3" /> Timeline Decisions
          </a>
          <a href={api.getProviderModeTraceUrl(videoId)} target="_blank" rel="noreferrer"
            className="flex items-center gap-2 w-full py-2 bg-surface-overlay hover:bg-surface-border rounded-lg text-gray-200 text-center justify-center transition-all text-sm">
            <Download className="w-3 h-3" /> Provider Mode
          </a>
          <a href={api.getMetricsSummaryUrl(videoId)} target="_blank" rel="noreferrer"
            className="flex items-center gap-2 w-full py-2 bg-surface-overlay hover:bg-surface-border rounded-lg text-gray-200 text-center justify-center transition-all text-sm">
            <Download className="w-3 h-3" /> Metrics Summary
          </a>
          <a href={api.getAcademicEvidenceBundleUrl(videoId)} target="_blank" rel="noreferrer"
            className="flex items-center gap-2 w-full py-2 bg-surface-overlay hover:bg-surface-border rounded-lg text-gray-200 text-center justify-center transition-all text-sm">
            <Download className="w-3 h-3" /> Evidence Bundle
          </a>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, sub, highlight }: { label: string; value: string; sub?: string; highlight?: boolean }) {
  return (
    <div>
      <div className={`text-lg font-bold ${highlight ? "text-accent" : "text-gray-100"}`}>{value}</div>
      <div className="text-xs text-gray-400">{label}</div>
      {sub && <div className="text-xs text-gray-500">{sub}</div>}
    </div>
  );
}

function LegendRow({ color, label, value }: { color: string; label: string; value: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ backgroundColor: color }} />
      <span className="text-gray-300">{label}</span>
      <span className="text-gray-400 ml-auto">{value}</span>
    </div>
  );
}

function IconStat({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2 text-gray-300">{icon}{label}</div>
      <span className="font-semibold text-gray-100">{value}</span>
    </div>
  );
}

function formatDuration(seconds: number): string {
  if (seconds < 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
