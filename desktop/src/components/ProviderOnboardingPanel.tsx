import { CheckCircle2, KeyRound, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { providerCredentials, PROVIDER_CARDS, PROVIDER_SECRET_KEYS, redactProviderError, type ProviderCredentialStatus } from "../providerCredentials";

const DEFAULT_PROVIDER = "mistral";

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

  const save = async () => {
    if (!secret) {
      setMessage("Enter a provider credential before saving it securely.");
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      setStatus(await providerCredentials.save(providerId, keyName, secret));
      setSecret("");
      setMessage("Saved securely and read back from protected storage. Provider verification is still separate.");
    } catch (error) {
      setMessage(redactProviderError(error));
    } finally {
      setBusy(false);
    }
  };

  const verify = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const next = await providerCredentials.verify(providerId, keyName);
      setStatus(next);
      setMessage(next.providerVerified
        ? "Provider verified and available."
        : "Credential saved, but the provider is not verified yet. Try again when the local workspace and network are ready.");
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
    <div className="flex items-start gap-3"><KeyRound className="mt-0.5 h-5 w-5 shrink-0 text-accent" aria-hidden="true" /><div><h3 id="provider-onboarding-title" className="text-sm font-semibold text-white">Connect an AI provider</h3><p className="mt-1 text-xs leading-5 text-gray-400">Optional provider connections are separate from the local editor. Choose a supported provider, then protect its credential in Windows.</p></div></div>
    <div className="mt-4 grid gap-2 sm:grid-cols-2" aria-label="Supported providers">{PROVIDER_CARDS.map(provider => <button key={provider.id} type="button" onClick={() => setProviderId(provider.id)} aria-pressed={providerId === provider.id} className={`rounded-lg border p-3 text-left ${providerId === provider.id ? "border-accent bg-accent/10" : "border-surface-border bg-surface-raised"}`}><span className="block text-sm font-medium text-white">{provider.name}</span><span className="mt-1 block text-xs leading-5 text-gray-400">{provider.detail}</span></button>)}</div>
    <div className="mt-4 rounded-lg border border-surface-border bg-surface-raised p-3"><p className="text-xs font-semibold text-gray-200">Windows Credential Manager</p><p className="mt-1 text-xs leading-5 text-gray-500">Save securely writes and reads back protected storage without displaying the value. Verify provider is a separate availability check through the local workspace.</p><div className="mt-3 grid gap-3 sm:grid-cols-2"><label className="text-xs text-gray-300">Credential type<select value={keyName} onChange={event => setKeyName(event.target.value as typeof keyName)} className="mt-1 w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-xs text-white">{PROVIDER_SECRET_KEYS.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label><label className="text-xs text-gray-300">Credential<input type="password" value={secret} onChange={event => setSecret(event.target.value)} maxLength={4096} autoComplete="off" placeholder={status?.configured ? "Configured — enter to replace" : "Enter manually"} className="mt-1 w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-xs text-white" /></label></div>
    <div className="mt-3 flex flex-wrap items-center gap-2"><button type="button" onClick={() => void save()} disabled={busy || !secret} className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-xs font-medium text-white disabled:opacity-50"><KeyRound className="h-3.5 w-3.5" aria-hidden="true" /> Save securely</button><button type="button" onClick={() => void verify()} disabled={busy || !status?.storageVerified} className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-400/30 px-3 py-2 text-xs font-medium text-emerald-100 disabled:opacity-50"><CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" /> Verify provider</button><button type="button" onClick={() => void clear()} disabled={busy || !status?.configured} className="inline-flex items-center gap-1.5 rounded-lg border border-rose-400/30 px-3 py-2 text-xs font-medium text-rose-100 disabled:opacity-50"><Trash2 className="h-3.5 w-3.5" aria-hidden="true" /> Clear</button><button type="button" onClick={() => void refresh()} disabled={busy} className="inline-flex items-center gap-1.5 rounded-lg border border-surface-border px-3 py-2 text-xs text-gray-300 disabled:opacity-50"><RefreshCw className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`} aria-hidden="true" /> Refresh status</button><span role={message ? "status" : undefined} className="text-xs text-gray-400">{message ?? (status?.providerVerified ? "Provider verified." : status?.storageVerified ? "Saved securely · provider not verified yet." : "No protected credential configured.")}</span></div></div>
  </section>;
}
