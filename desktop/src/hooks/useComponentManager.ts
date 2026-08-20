import { useCallback, useEffect, useMemo, useState } from "react";
import {
  componentManager,
  type ComponentProgress,
  type ComponentStatusResult,
  type ComponentManagerError,
} from "../componentManager.ts";

export interface ComponentManagerState {
  statuses: ComponentStatusResult[];
  progressByOperation: Record<string, ComponentProgress>;
  loading: boolean;
  error: ComponentManagerError | null;
  refresh: () => Promise<void>;
}

function normalizeError(error: unknown): ComponentManagerError {
  if (typeof error === "object" && error !== null && "code" in error && "message" in error) {
    const candidate = error as Partial<ComponentManagerError>;
    return {
      code: typeof candidate.code === "string" ? candidate.code : "COMPONENT_OPERATION_FAILED",
      message: typeof candidate.message === "string" ? candidate.message : "Component operation failed.",
      retryable: candidate.retryable === true,
      remediationCodes: Array.isArray(candidate.remediationCodes)
        ? candidate.remediationCodes.filter((code): code is string => typeof code === "string")
        : [],
    };
  }
  return {
    code: "COMPONENT_OPERATION_FAILED",
    message: "Desktop V2 could not complete the component operation.",
    retryable: true,
    remediationCodes: [],
  };
}

export function useComponentManager(componentId?: string): ComponentManagerState {
  const [statuses, setStatuses] = useState<ComponentStatusResult[]>([]);
  const [progressByOperation, setProgressByOperation] = useState<Record<string, ComponentProgress>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ComponentManagerError | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const next = await componentManager.status(componentId);
      setStatuses(next);
      setError(null);
    } catch (operationError) {
      setError(normalizeError(operationError));
    } finally {
      setLoading(false);
    }
  }, [componentId]);

  useEffect(() => {
    void refresh();
    let disposed = false;
    let unlisten: (() => void) | undefined;
    void componentManager.onProgress((progress) => {
      if (disposed) return;
      setProgressByOperation((current) => ({ ...current, [progress.operationId]: progress }));
    }).then((dispose) => {
      if (disposed) dispose();
      else unlisten = dispose;
    });
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [refresh]);

  return useMemo(
    () => ({ statuses, progressByOperation, loading, error, refresh }),
    [statuses, progressByOperation, loading, error, refresh],
  );
}
