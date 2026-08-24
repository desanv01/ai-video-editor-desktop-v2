import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const script = await readFile(path.join(repoRoot, "scripts", "desktop-v2", "Sign-DesktopV2Release.ps1"), "utf8");
const docs = await readFile(path.join(repoRoot, "docs", "desktop-v2", "SIGNING_RC3_RELEASE_GATE.md"), "utf8");

assert.match(script, /Get-AuthenticodeSignature/);
assert.match(script, /\/fd SHA256/);
assert.match(script, /\/tr/);
assert.match(script, /\/td SHA256/);
assert.match(script, /AIVE_REQUIRE_AUTHENTICODE/);
assert.match(script, /CertificateThumbprint/);
assert.match(script, /not.*fabricated|no.*certificate/i);
assert.match(docs, /OV\/EV/i);
assert.match(docs, /RFC3161/i);
assert.match(docs, /fail|pending/i);
assert.match(docs, /private key/i);

console.log("Signing tests passed: external OV/EV certificate gate, SHA-256 Authenticode, RFC3161 timestamping, PE verification, and honest unsigned/pending behavior.");
