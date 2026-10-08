# Aivora brand assets

`aivora-mark.svg` is the product mark: a cutout play symbol inside an A, with a mint timeline stroke. `aivora-lockup.svg` adds the wordmark. `aivora-workflow.svg` illustrates the six stages; it is not a screenshot.

The accent is violet `#635bff`; the secondary highlight is mint `#b8ffda` on charcoal `#17171c`. All SVGs are self-contained and include accessible titles. The UI uses the mark decoratively beside the visible product name.

`desktop/public/` contains the same SVG plus a 512px PNG and a Windows ICO rendered from it. Electron Builder uses the ICO for the Windows application and installer. Keep these derivatives synchronized with the vector source.

Product-facing text uses **Aivora**. Existing `AIVE` application IDs, protocols, environment variables, storage roots, and managed component names remain compatibility identifiers. The GitHub repository slug remains `ai-video-editor-desktop-v2` so existing clone, release, and CI URLs continue to resolve.
