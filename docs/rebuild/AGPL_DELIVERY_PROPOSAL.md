# Desktop release license proposal — human approved AGPL-3.0

The actual frozen dcbdedfe9247fc31ef68ec5f9b015f58013da5fa engine contains PyMuPDF 1.25.3 and MuPDF 1.25.4. Installed wheel COPYING is a 64-byte dual-license label. Full exact-tag upstream COPYING notices were captured, both SHA256 57c8ff33c9c0cfc3ef00e650a1cc910d7ee479a8bc509f6c9209a7c2a11399d6.

Proposed release treatment: publish the dedicated Desktop repository source under GNU Affero General Public License version 3, retain existing third-party licenses/notices, and supply matching application/component corresponding sources and build instructions with the release. Proposed exact license text is retained at validation/runtime-notice-supplements-main2/PROPOSED-AGPL-3.0-LICENSE.txt; human directly approved AGPL-3.0 and publishing matching source in this main chat; exact LICENSE now added to the dedicated repository. The original FYP remains read-only and its license is not changed.

Official sources: https://github.com/pymupdf/PyMuPDF/blob/d84e90c3d9048f060ebc356e6aefdf33a5644624/COPYING and https://github.com/ArtifexSoftware/mupdf/blob/f1bcc4481c615b0c8abfa2c2602dc3367e1f4880/COPYING. A proprietary treatment instead requires appropriate Artifex commercial licensing; no such license is assumed.

The human approved this release treatment. Private packaging, managed CI and installed acceptance continue. Final public runtime release still requires complete corresponding-source preparation and actual installed acceptance.

Human answer: Yes — use AGPL-3.0 and publish matching source. Publication decision resolved; matching source and installed acceptance remain required.
