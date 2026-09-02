use std::{env, fs, path::PathBuf};

fn main() {
    for name in [
        "AIVE_RELEASE_KEY_ID",
        "AIVE_RELEASE_PUBLIC_KEY_B64",
        "AIVE_RELEASE_PUBLIC_KEY_SHA256",
        "AIVE_RELEASE_TRUST_PROFILE",
    ] {
        println!("cargo:rerun-if-env-changed={name}");
    }
    // RC.6 defaults to the deterministic NON-PRODUCTION fixture trust root so
    // a developer/test shell can actually verify its matching test catalog.
    // Commercial builds override all four public values. A private seed is
    // never accepted by, read by, or embedded through this build script.
    let key_id = env::var("AIVE_RELEASE_KEY_ID").unwrap_or_else(|_| "test-fixture-2026".into());
    let public_key = env::var("AIVE_RELEASE_PUBLIC_KEY_B64")
        .unwrap_or_else(|_| "hfqZ1Gk2qemcp+23vgMKpdMauxUlEXuBWF3NilhYA44=".into());
    let fingerprint = env::var("AIVE_RELEASE_PUBLIC_KEY_SHA256").unwrap_or_else(|_| {
        "22094d0fd9318ff224ea22abeec545b5c5d653fd8be5b480790de2d7743bb404".into()
    });
    let profile =
        env::var("AIVE_RELEASE_TRUST_PROFILE").unwrap_or_else(|_| "developer-test".into());
    if key_id.is_empty() || public_key.is_empty() || fingerprint.len() != 64 || profile.is_empty() {
        panic!("release public trust override is incomplete");
    }
    let output = PathBuf::from(env::var("OUT_DIR").expect("OUT_DIR"));
    fs::write(
        output.join("release_trust_build.rs"),
        format!(
            "pub const RELEASE_KEY_ID: &str = {key_id:?};\n\
             pub const RELEASE_PUBLIC_KEY_B64: &str = {public_key:?};\n\
             pub const RELEASE_PUBLIC_KEY_SHA256: &str = {fingerprint:?};\n\
             pub const RELEASE_TRUST_PROFILE: &str = {profile:?};\n"
        ),
    )
    .expect("write release trust constants");
    tauri_build::build()
}
