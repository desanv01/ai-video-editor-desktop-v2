Release staging directory for the bundled lecturer handoff.

Release packaging may place a verified Catalog/offline-catalog.json and its
sibling Components directory here. The shell never trusts this directory by
name alone: it bounds discovery, requires a single JSON catalog, checks the
catalog and embedded component signatures, and enforces offline path
containment before persisting verified metadata.
