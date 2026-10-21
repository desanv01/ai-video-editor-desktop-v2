# JavaScript dependency source remedy

`react-player` was an unused production dependency in the accepted application source. Its removal prunes `load-script`, `deepmerge`, `memoize-one`, and `react-fast-compare` from that dependency closure. Native video playback and all Revideo roots remain.

`@aivora/deferred-value@1.0.0` is independently authored from the observed updater consumer API: a named CommonJS `Lazy` constructor with deferred, cached `.value`. It caches successful values including undefined/null and promises, while a synchronous factory throw permits retry. Its source, types and complete app-approved AGPL version3 license are included in `desktop/vendor/aivora-deferred-value`.

The npm override is scoped only to `electron-updater@6.8.9`; its relative file spec resolves from that package directory to the local helper. Builder development consumers continue resolving the original `lazy-val@1.0.5`. The first attempted file spec produced an unbound local target despite npm exit zero; the separately authorized relative-base correction establishes the actual named local package in the lockfile. No original lazy-val implementation was read or copied, and no missing original MIT grant is supplied or inferred.

This is a source/lock-graph remedy. New package and ASAR evidence must still prove original runtime packages absent and the new helper selected, updater initialization/flags preserved, and notices/source mapping aligned. Historical old-artifact missing-grant facts remain unchanged; development/build-tool and other existing obligations are not waived.
