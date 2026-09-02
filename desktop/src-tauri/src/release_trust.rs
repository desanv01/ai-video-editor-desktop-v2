//! Compiled Desktop V2 lecturer-release identity and trust policy.
//!
//! The matching private Ed25519 seed is stored outside the repository in the
//! restricted release-secrets folder. Only this public trust root is shipped.

pub const RELEASE_VERSION: &str = "2.0.0-rc.5";
pub const RELEASE_CHANNEL: &str = "beta";
pub const RELEASE_KEY_ID: &str = "aive-desktop-v2-lecturer-2026";
pub const RELEASE_PUBLIC_KEY_B64: &str = "MhUdd64qlUHYivcNkTsopbtIA1o2nEMUb8fXV5HHY8A=";
pub const RELEASE_PUBLIC_KEY_SHA256: &str =
    "471e7b08109f8723400afea495f63d1d93753e4757386e31560a7cbee6bd2a2d";

/// Signed offline catalogs are a supported release feature. Local artifact
/// URLs are accepted only after the catalog and embedded manifests verify
/// against the compiled release trust root.
pub const OFFLINE_IMPORT_SUPPORTED: bool = true;
