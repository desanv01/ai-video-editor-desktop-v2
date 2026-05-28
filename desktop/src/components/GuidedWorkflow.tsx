import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  ArrowLeft,
  ArrowRight,
  AlertTriangle,
  Captions,
  CheckCircle2,
  Circle,
  Crosshair,
  Download,
  ExternalLink,
  FileText,
  Film,
  Layers,
  ListChecks,
  Loader2,
  MessageSquare,
  MessageSquareOff,
  MonitorPlay,
  Palette,
  Plus,
  RefreshCw,
  Scissors,
  SlidersHorizontal,
  Sparkles,
  SplitSquareHorizontal,
  TextSelect,
  Trash2,
  Wand2,
  Volume2,
  XCircle,
} from "lucide-react";
import { SegmentDetail } from "./SegmentDetail";
import * as api from "../lib/api";
import type {
  CameraCorner,
  CameraShape,
  AnnotationAction,
  AnnotationActionUpdate,
  AnnotationPosition,
  AnnotationType,
  AnimationPreset,
  AnimationSettings,
  CaptionAppearance,
  CaptionExportBehavior,
  CaptionPlacement,
  CaptionPolicy,
  CaptionPolicyUpdate,
  Chapter,
  CleanAnalyzeResult,
  CleanProfileId,
  EducationalOverlayAction,
  EducationalOverlayActionUpdate,
  EducationalOverlayPosition,
  EducationalOverlayType,
  EndCardAction,
  EndCardActionUpdate,
  EndCardType,
  EditPlan,
  ExportPreset,
  ExportPresetCatalog,
  LayoutAspectRatio,
  LayoutCue,
  LayoutMode,
  ProcessingStatus,
  RevalidationResult,
  Segment,
} from "../types/api";

export type GuidedWorkflowStepId = "transcribe" | "clean" | "sections" | "layout" | "polish" | "export";

export type GuidedWorkflowStep = {
  id: GuidedWorkflowStepId;
  label: string;
  shortLabel: string;
  eyebrow: string;
  description: string;
  icon: LucideIcon;
};

export type CameraSize = "small" | "medium" | "large";

export type LayoutPreviewSettings = {
  layout: LayoutMode;
  aspectRatio: LayoutAspectRatio;
  cameraCorner: CameraCorner;
  cameraShape: CameraShape;
  cameraSize: CameraSize;
  cameraMarginPercent: number;
  transitionPreset: string;
  transitionDurationSeconds: number;
};

export const DEFAULT_LAYOUT_PREVIEW_SETTINGS: LayoutPreviewSettings = {
  layout: "picture_in_picture",
  aspectRatio: "16:9",
  cameraCorner: "bottom_right",
  cameraShape: "rounded_rectangle",
  cameraSize: "medium",
  cameraMarginPercent: 4,
  transitionPreset: "crossfade",
  transitionDurationSeconds: 0.35,
};

const DEFAULT_CAPTION_POLICY: CaptionPolicy = {
  id: "polish-default-captions",
  kind: "caption_policy",
  schema_version: "phase6.edit-plan.v2",
  status: "planned",
  enabled: true,
  appearance: "always",
  placement: "bottom_center",
  export_behavior: "sidecar",
  style: {
    font_size: 24,
    font_family: "Arial",
    primary_color: "#FFFFFF",
    outline_color: "#000000",
    outline_width: 2,
    background: "transparent",
    max_chars_per_line: 80,
    max_duration_per_cue: 5,
  },
  ranges: [],
  section_intro_seconds: 6,
  reason: "Keep captions available as SRT/VTT without forcing burn-in.",
};

const DEFAULT_ANNOTATION_STYLE = {
  font_size: 28,
  text_color: "#FFFFFF",
  background_color: "#111827",
  border_color: "#38BDF8",
  opacity: 0.88,
};

const DEFAULT_EDUCATIONAL_OVERLAY_STYLE = {
  font_size: 34,
  subtitle_font_size: 18,
  text_color: "#FFFFFF",
  subtitle_color: "#CBD5E1",
  background_color: "#111827",
  accent_color: "#FACC15",
  opacity: 0.9,
};

const DEFAULT_END_CARD_STYLE = {
  font_size: 42,
  body_font_size: 24,
  text_color: "#FFFFFF",
  body_color: "#CBD5E1",
  background_color: "#111827",
  accent_color: "#38BDF8",
  opacity: 1,
};

const DEFAULT_CALLOUT_ANIMATION: AnimationSettings = {
  preset: "pop",
  direction: "left",
  duration_seconds: 0.35,
  easing: "ease_out",
};

const DEFAULT_TITLE_CARD_ANIMATION: AnimationSettings = {
  preset: "fade",
  direction: "up",
  duration_seconds: 0.45,
  easing: "ease_out",
};

export function layoutPreviewSettingsFromCue(cue: LayoutCue | null | undefined): LayoutPreviewSettings {
  return {
    layout: cue?.layout ?? DEFAULT_LAYOUT_PREVIEW_SETTINGS.layout,
    aspectRatio: cue?.output.aspect_ratio ?? DEFAULT_LAYOUT_PREVIEW_SETTINGS.aspectRatio,
    cameraCorner: cue?.camera.corner ?? DEFAULT_LAYOUT_PREVIEW_SETTINGS.cameraCorner,
    cameraShape: cue?.camera.shape ?? DEFAULT_LAYOUT_PREVIEW_SETTINGS.cameraShape,
    cameraSize: normalizeCameraSize(cue?.camera.size),
    cameraMarginPercent: normalizeMarginPercent(cue?.camera.margin_percent),
    transitionPreset: String(cue?.timing.transition_in ?? DEFAULT_LAYOUT_PREVIEW_SETTINGS.transitionPreset),
    transitionDurationSeconds: normalizeTransitionDuration(cue?.timing.transition_duration_seconds),
  };
}

export const GUIDED_WORKFLOW_STEPS: GuidedWorkflowStep[] = [
  {
    id: "transcribe",
    label: "Transcribe",
    shortLabel: "Transcript",
    eyebrow: "Speech to text",
    description: "Confirm the generated transcript and timing are ready for editing.",
    icon: TextSelect,
  },
  {
    id: "clean",
    label: "Clean",
    shortLabel: "Cleanup",
    eyebrow: "Decision review",
    description: "Review cuts, filler words, silence, and teacher overrides.",
    icon: Scissors,
  },
  {
    id: "sections",
    label: "Sections",
    shortLabel: "Sections",
    eyebrow: "Lecture structure",
    description: "Check generated chapters and the teaching flow before layout work.",
    icon: ListChecks,
  },
  {
    id: "layout",
    label: "Layout",
    shortLabel: "Layout",
    eyebrow: "Composition",
    description: "Choose the intended screen, camera, and slide framing direction.",
    icon: SplitSquareHorizontal,
  },
  {
    id: "polish",
    label: "Polish",
    shortLabel: "Polish",
    eyebrow: "Presentation",
    description: "Prepare captions, labels, cards, transitions, and review polish.",
    icon: Sparkles,
  },
  {
    id: "export",
    label: "Export",
    shortLabel: "Export",
    eyebrow: "Delivery",
    description: "Approve the edit and download video, subtitle, chapter, and plan files.",
    icon: Download,
  },
];

type StepperProps = {
  activeStep: GuidedWorkflowStepId;
  completedStepIds: Set<GuidedWorkflowStepId>;
  onStepChange: (step: GuidedWorkflowStepId) => void;
};

type PanelProps = StepperProps & {
  videoId: string;
  segments: Segment[];
  selectedSegment: Segment | null;
  selectedAnnotationId: string | null;
  selectedEducationalOverlayId: string | null;
  plan: EditPlan | null;
  currentTime: number;
  layoutSettings: LayoutPreviewSettings;
  warnings: RevalidationResult | null;
  chapters: Chapter[];
  chaptersLoading: boolean;
  approving: boolean;
  renderStatus: ProcessingStatus | null;
  renderCancelling: boolean;
  onLayoutSettingsChange: (settings: LayoutPreviewSettings) => void;
  onPolishPlanUpdated: (plan: EditPlan) => void;
  onSelectedAnnotationChange: (annotationId: string | null) => void;
  onSelectedEducationalOverlayChange: (overlayId: string | null) => void;
  onAcceptAll: () => void;
  onCleanApplied: () => Promise<void> | void;
  onApprove: (exportPresetId?: string) => void;
  onCancelRender: () => void;
  onRefreshChapters: () => void;
  onSeekToTime: (time: number) => void;
  onUpdateAction: (segId: string, action: Segment["action"], note?: string) => void;
  onCompleteStep: (step: GuidedWorkflowStepId) => void;
  onNextStep: () => void;
  onPreviousStep: () => void;
};

