import { useLayoutEffect, useRef, useState } from "react";
import * as api from "../lib/api";

interface Props {
  sourceUrl: string | null;
  label: string;
  currentTime: number;
  offsetSeconds: number;
  isPlaying: boolean;
}

export function SyncedSourceVideo(props: Props) {
  // A new media identity owns a new element; late play/fetch completions cannot
  // affect the element used by a different source or project.
  return <OwnedSourceVideo key={props.sourceUrl ?? "unavailable"} {...props} />;
}

function OwnedSourceVideo({ sourceUrl, label, currentTime, offsetSeconds, isPlaying }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const clock = useRef({ currentTime, offsetSeconds, isPlaying });
  const syncRef = useRef<(() => void) | null>(null);
  const [mediaUrl, setMediaUrl] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useLayoutEffect(() => {
    clock.current = { currentTime, offsetSeconds, isPlaying };
    syncRef.current?.();
  }, [currentTime, offsetSeconds, isPlaying]);

  useLayoutEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    if (!sourceUrl) return;
    if (!api.isNativeBridgeEnabled()) {
      setMediaUrl(sourceUrl);
    } else {
      const parsed = new URL(sourceUrl, window.location.href);
      void api.fetchEngineResource(parsed.pathname + parsed.search).then(blob => {
        if (!active) return;
        objectUrl = URL.createObjectURL(blob);
        setMediaUrl(objectUrl);
      }).catch(() => {
        if (active) setError("This source could not be loaded.");
      });
    }
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [sourceUrl]);

  useLayoutEffect(() => {
    const video = videoRef.current;
    if (!video || !mediaUrl) return;
    let active = true;
    let pendingPlay = false;
    let playFailed = false;
    const wantsPlayback = () => {
      const { currentTime: time, offsetSeconds: offset, isPlaying: playing } = clock.current;
      const sourceTime = (Number.isFinite(time) ? time : 0) - (Number.isFinite(offset) ? offset : 0);
      return playing && sourceTime >= 0 && (!Number.isFinite(video.duration) || sourceTime < video.duration);
    };
    const sync = () => {
      if (!active || video.readyState < 1) return;
      const { currentTime: time, offsetSeconds: offset, isPlaying: playing } = clock.current;
      let target = Math.round(Math.max(0, (Number.isFinite(time) ? time : 0) - (Number.isFinite(offset) ? offset : 0)) * 1000) / 1000;
      if (Number.isFinite(video.duration) && video.duration >= 0) target = Math.min(target, video.duration);
      // Paused scrubbing is precise; normal playback tolerates small drift so
      // timeupdate does not repeatedly interrupt decoding with tiny seeks.
      if (!video.seeking && Math.abs(video.currentTime - target) > (playing ? 0.2 : 0.015)) {
        try { video.currentTime = target; } catch { /* Wait for usable metadata/seekable media. */ }
      }
      if (!wantsPlayback()) {
        video.pause();
      } else if (video.paused && !pendingPlay && !playFailed) {
        pendingPlay = true;
        void video.play().then(() => {
          pendingPlay = false;
          if (!active) {
            if (videoRef.current !== video || !syncRef.current) video.pause();
          } else if (!wantsPlayback()) video.pause();
        }).catch(reason => {
          pendingPlay = false;
          if (!active) {
            if (videoRef.current !== video || !syncRef.current) video.pause();
            return;
          }
          if (wantsPlayback() && !(reason instanceof DOMException && reason.name === "AbortError")) {
            playFailed = true;
            setError("This source could not play. Primary playback remains available.");
          }
        });
      }
    };
    const metadata = () => { if (active) { setReady(true); sync(); } };
    const failed = () => { if (active) { video.pause(); setError("This source is unavailable or cannot be decoded."); } };
    syncRef.current = sync;
    video.muted = true;
    // Re-establish src after an effect cleanup/replay on the same element.
    video.setAttribute("src", mediaUrl);
    video.addEventListener("loadedmetadata", metadata);
    video.addEventListener("durationchange", sync);
    video.addEventListener("canplay", sync);
    video.addEventListener("seeked", sync);
    video.addEventListener("error", failed);
    if (video.readyState >= 1) metadata();
    return () => {
      active = false;
      if (syncRef.current === sync) syncRef.current = null;
      video.removeEventListener("loadedmetadata", metadata);
      video.removeEventListener("durationchange", sync);
      video.removeEventListener("canplay", sync);
      video.removeEventListener("seeked", sync);
      video.removeEventListener("error", failed);
      video.pause();
      video.removeAttribute("src");
      video.load();
    };
  }, [mediaUrl]);

  return (
    <div className="relative h-full w-full overflow-hidden bg-black">
      <video ref={videoRef} src={mediaUrl ?? undefined} muted playsInline preload="metadata" aria-label={label} className="h-full w-full object-contain" />
      <span className="pointer-events-none absolute bottom-1 left-1 right-1 truncate rounded bg-black/75 px-2 py-1 text-xs text-gray-100" title={label}>{label}</span>
      {(!sourceUrl || error || !ready) && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/75 p-3 text-center text-xs text-gray-100" role="status">
          {error || (!sourceUrl ? "Selected video source unavailable" : "Loading source preview…")}
        </div>
      )}
    </div>
  );
}
