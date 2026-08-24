# Desktop V2 rc.3 antivirus evidence template

This is a record template, not a promise that the release will produce zero detections. Microsoft does not provide a blanket known-list/false-positive-prevention program. Consistent CA-backed Authenticode signing, deterministic onedir packaging, an SBOM, exact hashes, and prompt submission of real detections are the available controls.

| Field | Evidence |
|---|---|
| Handoff version | `2.0.0-rc.3` |
| Git commit | fill from release commit |
| Artifact SHA-256 | fill from `release-manifest.json` |
| SBOM | path/hash of `sbom.cdx.json` |
| Local Defender engine/signature | fill from `desktop.av-scan.v1` |
| Clean local Defender result | attach JSON; do not write “zero detections guaranteed” |
| Vendor/portal | Microsoft Defender, VirusTotal, vendor portal, or other named service |
| Submission ID | fill only after a real detection is submitted |
| Detection name | exact vendor result, if any |
| False-positive response | vendor response/date |

Run `scripts/desktop-v2/Run-DefenderScan.ps1` on the assembled handoff. Keep third-party portal results separate from CI/local evidence. A detection is a release decision requiring investigation; it is never silently ignored.

Reference: [Microsoft Defender developer FAQ](https://learn.microsoft.com/defender-xdr/developer-faq).
