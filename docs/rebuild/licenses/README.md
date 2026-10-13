# Application notice supplements

The optional supplement manifest supplies retained upstream license and attribution bytes for packages whose selected ASAR inventory has no captured notice. It keeps those upstream inputs distinct from bytes captured from the application.

## Assemble with supplements

Run from the repository root. Configure `AIVE_REBUILD_ROOT` to an absolute root containing the selected inputs and output locations. The relative paths below are examples; select a freshly captured inventory for the actual application payload and an output directory that does not already exist.

```shell
node scripts/rebuild/assemble_application_notices.cjs --inventory evidence/captured/inventory.json --output-dir evidence/assembled-with-supplements --supplements docs/rebuild/licenses/application-notice-supplements.v1.json
```

The output parent must exist. Input and output directories must be separate. The assembler reads retained local files; it does not fetch upstream packages or licenses. Raw notice files are protected by the scoped Git attributes from checkout line-ending conversion.

Omit `--supplements` to use the existing captured-only assembly. Its schema remains `aive.application-notices-assembly.v1`, and its output bytes remain unchanged.

## Exact package binding and output

Every supplement must match an inventory entry's package JSON path, package name, version, declared license, package JSON SHA256 and byte size. The entry must have no captured notices. An unknown owner, duplicate owner or identity mismatch fails assembly. Each manifest entry supplies one full-license file and one attribution file, with exact SHA256 and size checks. Files must stay within the manifest directory; unsafe paths, symlinks, modified inputs and existing output directories are rejected.

With supplements, `notice-assembly.json` uses `aive.application-notices-assembly.v2` and records:

- `inputs.upstreamSupplements`: the selected manifest's SHA256 and size.
- `supplementalNoticeBlobs`: the number of distinct upstream blobs.
- `supplementedPackages`: matched owners, package JSON identities, provenance and supplemental file identities.
- `unresolvedNoticeInputs`: capture gaps remaining after matched supplements.

The original `missingCapturedNotices` list and `capturedNoticeBlobs` count stay unchanged. A supplement does not manufacture an ASAR-captured notice or alter the inventory. The text output labels the original list as ASAR capture gaps, then includes a separate upstream supplemental section and the remaining unresolved inputs. `releaseApproved` remains `false`.

## mj-context-menu 0.6.1 input association

The current manifest binds `node_modules/mj-context-menu/package.json` to version `0.6.1`, declared license `Apache-2.0`, size 807 bytes and SHA256 `f53538dc52884ad822cd53f22940f29103b6872c02a2bfa5fc5eb27c8dd865eb`. This identity must also match the newly selected inventory; a different payload requires review rather than relaxing the binding.

The accepted input association combines:

- The [complete root Apache 2.0 terms](https://github.com/mathjax/context-menu/blob/72e16a5713cf30b390776c89bb6c1428747472f1/LICENSE) added at commit `72e16a5713cf30b390776c89bb6c1428747472f1`, retained in [LICENSE.txt](mj-context-menu-0.6.1/LICENSE.txt).
- The pre-existing copyright and Apache application headers at the published package gitHead `8ddd26a41f834cd23b9bb20737dfae5fa9b05eb4`, grouped by exact header and source paths in [SOURCE_NOTICES.txt](mj-context-menu-0.6.1/SOURCE_NOTICES.txt).
- The [maintainer's explanation](https://github.com/mathjax/context-menu/issues/32#issuecomment-1629273186) that source files already carried Apache 2.0 headers.

At that exact gitHead, 38 of 39 TypeScript files carry those headers; `ts/index.ts` is a headerless export aggregator. The association relies on existing version-specific source notices, not assumed retroactive application of a later grant. The [manifest](application-notice-supplements.v1.json) retains exact revisions, blob and tarball identities, public source URLs, and hashes for both supplied files.

## Typed retained inputs (manifest v2)

Use the existing CLI with the new manifest:

~~~shell
node scripts/rebuild/assemble_application_notices.cjs --inventory evidence/captured/inventory.json --output-dir evidence/assembled-typed --supplements docs/rebuild/licenses/application-notice-supplements.v2.json
~~~

The original v1 manifest retains assembly.v2 output. No flag still uses captured-only assembly.v1. Typed v2 manifests emit aive.application-notices-assembly.v3 and distinguish:

- source-license-file: one exact retained upstream root license, without synthetic separate attribution.
- source-readme-full-mit-grant: the entire original README containing the grant/copyright, retaining entity bytes; it is not a standalone root LICENSE.
- license-text-with-source-application-notices: complete terms plus separately retained exact-version source application notices, preserving the qualified mj association.

Published-git-head bindings match actual recorded registry gitHead. Version-tag bindings have explicit null gitHead and an annotated-tag chain/package-version-license witness. Degenerator5.0.1 uses annotated398c4707c9edf23ae89f6f2383964d16bd1cd3c6 -> commitd5cdaa1b774c699c75b543eb4b112290d261e321. No gitHead is invented. Source URLs match structured repository, revision and source path. Registry/tarball hashes and SHA512 integrity are previously reviewed provenance; the assembler does not acquire or reverify those archives.

The manifest binds nine exact owners to eight distinct raw blobs; three Puppeteer owners share one license. Expected selected-current output is274 packages,176 captured blobs,11 raw capture gaps unchanged,9 upstream associations and2 unresolved MIT grants (lazy-val/load-script). Typed stdout distinguishes remaining unresolved inputs from capture gaps. Output still requires exact package JSON matching and does not establish release approval.

Strict validation covers evidence roles, provenance linkage, current package identity, raw bytes and mechanical complete-grant/attribution markers. Marker checks use a temporary whitespace-folded inspection copy; original bytes/entities are not changed and licensing scope is not determined. Scoped -text attributes preserve retained-upstream files. Unsafe/reparse paths, input/output overlap, existing output, size limits, tampering and changed inputs remain rejected.

## Remaining gaps

Full applicable MIT grants for `lazy-val@1.0.5` and `load-script@1.0.0` remain missing. License declarations alone do not resolve those gaps, and this manifest supplies no invented grants for them.

Matched notice inputs do not establish complete license compliance, corresponding-source coverage, final inventory completeness or release approval. Assembly, current-payload verification and release review remain separate work.
