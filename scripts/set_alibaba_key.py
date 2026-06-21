"""Safely update the local .env Alibaba/DashScope key without hard-coding it."""

from __future__ import annotations

import getpass
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
VARIABLE = "ALIBABA_API_KEY"


def main() -> None:
    if not ENV_PATH.exists():
        raise SystemExit(".env does not exist. Copy .env.example to .env first.")

    key = os.environ.get(VARIABLE, "").strip()
    if not key:
        key = getpass.getpass("Alibaba/DashScope API key (input hidden): ").strip()
    if not key:
        raise SystemExit("No key supplied; .env was not changed.")

    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    replacement = f"{VARIABLE}={key}"
    updated: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith(f"{VARIABLE}="):
            updated.append(replacement)
            replaced = True
        else:
            updated.append(line)

    if not replaced:
        updated.append(replacement)

    ENV_PATH.write_text("\n".join(updated) + "\n", encoding="utf-8")
    print(f"Updated {VARIABLE} in {ENV_PATH.name}; value length={len(key)}. The value was not printed.")


if __name__ == "__main__":
    main()
