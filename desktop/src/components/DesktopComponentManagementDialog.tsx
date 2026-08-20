import { useEffect, useState } from "react";
import type { ComponentStatusResult } from "../componentManager.ts";
import type { SupervisorStatus } from "../desktopV2.ts";
import * as api from "../lib/api";
import {
  defaultSetupState,
  setupClient,
  type SetupCatalogInfo,
  type SetupState,
} from "../setupCenter.ts";
import { SetupCenterPanel } from "./SetupCenterPanel";
import { X } from "lucide-react";
import { componentManager } from "../componentManager.ts";

export function DesktopComponentManagementDialog({ onClose }: { onClose: () => void }) {
  const [state, setState] = useState<SetupState>(() => defaultSetupState());
  const [catalog, setCatalog] = useState<SetupCatalogInfo | null>(null);
  const [statuses, setStatuses] = useState<ComponentStatusResult[]>([]);
  const [supervisor, setSupervisor] = useState<SupervisorStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([
      setupClient.getState().catch(() => defaultSetupState()),
      setupClient.getCatalog().catch(() => null),
      componentManager.status().catch(() => []),
      api.getSupervisorStatus().catch(() => null),
    ]).then(([nextState, nextCatalog, nextStatuses, nextSupervisor]) => {
      if (cancelled) return;
      setState(nextState);
      setCatalog(nextCatalog);
      setStatuses(nextStatuses);
      setSupervisor(nextSupervisor);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="fixed inset-0 z-50 overflow-auto bg-black/70 p-4 backdrop-blur-sm sm:p-8" role="dialog" aria-modal="true" aria-labelledby="desktop-management-dialog-title">
      <div className="mx-auto max-w-6xl">
        <div className="mb-3 flex items-center justify-between gap-3 rounded-xl border border-surface-border bg-surface-raised px-4 py-3">
          <p id="desktop-management-dialog-title" className="text-sm font-semibold text-white">Desktop component management</p>
          <button type="button" onClick={onClose} aria-label="Close desktop component management" className="rounded-lg p-2 text-gray-400 hover:bg-surface-overlay hover:text-white focus:outline-none focus:ring-2 focus:ring-accent/70"><X className="h-4 w-4" aria-hidden="true" /></button>
        </div>
        {loading ? <div className="rounded-2xl border border-surface-border bg-surface-raised p-8 text-center text-sm text-gray-400">Reading signed catalog and installed component state…</div> : <SetupCenterPanel bootstrap={null} supervisor={supervisor} initialStatuses={statuses} initialState={state} initialCatalog={catalog} setupRequired={false} initialStage="management" onSupervisorStatus={setSupervisor} onSetupComplete={(nextSupervisor, nextState) => { setSupervisor(nextSupervisor); setState(nextState); }} onLaunchEditor={onClose} onOpenDiagnostics={onClose} />}
      </div>
    </div>
  );
}
