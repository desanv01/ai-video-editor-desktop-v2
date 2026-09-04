# Evidence-to-release workflow

This playbook is codebase-neutral. It defines how an observed defect becomes a traceable implementation, verified artifact, and honest release decision. A release claim is valid only when its evidence directly exercises the claimed boundary.

## 1. Open an evidence register

Give every input a stable ID. Record the source, acquisition time, original filename, byte size, cryptographic hash, tool used to inspect it, and access restrictions. Preserve originals read-only. Store derived frames, transcripts, logs, and notes separately and link each derivative to its source hash.

Maintain an observed-versus-inferred ledger:

| ID | Statement | Status | Supporting evidence | Confidence / next check |
| --- | --- | --- | --- | --- |
| O-1 | Directly visible or measured fact | Observed | File, timestamp, log line, hash | High |
| I-1 | Proposed explanation | Inferred | Related observations | Confirm with reproduction |

Never promote an inference to an observation. Redact credentials, tokens, personal paths, and user content before attaching logs.

## 2. Reproduce and isolate the root cause

Write a minimal reproduction with exact inputs, environment, starting state, commands/actions, expected result, actual result, and repeat count. Capture version, commit, dirty state, OS/toolchain versions, privileges, and relevant configuration.

Reduce the failing path until one causal mechanism explains the evidence. Document competing hypotheses and the check that rejected each. A root-cause statement must name:

- the incorrect state or operation;
- the function/file that introduced it;
- why the observed failure follows;
- why existing tests did not detect it.

## 3. Define invariants and risks before editing

Translate acceptance criteria into invariants that can be tested. Include success, failure, interruption, retry, concurrency, rollback, upgrade, uninstall, data retention, security boundaries, and compatibility. For destructive paths, define ownership markers, canonical roots, reparse/symlink policy, allowlists, and recovery-material retention.

Create a risk register with likelihood, impact, detection, mitigation, and owner. Stop when a required action would exceed the authorized scope or when recovery cannot be proven.

## 4. Produce a file/function implementation plan

Map every invariant to the smallest responsible file and function. Separate:

1. state discovery and classification;
2. validation and invariant checks;
3. mutation/activation;
4. rollback and crash recovery;
5. diagnostics and stable error codes;
6. verification and release packaging.

Refactor before adding branches when one function mixes these boundaries. Avoid unrelated product changes. Record each material design decision, alternatives considered, and consequences.

## 5. Build the test matrix

For every state, specify setup, action, expected exit/status, expected filesystem/registry/external state, preserved sentinels, and cleanup. Include pristine, valid prior version, repairable registration, empty residue, unknown nonempty conflict, reparse/symlink conflict, interrupted phases, stale/unknown backup, locks, retry, re-entry, concurrency, fault injection, failed-fresh cleanup, failed-upgrade restore, default uninstall retention, full wipe, and locked uninstall.

Use layers:

- source/static guards for forbidden operations and ordering;
- rendered/generated-source verification;
- compiled disposable-root integration tests;
- unit and component tests;
- packaged-artifact smoke tests;
- clean target-system lifecycle tests;
- signature, provenance, checksum, extraction, and malware-scanner gates.

Passing a lower layer never proves a higher one.

## 6. Keep an execution log

For each command record start/end time, working directory, exact revision, environment overrides, exit code, output/evidence path, and result. Classify every gate as passed, failed, or skipped; skipped gates require a reason and limit the release claims.

Failures are evidence. Do not delete logs or recovery material merely to obtain a clean rerun. After a fix, rerun the focused reproduction first, then the broader regression and artifact gates.

## 7. Maintain acceptance traceability

Use a table linking each acceptance criterion to implementation locations, test cases, executed evidence, and status. A criterion is complete only when all four columns are populated. Reviewers should be able to start from any release claim and reach the exact command output and artifact hash that supports it.

## 8. Freeze the release in dependency order

Record branch, commit, clean/dirty status, version, channel, target, build-time trust configuration, deterministic timestamp inputs, and external source hashes. A safe generic order is:

1. verify sources and licenses;
2. build and test loose binaries;
3. apply required executable signing;
4. package components and compute their hashes;
5. sign component manifests/catalogs;
6. build the shell/installer against the intended public trust record;
7. verify rendered installer and compiled state matrix;
8. assemble a uniquely named staging handoff;
9. generate SBOM, provenance, and exact-coverage checksums;
10. verify signatures and checksums independently;
11. create the archive;
12. generate an adjacent archive SHA-256 file;
13. extract to a new directory and repeat verification.

Any byte change invalidates all downstream hashes, signatures, SBOM entries, and evidence. Never overwrite a prior handoff.

## 9. Signing and provenance rules

Keep private keys and certificates outside the repository and handoff. Record only public identifiers, certificate chain metadata, timestamp evidence, and verification output. Distinguish application trust signatures from OS publisher signatures. “Not claimed” is the correct status when external signing evidence is absent.

Provenance must name source revision, inputs, tool versions, trust profile, component hashes, installer hash, archive hash, and all skipped external gates. Do not describe a developer/test key as a production publisher identity.

## 10. Sign-off

Release sign-off requires:

- a clean acceptance-traceability table;
- independent review of destructive and recovery paths;
- all required gates passed;
- limitations stated beside the artifact hashes;
- exact installation, configuration, use, troubleshooting, and uninstall instructions;
- release-owner approval recorded with date and artifact identity.

If clean-system lifecycle, platform trust, or antivirus scanning was not executed, state that plainly. The artifact may still be useful for supervised evaluation, but those claims remain unproven.
