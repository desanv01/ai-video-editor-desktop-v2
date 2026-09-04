# RC.6 Lecturer Configuration Guide

Complete Setup Center before changing editor settings. Open **Settings** from the application; the RC.6 tabs are **AI Mode**, **Providers**, **Local Models**, **Export**, **Appearance**, and **Tours**.

## AI mode

- **Local** keeps supported work on installed local components and models.
- **API** uses the selected configured provider for provider-backed operations.
- **Hybrid** may use local capabilities first and a provider where the workflow requires it.

The visible readiness/capability status is authoritative. Selecting a mode does not manufacture a missing model, provider credential, or network entitlement.

## Providers

Choose a listed provider and enter only a lecturer-owned credential. The current RC.6 UI offers **Test**, **Clear**, and environment-source handling; follow those labels rather than older “Verify provider” instructions. Never paste a secret into Diagnostics, project notes, screenshots, shell commands, or support logs.

Use **Test** before provider-backed work. A failed provider test does not affect local import or manual editing. **Clear** removes only the selected product-owned provider value. Setup and uninstall logs are redacted and do not record credential values.

## Local models

Review the model name, size, source, hash, storage path, and license before downloading. Keep sufficient free disk space and leave the app open during a verified download/activation. Models are user data and are not installed under Program Files. A normal uninstall preserves them; explicit full wipe may remove only the documented allowlisted model roots.

## Export, appearance, and tours

In **Export**, choose the default destination and supported preset. Confirm the destination is writable before a long job. **Appearance** changes presentation only. **Tours** can restart guided UI help without modifying projects.

## Data locations

The shell is fixed at `%ProgramFiles%\AI Video Editor Desktop V2\Shell`. Machine components and redacted installer diagnostics are under `%ProgramData%\AI Video Editor`. Per-user configuration/models live under the product user-data boundary, while projects and exports live below `%USERPROFILE%\Documents\AI Video Editor` unless the user selects another export folder.

Back up valuable projects and exports independently. Configuration repair, component repair, and normal uninstall must not be treated as a backup.
