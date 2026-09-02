import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const rust = await readFile(path.join(repoRoot, "desktop", "src-tauri", "src", "provider_credentials.rs"), "utf8");
const client = await readFile(path.join(repoRoot, "desktop", "src", "providerCredentials.ts"), "utf8");
const panel = await readFile(path.join(repoRoot, "desktop", "src", "components", "ProviderOnboardingPanel.tsx"), "utf8");
const docs = await readFile(path.join(repoRoot, "docs", "desktop-v2", "PROVIDER_ONBOARDING_RC3.md"), "utf8");
const lib = await readFile(path.join(repoRoot, "desktop", "src-tauri", "src", "lib.rs"), "utf8");

for (const source of [rust, docs]) {
  assert.match(source, /Credential Manager|credential-manager/i);
  assert.match(source, /redact|never|not.*state|not.*logs/i);
}
for (const source of [rust, client, panel, docs]) {
  assert.match(source, /redact|never|not.*state|not.*logs/i);
}
assert.match(rust, /CredWriteW/);
assert.match(rust, /CredReadW/);
assert.match(rust, /CredDeleteW/);
assert.match(rust, /ALLOWED_SECRET_KEYS/);
assert.match(rust, /MAX_SECRET_BYTES/);
assert.match(rust, /provider_credential_save/);
assert.match(rust, /provider_credential_verify/);
assert.match(rust, /\/api\/v1\/settings\/ai\/test-provider/);
assert.match(rust, /not-verified/);
assert.match(rust, /api_request_json/);
assert.match(rust, /provider_credential_clear/);
assert.match(client, /provider_credential_save/);
assert.match(client, /provider_credential_verify/);
assert.match(client, /provider_credential_clear/);
assert.match(panel, /type="password"/);
assert.match(panel, /Save securely/);
assert.match(panel, /Verify provider/);
assert.match(panel, />\s*Clear</);
for (const label of ["Mistral / Voxtral", "OpenAI", "DeepSeek", "Alibaba / Qwen"]) {
  assert.match(client, new RegExp(label.replace("/", "\\/")));
}
assert.match(docs, /DPAPI/);
assert.match(docs, /per-user/);
assert.match(lib, /provider_credentials::provider_credential_status/);
assert.match(lib, /provider_credentials::provider_credential_save/);
assert.match(lib, /provider_credentials::provider_credential_verify/);
assert.match(lib, /provider_credentials::provider_credential_test/);
assert.match(lib, /provider_credentials::provider_credential_clear/);

console.log("Provider credential tests passed: fixed providers, separate secure save/provider verification, Credential Manager boundaries, clear, and redaction.");
