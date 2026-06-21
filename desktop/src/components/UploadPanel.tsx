import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  BookOpen,
  Camera,
  FileText,
  FileVideo,
  Loader2,
  Mic,
  MonitorUp,
  Play,
  Presentation,
  ScreenShare,
  Square,
  Upload,
  X,
} from "lucide-react";
import * as api from "../lib/api";
import type {
  NativeImportProgress,
  Project,
  ProjectAsset,
  ProjectAssetUploadType,
  Video,
} from "../types/api";

interface Props {
  onUpload: (videoId: string, filename: string) => void;
  onProjectResolved?: (project: Project) => void;
  project?: Project | null;
  existingVideo?: Video | null;
}

type UploadedVideo = {
  id: string;
  filename: string;
  projectId: string | null;
};

type MaterialItem = {
  id: string;
  filename: string;
  chunk_count: number;
};

type StructureUploadOption = {
  type: ProjectAssetUploadType;
  label: string;
  accept: string;
  icon: "slides" | "notes";
};

type RecordingState = {
  type: ProjectAssetUploadType;
  label: string;
  recorder: MediaRecorder;
  stream: MediaStream;
  mimeType: string;
  sourceStreams?: MediaStream[];
  mode?: "asset" | "primary";
};

type StudioLayoutPreset = "picture_in_picture" | "side_by_side" | "screen_only" | "camera_full";

type StudioOverlaySettings = {
  xPercent: number;
  yPercent: number;
  sizePercent: number;
};

type StudioSettings = {
  layout: StudioLayoutPreset;
  overlay: StudioOverlaySettings;
};

const DEFAULT_STUDIO_SETTINGS: StudioSettings = {
  layout: "picture_in_picture",
  overlay: {
    xPercent: 72,
    yPercent: 7,
    sizePercent: 24,
  },
};

const structureUploadOptions: StructureUploadOption[] = [
  { type: "slides", label: "Add deck", accept: ".ppt,.pptx,.pdf", icon: "slides" },
  { type: "notes", label: "Add PDF", accept: ".pdf", icon: "notes" },
  { type: "notes", label: "Add notes", accept: ".docx,.txt,.md", icon: "notes" },
];

const studioLayoutOptions: { value: StudioLayoutPreset; label: string; detail: string }[] = [
  { value: "picture_in_picture", label: "PiP overlay", detail: "Slides or screen behind lecturer" },
  { value: "side_by_side", label: "Side by side", detail: "Screen and lecturer equal priority" },
  { value: "screen_only", label: "Screen only", detail: "Hide lecturer camera in output" },
  { value: "camera_full", label: "Camera full", detail: "Lecturer face as main program" },
];

const sourceRoles = new Set(["primary", "screen", "camera", "audio"]);
const structureRoles = new Set(["slides", "notes", "supporting_material"]);

function structureAssetLabel(asset: ProjectAsset) {
  const role = asset.structure_reference_role || asset.source_type;
  return role.replace(/_/g, " ");
}

function sourceAssetLabel(asset: ProjectAsset) {
  if (asset.role === "primary") return "Primary timeline";
  return asset.source_type.replace(/_/g, " ");
}