export function GuidedWorkflowStepper({ activeStep, completedStepIds, onStepChange }: StepperProps) {
  const completedCount = GUIDED_WORKFLOW_STEPS.filter((step) => completedStepIds.has(step.id)).length;
  const progressPercent = Math.round((completedCount / GUIDED_WORKFLOW_STEPS.length) * 100);

  return (
    <div className="border-b border-surface-border bg-surface-raised px-4 py-3">
      <div className="mb-3 flex items-center justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-white">Guided Editor Workflow</h2>
          <p className="text-xs text-gray-400">{completedCount} of {GUIDED_WORKFLOW_STEPS.length} steps complete</p>
        </div>
        <div className="w-44">
          <div className="mb-1 flex items-center justify-between text-[11px] text-gray-400">
            <span>Progress</span>
            <span>{progressPercent}%</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-surface-overlay">
            <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${progressPercent}%` }} />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-6 gap-2">
        {GUIDED_WORKFLOW_STEPS.map((step, index) => {
          const Icon = step.icon;
          const isActive = activeStep === step.id;
          const isComplete = completedStepIds.has(step.id);

          return (
            <button
              key={step.id}
              type="button"
              onClick={() => onStepChange(step.id)}
              aria-current={isActive ? "step" : undefined}
              className={`flex min-w-0 items-center gap-2 rounded-md border px-2.5 py-2 text-left transition-colors ${
                isActive
                  ? "border-accent bg-accent/15 text-white"
                  : isComplete
                    ? "border-green-500/30 bg-green-500/10 text-gray-100 hover:bg-green-500/15"
                    : "border-surface-border bg-surface-overlay text-gray-400 hover:border-gray-500 hover:text-gray-200"
              }`}
            >
              <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded ${
                isComplete ? "bg-green-500/20 text-green-300" : isActive ? "bg-accent text-white" : "bg-surface-raised"
              }`}>
                {isComplete ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Icon className="h-3.5 w-3.5" />}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-xs font-semibold">{index + 1}. {step.label}</span>
                <span className="block truncate text-[11px] text-gray-500">{step.eyebrow}</span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function GuidedWorkflowPanel({
  activeStep,
  completedStepIds,
  videoId,
  segments,
  selectedSegment,
  selectedAnnotationId,
  selectedEducationalOverlayId,
  plan,
  currentTime,
  layoutSettings,
  warnings,
  chapters,
  chaptersLoading,
  approving,
  renderStatus,
  renderCancelling,
  onLayoutSettingsChange,
  onPolishPlanUpdated,
  onSelectedAnnotationChange,
  onSelectedEducationalOverlayChange,
  onAcceptAll,
  onCleanApplied,
  onApprove,
  onCancelRender,
  onRefreshChapters,
  onSeekToTime,
  onUpdateAction,
  onCompleteStep,
  onNextStep,
  onPreviousStep,
  onStepChange,
}: PanelProps) {
  const [cleanProfile, setCleanProfile] = useState<CleanProfileId>("conservative");
  const [cleanPreview, setCleanPreview] = useState<CleanAnalyzeResult | null>(null);
  const [cleanBusy, setCleanBusy] = useState(false);
  const [cleanMessage, setCleanMessage] = useState<string | null>(null);
  const [captionPolicy, setCaptionPolicy] = useState<CaptionPolicy>(DEFAULT_CAPTION_POLICY);
  const [captionSaving, setCaptionSaving] = useState(false);
  const [captionMessage, setCaptionMessage] = useState<string | null>(null);
  const [annotations, setAnnotations] = useState<AnnotationAction[]>([]);
  const [annotationSaving, setAnnotationSaving] = useState(false);
  const [annotationMessage, setAnnotationMessage] = useState<string | null>(null);
  const [educationalOverlays, setEducationalOverlays] = useState<EducationalOverlayAction[]>([]);
  const [educationalOverlaySaving, setEducationalOverlaySaving] = useState(false);
  const [educationalOverlayMessage, setEducationalOverlayMessage] = useState<string | null>(null);
  const [endCards, setEndCards] = useState<EndCardAction[]>([]);
  const [endCardSaving, setEndCardSaving] = useState(false);
  const [endCardMessage, setEndCardMessage] = useState<string | null>(null);
  const [exportPresetCatalog, setExportPresetCatalog] = useState<ExportPresetCatalog | null>(null);
  const [selectedExportPresetId, setSelectedExportPresetId] = useState<string>("youtube_1080p");
  const [exportPresetMessage, setExportPresetMessage] = useState<string | null>(null);

  const activeStepMeta = GUIDED_WORKFLOW_STEPS.find((step) => step.id === activeStep) ?? GUIDED_WORKFLOW_STEPS[0];
  const activeIndex = GUIDED_WORKFLOW_STEPS.findIndex((step) => step.id === activeStep);
  const isFirstStep = activeIndex === 0;
  const isLastStep = activeIndex === GUIDED_WORKFLOW_STEPS.length - 1;

  const actionCounts = useMemo(() => {
    return segments.reduce(
      (counts, segment) => {
        const action = segment.is_teacher_modified && segment.teacher_action ? segment.teacher_action : segment.action;
        counts[action] += 1;
        return counts;
      },
      { keep: 0, cut: 0, shorten: 0, highlight: 0 },
    );
  }, [segments]);

  const original = plan?.original_duration ?? 0;
  const estimated = plan?.estimated_duration ?? 0;
  const saved = Math.max(0, original - estimated);
  const warningCount = (warnings?.warnings.length ?? 0) + (warnings?.consequence_alerts.length ?? 0);
  const StepIcon = activeStepMeta.icon;
  const layoutCues = plan?.layout_cues ?? [];
  const primaryLayoutCue = layoutCues[0] ?? null;
  const exportPresets = useMemo(() => exportPresetCatalog?.groups.flatMap((group) => group.presets) ?? [], [exportPresetCatalog]);
  const selectedExportPreset =
    exportPresets.find((preset) => preset.id === selectedExportPresetId) ?? exportPresets[0] ?? null;
  const renderJob = renderStatus?.render_job ?? null;
  const renderActive = Boolean(renderJob && ["queued", "running", "cancel_requested"].includes(renderJob.status));
  const renderFailed = renderJob?.status === "failed";
  const renderCancelled = renderJob?.status === "cancelled";
  const renderComplete = renderJob?.status === "completed" || renderStatus?.status === "completed";
  const cameraEnabled = layoutUsesCamera(layoutSettings.layout);
  const updateLayoutSettings = (patch: Partial<LayoutPreviewSettings>) => {
    onLayoutSettingsChange({ ...layoutSettings, ...patch });
  };
  useEffect(() => {
    setCaptionPolicy(captionPolicyFromPlan(plan));
    setAnnotations(annotationsFromPlan(plan));
    setEducationalOverlays(educationalOverlaysFromPlan(plan));
    setEndCards(endCardsFromPlan(plan));
    setCaptionMessage(null);
    setAnnotationMessage(null);
    setEducationalOverlayMessage(null);
    setEndCardMessage(null);
  }, [plan?.polish_actions]);

  useEffect(() => {
    let cancelled = false;
    api.getExportPresets()
      .then((catalog) => {
        if (cancelled) return;
        setExportPresetCatalog(catalog);
        setSelectedExportPresetId((current) => {
          const planPreset = selectedExportPresetIdFromPlan(plan);
          const preferred = planPreset || current || catalog.default_preset_id;
          const knownIds = new Set(catalog.groups.flatMap((group) => group.presets.map((preset) => preset.id)));
          return knownIds.has(preferred) ? preferred : catalog.default_preset_id;
        });
        setExportPresetMessage(null);
      })
      .catch((error) => {
        if (!cancelled) setExportPresetMessage(`Preset catalog unavailable: ${error}`);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const planPreset = selectedExportPresetIdFromPlan(plan);
    if (planPreset) {
      setSelectedExportPresetId(planPreset);
    }
  }, [plan?.export_metadata]);

  const selectedAnnotation = annotations.find((annotation) => annotation.id === selectedAnnotationId) ?? annotations[0] ?? null;
  const selectedEducationalOverlay =
    educationalOverlays.find((overlay) => overlay.id === selectedEducationalOverlayId) ?? educationalOverlays[0] ?? null;
  const selectedEndCard = endCards[0] ?? null;

  const updateCaptionPolicyDraft = (patch: CaptionPolicyUpdate) => {
    setCaptionPolicy((prev) => ({
      ...prev,
      ...patch,
      style: { ...prev.style, ...(patch.style ?? {}) },
    }));
    setCaptionMessage(null);
  };

  const handleAnalyzeClean = async () => {
    setCleanBusy(true);
    setCleanMessage(null);
    try {
      const result = await api.analyzeCleanSuggestions(videoId, cleanProfile);
      setCleanPreview(result);
      setCleanMessage(`${result.summary.suggestions_total} suggestions found`);
    } catch (error) {
      setCleanMessage(`Clean analysis failed: ${error}`);
    } finally {
      setCleanBusy(false);
    }
  };

  const handleApplyClean = async () => {
    setCleanBusy(true);
    setCleanMessage(null);
    try {
      const result = await api.applyCleanSuggestions(videoId, cleanProfile);
      setCleanPreview({
        schema_version: result.schema_version,
        profile: result.profile,
        profiles: cleanPreview?.profiles ?? [],
        summary: result.summary,
        suggestions: result.suggestions,
      });
      await onCleanApplied();
      onCompleteStep("clean");
      setCleanMessage(
        `Applied ${result.created_transcript_cuts.length} transcript cuts and ${result.updated_segments.length} segment edits`,
      );
    } catch (error) {
      setCleanMessage(`Auto-clean failed: ${error}`);
    } finally {
      setCleanBusy(false);
    }
  };

  const handleSaveCaptionPolicy = async () => {
    setCaptionSaving(true);
    setCaptionMessage(null);
    try {
      const updatedPlan = await api.updateCaptionPolicy(videoId, {
        enabled: captionPolicy.enabled,
        appearance: captionPolicy.enabled ? captionPolicy.appearance : "off",
        placement: captionPolicy.placement,
        export_behavior: captionPolicy.enabled ? captionPolicy.export_behavior : "none",
        style: captionPolicy.style,
        ranges: captionPolicy.ranges,
        section_intro_seconds: captionPolicy.section_intro_seconds,
      });
      onPolishPlanUpdated(updatedPlan);
      onCompleteStep("polish");
      setCaptionMessage("Caption policy saved");
    } catch (error) {
      setCaptionMessage(`Caption settings failed: ${error}`);
    } finally {
      setCaptionSaving(false);
    }
  };

  const handleAddAnnotation = () => {
    const annotation = createAnnotationDraft(currentTime, plan?.original_duration ?? currentTime + 4);
    setAnnotations((prev) => [...prev, annotation]);
    onSelectedAnnotationChange(annotation.id);
    onSelectedEducationalOverlayChange(null);
    setAnnotationMessage(null);
  };

  const handleUpdateAnnotationDraft = (id: string, patch: AnnotationActionUpdate) => {
    setAnnotations((prev) => prev.map((annotation) => (
      annotation.id === id ? mergeAnnotationDraft(annotation, patch) : annotation
    )));
    setAnnotationMessage(null);
  };

  const handleDeleteAnnotation = (id: string) => {
    setAnnotations((prev) => prev.filter((annotation) => annotation.id !== id));
    if (selectedAnnotationId === id) {
      onSelectedAnnotationChange(null);
    }
    setAnnotationMessage(null);
  };

  const handleSaveAnnotations = async () => {
    setAnnotationSaving(true);
    setAnnotationMessage(null);
    try {
      const updatedPlan = await api.updateAnnotations(videoId, annotations.map(annotationForSave));
      onPolishPlanUpdated(updatedPlan);
      onCompleteStep("polish");
      setAnnotationMessage(`${annotations.length} annotations saved`);
    } catch (error) {
      setAnnotationMessage(`Annotation save failed: ${error}`);
    } finally {
      setAnnotationSaving(false);
    }
  };

  const handleAddEducationalOverlay = (overlayType: EducationalOverlayType) => {
    const overlay = createEducationalOverlayDraft(
      overlayType,
      currentTime,
      plan?.original_duration ?? currentTime + 4,
      educationalOverlays.length + 1,
    );
    setEducationalOverlays((prev) => [...prev, overlay]);
    onSelectedEducationalOverlayChange(overlay.id);
    onSelectedAnnotationChange(null);
    setEducationalOverlayMessage(null);
  };

  const handleGenerateEducationalOverlays = () => {
    const generated = createEducationalOverlaysFromChapters(chapters, plan?.original_duration ?? 0);
    setEducationalOverlays(generated);
    onSelectedEducationalOverlayChange(generated[0]?.id ?? null);
    onSelectedAnnotationChange(null);
    setEducationalOverlayMessage(`${generated.length} overlays prepared from chapters`);
  };

  const handleUpdateEducationalOverlayDraft = (id: string, patch: EducationalOverlayActionUpdate) => {
    setEducationalOverlays((prev) => prev.map((overlay) => (
      overlay.id === id ? mergeEducationalOverlayDraft(overlay, patch) : overlay
    )));
    setEducationalOverlayMessage(null);
  };

  const handleDeleteEducationalOverlay = (id: string) => {
    setEducationalOverlays((prev) => prev.filter((overlay) => overlay.id !== id));
    if (selectedEducationalOverlayId === id) {
      onSelectedEducationalOverlayChange(null);
    }
    setEducationalOverlayMessage(null);
  };

  const handleSaveEducationalOverlays = async () => {
    setEducationalOverlaySaving(true);
    setEducationalOverlayMessage(null);
    try {
      const updatedPlan = await api.updateEducationalOverlays(videoId, educationalOverlays.map(educationalOverlayForSave));
      onPolishPlanUpdated(updatedPlan);
      onCompleteStep("polish");
      setEducationalOverlayMessage(`${educationalOverlays.length} educational overlays saved`);
    } catch (error) {
      setEducationalOverlayMessage(`Educational overlays failed: ${error}`);
    } finally {
      setEducationalOverlaySaving(false);
    }
  };

  const handleCreateEndCard = (cardType: EndCardType) => {
    setEndCards([createEndCardDraft(cardType, plan?.original_duration ?? 0)]);
    setEndCardMessage(null);
  };

  const handleUpdateEndCardDraft = (id: string, patch: EndCardActionUpdate) => {
    setEndCards((prev) => prev.map((card) => (
      card.id === id ? mergeEndCardDraft(card, patch) : card
    )));
    setEndCardMessage(null);
  };

  const handleDeleteEndCard = (id: string) => {
    setEndCards((prev) => prev.filter((card) => card.id !== id));
    setEndCardMessage(null);
  };

  const handleSaveEndCards = async () => {
    setEndCardSaving(true);
    setEndCardMessage(null);
    try {
      const updatedPlan = await api.updateEndCards(videoId, endCards.map(endCardForSave));
      onPolishPlanUpdated(updatedPlan);
      onCompleteStep("polish");
      setEndCardMessage(endCards.length > 0 ? "End card saved for export" : "End card removed");
    } catch (error) {
      setEndCardMessage(`End card save failed: ${error}`);
    } finally {
      setEndCardSaving(false);
    }
  };

  return (
    <aside className="flex h-full flex-col bg-surface-raised">
      <div className="border-b border-surface-border p-4">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-accent">{activeStepMeta.eyebrow}</p>
            <h3 className="mt-1 flex items-center gap-2 text-base font-semibold text-white">
              <StepIcon className="h-4 w-4" />
              {activeStepMeta.label}
            </h3>
          </div>
          <StepStatus complete={completedStepIds.has(activeStep)} />
        </div>
        <p className="text-xs leading-5 text-gray-400">{activeStepMeta.description}</p>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {activeStep === "transcribe" && (
          <PanelStack>
            <MetricGrid>
              <Metric label="Transcript segments" value={String(segments.length)} />
              <Metric label="Source duration" value={formatDuration(original)} />
              <Metric label="Timing state" value={segments.length > 0 ? "Ready" : "Waiting"} tone={segments.length > 0 ? "good" : "muted"} />
            </MetricGrid>
            <WorkflowCard title="Transcript Review" icon={<FileText className="h-4 w-4 text-sky-300" />}>
              <p className="text-xs leading-5 text-gray-400">
                Use the transcript panel to skim sentence order, timing, and speaker content. The step is marked ready once transcript segments exist.
              </p>
            </WorkflowCard>
          </PanelStack>
        )}

        {activeStep === "clean" && (
          <PanelStack>
            <WorkflowCard title="Auto-Clean" icon={<Wand2 className="h-4 w-4 text-sky-300" />}>
              <div className="space-y-3">
                <OptionGroup
                  value={cleanProfile}
                  onChange={(value) => {
                    setCleanProfile(value as CleanProfileId);
                    setCleanPreview(null);
                    setCleanMessage(null);
                  }}
                  options={[
                    { value: "conservative", label: "Conservative", icon: SlidersHorizontal },
                    { value: "aggressive", label: "Aggressive", icon: Sparkles },
                  ]}
                />
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={handleAnalyzeClean}
                    disabled={cleanBusy}
                    className="flex items-center justify-center gap-2 rounded-md bg-surface-raised px-3 py-2 text-xs font-semibold text-gray-200 transition-colors hover:bg-surface-border disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {cleanBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                    Analyze
                  </button>
                  <button
                    type="button"
                    onClick={handleApplyClean}
                    disabled={cleanBusy}
                    className="flex items-center justify-center gap-2 rounded-md bg-accent px-3 py-2 text-xs font-semibold text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {cleanBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Scissors className="h-3.5 w-3.5" />}
                    Auto-clean
                  </button>
                </div>
                {cleanPreview && (
                  <div className="grid grid-cols-2 gap-2">
                    <MiniMetric label="Fillers" value={String(cleanPreview.summary.filler_word_count)} />
                    <MiniMetric label="Dead air" value={String(cleanPreview.summary.dead_air_count)} />
                    <MiniMetric label="Bad takes" value={String(cleanPreview.summary.bad_take_count)} />
                    <MiniMetric label="Repetition" value={String(cleanPreview.summary.repetition_suggestion_count ?? 0)} />
                  </div>
                )}
                {cleanMessage && <p className="text-xs leading-5 text-gray-400">{cleanMessage}</p>}
              </div>
            </WorkflowCard>
            <button
              type="button"
              onClick={onAcceptAll}
              className="flex w-full items-center justify-center gap-2 rounded-md bg-green-600/20 px-3 py-2.5 text-sm font-semibold text-green-300 transition-colors hover:bg-green-600/30"
            >
              <CheckCircle2 className="h-4 w-4" />
              Accept All High-Confidence
            </button>
            <MetricGrid>
              <Metric label="Keep" value={String(actionCounts.keep)} tone="good" />
              <Metric label="Cut" value={String(actionCounts.cut)} tone="danger" />
              <Metric label="Shorten" value={String(actionCounts.shorten)} />
              <Metric label="Highlight" value={String(actionCounts.highlight)} tone="warn" />
            </MetricGrid>
            <WorkflowCard title="Cleaning Signals" icon={<MessageSquareOff className="h-4 w-4 text-orange-300" />}>
              <div className="space-y-2 text-xs text-gray-300">
                <IconStat icon={<MessageSquareOff className="h-3.5 w-3.5 text-orange-300" />} label="Filler words removed" value={String(plan?.filler_words_removed ?? 0)} />
                <IconStat icon={<Volume2 className="h-3.5 w-3.5 text-blue-300" />} label="Silence removed" value={`${(plan?.silence_removed_seconds ?? 0).toFixed(1)}s`} />
                <IconStat icon={<Circle className="h-3.5 w-3.5 text-yellow-300" />} label="Open warnings" value={String(warningCount)} />
              </div>
            </WorkflowCard>
            <div className="rounded-md border border-surface-border bg-surface-overlay">
              {selectedSegment ? (
                <SegmentDetail segment={selectedSegment} onUpdateAction={onUpdateAction} />
              ) : (
                <div className="p-4 text-center text-sm text-gray-500">
                  Select a transcript or timeline segment to inspect the AI decision.
                </div>
              )}
            </div>
          </PanelStack>
        )}

        {activeStep === "sections" && (
          <PanelStack>
            <div className="flex items-center justify-between gap-3">
              <div>
                <h4 className="text-sm font-semibold text-white">Generated Chapters</h4>
                <p className="text-xs text-gray-500">{chapters.length} chapter markers found</p>
              </div>
              <button
                type="button"
                onClick={onRefreshChapters}
                className="rounded-md p-2 text-gray-400 transition-colors hover:bg-surface-overlay hover:text-gray-200"
                aria-label="Refresh chapters"
              >
                {chaptersLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              </button>
            </div>
            {chapters.length > 0 ? (
              <div className="space-y-2">
                {chapters.map((chapter, index) => (
                  <button
                    key={`${chapter.timestamp}-${chapter.segment_index}-${index}`}
                    type="button"
                    onClick={() => onSeekToTime(chapter.timestamp)}
                    className="flex w-full items-start gap-3 rounded-md border border-surface-border bg-surface-overlay px-3 py-2 text-left"
                  >
                    <span className="font-mono text-xs text-accent">{chapter.formatted}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-xs text-gray-200">{chapter.label}</span>
                      <span className="mt-1 block text-[11px] leading-4 text-gray-500">
                        {[
                          chapter.segment_count ? `${chapter.segment_count} segments` : null,
                          chapter.confidence != null ? `${Math.round(chapter.confidence * 100)}% confidence` : null,
                          chapter.boundary_reason,
                        ].filter(Boolean).join(" - ")}
                      </span>
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <EmptyState title="No chapters yet" detail="Chapters appear here after the edit plan has section markers." />
            )}
          </PanelStack>
        )}

        {activeStep === "layout" && (
          <PanelStack>
            <WorkflowCard title="Layout Style" icon={<SplitSquareHorizontal className="h-4 w-4 text-blue-300" />}>
              <OptionGroup
                value={layoutSettings.layout}
                onChange={(value) => updateLayoutSettings({ layout: value as LayoutMode })}
                options={[
                  { value: "picture_in_picture", label: "Picture-in-picture", icon: MonitorPlay },
                  { value: "side_by_side", label: "Side by side", icon: SplitSquareHorizontal },
                  { value: "full_screen_source", label: "Full screen", icon: Layers },
                  { value: "full_camera_source", label: "Full camera", icon: Film },
                ]}
              />
            </WorkflowCard>

            <WorkflowCard title="Output Aspect" icon={<MonitorPlay className="h-4 w-4 text-sky-300" />}>
              <ChoiceGrid
                value={layoutSettings.aspectRatio}
                onChange={(value) => updateLayoutSettings({ aspectRatio: value as LayoutAspectRatio })}
                options={[
                  { value: "16:9", label: "16:9", detail: "YouTube, LMS" },
                  { value: "4:3", label: "4:3", detail: "Classic slides" },
                  { value: "1:1", label: "1:1", detail: "Square clip" },
                  { value: "9:16", label: "9:16", detail: "Vertical" },
                ]}
              />
            </WorkflowCard>

            <WorkflowCard title="Camera Position" icon={<Film className="h-4 w-4 text-green-300" />}>
              <div className="space-y-3">
                <ChoiceGrid
                  value={layoutSettings.cameraCorner}
                  onChange={(value) => updateLayoutSettings({ cameraCorner: value as CameraCorner })}
                  disabled={!cameraEnabled}
                  options={[
                    { value: "top_left", label: "Top left", detail: "Slides bottom-right clear" },
                    { value: "top_right", label: "Top right", detail: "Common lecture frame" },
                    { value: "bottom_left", label: "Bottom left", detail: "Presenter near captions" },
                    { value: "bottom_right", label: "Bottom right", detail: "Default PiP" },
                  ]}
                />
                <SliderControl
                  label="Inset margin"
                  value={layoutSettings.cameraMarginPercent}
                  min={2}
                  max={8}
                  step={1}
                  suffix="%"
                  disabled={!cameraEnabled}
                  onChange={(value) => updateLayoutSettings({ cameraMarginPercent: value })}
                />
              </div>
            </WorkflowCard>

            <WorkflowCard title="Camera Shape" icon={<Circle className="h-4 w-4 text-yellow-300" />}>
              <div className="space-y-3">
                <ChoiceGrid
                  value={layoutSettings.cameraShape}
                  onChange={(value) => updateLayoutSettings({ cameraShape: value as CameraShape })}
                  disabled={!cameraEnabled}
                  options={[
                    { value: "rectangle", label: "Rectangle", detail: "Maximum image area" },
                    { value: "rounded_rectangle", label: "Rounded", detail: "Soft inset" },
                    { value: "circle", label: "Circle", detail: "Headshot crop" },
                  ]}
                />
                <ChoiceGrid
                  value={layoutSettings.cameraSize}
                  onChange={(value) => updateLayoutSettings({ cameraSize: value as CameraSize })}
                  disabled={!cameraEnabled}
                  options={[
                    { value: "small", label: "Small", detail: "18% frame" },
                    { value: "medium", label: "Medium", detail: "24% frame" },
                    { value: "large", label: "Large", detail: "31% frame" },
                  ]}
                />
              </div>
            </WorkflowCard>

            <WorkflowCard title="Preview Cue" icon={<Layers className="h-4 w-4 text-purple-300" />}>
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-2">
                  <MiniMetric label="Plan cues" value={String(layoutCues.length)} />
                  <MiniMetric label="Camera" value={cameraEnabled ? "On" : "Off"} />
                  <MiniMetric label="Aspect" value={layoutSettings.aspectRatio} />
                  <MiniMetric label="Status" value={primaryLayoutCue?.status ?? "Preview"} />
                </div>
                {primaryLayoutCue?.reason ? (
                  <p className="text-xs leading-5 text-gray-400">{primaryLayoutCue.reason}</p>
                ) : (
                  <p className="text-xs leading-5 text-gray-400">
                    No planned layout cue is attached to this edit plan yet.
                  </p>
                )}
              </div>
            </WorkflowCard>
            <WorkflowCard title="Layout Transitions" icon={<Sparkles className="h-4 w-4 text-sky-300" />}>
              <div className="space-y-3">
                <ChoiceGrid
                  value={layoutSettings.transitionPreset}
                  onChange={(value) => updateLayoutSettings({ transitionPreset: value })}
                  options={[
                    { value: "crossfade", label: "Crossfade", detail: "Smooth layout change" },
                    { value: "fade", label: "Fade", detail: "Gentle section reset" },
                    { value: "wipe_left", label: "Wipe", detail: "Slide-led topic shift" },
                    { value: "cut", label: "Cut", detail: "Instant switch" },
                  ]}
                />
                <SliderControl
                  label="Transition duration"
                  value={layoutSettings.transitionDurationSeconds}
                  min={0}
                  max={1}
                  step={0.05}
                  suffix="s"
                  onChange={(value) => updateLayoutSettings({ transitionDurationSeconds: value })}
                />
                <p className="text-xs leading-5 text-gray-500">
                  Current plan default: {primaryLayoutCue?.timing.transition_in ?? "crossfade"}.
                </p>
              </div>
            </WorkflowCard>
          </PanelStack>
        )}

        {activeStep === "polish" && (
          <PanelStack>
            <ToggleRow
              label="Selective captions"
              detail="Control where captions appear and how they export."
              checked={captionPolicy.enabled}
              icon={<Captions className="h-4 w-4 text-sky-300" />}
              onChange={(checked) => updateCaptionPolicyDraft({
                enabled: checked,
                appearance: checked ? captionPolicy.appearance === "off" ? "always" : captionPolicy.appearance : "off",
                export_behavior: checked ? captionPolicy.export_behavior === "none" ? "sidecar" : captionPolicy.export_behavior : "none",
              })}
            />
            <WorkflowCard title="Caption Timing" icon={<TextSelect className="h-4 w-4 text-sky-300" />}>
              <ChoiceGrid
                value={captionPolicy.appearance}
                onChange={(value) => updateCaptionPolicyDraft({ appearance: value as CaptionAppearance, enabled: value !== "off" })}
                options={[
                  { value: "always", label: "Full edit", detail: "Caption every kept range" },
                  { value: "highlight_segments", label: "Highlights", detail: "Only highlighted segments" },
                  { value: "section_starts", label: "Section starts", detail: "First seconds per topic" },
                  { value: "off", label: "Off", detail: "No caption output" },
                ]}
              />
              {captionPolicy.appearance === "section_starts" && (
                <div className="mt-3">
                  <SliderControl
                    label="Section caption window"
                    value={captionPolicy.section_intro_seconds}
                    min={2}
                    max={12}
                    step={1}
                    suffix="s"
                    onChange={(value) => updateCaptionPolicyDraft({ section_intro_seconds: value })}
                  />
                </div>
              )}
            </WorkflowCard>
            <WorkflowCard title="Placement" icon={<Captions className="h-4 w-4 text-green-300" />}>
              <ChoiceGrid
                value={captionPolicy.placement}
                onChange={(value) => updateCaptionPolicyDraft({ placement: value as CaptionPlacement })}
                disabled={!captionPolicy.enabled}
                options={[
                  { value: "bottom_center", label: "Bottom", detail: "Standard subtitle position" },
                  { value: "top_center", label: "Top", detail: "Keeps slide footer clear" },
                  { value: "bottom_left", label: "Lower left", detail: "Avoids lower-right camera" },
                  { value: "bottom_right", label: "Lower right", detail: "Avoids lower-left camera" },
                ]}
              />
            </WorkflowCard>
            <WorkflowCard title="Export Behavior" icon={<Download className="h-4 w-4 text-yellow-300" />}>
              <ChoiceGrid
                value={captionPolicy.export_behavior}
                onChange={(value) => updateCaptionPolicyDraft({ export_behavior: value as CaptionExportBehavior, enabled: value !== "none" })}
                options={[
                  { value: "sidecar", label: "Sidecar", detail: "SRT and VTT files" },
                  { value: "burn_in", label: "Burn in", detail: "Captions in MP4" },
                  { value: "sidecar_and_burn_in", label: "Both", detail: "Files and hard captions" },
                  { value: "none", label: "None", detail: "No caption artifacts" },
                ]}
              />
            </WorkflowCard>
            <WorkflowCard title="Caption Style" icon={<Palette className="h-4 w-4 text-pink-300" />}>
              <div className="space-y-3">
                <SliderControl
                  label="Font size"
                  value={captionPolicy.style.font_size}
                  min={16}
                  max={40}
                  step={2}
                  suffix="px"
                  disabled={!captionPolicy.enabled}
                  onChange={(value) => updateCaptionPolicyDraft({ style: { font_size: value } })}
                />
                <ChoiceGrid
                  value={captionPolicy.style.background}
                  onChange={(value) => updateCaptionPolicyDraft({ style: { background: value as "transparent" | "box" } })}
                  disabled={!captionPolicy.enabled}
                  options={[
                    { value: "transparent", label: "Outline", detail: "Clean subtitle edge" },
                    { value: "box", label: "Box", detail: "Maximum readability" },
                  ]}
                />
              </div>
            </WorkflowCard>
            <button
              type="button"
              onClick={handleSaveCaptionPolicy}
              disabled={captionSaving}
              className="flex w-full items-center justify-center gap-2 rounded-md bg-accent px-3 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
            >
              {captionSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
              Save Caption Policy
            </button>
            {captionMessage && <p className="text-xs leading-5 text-gray-400">{captionMessage}</p>}
            <WorkflowCard title="Annotations & Callouts" icon={<MessageSquare className="h-4 w-4 text-sky-300" />}>
              <div className="space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-xs text-gray-400">{annotations.length} timeline items</div>
                  <button
                    type="button"
                    onClick={handleAddAnnotation}
                    className="flex items-center gap-1.5 rounded-md bg-surface-raised px-2.5 py-1.5 text-xs font-semibold text-gray-200 transition-colors hover:bg-surface-border"
                  >
                    <Plus className="h-3.5 w-3.5" />
                    Add
                  </button>
                </div>

                {annotations.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {annotations.map((annotation) => (
                      <button
                        key={annotation.id}
                        type="button"
                        onClick={() => {
                          onSelectedAnnotationChange(annotation.id);
                          onSelectedEducationalOverlayChange(null);
                        }}
                        className={`rounded px-2 py-1 text-[11px] font-semibold transition-colors ${
                          selectedAnnotation?.id === annotation.id
                            ? "bg-accent text-white"
                            : "bg-surface-raised text-gray-400 hover:text-gray-200"
                        }`}
                      >
                        {formatDuration(annotation.start_time)}
                      </button>
                    ))}
                  </div>
                )}

                {selectedAnnotation ? (
                  <div className="space-y-3 rounded-md border border-surface-border bg-surface-raised p-3">
                    <div className="flex items-center justify-between gap-3">
                      <OptionGroup
                        value={selectedAnnotation.annotation_type}
                        onChange={(value) => handleUpdateAnnotationDraft(selectedAnnotation.id, {
                          annotation_type: value as AnnotationType,
                          pointer: { enabled: value === "callout" },
                        })}
                        options={[
                          { value: "callout", label: "Callout", icon: Crosshair },
                          { value: "label", label: "Label", icon: MessageSquare },
                        ]}
                      />
                      <button
                        type="button"
                        onClick={() => handleDeleteAnnotation(selectedAnnotation.id)}
                        className="rounded-md p-2 text-gray-500 transition-colors hover:bg-red-500/10 hover:text-red-300"
                        aria-label="Delete annotation"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>

                    <label className="block">
                      <span className="mb-1 block text-xs font-medium text-gray-400">Text</span>
                      <input
                        value={selectedAnnotation.text}
                        onChange={(event) => handleUpdateAnnotationDraft(selectedAnnotation.id, { text: event.target.value })}
                        className="w-full rounded-md border border-surface-border bg-surface-overlay px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent"
                      />
                    </label>

                    <div className="grid grid-cols-2 gap-2">
                      <NumberField
                        label="Start"
                        value={selectedAnnotation.start_time}
                        min={0}
                        step={0.5}
                        suffix="s"
                        onChange={(value) => handleUpdateAnnotationDraft(selectedAnnotation.id, {
                          start_time: value,
                          end_time: Math.max(value + 0.5, selectedAnnotation.end_time),
                        })}
                      />
                      <NumberField
                        label="End"
                        value={selectedAnnotation.end_time}
                        min={selectedAnnotation.start_time + 0.5}
                        step={0.5}
                        suffix="s"
                        onChange={(value) => handleUpdateAnnotationDraft(selectedAnnotation.id, { end_time: value })}
                      />
                    </div>

                    <ChoiceGrid
                      value={selectedAnnotation.position}
                      onChange={(value) => handleUpdateAnnotationDraft(selectedAnnotation.id, annotationPositionPatch(value as AnnotationPosition))}
                      options={[
                        { value: "top_left", label: "Top left", detail: "Upper slide note" },
                        { value: "top_right", label: "Top right", detail: "Default callout" },
                        { value: "middle_left", label: "Mid left", detail: "Side emphasis" },
                        { value: "middle_right", label: "Mid right", detail: "Side emphasis" },
                        { value: "bottom_left", label: "Low left", detail: "Lower note" },
                        { value: "bottom_right", label: "Low right", detail: "Lower note" },
                      ]}
                    />

                    <div className="grid grid-cols-2 gap-2">
                      <NumberField
                        label="X"
                        value={selectedAnnotation.x_percent}
                        min={2}
                        max={98}
                        step={1}
                        suffix="%"
                        onChange={(value) => handleUpdateAnnotationDraft(selectedAnnotation.id, { x_percent: value })}
                      />
                      <NumberField
                        label="Y"
                        value={selectedAnnotation.y_percent}
                        min={2}
                        max={98}
                        step={1}
                        suffix="%"
                        onChange={(value) => handleUpdateAnnotationDraft(selectedAnnotation.id, { y_percent: value })}
                      />
                    </div>

                    <ChoiceGrid
                      value={selectedAnnotation.pointer.direction}
                      onChange={(value) => handleUpdateAnnotationDraft(selectedAnnotation.id, { pointer: { direction: value } })}
                      disabled={!selectedAnnotation.pointer.enabled}
                      options={[
                        { value: "left", label: "Left", detail: "Points left" },
                        { value: "right", label: "Right", detail: "Points right" },
                        { value: "up", label: "Up", detail: "Points up" },
                        { value: "down", label: "Down", detail: "Points down" },
                      ]}
                    />

                    <ChoiceGrid
                      value={selectedAnnotation.animation.preset}
                      onChange={(value) => handleUpdateAnnotationDraft(selectedAnnotation.id, annotationAnimationPatch(value as AnimationPreset))}
                      options={[
                        { value: "pop", label: "Pop", detail: "Quick emphasis" },
                        { value: "fade", label: "Fade", detail: "Subtle reveal" },
                        { value: "slide_left", label: "Slide", detail: "Moves into view" },
                        { value: "none", label: "None", detail: "Static overlay" },
                      ]}
                    />
                    <SliderControl
                      label="Animation duration"
                      value={selectedAnnotation.animation.duration_seconds}
                      min={0}
                      max={1}
                      step={0.05}
                      suffix="s"
                      onChange={(value) => handleUpdateAnnotationDraft(selectedAnnotation.id, { animation: { duration_seconds: value } })}
                      disabled={selectedAnnotation.animation.preset === "none"}
                    />
                  </div>
                ) : (
                  <EmptyState title="No callouts yet" detail="Add one at the current playhead time." />
                )}

                <button
                  type="button"
                  onClick={handleSaveAnnotations}
                  disabled={annotationSaving}
                  className="flex w-full items-center justify-center gap-2 rounded-md bg-accent px-3 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {annotationSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                  Save Callouts
                </button>
                {annotationMessage && <p className="text-xs leading-5 text-gray-400">{annotationMessage}</p>}
              </div>
            </WorkflowCard>
            <WorkflowCard title="Educational Labels & Cards" icon={<ListChecks className="h-4 w-4 text-amber-300" />}>
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={handleGenerateEducationalOverlays}
                    className="flex items-center justify-center gap-2 rounded-md bg-surface-raised px-3 py-2 text-xs font-semibold text-gray-200 transition-colors hover:bg-surface-border"
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                    From chapters
                  </button>
                  <button
                    type="button"
                    onClick={() => handleAddEducationalOverlay("intro_card")}
                    className="flex items-center justify-center gap-2 rounded-md bg-surface-raised px-3 py-2 text-xs font-semibold text-gray-200 transition-colors hover:bg-surface-border"
                  >
                    <Plus className="h-3.5 w-3.5" />
                    Intro card
                  </button>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  {[
                    { value: "section_title_card", label: "Section" },
                    { value: "chapter_label", label: "Chapter" },
                    { value: "step_label", label: "Step" },
                  ].map((item) => (
                    <button
                      key={item.value}
                      type="button"
                      onClick={() => handleAddEducationalOverlay(item.value as EducationalOverlayType)}
                      className="rounded-md bg-surface-raised px-2 py-2 text-xs font-semibold text-gray-300 transition-colors hover:bg-surface-border"
                    >
                      {item.label}
                    </button>
                  ))}
                </div>

                {educationalOverlays.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {educationalOverlays.map((overlay) => (
                      <button
                        key={overlay.id}
                        type="button"
                        onClick={() => {
                          onSelectedEducationalOverlayChange(overlay.id);
                          onSelectedAnnotationChange(null);
                        }}
                        className={`rounded px-2 py-1 text-[11px] font-semibold transition-colors ${
                          selectedEducationalOverlay?.id === overlay.id
                            ? "bg-amber-400 text-gray-950"
                            : "bg-surface-raised text-gray-400 hover:text-gray-200"
                        }`}
                      >
                        {formatDuration(overlay.start_time)}
                      </button>
                    ))}
                  </div>
                )}

                {selectedEducationalOverlay ? (
                  <div className="space-y-3 rounded-md border border-surface-border bg-surface-raised p-3">
                    <div className="flex items-center justify-between gap-3">
                      <ChoiceGrid
                        value={selectedEducationalOverlay.overlay_type}
                        onChange={(value) => handleUpdateEducationalOverlayDraft(
                          selectedEducationalOverlay.id,
                          educationalOverlayTypePatch(value as EducationalOverlayType),
                        )}
                        options={[
                          { value: "intro_card", label: "Intro", detail: "Opening title" },
                          { value: "section_title_card", label: "Section", detail: "Topic card" },
                          { value: "chapter_label", label: "Chapter", detail: "Corner marker" },
                          { value: "step_label", label: "Step", detail: "Procedure badge" },
                        ]}
                      />
                      <button
                        type="button"
                        onClick={() => handleDeleteEducationalOverlay(selectedEducationalOverlay.id)}
                        className="rounded-md p-2 text-gray-500 transition-colors hover:bg-red-500/10 hover:text-red-300"
                        aria-label="Delete educational overlay"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>

                    <label className="block">
                      <span className="mb-1 block text-xs font-medium text-gray-400">Title</span>
                      <input
                        value={selectedEducationalOverlay.title}
                        onChange={(event) => handleUpdateEducationalOverlayDraft(selectedEducationalOverlay.id, { title: event.target.value })}
                        className="w-full rounded-md border border-surface-border bg-surface-overlay px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent"
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-xs font-medium text-gray-400">Subtitle</span>
                      <input
                        value={selectedEducationalOverlay.subtitle}
                        onChange={(event) => handleUpdateEducationalOverlayDraft(selectedEducationalOverlay.id, { subtitle: event.target.value })}
                        className="w-full rounded-md border border-surface-border bg-surface-overlay px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent"
                      />
                    </label>

                    <div className="grid grid-cols-2 gap-2">
                      <NumberField
                        label="Start"
                        value={selectedEducationalOverlay.start_time}
                        min={0}
                        step={0.5}
                        suffix="s"
                        onChange={(value) => handleUpdateEducationalOverlayDraft(selectedEducationalOverlay.id, {
                          start_time: value,
                          end_time: Math.max(value + 0.5, selectedEducationalOverlay.end_time),
                        })}
                      />
                      <NumberField
                        label="End"
                        value={selectedEducationalOverlay.end_time}
                        min={selectedEducationalOverlay.start_time + 0.5}
                        step={0.5}
                        suffix="s"
                        onChange={(value) => handleUpdateEducationalOverlayDraft(selectedEducationalOverlay.id, { end_time: value })}
                      />
                    </div>

                    <ChoiceGrid
                      value={selectedEducationalOverlay.position}
                      onChange={(value) => handleUpdateEducationalOverlayDraft(
                        selectedEducationalOverlay.id,
                        educationalOverlayPositionPatch(value as EducationalOverlayPosition),
                      )}
                      options={[
                        { value: "center", label: "Center", detail: "Title card" },
                        { value: "top_left", label: "Top left", detail: "Badge" },
                        { value: "top_center", label: "Top", detail: "Header" },
                        { value: "top_right", label: "Top right", detail: "Badge" },
                        { value: "bottom_left", label: "Low left", detail: "Footer" },
                        { value: "bottom_right", label: "Low right", detail: "Footer" },
                      ]}
                    />

                    <div className="grid grid-cols-2 gap-2">
                      <NumberField
                        label="Step"
                        value={selectedEducationalOverlay.step_number ?? 1}
                        min={1}
                        step={1}
                        suffix=""
                        onChange={(value) => handleUpdateEducationalOverlayDraft(selectedEducationalOverlay.id, { step_number: Math.max(1, Math.round(value)) })}
                      />
                      <SliderControl
                        label="Text size"
                        value={selectedEducationalOverlay.style.font_size}
                        min={18}
                        max={56}
                        step={2}
                        suffix="px"
                        onChange={(value) => handleUpdateEducationalOverlayDraft(selectedEducationalOverlay.id, { style: { font_size: value } })}
                      />
                    </div>

                    <ChoiceGrid
                      value={selectedEducationalOverlay.animation.preset}
                      onChange={(value) => handleUpdateEducationalOverlayDraft(
                        selectedEducationalOverlay.id,
                        educationalOverlayAnimationPatch(value as AnimationPreset, selectedEducationalOverlay.overlay_type),
                      )}
                      options={[
                        { value: "fade", label: "Fade", detail: "Section start" },
                        { value: "slide_up", label: "Slide", detail: "Title motion" },
                        { value: "zoom", label: "Zoom", detail: "Card emphasis" },
                        { value: "none", label: "None", detail: "Static label" },
                      ]}
                    />
                    <SliderControl
                      label="Animation duration"
                      value={selectedEducationalOverlay.animation.duration_seconds}
                      min={0}
                      max={1.25}
                      step={0.05}
                      suffix="s"
                      onChange={(value) => handleUpdateEducationalOverlayDraft(selectedEducationalOverlay.id, { animation: { duration_seconds: value } })}
                      disabled={selectedEducationalOverlay.animation.preset === "none"}
                    />
                  </div>
                ) : (
                  <EmptyState title="No educational overlays yet" detail="Generate labels from chapters or add one at the current playhead." />
                )}

                <button
                  type="button"
                  onClick={handleSaveEducationalOverlays}
                  disabled={educationalOverlaySaving}
                  className="flex w-full items-center justify-center gap-2 rounded-md bg-accent px-3 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {educationalOverlaySaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                  Save Educational Overlays
                </button>
                {educationalOverlayMessage && <p className="text-xs leading-5 text-gray-400">{educationalOverlayMessage}</p>}
              </div>
            </WorkflowCard>
            <WorkflowCard title="End Card / CTA" icon={<ExternalLink className="h-4 w-4 text-cyan-300" />}>
              <div className="space-y-3">
                <ChoiceGrid
                  value={selectedEndCard?.card_type ?? "lecture_summary"}
                  onChange={(value) => {
                    if (selectedEndCard) {
                      handleUpdateEndCardDraft(selectedEndCard.id, endCardTypePatch(value as EndCardType));
                    } else {
                      handleCreateEndCard(value as EndCardType);
                    }
                  }}
                  options={[
                    { value: "lecture_summary", label: "Summary", detail: "Key takeaways" },
                    { value: "next_topic", label: "Next topic", detail: "Preview lesson" },
                    { value: "course_link", label: "Course link", detail: "Resource CTA" },
                    { value: "custom_message", label: "Custom", detail: "Closing note" },
                  ]}
                />

                {!selectedEndCard ? (
                  <button
                    type="button"
                    onClick={() => handleCreateEndCard("lecture_summary")}
                    className="flex w-full items-center justify-center gap-2 rounded-md bg-surface-raised px-3 py-2 text-sm font-semibold text-gray-200 transition-colors hover:bg-surface-border"
                  >
                    <Plus className="h-4 w-4" />
                    Add End Card
                  </button>
                ) : (
                  <div className="space-y-3 rounded-md border border-surface-border bg-surface-raised p-3">
                    <div className="flex items-center justify-between gap-3">
                      <ToggleRow
                        label="Append to export"
                        detail="Adds a silent CTA card after the edited lecture."
                        checked={selectedEndCard.enabled}
                        icon={<ExternalLink className="h-4 w-4 text-cyan-300" />}
                        onChange={(checked) => handleUpdateEndCardDraft(selectedEndCard.id, { enabled: checked })}
                      />
                      <button
                        type="button"
                        onClick={() => handleDeleteEndCard(selectedEndCard.id)}
                        className="rounded-md p-2 text-gray-500 transition-colors hover:bg-red-500/10 hover:text-red-300"
                        aria-label="Delete end card"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>

                    <label className="block">
                      <span className="mb-1 block text-xs font-medium text-gray-400">Title</span>
                      <input
                        value={selectedEndCard.title}
                        onChange={(event) => handleUpdateEndCardDraft(selectedEndCard.id, { title: event.target.value })}
                        className="w-full rounded-md border border-surface-border bg-surface-overlay px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent"
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-xs font-medium text-gray-400">Message</span>
                      <textarea
                        value={selectedEndCard.message}
                        onChange={(event) => handleUpdateEndCardDraft(selectedEndCard.id, { message: event.target.value })}
                        rows={3}
                        className="w-full resize-none rounded-md border border-surface-border bg-surface-overlay px-3 py-2 text-sm leading-5 text-gray-100 outline-none focus:border-accent"
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-xs font-medium text-gray-400">Summary points</span>
                      <textarea
                        value={selectedEndCard.summary_points.join("\n")}
                        onChange={(event) => handleUpdateEndCardDraft(selectedEndCard.id, {
                          summary_points: event.target.value.split("\n").map((line) => line.trim()).filter(Boolean).slice(0, 5),
                        })}
                        rows={3}
                        className="w-full resize-none rounded-md border border-surface-border bg-surface-overlay px-3 py-2 text-sm leading-5 text-gray-100 outline-none focus:border-accent"
                      />
                    </label>

                    <div className="grid grid-cols-2 gap-2">
                      <label className="block">
                        <span className="mb-1 block text-xs font-medium text-gray-400">Next topic</span>
                        <input
                          value={selectedEndCard.next_topic}
                          onChange={(event) => handleUpdateEndCardDraft(selectedEndCard.id, { next_topic: event.target.value })}
                          className="w-full rounded-md border border-surface-border bg-surface-overlay px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent"
                        />
                      </label>
                      <label className="block">
                        <span className="mb-1 block text-xs font-medium text-gray-400">Button text</span>
                        <input
                          value={selectedEndCard.button_text}
                          onChange={(event) => handleUpdateEndCardDraft(selectedEndCard.id, { button_text: event.target.value })}
                          className="w-full rounded-md border border-surface-border bg-surface-overlay px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent"
                        />
                      </label>
                    </div>
                    <label className="block">
                      <span className="mb-1 block text-xs font-medium text-gray-400">Course link</span>
                      <input
                        value={selectedEndCard.course_url}
                        onChange={(event) => handleUpdateEndCardDraft(selectedEndCard.id, { course_url: event.target.value })}
                        className="w-full rounded-md border border-surface-border bg-surface-overlay px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent"
                      />
                    </label>

                    <div className="grid grid-cols-2 gap-2">
                      <SliderControl
                        label="Duration"
                        value={selectedEndCard.duration_seconds}
                        min={2}
                        max={15}
                        step={0.5}
                        suffix="s"
                        onChange={(value) => handleUpdateEndCardDraft(selectedEndCard.id, { duration_seconds: value })}
                      />
                      <SliderControl
                        label="Title size"
                        value={selectedEndCard.style.font_size}
                        min={28}
                        max={60}
                        step={2}
                        suffix="px"
                        onChange={(value) => handleUpdateEndCardDraft(selectedEndCard.id, { style: { font_size: value } })}
                      />
                    </div>
                  </div>
                )}

                <button
                  type="button"
                  onClick={handleSaveEndCards}
                  disabled={endCardSaving}
                  className="flex w-full items-center justify-center gap-2 rounded-md bg-accent px-3 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {endCardSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                  Save End Card
                </button>
                {endCardMessage && <p className="text-xs leading-5 text-gray-400">{endCardMessage}</p>}
              </div>
            </WorkflowCard>
          </PanelStack>
        )}

        {activeStep === "export" && (
          <PanelStack>
            <MetricGrid>
              <Metric label="Original" value={formatDuration(original)} />
              <Metric label="Estimated" value={formatDuration(estimated)} tone="good" />
              <Metric label="Saved" value={formatDuration(saved)} tone="warn" />
            </MetricGrid>
            <WorkflowCard title="Export Preset" icon={<Download className="h-4 w-4 text-green-300" />}>
              <div className="space-y-4">
                {exportPresetCatalog ? (
                  exportPresetCatalog.groups.map((group) => (
                    <div key={group.id} className="space-y-2">
                      <div className="flex items-center justify-between gap-3">
                        <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-400">{group.label}</h4>
                        <span className="text-[11px] text-gray-500">{group.presets.length} presets</span>
                      </div>
                      <div className="grid gap-2">
                        {group.presets.map((preset) => (
                          <ExportPresetButton
                            key={preset.id}
                            preset={preset}
                            selected={preset.id === selectedExportPresetId}
                            onSelect={() => {
                              setSelectedExportPresetId(preset.id);
                              setExportPresetMessage(null);
                            }}
                          />
                        ))}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="flex items-center gap-2 rounded-md border border-surface-border bg-surface-overlay px-3 py-2 text-sm text-gray-300">
                    <Loader2 className="h-4 w-4 animate-spin text-accent" />
                    Loading presets
                  </div>
                )}
                {selectedExportPreset && (
                  <div className="rounded-md border border-green-500/30 bg-green-500/10 px-3 py-2 text-xs leading-5 text-green-100">
                    Selected: {selectedExportPreset.label} - {exportPresetSummary(selectedExportPreset)}
                  </div>
                )}
                {exportPresetMessage && <p className="text-xs leading-5 text-yellow-200">{exportPresetMessage}</p>}
              </div>
            </WorkflowCard>
            {(renderActive || renderFailed || renderCancelled) && (
              <RenderProgressCard
                status={renderStatus}
                onCancel={onCancelRender}
                cancelling={renderCancelling}
              />
            )}
            {!plan?.is_approved ? (
              <button
                type="button"
                onClick={() => onApprove(selectedExportPreset?.id ?? selectedExportPresetId)}
                disabled={approving || !plan}
                className="flex w-full items-center justify-center gap-2 rounded-md bg-accent px-3 py-3 text-sm font-semibold text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
              >
                {approving ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                {approving ? "Rendering..." : `Approve & Render ${selectedExportPreset?.label ?? "Video"}`}
              </button>
            ) : renderComplete ? (
              <div className="space-y-2">
                <DownloadLink
                  href={api.getVideoDownloadUrl(videoId)}
                  label={selectedExportPreset?.audio_only ? "Lecture Audio (M4A)" : "Edited Video (MP4)"}
                  primary
                />
                <DownloadLink href={api.getSubtitleDownloadUrl(videoId)} label="Subtitles (SRT)" />
                <DownloadLink href={api.getSubtitleVttUrl(videoId)} label="Subtitles (VTT)" />
                <DownloadLink href={api.getChaptersDownloadUrl(videoId)} label="Chapter Markers" />
                <DownloadLink href={api.getPlanExportUrl(videoId)} label="Edit Plan (JSON)" />
                <DownloadLink href={api.getQualityReportExportUrl(videoId)} label="Quality Report (JSON)" />
                <DownloadLink href={api.getAcademicEvidenceExportUrl(videoId)} label="Academic Evidence (JSON)" />
                <DownloadLink href={api.getAcademicEvidenceSummaryUrl(videoId)} label="Evidence Summary (Markdown)" />
                <DownloadLink href={api.getBeforeAfterComparisonUrl(videoId)} label="Before/After Comparison" />
                <DownloadLink href={api.getTimelineDecisionsUrl(videoId)} label="Timeline Decisions (CSV)" />
                <DownloadLink href={api.getProviderModeTraceUrl(videoId)} label="Provider Mode Trace" />
                <DownloadLink href={api.getMetricsSummaryUrl(videoId)} label="Metrics Summary" />
                <DownloadLink href={api.getAcademicEvidenceBundleUrl(videoId)} label="Evidence Bundle (ZIP)" />
              </div>
            ) : renderActive ? null : (
              <button
                type="button"
                onClick={() => onApprove(selectedExportPreset?.id ?? selectedExportPresetId)}
                disabled={approving || !plan}
                className="flex w-full items-center justify-center gap-2 rounded-md bg-accent px-3 py-3 text-sm font-semibold text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
              >
                {approving ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                {approving ? "Starting render..." : `Render ${selectedExportPreset?.label ?? "Video"}`}
              </button>
            )}
            {plan?.is_approved && !renderActive && !renderFailed && !renderCancelled && !renderComplete && (
              <div className="rounded-md border border-surface-border bg-surface-overlay px-3 py-2 text-xs leading-5 text-gray-300">
                Render status is unavailable. Start a new render when ready.
              </div>
            )}
          </PanelStack>
        )}
      </div>

      <div className="border-t border-surface-border p-3">
        <div className="mb-3 grid grid-cols-6 gap-1">
          {GUIDED_WORKFLOW_STEPS.map((step) => (
            <button
              key={step.id}
              type="button"
              onClick={() => onStepChange(step.id)}
              className={`h-1.5 rounded-full transition-colors ${
                activeStep === step.id || completedStepIds.has(step.id) ? "bg-accent" : "bg-surface-overlay"
              }`}
              aria-label={`Go to ${step.label}`}
            />
          ))}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onPreviousStep}
            disabled={isFirstStep}
            className="flex h-9 w-9 items-center justify-center rounded-md bg-surface-overlay text-gray-300 transition-colors hover:bg-surface-border disabled:cursor-not-allowed disabled:opacity-40"
            aria-label="Previous step"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => onCompleteStep(activeStep)}
            className="flex-1 rounded-md bg-surface-overlay px-3 py-2 text-xs font-semibold text-gray-200 transition-colors hover:bg-surface-border"
          >
            Mark {activeStepMeta.shortLabel} Complete
          </button>
          <button
            type="button"
            onClick={onNextStep}
            disabled={isLastStep}
            className="flex h-9 w-9 items-center justify-center rounded-md bg-accent text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40"
            aria-label="Next step"
          >
            <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      </div>
    </aside>
  );
}

function StepStatus({ complete }: { complete: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] font-semibold ${
      complete ? "bg-green-500/15 text-green-300" : "bg-surface-overlay text-gray-400"
    }`}>
      {complete ? <CheckCircle2 className="h-3 w-3" /> : <Circle className="h-3 w-3" />}
      {complete ? "Complete" : "In progress"}
    </span>
  );
}

function PanelStack({ children }: { children: ReactNode }) {
  return <div className="space-y-4">{children}</div>;
}

function WorkflowCard({ title, icon, children }: { title: string; icon: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-md border border-surface-border bg-surface-overlay p-3">
      <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold text-white">
        {icon}
        {title}
      </h4>
      {children}
    </section>
  );
}

function MetricGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-3 gap-2">{children}</div>;
}

function Metric({ label, value, tone = "muted" }: { label: string; value: string; tone?: "muted" | "good" | "warn" | "danger" }) {
  const toneClass = {
    muted: "text-gray-100",
    good: "text-green-300",
    warn: "text-yellow-300",
    danger: "text-red-300",
  }[tone];

  return (
    <div className="rounded-md border border-surface-border bg-surface-overlay px-3 py-2">
      <div className={`text-sm font-semibold ${toneClass}`}>{value}</div>
      <div className="mt-1 text-[11px] text-gray-500">{label}</div>
    </div>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-surface-border bg-surface-raised px-2 py-2">
      <div className="text-sm font-semibold text-gray-100">{value}</div>
      <div className="mt-0.5 truncate text-[11px] text-gray-500">{label}</div>
    </div>
  );
}

function IconStat({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="flex items-center gap-2 text-gray-400">{icon}{label}</span>
      <span className="font-semibold text-gray-100">{value}</span>
    </div>
  );
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="rounded-md border border-dashed border-surface-border bg-surface-overlay px-4 py-6 text-center">
      <p className="text-sm font-semibold text-gray-300">{title}</p>
      <p className="mt-1 text-xs leading-5 text-gray-500">{detail}</p>
    </div>
  );
}

type OptionGroupProps = {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string; icon: LucideIcon }[];
};

function OptionGroup({ value, onChange, options }: OptionGroupProps) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {options.map((option) => {
        const Icon = option.icon;
        const active = value === option.value;

        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            className={`flex items-center gap-2 rounded-md border px-3 py-2 text-left text-xs font-semibold transition-colors ${
              active ? "border-accent bg-accent/15 text-white" : "border-surface-border bg-surface-overlay text-gray-400 hover:text-gray-200"
            }`}
          >
            <Icon className="h-4 w-4 shrink-0" />
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

type ChoiceGridProps = {
  value: string;
  disabled?: boolean;
  onChange: (value: string) => void;
  options: { value: string; label: string; detail: string }[];
};

function ChoiceGrid({ value, disabled = false, onChange, options }: ChoiceGridProps) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {options.map((option) => {
        const active = value === option.value;

        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            disabled={disabled}
            className={`min-h-[58px] rounded-md border px-3 py-2 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${
              active ? "border-accent bg-accent/15 text-white" : "border-surface-border bg-surface-overlay text-gray-400 hover:text-gray-200"
            }`}
          >
            <span className="block text-xs font-semibold">{option.label}</span>
            <span className="mt-1 block text-[11px] leading-4 text-gray-500">{option.detail}</span>
          </button>
        );
      })}
    </div>
  );
}

function SliderControl({
  label,
  value,
  min,
  max,
  step,
  suffix,
  disabled = false,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  suffix: string;
  disabled?: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <label className="block rounded-md border border-surface-border bg-surface-raised px-3 py-2">
      <span className="mb-2 flex items-center justify-between gap-2 text-xs font-semibold text-gray-300">
        <span>{label}</span>
        <span className="font-mono text-gray-400">{value}{suffix}</span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
        className="w-full accent-accent disabled:cursor-not-allowed disabled:opacity-45"
      />
    </label>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  step,
  suffix,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max?: number;
  step: number;
  suffix: string;
  onChange: (value: number) => void;
}) {
  return (
    <label className="block rounded-md border border-surface-border bg-surface-overlay px-3 py-2">
      <span className="mb-1 block text-xs font-medium text-gray-400">{label}</span>
      <div className="flex items-center gap-2">
        <input
          type="number"
          value={Number.isFinite(value) ? value : 0}
          min={min}
          max={max}
          step={step}
          onChange={(event) => onChange(Number(event.target.value))}
          className="min-w-0 flex-1 bg-transparent font-mono text-sm text-gray-100 outline-none"
        />
        <span className="text-xs text-gray-500">{suffix}</span>
      </div>
    </label>
  );
}

function ToggleRow({
  label,
  detail,
  checked,
  icon,
  onChange,
}: {
  label: string;
  detail: string;
  checked: boolean;
  icon: ReactNode;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-3 rounded-md border border-surface-border bg-surface-overlay p-3">
      <span className="mt-0.5">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold text-gray-100">{label}</span>
        <span className="mt-1 block text-xs leading-5 text-gray-500">{detail}</span>
      </span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-1 h-4 w-4 accent-accent"
      />
    </label>
  );
}

function ExportPresetButton({
  preset,
  selected,
  onSelect,
}: {
  preset: ExportPreset;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`flex min-w-0 items-start gap-3 rounded-md border px-3 py-2.5 text-left transition-colors ${
        selected
          ? "border-accent bg-accent/15 text-white"
          : "border-surface-border bg-surface-overlay text-gray-200 hover:border-gray-500"
      }`}
    >
      <span className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border ${
        selected ? "border-accent bg-accent text-white" : "border-gray-600 text-transparent"
      }`}>
        <Circle className="h-2 w-2 fill-current" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center justify-between gap-2">
          <span className="truncate text-sm font-semibold">{preset.label}</span>
          <span className="shrink-0 rounded bg-surface-raised px-1.5 py-0.5 text-[11px] uppercase text-gray-400">
            {preset.audio_only ? preset.container : preset.aspect_ratio}
          </span>
        </span>
        <span className="mt-1 block text-xs leading-5 text-gray-400">{preset.description}</span>
        <span className="mt-1 block text-[11px] text-gray-500">{exportPresetSummary(preset)}</span>
      </span>
    </button>
  );
}

function RenderProgressCard({
  status,
  onCancel,
  cancelling,
}: {
  status: ProcessingStatus | null;
  onCancel: () => void;
  cancelling: boolean;
}) {
  const job = status?.render_job ?? null;
  const progress = Math.round(job?.progress_percent ?? status?.progress_percent ?? 0);
  const active = Boolean(job && ["queued", "running", "cancel_requested"].includes(job.status));
  const failed = job?.status === "failed";
  const cancelled = job?.status === "cancelled";
  const title = failed ? "Render Failed" : cancelled ? "Render Cancelled" : "Render Progress";
  const icon = failed || cancelled
    ? <AlertTriangle className="h-4 w-4 text-yellow-300" />
    : <Loader2 className="h-4 w-4 animate-spin text-accent" />;

  return (
    <WorkflowCard title={title} icon={icon}>
      <div className="space-y-3">
        <div>
          <div className="mb-1 flex items-center justify-between gap-3 text-xs">
            <span className="truncate font-semibold text-gray-200">{job?.phase_label ?? status?.current_step_label ?? "Rendering final video"}</span>
            <span className="font-semibold text-gray-300">{progress}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-surface-overlay">
            <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${Math.max(0, Math.min(100, progress))}%` }} />
          </div>
        </div>
        <p className="text-xs leading-5 text-gray-400">
          {job?.message ?? "Preparing render status"}
        </p>
        {(job?.error || status?.error_message) && (
          <div className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs leading-5 text-red-200">
            {job?.error ?? status?.error_message}
          </div>
        )}
        {active && (
          <button
            type="button"
            onClick={onCancel}
            disabled={cancelling || job?.status === "cancel_requested"}
            className="flex w-full items-center justify-center gap-2 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs font-semibold text-red-200 transition-colors hover:bg-red-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {cancelling ? <Loader2 className="h-4 w-4 animate-spin" /> : <XCircle className="h-4 w-4" />}
            {job?.status === "cancel_requested" ? "Cancelling..." : "Cancel Render"}
          </button>
        )}
      </div>
    </WorkflowCard>
  );
}

function DownloadLink({ href, label, primary = false }: { href: string; label: string; primary?: boolean }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className={`flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-semibold transition-colors ${
        primary ? "bg-green-600 text-white hover:bg-green-700" : "bg-surface-overlay text-gray-200 hover:bg-surface-border"
      }`}
    >
      <Download className="h-4 w-4" />
      {label}
    </a>
  );
}

function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "0:00";
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.round(seconds % 60);
  return `${minutes}:${remainingSeconds.toString().padStart(2, "0")}`;
}

function selectedExportPresetIdFromPlan(plan: EditPlan | null): string | null {
  const metadata = plan?.export_metadata;
  if (!metadata || typeof metadata !== "object") return null;
  const selected = metadata.selected_preset;
  if (selected && typeof selected === "object" && "id" in selected) {
    const id = String(selected.id || "").trim();
    if (id) return id;
  }
  const targetPresets = metadata.target_presets;
  if (Array.isArray(targetPresets) && targetPresets.length > 0) {
    const id = String(targetPresets[0] || "").trim();
    if (id) return id;
  }
  return null;
}

function exportPresetSummary(preset: ExportPreset): string {
  if (preset.audio_only) {
    return `${preset.container.toUpperCase()} ${preset.audio_codec.toUpperCase()} ${preset.audio_bitrate}`;
  }
  const size = preset.width && preset.height ? `${preset.width}x${preset.height}` : preset.aspect_ratio || "video";
  return `${size} ${preset.video_codec?.toUpperCase() ?? "VIDEO"} / ${preset.audio_codec.toUpperCase()}`;
}

function layoutUsesCamera(layout: LayoutMode): boolean {
  return layout === "picture_in_picture" || layout === "side_by_side" || layout === "full_camera_source";
}

function captionPolicyFromPlan(plan: EditPlan | null): CaptionPolicy {
  const action = plan?.polish_actions.find((item) => {
    return typeof item === "object" && item != null && "kind" in item && item.kind === "caption_policy";
  });
  if (!action) return DEFAULT_CAPTION_POLICY;
  const policy = action as CaptionPolicy;
  return {
    ...DEFAULT_CAPTION_POLICY,
    ...policy,
    style: { ...DEFAULT_CAPTION_POLICY.style, ...(policy.style ?? {}) },
    ranges: Array.isArray(policy.ranges) ? policy.ranges : [],
  };
}

function annotationsFromPlan(plan: EditPlan | null): AnnotationAction[] {
  return (plan?.polish_actions ?? []).filter((item): item is AnnotationAction => {
    return typeof item === "object" && item != null && "kind" in item && item.kind === "annotation";
  }).map((annotation) => ({
    ...annotation,
    style: { ...DEFAULT_ANNOTATION_STYLE, ...(annotation.style ?? {}) },
    pointer: {
      enabled: annotation.pointer?.enabled ?? annotation.annotation_type === "callout",
      direction: annotation.pointer?.direction ?? "left",
    },
    animation: normalizeAnimationSettings(annotation.animation, annotation.annotation_type === "callout" ? DEFAULT_CALLOUT_ANIMATION : {
      ...DEFAULT_CALLOUT_ANIMATION,
      preset: "fade",
      direction: "none",
    }),
  }));
}

function educationalOverlaysFromPlan(plan: EditPlan | null): EducationalOverlayAction[] {
  return (plan?.polish_actions ?? []).filter((item): item is EducationalOverlayAction => {
    return typeof item === "object" && item != null && "kind" in item && item.kind === "educational_overlay";
  }).map((overlay) => ({
    ...overlay,
    subtitle: overlay.subtitle ?? "",
    style: { ...DEFAULT_EDUCATIONAL_OVERLAY_STYLE, ...(overlay.style ?? {}) },
    animation: normalizeAnimationSettings(overlay.animation, defaultEducationalOverlayAnimation(overlay.overlay_type)),
  }));
}

function endCardsFromPlan(plan: EditPlan | null): EndCardAction[] {
  return (plan?.polish_actions ?? []).filter((item): item is EndCardAction => {
    return typeof item === "object" && item != null && "kind" in item && item.kind === "end_card";
  }).map((card) => ({
    ...card,
    message: card.message ?? "",
    summary_points: Array.isArray(card.summary_points) ? card.summary_points : [],
    next_topic: card.next_topic ?? "",
    course_url: card.course_url ?? "",
    button_text: card.button_text ?? defaultEndCardButtonText(card.card_type),
    duration_seconds: normalizeEndCardDuration(card.duration_seconds),
    style: { ...DEFAULT_END_CARD_STYLE, ...(card.style ?? {}) },
    animation: normalizeAnimationSettings(card.animation, DEFAULT_TITLE_CARD_ANIMATION),
  }));
}

function createEndCardDraft(cardType: EndCardType, duration: number): EndCardAction {
  return {
    id: `end-card-${Date.now()}`,
    kind: "end_card",
    schema_version: "phase6.edit-plan.v2",
    status: "active",
    enabled: true,
    card_type: cardType,
    title: defaultEndCardTitle(cardType),
    message: defaultEndCardMessage(cardType),
    summary_points: defaultEndCardSummaryPoints(cardType),
    next_topic: cardType === "next_topic" ? "Next lesson topic" : "",
    course_url: cardType === "course_link" ? "https://example.edu/course" : "",
    button_text: defaultEndCardButtonText(cardType),
    duration_seconds: Math.min(8, Math.max(5, duration ? Math.round(duration * 0.04) : 6)),
    style: DEFAULT_END_CARD_STYLE,
    animation: DEFAULT_TITLE_CARD_ANIMATION,
    source: "teacher_polish",
    reason: "Teacher-added end card CTA.",
  };
}

function mergeEndCardDraft(card: EndCardAction, patch: EndCardActionUpdate): EndCardAction {
  const nextType = (patch.card_type ?? card.card_type) as EndCardType;
  const next = {
    ...card,
    ...patch,
    style: { ...card.style, ...(patch.style ?? {}) },
    animation: normalizeAnimationSettings({ ...card.animation, ...(patch.animation ?? {}) }, DEFAULT_TITLE_CARD_ANIMATION),
  };
  return {
    ...next,
    title: next.title || defaultEndCardTitle(nextType),
    message: next.message ?? "",
    summary_points: Array.isArray(next.summary_points) ? next.summary_points.slice(0, 5) : [],
    next_topic: next.next_topic ?? "",
    course_url: next.course_url ?? "",
    button_text: next.button_text || defaultEndCardButtonText(nextType),
    duration_seconds: normalizeEndCardDuration(next.duration_seconds),
  };
}

function endCardForSave(card: EndCardAction): EndCardActionUpdate {
  return {
    id: card.id,
    enabled: card.enabled,
    card_type: card.card_type,
    title: card.title,
    message: card.message,
    summary_points: card.summary_points,
    next_topic: card.next_topic,
    course_url: card.course_url,
    button_text: card.button_text,
    duration_seconds: card.duration_seconds,
    style: card.style,
    animation: card.animation,
    source: card.source,
    reason: card.reason,
  };
}

function endCardTypePatch(cardType: EndCardType): EndCardActionUpdate {
  return {
    card_type: cardType,
    title: defaultEndCardTitle(cardType),
    message: defaultEndCardMessage(cardType),
    button_text: defaultEndCardButtonText(cardType),
    summary_points: defaultEndCardSummaryPoints(cardType),
    next_topic: cardType === "next_topic" ? "Next lesson topic" : "",
    course_url: cardType === "course_link" ? "https://example.edu/course" : "",
  };
}

function defaultEndCardTitle(cardType: string): string {
  if (cardType === "next_topic") return "Next Topic";
  if (cardType === "course_link") return "Continue Learning";
  if (cardType === "custom_message") return "Thanks for Watching";
  return "Lecture Summary";
}

function defaultEndCardMessage(cardType: string): string {
  if (cardType === "next_topic") return "In the next lesson, we build on this concept.";
  if (cardType === "course_link") return "Open the course page for notes, exercises, and resources.";
  if (cardType === "custom_message") return "See you in the next lesson.";
  return "Review the key ideas before moving on.";
}

function defaultEndCardButtonText(cardType: string): string {
  if (cardType === "next_topic") return "Watch next";
  if (cardType === "course_link") return "Open course";
  if (cardType === "custom_message") return "Continue";
  return "Review notes";
}

function defaultEndCardSummaryPoints(cardType: string): string[] {
  return cardType === "lecture_summary" ? ["Key idea", "Worked example", "What to review"] : [];
}

function normalizeEndCardDuration(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.min(15, Math.max(2, Math.round(value * 2) / 2))
    : 6;
}

function createEducationalOverlayDraft(
  overlayType: EducationalOverlayType,
  currentTime: number,
  duration: number,
  ordinal: number,
): EducationalOverlayAction {
  const start = overlayType === "intro_card" ? 0 : Math.max(0, Math.round(currentTime * 2) / 2);
  const defaultDuration = overlayType === "intro_card" || overlayType === "section_title_card" ? 4.5 : 3;
  const end = Math.min(Math.max(duration, start + defaultDuration), start + defaultDuration);
  const isCard = overlayType === "intro_card" || overlayType === "section_title_card";
  return {
    id: `edu-overlay-${Date.now()}-${ordinal}`,
    kind: "educational_overlay",
    schema_version: "phase6.edit-plan.v2",
    status: "active",
    overlay_type: overlayType,
    title: defaultEducationalOverlayTitle(overlayType, ordinal),
    subtitle: overlayType === "intro_card" ? "Course lesson overview" : "",
    start_time: start,
    end_time: Math.max(start + 0.5, end),
    duration: Math.max(0.5, end - start),
    position: isCard ? "center" : "top_left",
    x_percent: isCard ? 50 : 9,
    y_percent: isCard ? 50 : 10,
    style: {
      ...DEFAULT_EDUCATIONAL_OVERLAY_STYLE,
      font_size: isCard ? 44 : 28,
      subtitle_font_size: isCard ? 24 : 18,
    },
    animation: defaultEducationalOverlayAnimation(overlayType),
    chapter_index: overlayType === "chapter_label" ? Math.max(0, ordinal - 1) : null,
    step_number: overlayType === "step_label" ? ordinal : null,
    source: "teacher_polish",
    reason: "Teacher-added educational polish overlay.",
  };
}

function createEducationalOverlaysFromChapters(chapters: Chapter[], duration: number): EducationalOverlayAction[] {
  const lessonTitle = chapters[0]?.label || "Lecture Overview";
  const overlays: EducationalOverlayAction[] = [
    {
      ...createEducationalOverlayDraft("intro_card", 0, duration || 4.5, 1),
      id: "edu-intro-card",
      title: lessonTitle,
      subtitle: chapters.length > 1 ? `${chapters.length} chapters in this lesson` : "Key ideas and examples",
      source: "chapter_generation",
    },
  ];

  chapters.slice(0, 12).forEach((chapter, index) => {
    const start = Math.max(0, chapter.timestamp);
    overlays.push({
      ...createEducationalOverlayDraft("section_title_card", start, duration || start + 4.5, index + 1),
      id: `edu-section-${index + 1}`,
      title: chapter.label,
      subtitle: chapter.keywords?.slice(0, 3).join(" / ") ?? "",
      chapter_index: index,
      source: "chapter_generation",
    });
    overlays.push({
      ...createEducationalOverlayDraft("chapter_label", start + 0.2, duration || start + 3.2, index + 1),
      id: `edu-chapter-${index + 1}`,
      title: chapter.label,
      chapter_index: index,
      source: "chapter_generation",
    });
  });

  return overlays;
}

function defaultEducationalOverlayTitle(overlayType: EducationalOverlayType, ordinal: number): string {
  if (overlayType === "intro_card") return "Lecture Overview";
  if (overlayType === "section_title_card") return `Section ${ordinal}`;
  if (overlayType === "step_label") return "Key step";
  return `Chapter ${ordinal}`;
}

function mergeEducationalOverlayDraft(
  overlay: EducationalOverlayAction,
  patch: EducationalOverlayActionUpdate,
): EducationalOverlayAction {
  const next = {
    ...overlay,
    ...patch,
    style: { ...overlay.style, ...(patch.style ?? {}) },
    animation: normalizeAnimationSettings(
      { ...overlay.animation, ...(patch.animation ?? {}) },
      defaultEducationalOverlayAnimation(String(patch.overlay_type ?? overlay.overlay_type)),
    ),
  };
  const start = Math.max(0, Number(next.start_time) || 0);
  const end = Math.max(start + 0.5, Number(next.end_time) || start + 4);
  return {
    ...next,
    start_time: start,
    end_time: end,
    duration: end - start,
  };
}

function educationalOverlayForSave(overlay: EducationalOverlayAction): EducationalOverlayActionUpdate {
  return {
    id: overlay.id,
    overlay_type: overlay.overlay_type,
    title: overlay.title,
    subtitle: overlay.subtitle,
    start_time: overlay.start_time,
    end_time: overlay.end_time,
    position: overlay.position,
    x_percent: overlay.x_percent,
    y_percent: overlay.y_percent,
    style: overlay.style,
    animation: overlay.animation,
    chapter_index: overlay.chapter_index,
    step_number: overlay.step_number,
    source: overlay.source,
    reason: overlay.reason,
  };
}

function educationalOverlayTypePatch(overlayType: EducationalOverlayType): EducationalOverlayActionUpdate {
  const isCard = overlayType === "intro_card" || overlayType === "section_title_card";
  const [x, y] = educationalOverlayPositionPercent(isCard ? "center" : "top_left");
  return {
    overlay_type: overlayType,
    position: isCard ? "center" : "top_left",
    x_percent: x,
    y_percent: y,
    style: {
      font_size: isCard ? 44 : 28,
      subtitle_font_size: isCard ? 24 : 18,
    },
    animation: defaultEducationalOverlayAnimation(overlayType),
  };
}

function educationalOverlayPositionPatch(position: EducationalOverlayPosition): EducationalOverlayActionUpdate {
  const [x, y] = educationalOverlayPositionPercent(position);
  return { position, x_percent: x, y_percent: y };
}

function educationalOverlayPositionPercent(position: string): [number, number] {
  return {
    center: [50, 50],
    top_left: [9, 10],
    top_center: [50, 10],
    top_right: [91, 10],
    bottom_left: [9, 87],
    bottom_center: [50, 87],
    bottom_right: [91, 87],
  }[position] as [number, number] ?? [50, 50];
}

function createAnnotationDraft(currentTime: number, duration: number): AnnotationAction {
  const start = Math.max(0, Math.round(currentTime * 2) / 2);
  const end = Math.min(Math.max(duration, start + 4), start + 4);
  return {
    id: `annotation-${Date.now()}`,
    kind: "annotation",
    schema_version: "phase6.edit-plan.v2",
    status: "active",
    annotation_type: "callout",
    text: "Key idea",
    start_time: start,
    end_time: Math.max(start + 0.5, end),
    duration: Math.max(0.5, end - start),
    position: "top_right",
    x_percent: 78,
    y_percent: 12,
    style: DEFAULT_ANNOTATION_STYLE,
    pointer: { enabled: true, direction: "left" },
    animation: DEFAULT_CALLOUT_ANIMATION,
    reason: "Teacher-added polish annotation.",
  };
}

function mergeAnnotationDraft(annotation: AnnotationAction, patch: AnnotationActionUpdate): AnnotationAction {
  const next = {
    ...annotation,
    ...patch,
    style: { ...annotation.style, ...(patch.style ?? {}) },
    pointer: { ...annotation.pointer, ...(patch.pointer ?? {}) },
    animation: normalizeAnimationSettings(
      { ...annotation.animation, ...(patch.animation ?? {}) },
      annotation.annotation_type === "callout" ? DEFAULT_CALLOUT_ANIMATION : {
        ...DEFAULT_CALLOUT_ANIMATION,
        preset: "fade",
        direction: "none",
      },
    ),
  };
  const start = Math.max(0, Number(next.start_time) || 0);
  const end = Math.max(start + 0.5, Number(next.end_time) || start + 4);
  return {
    ...next,
    start_time: start,
    end_time: end,
    duration: end - start,
  };
}

function annotationForSave(annotation: AnnotationAction): AnnotationActionUpdate {
  return {
    id: annotation.id,
    annotation_type: annotation.annotation_type,
    text: annotation.text,
    start_time: annotation.start_time,
    end_time: annotation.end_time,
    position: annotation.position,
    x_percent: annotation.x_percent,
    y_percent: annotation.y_percent,
    style: annotation.style,
    pointer: annotation.pointer,
    animation: annotation.animation,
    reason: annotation.reason,
  };
}

function annotationAnimationPatch(preset: AnimationPreset): AnnotationActionUpdate {
  return {
    animation: {
      preset,
      direction: animationDirectionForPreset(preset, "left"),
      duration_seconds: preset === "none" ? 0 : preset === "fade" ? 0.3 : 0.35,
      easing: "ease_out",
    },
  };
}

function educationalOverlayAnimationPatch(
  preset: AnimationPreset,
  overlayType: string,
): EducationalOverlayActionUpdate {
  const defaults = defaultEducationalOverlayAnimation(overlayType);
  return {
    animation: {
      preset,
      direction: animationDirectionForPreset(preset, defaults.direction),
      duration_seconds: preset === "none" ? 0 : defaults.duration_seconds,
      easing: "ease_out",
    },
  };
}

function defaultEducationalOverlayAnimation(overlayType: string): AnimationSettings {
  const isCard = overlayType === "intro_card" || overlayType === "section_title_card";
  return isCard ? DEFAULT_TITLE_CARD_ANIMATION : {
    preset: "slide_down",
    direction: "down",
    duration_seconds: 0.3,
    easing: "ease_out",
  };
}

function normalizeAnimationSettings(value: unknown, defaults: AnimationSettings): AnimationSettings {
  const source = typeof value === "object" && value != null ? value as Partial<AnimationSettings> : {};
  const preset = normalizeAnimationPreset(source.preset, defaults.preset);
  return {
    preset,
    direction: preset === "none" ? "none" : String(source.direction ?? defaults.direction),
    duration_seconds: normalizeAnimationDuration(source.duration_seconds, defaults.duration_seconds),
    easing: String(source.easing ?? defaults.easing),
  };
}

function normalizeAnimationPreset(value: unknown, fallback: AnimationSettings["preset"]): AnimationSettings["preset"] {
  if (
    value === "none" || value === "fade" || value === "pop" || value === "zoom" ||
    value === "slide_up" || value === "slide_down" || value === "slide_left" || value === "slide_right"
  ) {
    return value;
  }
  return fallback;
}

function animationDirectionForPreset(preset: AnimationPreset, fallback: string): string {
  if (preset === "slide_up") return "up";
  if (preset === "slide_down") return "down";
  if (preset === "slide_left") return "left";
  if (preset === "slide_right") return "right";
  if (preset === "none" || preset === "fade" || preset === "zoom") return "none";
  return fallback;
}

function normalizeAnimationDuration(value: unknown, fallback: number): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return fallback;
  }
  return Math.min(2, Math.max(0, Math.round(value * 100) / 100));
}

function annotationPositionPatch(position: AnnotationPosition): AnnotationActionUpdate {
  const [x, y] = annotationPositionPercent(position);
  return { position, x_percent: x, y_percent: y };
}

function annotationPositionPercent(position: string): [number, number] {
  return {
    top_left: [10, 12],
    top_center: [50, 12],
    top_right: [78, 12],
    middle_left: [10, 50],
    middle_center: [50, 50],
    middle_right: [78, 50],
    bottom_left: [10, 82],
    bottom_center: [50, 82],
    bottom_right: [78, 82],
  }[position] as [number, number] ?? [78, 12];
}

function normalizeCameraSize(value: unknown): CameraSize {
  if (value === "small" || value === "medium" || value === "large") return value;
  return DEFAULT_LAYOUT_PREVIEW_SETTINGS.cameraSize;
}

function normalizeMarginPercent(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return DEFAULT_LAYOUT_PREVIEW_SETTINGS.cameraMarginPercent;
  }
  return Math.min(8, Math.max(2, Math.round(value)));
}

function normalizeTransitionDuration(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return DEFAULT_LAYOUT_PREVIEW_SETTINGS.transitionDurationSeconds;
  }
  return Math.min(2, Math.max(0, Math.round(value * 100) / 100));
}
