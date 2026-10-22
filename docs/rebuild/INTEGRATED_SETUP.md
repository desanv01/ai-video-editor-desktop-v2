# Integrated supplier setup

The assisted per-user installer can launch Aivora with **Continue Aivora setup**. Only that explicit packaged launch starts first preparation automatically after initialization; normal launches and prior failed/interrupted preparations retain the in-app Prepare/retry flow. Silent installation does not pass the setup-download flag.

Engine and Whisper archives remain bundled. First setup acquires pinned FFmpeg 8.1.1 original ZIP and LibreOffice 26.2.6 original MSI from the manifest suppliers over controlled HTTPS origins. Verified cache files are reused. The installer and final mixed delivery exclude these two supplier binary archives. LibreOffice uses a private administrative image rather than a global product install; its native window waits for normal close, with uncertain ownership retained and blocked across restart.

Supplier archive URL/version/size/hash identify the external input, not its exact build source. Vendor build/source and notice applicability still need separate review; JavaScript grants and embedded engine/Python/native obligations remain open where previously recorded. No runtime/setup, privacy, final-gate or release acceptance follows from these source changes.