export function UploadPanel({ onUpload, onProjectResolved, project, existingVideo }: Props) {
  const [uploadingLabel, setUploadingLabel] = useState<string | null>(null);
  const [isNativeDesktopApp, setIsNativeDesktopApp] = useState(false);
  const [nativeImportProgress, setNativeImportProgress] = useState<NativeImportProgress | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [materials, setMaterials] = useState<MaterialItem[]>([]);
  const [materialUploading, setMaterialUploading] = useState(false);
  const [projectAssets, setProjectAssets] = useState<ProjectAsset[]>([]);
  const [starting, setStarting] = useState(false);
  const [recording, setRecording] = useState<RecordingState | null>(null);
  const [studioSettings, setStudioSettings] = useState<StudioSettings>(DEFAULT_STUDIO_SETTINGS);
  const [structurePageStart, setStructurePageStart] = useState("");
  const [structurePageEnd, setStructurePageEnd] = useState("");
  const [activeProject, setActiveProject] = useState<Project | null>(project ?? null);
  const [uploadedVideo, setUploadedVideo] = useState<UploadedVideo | null>(() => videoToUploaded(existingVideo));
  const recordingChunks = useRef<Blob[]>([]);
  const studioSettingsRef = useRef<StudioSettings>(DEFAULT_STUDIO_SETTINGS);
  const browserPrimaryUploadControllerRef = useRef<AbortController | null>(null);

  const projectId = activeProject?.id ?? uploadedVideo?.projectId ?? null;
  const uploading = Boolean(uploadingLabel);
  const isMultiSource = activeProject?.source_mode === "multi_source";
  const sourceAssets = useMemo(
    () => projectAssets.filter(asset => sourceRoles.has(asset.role)),
    [projectAssets],
  );
  const structureAssets = useMemo(
    () => projectAssets.filter(asset => structureRoles.has(asset.role)),
    [projectAssets],
  );
  const embeddedMaterials = materials.filter(m => m.chunk_count > 0).length;
  const nativeImportActive = nativeImportProgress && ["copying", "finalizing"].includes(nativeImportProgress.status);

  useEffect(() => {
    api.listMaterials().then(setMaterials).catch(() => {});
  }, []);

  useEffect(() => {
    let active = true;
    let unlisten: (() => void) | null = null;

    void (async () => {
      const nativeDesktop = await api.isNativeDesktop().catch(() => false);
      if (!active) return;
      setIsNativeDesktopApp(nativeDesktop);
      if (!nativeDesktop) return;

      unlisten = await api.listenToNativeImportProgress(payload => {
        if (!active) return;
        setNativeImportProgress(payload);
      });
    })();

    return () => {
      active = false;
      unlisten?.();
    };
  }, []);

  const refreshProjectAssets = useCallback(async (projectIdOverride?: string | null) => {
    const id = projectIdOverride ?? activeProject?.id;
    if (!id) {
      setProjectAssets([]);
      return;
    }
    try {
      setProjectAssets(await api.listProjectAssets(id));
    } catch {
      setProjectAssets([]);
    }
  }, [activeProject?.id]);

  const commitActiveProject = useCallback((nextProject: Project) => {
    setActiveProject(nextProject);
    onProjectResolved?.(nextProject);
  }, [onProjectResolved]);

  const ensureProjectForUpload = useCallback(async () => {
    if (!activeProject) return null;
    try {
      const latest = await api.getProject(activeProject.id);
      commitActiveProject(latest);
      return latest;
    } catch (err) {
      if (!isProjectNotFoundError(err)) throw err;
      const recovered = await api.createProject({
        title: activeProject.title || "Recovered editing project",
        description: activeProject.description,
        source_mode: activeProject.source_mode || "multi_source",
        project_type: activeProject.project_type || "lecture",
        metadata: {
          ...(activeProject.metadata_json || {}),
          recovered_from_missing_project_id: activeProject.id,
          recovery_reason: "upload_project_not_found",
        },
      });
      commitActiveProject(recovered);
      alert("The previously selected project no longer exists in the backend, so a replacement project was created and your upload will continue.");
      return recovered;
    }
  }, [activeProject, commitActiveProject]);

  useEffect(() => {
    setUploadedVideo(videoToUploaded(existingVideo));
  }, [existingVideo]);

  useEffect(() => {
    setActiveProject(project ?? null);
  }, [project]);

  useEffect(() => {
    void refreshProjectAssets();
  }, [refreshProjectAssets]);

  useEffect(() => {
    if (!activeProject?.id || uploadedVideo?.projectId === activeProject.id) return;
    let cancelled = false;
    api.listVideos()
      .then(videos => {
        if (cancelled) return;
        const projectVideo = videos.find(video => video.project_id === activeProject.id);
        if (projectVideo) setUploadedVideo(videoToUploaded(projectVideo));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [activeProject?.id, uploadedVideo?.projectId]);

  useEffect(() => {
    studioSettingsRef.current = studioSettings;
  }, [studioSettings]);

  const handlePrimaryVideo = useCallback(async (file: File) => {
    if (uploading || starting) return;
    if (!file.type.startsWith("video/")) {
      alert("Please upload a video file (MP4, MOV, AVI, WebM)");
      return;
    }

    setUploadingLabel("Uploading primary video");
    setNativeImportProgress(null);
    try {
      const uploadProject = await ensureProjectForUpload();
      const controller = new AbortController();
      browserPrimaryUploadControllerRef.current = controller;
      const result = uploadProject
        ? await api.uploadProjectPrimaryVideo(uploadProject.id, file, {
            signal: controller.signal,
            onProgress: payload => setNativeImportProgress(payload),
          })
        : await api.uploadVideo(file);
      setUploadedVideo({ id: result.id, filename: file.name, projectId: result.project_id });
      await refreshProjectAssets(result.project_id);
    } catch (e) {
      const message = String(e);
      if (!message.toLowerCase().includes("cancel")) {
        alert(`Upload failed: ${message}`);
      }
    } finally {
      browserPrimaryUploadControllerRef.current = null;
      setUploadingLabel(null);
    }
  }, [ensureProjectForUpload, refreshProjectAssets, starting, uploading]);

  const handleNativePrimaryVideoImport = useCallback(async (sourcePath: string) => {
    if (uploading || starting) return;

    const uploadProject = await ensureProjectForUpload();
    if (!uploadProject) {
      alert("Open or create a project before using the native desktop import.");
      return;
    }

    setNativeImportProgress(null);
    setUploadingLabel("Preparing native desktop import");
    try {
      const result = await api.startNativePrimaryImport(uploadProject.id, sourcePath);
      setUploadedVideo({ id: result.videoId, filename: result.filename, projectId: result.projectId });
      await refreshProjectAssets(result.projectId);
    } catch (error) {
      const message = String(error);
      if (!message.toLowerCase().includes("cancelled")) {
        alert(`Native import failed: ${message}`);
      }
    } finally {
      setUploadingLabel(null);
    }
  }, [ensureProjectForUpload, refreshProjectAssets, starting, uploading]);

  const pickPrimaryVideo = useCallback(async () => {
    if (uploading || starting) return;

    if (isNativeDesktopApp && activeProject?.id) {
      try {
        const sourcePath = await api.pickNativePrimaryVideoPath();
        if (sourcePath) {
          await handleNativePrimaryVideoImport(sourcePath);
          return;
        }
      } catch (error) {
        console.warn("Native desktop primary picker failed, falling back to the in-app file picker.", error);
        alert(
          "The native desktop file picker did not open correctly, so the app will fall back to the in-app picker for this upload.",
        );
      }
    }

    pickFile("video/*", file => void handlePrimaryVideo(file));
  }, [activeProject?.id, handleNativePrimaryVideoImport, handlePrimaryVideo, isNativeDesktopApp, starting, uploading]);

  const handleCancelNativeImport = useCallback(async () => {
    if (browserPrimaryUploadControllerRef.current) {
      browserPrimaryUploadControllerRef.current.abort();
      return;
    }
    if (!nativeImportProgress?.token) return;
    try {
      await api.cancelNativeImport(nativeImportProgress.token);
    } catch (error) {
      alert(`Could not cancel native import: ${error}`);
    }
  }, [nativeImportProgress?.token]);

  const uploadProjectAsset = async (
    assetType: ProjectAssetUploadType,
    file: File,
    label: string,
    metadata?: Record<string, unknown>,
  ) => {
    const uploadProject = await ensureProjectForUpload();
    const uploadProjectId = uploadProject?.id ?? projectId;
    if (!uploadProjectId) {
      alert("Create or open a project before adding sources.");
      return;
    }

    setUploadingLabel(label);
    try {
      const asset = await api.uploadProjectAsset(uploadProjectId, assetType, file, false, metadata);
      setProjectAssets(prev => [asset, ...prev.filter(item => item.id !== asset.id)]);
    } catch (err) {
      alert(`${label} failed: ${err}`);
    } finally {
      setUploadingLabel(null);
    }
  };

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (isNativeDesktopApp) {
      alert("Use Import video in the desktop app so the file is copied natively with progress and cancellation support.");
      return;
    }
    const file = e.dataTransfer.files[0];
    if (file) void handlePrimaryVideo(file);
  }, [handlePrimaryVideo, isNativeDesktopApp]);

  const pickFile = (
    accept: string,
    onFile: (file: File) => void,
  ) => {
    if (uploading || starting) return;
    const input = document.createElement("input");
    input.type = "file";
    input.accept = accept;
    input.onchange = (event) => {
      const file = (event.target as HTMLInputElement).files?.[0];
      if (file) onFile(file);
    };
    input.click();
  };

  const startRecording = async (type: ProjectAssetUploadType, label: string) => {
    if (!navigator.mediaDevices) {
      alert("Recording is not available in this desktop runtime right now. Use the Import button for this source instead.");
      return;
    }
    if (recording || uploading || starting) return;

    try {
      const stream = type === "screen"
        ? await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true })
        : await navigator.mediaDevices.getUserMedia({
            video: type !== "audio",
            audio: true,
          });
      const mimeType = preferredMimeType(type);
      recordingChunks.current = [];
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) recordingChunks.current.push(event.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(recordingChunks.current, {
          type: recorder.mimeType || (type === "audio" ? "audio/ogg" : "video/webm"),
        });
        stream.getTracks().forEach(track => track.stop());
        setRecording(null);
        if (blob.size === 0) return;
        const extension = type === "audio" && blob.type.includes("ogg") ? "ogg" : "webm";
        const file = new File([blob], `${type}-${new Date().toISOString().replace(/[:.]/g, "-")}.${extension}`, {
          type: blob.type,
        });
        void uploadProjectAsset(type, file, `Saving ${label}`, {
          recorded_in_app: true,
          recording_kind: type,
          recording_started_at: new Date().toISOString(),
        });
      };
      setRecording({ type, label, recorder, stream, mimeType: recorder.mimeType, mode: "asset" });
      recorder.start();
    } catch (err) {
      alert(`Recording could not start: ${err}`);
    }
  };

  const startStudioRecording = async () => {
    if (!navigator.mediaDevices?.getDisplayMedia || !navigator.mediaDevices?.getUserMedia) {
      alert(
        "Screen + camera studio recording is not available in this desktop runtime right now. Use Import mix, or import screen and webcam sources separately below.",
      );
      return;
    }
    if (recording || uploading || starting) return;

    let screenStream: MediaStream | null = null;
    let cameraStream: MediaStream | null = null;
    let audioContext: AudioContext | null = null;
    let animationFrame = 0;

    try {
      screenStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
      cameraStream = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
        },
      });

      const screenVideo = document.createElement("video");
      screenVideo.srcObject = screenStream;
      screenVideo.muted = true;
      screenVideo.playsInline = true;
      await screenVideo.play();

      const cameraVideo = document.createElement("video");
      cameraVideo.srcObject = cameraStream;
      cameraVideo.muted = true;
      cameraVideo.playsInline = true;
      await cameraVideo.play();

      const canvas = document.createElement("canvas");
      const screenSettings = screenStream.getVideoTracks()[0]?.getSettings();
      canvas.width = Math.max(1280, Number(screenSettings?.width ?? 1280));
      canvas.height = Math.max(720, Number(screenSettings?.height ?? 720));
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("Canvas capture is not available.");

      const drawFrame = () => {
        drawStudioFrame(ctx, screenVideo, cameraVideo, canvas.width, canvas.height, studioSettingsRef.current);
        animationFrame = window.requestAnimationFrame(drawFrame);
      };
      drawFrame();

      const canvasStream = canvas.captureStream(30);
      audioContext = new AudioContext();
      void audioContext.resume();
      const destination = audioContext.createMediaStreamDestination();
      if (screenStream.getAudioTracks().length > 0) {
        audioContext.createMediaStreamSource(screenStream).connect(destination);
      }
      if (cameraStream.getAudioTracks().length > 0) {
        audioContext.createMediaStreamSource(cameraStream).connect(destination);
      }
      const mixedStream = new MediaStream([
        ...canvasStream.getVideoTracks(),
        ...destination.stream.getAudioTracks(),
      ]);
      const mimeType = preferredMimeType("video");
      recordingChunks.current = [];
      const recorder = new MediaRecorder(mixedStream, mimeType ? { mimeType } : undefined);
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) recordingChunks.current.push(event.data);
      };
      recorder.onstop = () => {
        window.cancelAnimationFrame(animationFrame);
        const blob = new Blob(recordingChunks.current, {
          type: recorder.mimeType || "video/webm",
        });
        mixedStream.getTracks().forEach(track => track.stop());
        screenStream?.getTracks().forEach(track => track.stop());
        cameraStream?.getTracks().forEach(track => track.stop());
        void audioContext?.close();
        setRecording(null);
        if (blob.size === 0) return;
        const file = new File([blob], `studio-${new Date().toISOString().replace(/[:.]/g, "-")}.webm`, {
          type: blob.type,
        });
        void handlePrimaryVideo(file);
      };

      setRecording({
        type: "video",
        label: "screen + camera studio",
        recorder,
        stream: mixedStream,
        mimeType: recorder.mimeType,
        sourceStreams: [screenStream, cameraStream],
        mode: "primary",
      });
      recorder.start();
    } catch (err) {
      window.cancelAnimationFrame(animationFrame);
      screenStream?.getTracks().forEach(track => track.stop());
      cameraStream?.getTracks().forEach(track => track.stop());
      void audioContext?.close();
      alert(`Studio recording could not start: ${err}`);
    }
  };

  const stopRecording = () => {
    if (!recording) return;
    if (recording.recorder.state !== "inactive") recording.recorder.stop();
  };

  const handleMaterialUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (materialUploading) return;

    const file = e.target.files?.[0];
    if (!file) return;

    setMaterialUploading(true);
    try {
      const result = await api.uploadMaterial(file);
      setMaterials(prev => [...prev, { id: result.id, filename: file.name, chunk_count: result.chunk_count }]);
    } catch (err) {
      alert(`Material upload failed: ${err}`);
    } finally {
      setMaterialUploading(false);
      e.target.value = "";
    }
  };

  const handleStructureAssetUpload = async (
    option: StructureUploadOption,
    e: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const file = e.target.files?.[0];
    if (!file) return;

    await uploadProjectAsset(
      option.type,
      file,
      `Uploading ${option.label}`,
      {
        intended_use: "lecture_structure_inference",
        upload_surface: isMultiSource ? "multi_source_intake" : "single_video_upload_panel",
        ...(structurePageStart && structurePageEnd
          ? { slide_page_start: Number(structurePageStart), slide_page_end: Number(structurePageEnd) }
          : {}),
      },
    );
    e.target.value = "";
  };

  const handleStructureScopeUpdate = async (asset: ProjectAsset, pageStart: number | null, pageEnd: number | null) => {
    if (!projectId) return;
    const updated = await api.updateProjectAssetMetadata(projectId, asset.id, {
      slide_page_start: pageStart,
      slide_page_end: pageEnd,
    });
    setProjectAssets(prev => prev.map(item => item.id === updated.id ? updated : item));
  };

  const handleDeleteProjectAsset = async (asset: ProjectAsset) => {
    if (!projectId) return;
    await api.deleteProjectAsset(projectId, asset.id);
    setProjectAssets(prev => prev.filter(item => item.id !== asset.id));
  };

  const handleDeleteMaterial = async (id: string) => {
    await api.deleteMaterial(id);
    setMaterials(prev => prev.filter(m => m.id !== id));
  };

  const handleStartProcessing = async () => {
    if (!uploadedVideo) return;

    setStarting(true);
    try {
      await api.startVideoProcessing(uploadedVideo.id);
      onUpload(uploadedVideo.id, uploadedVideo.filename);
    } catch (e) {
      alert(`Processing failed to start: ${e}`);
    } finally {
      setStarting(false);
    }
  };

  return (
    <div className="h-full overflow-auto bg-surface p-8 text-gray-100">
      <div className="mx-auto max-w-5xl space-y-6">
        {isMultiSource ? (
          <MultiSourceIntake
            uploadingLabel={uploadingLabel}
            recording={recording}
            uploadedVideo={uploadedVideo}
            sourceAssets={sourceAssets}
            onPickPrimary={() => void pickPrimaryVideo()}
            onPickAsset={(type, accept, label) => pickFile(accept, file => void uploadProjectAsset(type, file, label, { upload_surface: "multi_source_intake" }))}
            onRecord={startRecording}
            onRecordStudio={startStudioRecording}
            onStopRecording={stopRecording}
            studioSettings={studioSettings}
            onStudioSettingsChange={setStudioSettings}
            onDeleteAsset={handleDeleteProjectAsset}
            busy={uploading || starting}
          />
        ) : (
          <SingleVideoIntake
            dragOver={dragOver}
            uploadingLabel={uploadingLabel}
            uploadedVideo={uploadedVideo}
            onDrop={handleDrop}
            onDragOver={() => setDragOver(true)}
            onDragLeave={() => setDragOver(false)}
            onPick={() => void pickPrimaryVideo()}
            isNativeDesktopApp={isNativeDesktopApp}
          />
        )}

        {nativeImportProgress ? (
          <NativeImportStatusCard
            progress={nativeImportProgress}
            onCancel={handleCancelNativeImport}
            cancellable={Boolean(nativeImportActive)}
          />
        ) : null}

        <StructureAssetsPanel
          structureAssets={structureAssets}
          uploadingLabel={uploadingLabel}
          busy={uploading || starting}
          projectReady={Boolean(projectId)}
          onUpload={handleStructureAssetUpload}
          onDelete={handleDeleteProjectAsset}
          pageStart={structurePageStart}
          pageEnd={structurePageEnd}
          onPageStartChange={setStructurePageStart}
          onPageEndChange={setStructurePageEnd}
          onScopeUpdate={handleStructureScopeUpdate}
        />

        <CourseMaterialsPanel
          materials={materials}
          materialUploading={materialUploading}
          onUpload={handleMaterialUpload}
          onDelete={handleDeleteMaterial}
        />

        <div className="flex items-center justify-between gap-4">
          <p className="text-xs text-gray-500">
            {materials.length > 0
              ? `${embeddedMaterials}/${materials.length} material${materials.length === 1 ? "" : "s"} embedded for RAG.`
              : "You can proceed without notes, but RAG context will be limited."}
            {isMultiSource && !uploadedVideo ? " Add a primary timeline or mixed fallback video before processing." : ""}
          </p>
          <button
            onClick={handleStartProcessing}
            disabled={!uploadedVideo || uploading || materialUploading || recording !== null || starting || Boolean(nativeImportActive)}
            className="inline-flex items-center gap-2 rounded-md bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            Start Processing
          </button>
        </div>
      </div>
    </div>
  );
}

