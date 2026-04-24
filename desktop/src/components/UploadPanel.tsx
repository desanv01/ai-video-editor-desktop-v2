import { useState, useCallback, useEffect } from "react";
import { Upload, FileVideo, BookOpen, X, Loader2, Play } from "lucide-react";
import * as api from "../lib/api";

interface Props {
  onUpload: (videoId: string, filename: string) => void;
}

export function UploadPanel({ onUpload }: Props) {
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [materials, setMaterials] = useState<{ id: string; filename: string; chunk_count: number }[]>([]);
  const [materialUploading, setMaterialUploading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [uploadedVideo, setUploadedVideo] = useState<{ id: string; filename: string } | null>(null);
  const embeddedMaterials = materials.filter(m => m.chunk_count > 0).length;

  // Load existing materials on mount
  useEffect(() => {
    api.listMaterials().then(setMaterials).catch(() => {});
  }, []);

  const handleFile = useCallback(async (file: File) => {
    if (uploading || starting) return;

    if (!file.type.startsWith("video/")) {
      alert("Please upload a video file (MP4, MOV, AVI, WebM)");
      return;
    }

    setUploading(true);
    try {
      const result = await api.uploadVideo(file);
      setUploadedVideo({ id: result.id, filename: file.name });
    } catch (e) {
      alert(`Upload failed: ${e}`);
    } finally {
      setUploading(false);
    }
  }, [uploading, starting]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }, [handleFile]);

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
    <div className="h-full flex items-center justify-center p-8">
      <div className="max-w-2xl w-full space-y-8">
        {/* ── Video Upload Zone ── */}
        <div
          className={`border-2 border-dashed rounded-xl p-12 text-center transition-all cursor-pointer
            ${dragOver ? "border-accent bg-accent/10" : "border-surface-border hover:border-gray-500"}`}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          onClick={() => {
            if (uploading || starting) return;
            const input = document.createElement("input");
            input.type = "file";
            input.accept = "video/*";
            input.onchange = (e) => {
              const file = (e.target as HTMLInputElement).files?.[0];
              if (file) handleFile(file);
            };
            input.click();
          }}
        >
          {uploading ? (
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="w-12 h-12 text-accent animate-spin" />
              <p className="text-lg">Uploading video...</p>
            </div>
          ) : uploadedVideo ? (
            <div className="flex flex-col items-center gap-3">
              <FileVideo className="w-12 h-12 text-accent" />
              <p className="text-lg font-medium">{uploadedVideo.filename}</p>
              <p className="text-sm text-gray-400">Video uploaded. Add notes below, or click here to replace it.</p>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-3">
              <FileVideo className="w-12 h-12 text-gray-400" />
              <p className="text-lg font-medium">Drop a lecture video here</p>
              <p className="text-sm text-gray-400">or click to browse — MP4, MOV, AVI, WebM (max 500MB)</p>
            </div>
          )}
        </div>

        {/* ── Course Materials ── */}
        <div className="bg-surface-raised rounded-xl p-6 border border-surface-border">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <BookOpen className="w-4 h-4 text-accent" />
              <h2 className="text-sm font-semibold">Course Materials (RAG Knowledge Base)</h2>
            </div>
            <label className="text-xs text-accent hover:text-accent-hover cursor-pointer transition-colors">
              {materialUploading ? (
                <span className="flex items-center gap-1"><Loader2 className="w-3 h-3 animate-spin" /> Uploading...</span>
              ) : (
                <span className="flex items-center gap-1"><Upload className="w-3 h-3" /> Add PDF / PPTX / DOCX</span>
              )}
              <input type="file" className="hidden" accept=".pdf,.pptx,.docx,.txt,.md"
                onChange={handleMaterialUpload} disabled={materialUploading} />
            </label>
          </div>

          {materials.length === 0 ? (
            <p className="text-xs text-gray-500">
              No materials uploaded. Upload lecture notes, slides, or textbook chapters
              to help the AI understand what content is important.
            </p>
          ) : (
            <div className="space-y-2">
              {materials.map(m => (
                <div key={m.id} className="flex items-center justify-between bg-surface-overlay rounded-lg px-3 py-2 text-sm">
                  <div>
                    <span className="text-gray-200">{m.filename}</span>
                    <span className="text-gray-500 ml-2">({m.chunk_count} chunks)</span>
                  </div>
                  <button onClick={() => handleDeleteMaterial(m.id)} className="text-gray-500 hover:text-red-400">
                    <X className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-4">
          <p className="text-xs text-gray-500">
            {materials.length > 0
              ? `${embeddedMaterials}/${materials.length} material${materials.length === 1 ? "" : "s"} embedded for RAG.`
              : "You can proceed without notes, but RAG context will be limited."}
          </p>
          <button
            onClick={handleStartProcessing}
            disabled={!uploadedVideo || uploading || materialUploading || starting}
            className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            {starting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            Start Processing
          </button>
        </div>
      </div>
    </div>
  );
}
