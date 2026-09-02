import { invoke } from "@tauri-apps/api/core";

export const PROVIDER_SECRET_KEYS = [
  { value: "api_key", label: "API key" },
  { value: "access_token", label: "Access token" },
  { value: "password", label: "Password" },
  { value: "hf_token", label: "Hugging Face token" },
  { value: "custom_endpoint_key", label: "Custom endpoint key" },
] as const;

export const PROVIDER_CARDS = [
  { id: "mistral", name: "Mistral / Voxtral", detail: "Hosted transcription and language models." },
  { id: "openai", name: "OpenAI", detail: "Hosted speech and language models." },
  { id: "deepseek", name: "DeepSeek", detail: "Hosted language models." },
  { id: "alibaba", name: "Alibaba / Qwen", detail: "Hosted Qwen language models." },
] as const;

export interface ProviderCredentialStatus {
  schemaVersion: "desktop.provider-credential.v1";
  providerId: string;
  keyName: string;
  configured: boolean;
  storageVerified: boolean;
  providerVerified: boolean;
  verification: "not-requested" | "verified" | "not-verified";
  storage: string;
  manualDefault: boolean;
  detail: string;
  remediationCodes: string[];
}

export const providerCredentials = {
  status: (providerId: string, keyName: string) =>
    invoke<ProviderCredentialStatus>("provider_credential_status", { providerId, keyName }),
  save: (providerId: string, keyName: string, secret: string) =>
    invoke<ProviderCredentialStatus>("provider_credential_save", { providerId, keyName, secret }),
  verify: (providerId: string, keyName: string) =>
    invoke<ProviderCredentialStatus>("provider_credential_verify", { providerId, keyName }),
  clear: (providerId: string, keyName: string) =>
    invoke<ProviderCredentialStatus>("provider_credential_clear", { providerId, keyName }),
};

export function redactProviderError(error: unknown): string {
  const value = error instanceof Error ? error.message : String(error);
  return value
    .slice(0, 400)
    .replace(/((?:password|passwd|secret|token|api[_-]?key|authorization)\s*[:=]\s*)[^\s,;&]+/gi, "$1[REDACTED]")
    .replace(/\bBearer\s+[^\s,;&]+/gi, "Bearer [REDACTED]");
}