function SingleVideoIntake({
  dragOver,
  uploadingLabel,
  uploadedVideo,
  onDrop,
  onDragOver,
  onDragLeave,
  onPick,
  isNativeDesktopApp,
}: {
  dragOver: boolean;
  uploadingLabel: string | null;
  uploadedVideo: UploadedVideo | null;
  onDrop: (event: React.DragEvent) => void;
  onDragOver: () => void;
  onDragLeave: () => void;
  onPick: () => void;
  isNativeDesktopApp: boolean;
}) {
  return (
    <div
      className={`cursor-pointer rounded-lg border-2 border-dashed p-12 text-center transition-all ${
        dragOver ? "border-accent bg-accent/10" : "border-surface-border hover:border-gray-500"
      }`}
      onDragOver={(event) => {
        event.preventDefault();
        onDragOver();
      }}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      onClick={onPick}
    >
      {uploadingLabel ? (
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="h-12 w-12 animate-spin text-accent" />
          <p className="text-lg">{uploadingLabel}</p>
        </div>
      ) : uploadedVideo ? (
        <div className="flex flex-col items-center gap-3">
          <FileVideo className="h-12 w-12 text-accent" />
          <p className="text-lg font-medium">{uploadedVideo.filename}</p>
          <p className="text-sm text-gray-400">Video uploaded. Add notes below, or click here to replace it.</p>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-3">
          <FileVideo className="h-12 w-12 text-gray-400" />
          <p className="text-lg font-medium">Drop the primary project video here</p>
          <p className="text-sm text-gray-400">
            {isNativeDesktopApp
              ? "Click to import natively from disk with progress, speed, ETA, and cancel support (max 10GB)"
              : "or click to browse - resumable chunked upload for MP4, MOV, AVI, WebM (max 10GB)"}
          </p>
        </div>
      )}
    </div>
  );
}

