# Desktop V2 rc.3 Authenticode release gate

The repository contains the signing gate and verification procedure, not a certificate. A real OV/EV certificate or approved signing service must be supplied outside the repository by the release owner. No certificate, private key, signature, or signed evidence is fabricated here.

`scripts/desktop-v2/Sign-DesktopV2Release.ps1` signs every `.exe`, `.dll`, and `.msi` under the supplied artifact root with `signtool` using SHA-256 file hashing and RFC3161 `/tr` plus `/td SHA256` timestamping. The final installer is included by the same recursive scan. The gate re-reads every PE signature with `Get-AuthenticodeSignature`; when `-RequireSigning` or `AIVE_REQUIRE_AUTHENTICODE=1` is set, any missing/invalid signature fails the release with exit code 33.

The secure procedure is:

1. Provision an OV/EV certificate through the organization’s certificate store or approved remote signing service. Do not copy a private key into this repository or pass a PFX password on a command line.
2. Set `AIVE_SIGNING_CERT_THUMBPRINT` to the externally supplied certificate thumbprint and `AIVE_TIMESTAMP_URL` to the approved RFC3161 HTTPS timestamp service.
3. Run the script against the fully assembled handoff, then run it again with `-VerifyOnly` after ZIP creation/extraction. Preserve the JSON signature inventory and exact hashes in the evidence bundle.
4. If the certificate or timestamp service is unavailable, leave the gate pending. The release verifier must fail if signing is declared required.

The policy follows Microsoft’s Authenticode guidance for SHA-256 and RFC3161 timestamping: [Time-stamping Authenticode signatures](https://learn.microsoft.com/windows/win32/seccrypto/time-stamping-authenticode-signatures).
