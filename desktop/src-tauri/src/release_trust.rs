//! Compiled Desktop V2 release identity and public trust policy.
//!
//! RC.6 source builds default to a coherent, explicitly non-production test
//! trust root. Commercial builds may override the public key metadata through
//! build-time environment variables. A private seed is never compiled in.

pub const RELEASE_VERSION: &str = "2.0.0-rc.6";
pub const RELEASE_CHANNEL: &str = "beta";
include!(concat!(env!("OUT_DIR"), "/release_trust_build.rs"));

pub fn release_trust_is_production() -> bool {
    RELEASE_TRUST_PROFILE == "external-release"
}

/// Signed offline catalogs are a supported release feature. Local artifact
/// URLs are accepted only after the catalog and embedded manifests verify
/// against the compiled release trust root.
pub const OFFLINE_IMPORT_SUPPORTED: bool = true;