function NativeImportStatusCard({
  progress,
  onCancel,
  cancellable,
}: {
  progress: NativeImportProgress;
  onCancel: () => void;
  cancellable: boolean;
}) {
  return (
    <div className="rounded-lg border border-accent/40 bg-accent/10 p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-white">{progress.message}</p>
          <p className="mt-1 text-xs text-gray-300">{progress.filename}</p>
          <p className="mt-1 text-xs text-gray-400">
            {formatBytes(progress.bytesCopied)} / {formatBytes(progress.totalBytes)}
            {" • "}
            {progress.bytesPerSecond > 0 ? `${formatBytes(progress.bytesPerSecond)}/s` : "Calculating speed"}
            {" • "}
            {progress.etaSeconds != null ? `${formatDuration(progress.etaSeconds)} remaining` : "ETA pending"}
          </p>
        </div>
        {cancellable ? (
          <button
            type="button"
            onClick={onCancel}
            className="inline-flex items-center gap-2 self-start rounded-md border border-surface-border px-3 py-1.5 text-xs font-medium text-gray-200 transition-colors hover:border-accent hover:text-white"
          >
            <Square className="h-3.5 w-3.5" />
            Cancel import
          </button>
        ) : null}
      </div>
      <div className="mt-4 h-2 overflow-hidden rounded-full bg-surface-overlay">
        <div
          className="h-full rounded-full bg-accent transition-[width]"
          style={{ width: `${Math.max(0, Math.min(100, progress.percent))}%` }}
        />
      </div>
      <p className="mt-2 text-right text-xs text-gray-400">{progress.percent.toFixed(1)}%</p>
    </div>
  );
}

