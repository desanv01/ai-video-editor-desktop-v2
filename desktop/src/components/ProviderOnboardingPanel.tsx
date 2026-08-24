import { CheckCircle2, KeyRound, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { providerCredentials, PROVIDER_SECRET_KEYS, redactProviderError, type ProviderCredentialStatus } from "../providerCredentials";

const DEFAULT_PROVIDER = "local";

export function ProviderOnboardingPanel() {
  const [providerId, setProviderId] = useState(DEFAULT_PROVIDER);
  const [keyName, setKeyName] = useState<(typeof PROVIDER_SECRET_KEYS)[number]["value"]>("api_key");
  const [secret, setSecret] = useState("");
  const [status, setStatus] = useState<ProviderCredentialStatus | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    setBusy(true);
    setMessage(null);
    try {
      setStatus(await providerCredentials.status(providerId, keyName));
    } catch (error) {
      setStatus(null);
      setMessage(redactProviderError(error));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => { void refresh(); }, [providerId, keyName]);

  const test = async () => {
    if (!secret) {
      setMessage("Enter a provider credential before testing it.");
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      setStatus(await providerCredentials.test(providerId, keyName, secret));
      setSecret("");
      setMessage("Protected credential test passed. The value is not retained in this form.");
    } catch (error) {
      setMessage(redactProviderError(error));
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    setBusy(true);
    setMessage(null);
    try {
      setStatus(await providerCredentials.clear(providerId, keyName));
      setSecret("");
      setMessage("Protected credential cleared.");
    } catch (error) {
      setMessage(redactProviderError(error));
    } finally {
      setBusy(false);
    }
  };

  return <section className="mt-6 rounded-xl border border-surface-border bg-surface-overlay p-4" aria-labelledby="provider-onboarding-title">
    <div className="flex items-start gap-3"><KeyRound className="mt-0.5 h-5 w-5 shrink-0 text-accent" aria-hidden="true" /><div><h3 id="provider-onboarding-title" className="text-sm font-semibold text-white">Provider onboarding</h3><p className="mt-1 text-xs leading-5 text-gray-400">Local/manual is the default. Add lecturer-owned provider password fields only after authenticated engine readiness. Values are stored in the current Windows user’s Credential Manager and never in setup state, logs, or diagnostics.</p></div></div>
    <div className="mt-4 grid gap-3 sm:grid-cols-3"><label className="text-xs text-gray-300">Provider<input value={providerId} onChange={event => setProviderId(event.target.value)} maxLength={64} className="mt-1 w-full rounded-lg border border-surface-border bg-surface-raised px-3 py-2 text-xs text-white" /></label><label className="text-xs text-gray-300">Password-field key<select value={keyName} onChange={event => setKeyName(event.target.value as typeof keyName)} className="mt-1 w-full rounded-lg border border-surface-border bg-surface-raised px-3 py-2 text-xs text-white">{PROVIDER_SECRET_KEYS.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label><label className="text-xs text-gray-300">Credential<input type="password" value={secret} onChange={event => setSecret(event.target.value)} maxLength={4096} autoComplete="off" placeholder={status?.configured ? "Configured — enter to replace" : "Enter manually"} className="mt-1 w-full rounded-lg border border-surface-border bg-surface-raised px-3 py-2 text-xs text-white" /></label></div>
    <div className="mt-3 flex flex-wrap items-center gap-2"><button type="button" onClick={() => void test()} disabled={busy || !secret} className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-xs font-medium text-white disabled:opacity-50"><CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" /> Test and store</button><button type="button" onClick={() => void clear()} disabled={busy || !status?.configured} className="inline-flex items-center gap-1.5 rounded-lg border border-rose-400/30 px-3 py-2 text-xs font-medium text-rose-100 disabled:opacity-50"><Trash2 className="h-3.5 w-3.5" aria-hidden="true" /> Clear</button><button type="button" onClick={() => void refresh()} disabled={busy} className="inline-flex items-center gap-1.5 rounded-lg border border-surface-border px-3 py-2 text-xs text-gray-300 disabled:opacity-50"><RefreshCw className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`} aria-hidden="true" /> Refresh</button><span role={message ? "status" : undefined} className="text-xs text-gray-400">{message ?? (status?.configured ? "Credential configured in protected storage." : "No protected credential configured.")}</span></div>
  </section>;
}
