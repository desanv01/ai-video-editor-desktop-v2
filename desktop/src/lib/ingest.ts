import type { ProjectAsset } from "../types/api";

export const MAX_VIDEO_SIZE_BYTES = 10 * 1024 * 1024 * 1024;
export const SUPPORTED_VIDEO_EXTENSIONS = [".mp4", ".mpeg", ".mpg", ".mov", ".avi", ".webm", ".mkv"] as const;

export type IngestValidation = {
  valid: boolean;
  errors: string[];
  warnings: string[];
  duplicate: boolean;
  extension: string;
};

export function validateVideoFile(
  file: Pick<File, "name" | "size" | "type">,
  existingAssets: Pick<ProjectAsset, "original_filename" | "file_size_bytes">[] = [],
): IngestValidation {
  const extension = `.${file.name.split(".").pop()?.toLowerCase() ?? ""}`;
  const errors: string[] = [];
  const warnings: string[] = [];
  if (!SUPPORTED_VIDEO_EXTENSIONS.includes(extension as (typeof SUPPORTED_VIDEO_EXTENSIONS)[number])) {
    errors.push(`Unsupported video format. Use ${SUPPORTED_VIDEO_EXTENSIONS.join(", ")}.`);
  }
  if (file.size <= 0) errors.push("The selected file is empty.");
  if (file.size > MAX_VIDEO_SIZE_BYTES) errors.push("The selected file is larger than the 10 GB limit.");
  if (file.type && !file.type.startsWith("video/") && extension !== ".mkv") {
    warnings.push("The browser MIME type is unusual; the backend will validate the media container.");
  }
  const duplicate = existingAssets.some(asset =>
    asset.original_filename.toLowerCase() === file.name.toLowerCase()
    && asset.file_size_bytes === file.size,
  );
  if (duplicate) warnings.push("A source with the same name and size is already in this project.");
  return { valid: errors.length === 0, errors, warnings, duplicate, extension };
}

export function formatBytes(bytes: number | null | undefined): string {
  if (!Number.isFinite(bytes) || !bytes || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / (1024 ** index)).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}