function MultiSourceIntake({
  uploadingLabel,
  recording,
  uploadedVideo,
  sourceAssets,
  onPickPrimary,
  onPickAsset,
  onRecord,
  onRecordStudio,
  onStopRecording,
  studioSettings,
  onStudioSettingsChange,
  onDeleteAsset,
  busy,
}: {
  uploadingLabel: string | null;
  recording: RecordingState | null;
  uploadedVideo: UploadedVideo | null;
  sourceAssets: ProjectAsset[];
  onPickPrimary: () => void;
  onPickAsset: (type: ProjectAssetUploadType, accept: string, label: string) => void;
  onRecord: (type: ProjectAssetUploadType, label: string) => void;
  onRecordStudio: () => void;
  onStopRecording: () => void;
  studioSettings: StudioSettings;
  onStudioSettingsChange: (settings: StudioSettings) => void;
  onDeleteAsset: (asset: ProjectAsset) => void;
  busy: boolean;
}) {
  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold text-white">Multi-source intake</h2>
        <p className="mt-1 text-sm text-gray-500">Add or record the teaching sources that make up this project.</p>
      </div>

      <div className="rounded-lg border border-surface-border bg-surface-raised p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h3 className="text-sm font-semibold text-white">Studio composition</h3>
            <p className="mt-1 text-xs leading-5 text-gray-500">
              Choose how screen, webcam, and microphone are composed before or during a studio recording.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:min-w-[360px]">
            {studioLayoutOptions.map(option => (
              <button
                key={option.value}
                type="button"
                onClick={() => onStudioSettingsChange({ ...studioSettings, layout: option.value })}
                disabled={busy && recording === null}
                className={`rounded-md border px-3 py-2 text-left text-xs transition-colors ${
                  studioSettings.layout === option.value
                    ? "border-accent bg-accent/15 text-white"
                    : "border-surface-border bg-surface-overlay text-gray-300 hover:border-accent"
                }`}
              >
                <span className="block font-semibold">{option.label}</span>
                <span className="mt-1 block leading-4 text-gray-500">{option.detail}</span>
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <SourceCard
          icon={MonitorUp}
          title="Primary timeline"
          detail={uploadedVideo ? uploadedVideo.filename : "Mixed fallback or main screen video for processing"}
          primary
          onUpload={onPickPrimary}
          uploadLabel={uploadedVideo ? "Replace" : "Import video"}
          disabled={busy || recording !== null}
        />
        <SourceCard
          icon={Presentation}
          title="Screen + camera studio"
          detail="Record the shared screen with a live camera inset as the primary timeline"
          primary
          onUpload={onPickPrimary}
          uploadLabel="Import mix"
          onRecord={onRecordStudio}
          recordLabel="Record mix"
          disabled={busy || recording !== null}
        />
        <SourceCard
          icon={ScreenShare}
          title="Screen recording"
          detail="Record or import the shared screen as its own source"
          onUpload={() => onPickAsset("screen", "video/*", "Uploading screen source")}
          onRecord={() => onRecord("screen", "screen recording")}
          disabled={busy || recording !== null}
        />
        <SourceCard
          icon={Camera}
          title="Webcam / camera"
          detail="Record or import the presenter camera source"
          onUpload={() => onPickAsset("webcam", "video/*", "Uploading camera source")}
          onRecord={() => onRecord("webcam", "webcam recording")}
          disabled={busy || recording !== null}
        />
        <SourceCard
          icon={Mic}
          title="Separate audio"
          detail="Record microphone audio or import a WAV/MP3/M4A track"
          onUpload={() => onPickAsset("audio", "audio/*", "Uploading audio source")}
          onRecord={() => onRecord("audio", "microphone audio")}
          disabled={busy || recording !== null}
        />
      </div>

      {recording ? (
        <RecordingPreview
          recording={recording}
          studioSettings={studioSettings}
          onStudioSettingsChange={onStudioSettingsChange}
          onStop={onStopRecording}
        />
      ) : uploadingLabel ? (
        <div className="flex items-center gap-2 rounded-md border border-surface-border bg-surface-raised px-4 py-3 text-sm text-gray-300">
          <Loader2 className="h-4 w-4 animate-spin text-accent" />
          {uploadingLabel}
        </div>
      ) : null}

      {sourceAssets.length > 0 ? (
        <div className="rounded-lg border border-surface-border bg-surface-raised p-4">
          <h3 className="text-sm font-semibold text-white">Project sources</h3>
          <div className="mt-3 grid gap-2">
            {sourceAssets.map(asset => (
              <AssetRow key={asset.id} asset={asset} onDelete={onDeleteAsset} />
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function SourceCard({
  icon: Icon,
  title,
  detail,
  primary = false,
  uploadLabel = "Import",
  recordLabel = "Record",
  onUpload,
  onRecord,
  disabled,
}: {
  icon: typeof FileVideo;
  title: string;
  detail: string;
  primary?: boolean;
  uploadLabel?: string;
  recordLabel?: string;
  onUpload: () => void;
  onRecord?: () => void;
  disabled: boolean;
}) {
  return (
    <div className={`rounded-lg border p-4 ${primary ? "border-accent/50 bg-accent/10" : "border-surface-border bg-surface-raised"}`}>
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-surface-overlay text-accent">
          <Icon className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-white">{title}</h3>
          <p className="mt-1 text-xs leading-5 text-gray-500">{detail}</p>
        </div>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onUpload}
          disabled={disabled}
          className="inline-flex items-center gap-2 rounded-md border border-surface-border px-3 py-1.5 text-xs font-medium text-gray-200 transition-colors hover:border-accent hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Upload className="h-3.5 w-3.5" />
          {uploadLabel}
        </button>
        {onRecord ? (
          <button
            type="button"
            onClick={onRecord}
            disabled={disabled}
            className="inline-flex items-center gap-2 rounded-md border border-surface-border px-3 py-1.5 text-xs font-medium text-gray-200 transition-colors hover:border-accent hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Play className="h-3.5 w-3.5" />
            {recordLabel}
          </button>
        ) : null}
      </div>
    </div>
  );
}

function RecordingPreview({
  recording,
  studioSettings,
  onStudioSettingsChange,
  onStop,
}: {
  recording: RecordingState;
  studioSettings: StudioSettings;
  onStudioSettingsChange: (settings: StudioSettings) => void;
  onStop: () => void;
}) {
  const hasVideo = recording.stream.getVideoTracks().length > 0;
  const audioTracks = recording.stream.getAudioTracks().length;
  const audioLevel = useAudioLevel(recording.stream);
  const isStudio = recording.mode === "primary";
  const screenStream = recording.sourceStreams?.[0] ?? null;
  const cameraStream = recording.sourceStreams?.[1] ?? null;
  const dragRef = useRef<{ startX: number; startY: number; initial: StudioOverlaySettings } | null>(null);

  const updateOverlay = (patch: Partial<StudioOverlaySettings>) => {
    onStudioSettingsChange({
      ...studioSettings,
      overlay: {
        ...studioSettings.overlay,
        ...patch,
      },
    });
  };

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!isStudio || studioSettings.layout !== "picture_in_picture") return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = {
      startX: event.clientX,
      startY: event.clientY,
      initial: studioSettings.overlay,
    };
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!dragRef.current) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const dx = ((event.clientX - dragRef.current.startX) / bounds.width) * 100;
    const dy = ((event.clientY - dragRef.current.startY) / bounds.height) * 100;
    updateOverlay({
      xPercent: clampPercent(dragRef.current.initial.xPercent + dx, 0, 100 - studioSettings.overlay.sizePercent),
      yPercent: clampPercent(dragRef.current.initial.yPercent + dy, 0, 100 - (studioSettings.overlay.sizePercent * 9 / 16)),
    });
  };

  const handlePointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!dragRef.current) return;
    event.currentTarget.releasePointerCapture(event.pointerId);
    dragRef.current = null;
  };

  return (
    <div className="grid gap-4 rounded-lg border border-red-400/40 bg-red-500/10 p-4 lg:grid-cols-[minmax(0,1fr)_260px]">
      <div className="min-w-0">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-red-100">Recording {recording.label}</p>
            <p className="mt-1 text-xs text-red-100/70">
              {hasVideo ? "Live monitor" : "Audio-only capture"} / {audioTracks} audio track{audioTracks === 1 ? "" : "s"}
            </p>
          </div>
          <button
            type="button"
            onClick={onStop}
            className="inline-flex items-center gap-2 rounded-md bg-red-500/20 px-3 py-1.5 text-sm font-medium text-red-100 hover:bg-red-500/30"
          >
            <Square className="h-3.5 w-3.5 fill-current" />
            Stop
          </button>
        </div>
        <div className="grid gap-3">
          {hasVideo ? (
            <div
              className="relative aspect-video overflow-hidden rounded-md border border-red-200/20 bg-black"
              onPointerDown={handlePointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
            >
              <PreviewVideo stream={recording.stream} label="Program output" />
              {isStudio && studioSettings.layout === "picture_in_picture" ? (
                <div
                  className="pointer-events-none absolute rounded-md border-2 border-accent bg-accent/10"
                  style={overlayPreviewStyle(studioSettings.overlay)}
                />
              ) : null}
            </div>
          ) : (
            <div className="flex aspect-video items-center justify-center rounded-md border border-red-200/20 bg-black">
              <Mic className="h-10 w-10 text-red-200" />
            </div>
          )}
          {isStudio ? (
            <div className="grid gap-3 md:grid-cols-2">
              <div className="aspect-video overflow-hidden rounded-md border border-surface-border bg-black">
                {screenStream ? <PreviewVideo stream={screenStream} label="Screen source" /> : null}
              </div>
              <div className="aspect-video overflow-hidden rounded-md border border-surface-border bg-black">
                {cameraStream ? <PreviewVideo stream={cameraStream} label="Camera source" /> : null}
              </div>
            </div>
          ) : null}
        </div>
      </div>
      <div className="grid content-start gap-2 text-xs">
        <div className="rounded-md border border-surface-border bg-surface-overlay px-3 py-2">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-gray-100">Mic level</span>
            <span className="text-gray-500">{Math.round(audioLevel * 100)}%</span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-raised">
            <div className="h-full rounded-full bg-green-400 transition-all" style={{ width: `${Math.round(audioLevel * 100)}%` }} />
          </div>
        </div>
        {isStudio ? (
          <div className="rounded-md border border-surface-border bg-surface-overlay px-3 py-2">
            <span className="font-semibold text-gray-100">Studio controls</span>
            <div className="mt-2 grid grid-cols-2 gap-1">
              {studioLayoutOptions.map(option => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => onStudioSettingsChange({ ...studioSettings, layout: option.value })}
                  className={`rounded px-2 py-1 text-left ${studioSettings.layout === option.value ? "bg-accent text-white" : "bg-surface-raised text-gray-300"}`}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <label className="mt-3 block text-gray-400">
              Camera size
              <input
                type="range"
                min={16}
                max={36}
                value={studioSettings.overlay.sizePercent}
                onChange={(event) => updateOverlay({ sizePercent: Number(event.target.value) })}
                disabled={studioSettings.layout !== "picture_in_picture"}
                className="mt-1 w-full accent-purple-500"
              />
            </label>
          </div>
        ) : null}
        <StudioRole label="Screen" active={recording.type === "screen" || recording.mode === "primary"} detail="Slides, demos, or shared desktop" />
        <StudioRole label="Camera" active={recording.type === "webcam" || recording.type === "camera" || recording.mode === "primary"} detail="Lecturer face overlay source" />
        <StudioRole label="Audio" active={audioTracks > 0} detail="Voice track for transcript and sync" />
        <StudioRole label="Slides/notes" active={false} detail="Upload below for structure and layout cues" />
      </div>
    </div>
  );
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size >= 100 || unitIndex === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[unitIndex]}`;
}

function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "0s";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.round(seconds % 60);
  if (minutes < 60) return `${minutes}m ${remainingSeconds}s`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return `${hours}h ${remainingMinutes}m`;
}

function PreviewVideo({ stream, label }: { stream: MediaStream; label: string }) {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (!videoRef.current) return;
    videoRef.current.srcObject = stream;
    return () => {
      if (videoRef.current) videoRef.current.srcObject = null;
    };
  }, [stream]);

  return (
    <div className="relative h-full w-full">
      <video ref={videoRef} muted playsInline autoPlay className="h-full w-full object-contain" />
      <div className="absolute left-2 top-2 rounded bg-black/65 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-gray-200">
        {label}
      </div>
    </div>
  );
}

function useAudioLevel(stream: MediaStream): number {
  const [level, setLevel] = useState(0);

  useEffect(() => {
    if (stream.getAudioTracks().length === 0) {
      setLevel(0);
      return;
    }
    const context = new AudioContext();
    void context.resume();
    const source = context.createMediaStreamSource(stream);
    const analyser = context.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);
    const data = new Uint8Array(analyser.frequencyBinCount);
    let frame = 0;

    const tick = () => {
      analyser.getByteFrequencyData(data);
      const average = data.reduce((sum, value) => sum + value, 0) / Math.max(1, data.length);
      setLevel(Math.min(1, average / 96));
      frame = window.requestAnimationFrame(tick);
    };
    tick();

    return () => {
      window.cancelAnimationFrame(frame);
      source.disconnect();
      void context.close();
    };
  }, [stream]);

  return level;
}

function StudioRole({ label, active, detail }: { label: string; active: boolean; detail: string }) {
  return (
    <div className={`rounded-md border px-3 py-2 ${active ? "border-green-400/30 bg-green-500/10" : "border-surface-border bg-surface-overlay"}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold text-gray-100">{label}</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${active ? "bg-green-500/20 text-green-300" : "bg-surface-raised text-gray-500"}`}>
          {active ? "live" : "idle"}
        </span>
      </div>
      <p className="mt-1 leading-4 text-gray-500">{detail}</p>
    </div>
  );
}

function StructureAssetsPanel({
  structureAssets,
  uploadingLabel,
  busy,
  projectReady,
  onUpload,
  onDelete,
  pageStart,
  pageEnd,
  onPageStartChange,
  onPageEndChange,
  onScopeUpdate,
}: {
  structureAssets: ProjectAsset[];
  uploadingLabel: string | null;
  busy: boolean;
  projectReady: boolean;
  onUpload: (option: StructureUploadOption, event: React.ChangeEvent<HTMLInputElement>) => void;
  onDelete: (asset: ProjectAsset) => void;
  pageStart: string;
  pageEnd: string;
  onPageStartChange: (value: string) => void;
  onPageEndChange: (value: string) => void;
  onScopeUpdate: (asset: ProjectAsset, pageStart: number | null, pageEnd: number | null) => Promise<void>;
}) {
  const unscopedAssets = structureAssets.filter(asset => {
    const metadata = (asset.metadata_json.user_metadata || {}) as Record<string, unknown>;
    return !metadata.slide_page_start || !metadata.slide_page_end;
  });
  return (
    <div className="rounded-lg border border-surface-border bg-surface-raised p-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <Presentation className="h-4 w-4 text-accent" />
          <h2 className="text-sm font-semibold">Lecture Structure Assets</h2>
        </div>
        <div className="flex flex-wrap gap-2">
          {structureUploadOptions.map((option) => {
            const disabled = !projectReady || busy;
            const Icon = option.icon === "slides" ? Presentation : FileText;
            return (
              <label
                key={`${option.label}-${option.accept}`}
                className={`inline-flex items-center gap-1 rounded-md border px-3 py-1.5 text-xs transition-colors ${
                  disabled
                    ? "cursor-not-allowed border-surface-border text-gray-600"
                    : "cursor-pointer border-surface-border text-gray-300 hover:border-accent hover:text-accent"
                }`}
              >
                {uploadingLabel === `Uploading ${option.label}` ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Icon className="h-3 w-3" />
                )}
                {option.label}
                <input
                  type="file"
                  className="hidden"
                  accept={option.accept}
                  disabled={disabled}
                  onChange={(event) => onUpload(option, event)}
                />
              </label>
            );
          })}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-end gap-3 border-t border-surface-border pt-4">
        <div>
          <p className="text-xs font-medium text-gray-300">Pages covered by this video</p>
          <p className="mt-1 text-[11px] text-gray-500">Strongly recommended when one PDF or deck is shared by multiple recordings. Overlapping ranges are allowed.</p>
        </div>
        <label className="text-[11px] text-gray-500">
          Start page
          <input
            type="number"
            min={1}
            value={pageStart}
            onChange={(event) => onPageStartChange(event.target.value)}
            className="mt-1 block w-24 rounded-md border border-surface-border bg-surface-overlay px-2 py-1.5 text-xs text-gray-200"
          />
        </label>
        <label className="text-[11px] text-gray-500">
          End page
          <input
            type="number"
            min={1}
            value={pageEnd}
            onChange={(event) => onPageEndChange(event.target.value)}
            className="mt-1 block w-24 rounded-md border border-surface-border bg-surface-overlay px-2 py-1.5 text-xs text-gray-200"
          />
        </label>
      </div>

      {unscopedAssets.length > 0 && (
        <div className="mt-3 rounded-md border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-xs leading-5 text-amber-200">
          {unscopedAssets.length} structure asset{unscopedAssets.length === 1 ? " has" : "s have"} no saved page range. Agent 4 can infer it, but shared decks are substantially more accurate when this video's page range is saved.
        </div>
      )}

      {structureAssets.length === 0 ? (
        <p className="mt-4 text-xs text-gray-500">
          Add slide decks, exported slide PDFs, or lecture notes to preserve project structure for section inference.
        </p>
      ) : (
        <div className="mt-4 space-y-2">
          {structureAssets.map(asset => (
            <StructureAssetRow key={asset.id} asset={asset} onDelete={onDelete} onScopeUpdate={onScopeUpdate} />
          ))}
        </div>
      )}
    </div>
  );
}

function StructureAssetRow({
  asset,
  onDelete,
  onScopeUpdate,
}: {
  asset: ProjectAsset;
  onDelete: (asset: ProjectAsset) => void;
  onScopeUpdate: (asset: ProjectAsset, pageStart: number | null, pageEnd: number | null) => Promise<void>;
}) {
  const userMetadata = (asset.metadata_json.user_metadata || {}) as Record<string, unknown>;
  const [start, setStart] = useState(String(userMetadata.slide_page_start || ""));
  const [end, setEnd] = useState(String(userMetadata.slide_page_end || ""));
  const [saving, setSaving] = useState(false);
  const save = async () => {
    if ((start && !end) || (!start && end) || (start && end && Number(end) < Number(start))) return;
    setSaving(true);
    try {
      await onScopeUpdate(asset, start ? Number(start) : null, end ? Number(end) : null);
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="rounded-md bg-surface-overlay px-3 py-2 text-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-gray-200">{asset.original_filename}</p>
          <p className="text-xs capitalize text-gray-500">
            {structureAssetLabel(asset)}{asset.document_format ? ` / ${asset.document_format}` : ""}
          </p>
        </div>
        <button onClick={() => onDelete(asset)} className="text-gray-500 hover:text-red-400" aria-label={`Remove ${asset.original_filename}`}>
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="mt-2 flex items-end gap-2">
        <label className="text-[10px] text-gray-500">Start<input type="number" min={1} value={start} onChange={event => setStart(event.target.value)} className="mt-1 block w-20 rounded border border-surface-border bg-surface-raised px-2 py-1 text-xs text-gray-200" /></label>
        <label className="text-[10px] text-gray-500">End<input type="number" min={1} value={end} onChange={event => setEnd(event.target.value)} className="mt-1 block w-20 rounded border border-surface-border bg-surface-raised px-2 py-1 text-xs text-gray-200" /></label>
        <button type="button" onClick={() => void save()} disabled={saving} className="rounded border border-surface-border px-2 py-1 text-xs text-gray-300 hover:border-accent disabled:opacity-50">
          {saving ? "Saving" : "Save range"}
        </button>
      </div>
    </div>
  );
}

function CourseMaterialsPanel({
  materials,
  materialUploading,
  onUpload,
  onDelete,
}: {
  materials: MaterialItem[];
  materialUploading: boolean;
  onUpload: (event: React.ChangeEvent<HTMLInputElement>) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <div className="rounded-lg border border-surface-border bg-surface-raised p-6">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BookOpen className="h-4 w-4 text-accent" />
          <h2 className="text-sm font-semibold">Course Materials (RAG Knowledge Base)</h2>
        </div>
        <label className="cursor-pointer text-xs text-accent transition-colors hover:text-accent-hover">
          {materialUploading ? (
            <span className="flex items-center gap-1"><Loader2 className="h-3 w-3 animate-spin" /> Uploading...</span>
          ) : (
            <span className="flex items-center gap-1"><Upload className="h-3 w-3" /> Add PDF / PPTX / DOCX</span>
          )}
          <input type="file" className="hidden" accept=".pdf,.pptx,.docx,.txt,.md" onChange={onUpload} disabled={materialUploading} />
        </label>
      </div>

      {materials.length === 0 ? (
        <p className="text-xs text-gray-500">
          No materials uploaded. Upload lecture notes, slides, or textbook chapters to help the AI understand what content is important.
        </p>
      ) : (
        <div className="space-y-2">
          {materials.map(material => (
            <div key={material.id} className="flex items-center justify-between rounded-md bg-surface-overlay px-3 py-2 text-sm">
              <div>
                <span className="text-gray-200">{material.filename}</span>
                <span className="ml-2 text-gray-500">({material.chunk_count} chunks)</span>
              </div>
              <button onClick={() => onDelete(material.id)} className="text-gray-500 hover:text-red-400">
                <X className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AssetRow({ asset, onDelete }: { asset: ProjectAsset; onDelete: (asset: ProjectAsset) => void }) {
  return (
    <div className="flex items-center justify-between rounded-md bg-surface-overlay px-3 py-2 text-sm">
      <div className="min-w-0">
        <p className="truncate text-gray-200">{asset.original_filename}</p>
        <p className="text-xs capitalize text-gray-500">
          {sourceRoles.has(asset.role) ? sourceAssetLabel(asset) : structureAssetLabel(asset)}
          {asset.document_format ? ` / ${asset.document_format}` : ""}
        </p>
      </div>
      {!asset.is_primary ? (
        <button onClick={() => onDelete(asset)} className="text-gray-500 hover:text-red-400" aria-label={`Remove ${asset.original_filename}`}>
          <X className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  );
}

function videoToUploaded(video?: Video | null): UploadedVideo | null {
  if (!video) return null;
  return {
    id: video.id,
    filename: video.original_filename,
    projectId: video.project_id,
  };
}

function isProjectNotFoundError(error: unknown) {
  const message = String(error instanceof Error ? error.message : error || "");
  return message.includes("404") && message.toLowerCase().includes("project not found");
}

function drawStudioFrame(
  ctx: CanvasRenderingContext2D,
  screenVideo: HTMLVideoElement,
  cameraVideo: HTMLVideoElement,
  width: number,
  height: number,
  settings: StudioSettings,
) {
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, width, height);

  if (settings.layout === "camera_full") {
    drawVideoCover(ctx, cameraVideo, 0, 0, width, height);
    return;
  }

  if (settings.layout === "side_by_side") {
    const screenWidth = Math.round(width * 0.64);
    drawVideoContain(ctx, screenVideo, 0, 0, screenWidth, height);
    drawVideoCover(ctx, cameraVideo, screenWidth, 0, width - screenWidth, height);
    return;
  }

  drawVideoContain(ctx, screenVideo, 0, 0, width, height);
  if (settings.layout === "screen_only") return;

  const overlay = overlayCanvasRect(settings.overlay, width, height);
  ctx.fillStyle = "rgba(0,0,0,0.68)";
  ctx.fillRect(overlay.x - 8, overlay.y - 8, overlay.width + 16, overlay.height + 16);
  drawVideoCover(ctx, cameraVideo, overlay.x, overlay.y, overlay.width, overlay.height);
}

function drawVideoContain(
  ctx: CanvasRenderingContext2D,
  video: HTMLVideoElement,
  x: number,
  y: number,
  width: number,
  height: number,
) {
  if (video.readyState < 2) return;
  const sourceWidth = video.videoWidth || width;
  const sourceHeight = video.videoHeight || height;
  const scale = Math.min(width / sourceWidth, height / sourceHeight);
  const drawWidth = sourceWidth * scale;
  const drawHeight = sourceHeight * scale;
  const drawX = x + (width - drawWidth) / 2;
  const drawY = y + (height - drawHeight) / 2;
  ctx.drawImage(video, drawX, drawY, drawWidth, drawHeight);
}

function drawVideoCover(
  ctx: CanvasRenderingContext2D,
  video: HTMLVideoElement,
  x: number,
  y: number,
  width: number,
  height: number,
) {
  if (video.readyState < 2) return;
  const sourceWidth = video.videoWidth || width;
  const sourceHeight = video.videoHeight || height;
  const scale = Math.max(width / sourceWidth, height / sourceHeight);
  const cropWidth = width / scale;
  const cropHeight = height / scale;
  const sx = Math.max(0, (sourceWidth - cropWidth) / 2);
  const sy = Math.max(0, (sourceHeight - cropHeight) / 2);
  ctx.drawImage(video, sx, sy, cropWidth, cropHeight, x, y, width, height);
}

function overlayCanvasRect(overlay: StudioOverlaySettings, canvasWidth: number, canvasHeight: number) {
  const width = Math.round(canvasWidth * overlay.sizePercent / 100);
  const height = Math.round(width * 9 / 16);
  const maxX = canvasWidth - width;
  const maxY = canvasHeight - height;
  return {
    x: Math.round(Math.min(maxX, Math.max(0, canvasWidth * overlay.xPercent / 100))),
    y: Math.round(Math.min(maxY, Math.max(0, canvasHeight * overlay.yPercent / 100))),
    width,
    height,
  };
}

function overlayPreviewStyle(overlay: StudioOverlaySettings): CSSProperties {
  return {
    left: `${overlay.xPercent}%`,
    top: `${overlay.yPercent}%`,
    width: `${overlay.sizePercent}%`,
    aspectRatio: "16 / 9",
  };
}

function clampPercent(value: number, min: number, max: number): number {
  return Math.round(Math.min(max, Math.max(min, value)) * 10) / 10;
}

function preferredMimeType(assetType: ProjectAssetUploadType): string {
  const candidates = assetType === "audio"
    ? ["audio/ogg;codecs=opus", "audio/webm;codecs=opus", "audio/webm"]
    : ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"];
  return candidates.find(candidate => MediaRecorder.isTypeSupported(candidate)) ?? "";
}
