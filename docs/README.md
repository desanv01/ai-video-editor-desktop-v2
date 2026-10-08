# Aivora documentation

Start with [setup](getting-started.md), then follow the six stages in the editor: Transcribe, Clean, Sections, Layout, Polish, Export.

| Guide | What it covers |
| --- | --- |
| [Getting started](getting-started.md) | Windows handoffs, component preparation, credentials, and source development |
| [Architecture](architecture.md) | Current Electron runtime, storage, and repository layout |
| [Exports](exports.md) | Original transcript downloads, final media, and editing evidence |
| [Contributing](../CONTRIBUTING.md) | Development checks and reporting issues |
| [Runtime contracts](rebuild/CONTRACTS.md) | Engine, components, security, and release acceptance requirements |
| [Delivery guide template](rebuild/DELIVERY_GUIDE_TEMPLATE.md) | Release-owner checklist; finalize using actual installed results |

`rebuild/` contains implementation contracts and coordination records. `desktop-v2/` describes the retained Tauri runtime and its older installers; use those documents only when working with that runtime. The root README and guides above describe the current Electron application.
