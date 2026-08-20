"""FFmpeg component discovery and deterministic version/self-test probes."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


_VERSION_RE = re.compile(r"\bversion\s+([0-9]+(?:\.[0-9]+){1,3})", re.IGNORECASE)


@dataclass(frozen=True)
class ToolProbe:
    path: str | None
    present: bool
    version: str | None
    version_ok: bool
    return_code: int | None
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "present": self.present,
            "version": self.version,
            "versionOk": self.version_ok,
            "returnCode": self.return_code,
            "detail": self.detail,
        }


@dataclass
class FFmpegProbeResult:
    component_root: str
    ffmpeg: ToolProbe
    ffprobe: ToolProbe
    encode_self_test: ToolProbe
    decode_self_test: ToolProbe
    ready: bool
    remediation_codes: list[str] = field(default_factory=list)

    @property
    def ffmpeg_path(self) -> str | None:
        return self.ffmpeg.path

    @property
    def ffprobe_path(self) -> str | None:
        return self.ffprobe.path

    @property
    def version(self) -> str | None:
        return self.ffmpeg.version or self.ffprobe.version

    def as_dict(self) -> dict[str, object]:
        return {
            "componentRoot": self.component_root,
            "ffmpeg": self.ffmpeg.as_dict(),
            "ffprobe": self.ffprobe.as_dict(),
            "encodeSelfTest": self.encode_self_test.as_dict(),
            "decodeSelfTest": self.decode_self_test.as_dict(),
            "ready": self.ready,
            "remediationCodes": list(dict.fromkeys(self.remediation_codes)),
        }


def _candidate(root: Path, name: str, *, allow_fixture: bool) -> Path | None:
    suffixes = [".exe"] if os.name == "nt" else [""]
    if allow_fixture:
        suffixes.extend([".cmd", ".bat", ""])
    seen: set[Path] = set()
    for base in (root / "bin", root):
        for suffix in suffixes:
            path = (base / f"{name}{suffix}").resolve(strict=False)
            if path in seen:
                continue
            seen.add(path)
            if path.is_file():
                return path
    return None


def _command(path: Path, args: Sequence[str], *, allow_fixture: bool) -> list[str]:
    if allow_fixture and path.suffix.lower() in {".cmd", ".bat"}:
        return ["cmd.exe", "/D", "/C", str(path), *args]
    return [str(path), *args]


def _run_probe(path: Path | None, args: Sequence[str], *, allow_fixture: bool) -> ToolProbe:
    if path is None:
        return ToolProbe(
            path=None,
            present=False,
            version=None,
            version_ok=False,
            return_code=None,
            detail="Tool was not found under the activated component root; global PATH was not searched.",
        )
    try:
        completed = subprocess.run(
            _command(path, args, allow_fixture=allow_fixture),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ToolProbe(
            path=str(path),
            present=True,
            version=None,
            version_ok=False,
            return_code=None,
            detail=f"Probe failed: {exc}",
        )
    output = f"{completed.stdout}\n{completed.stderr}".strip()
    match = _VERSION_RE.search(output)
    version = match.group(1) if match else None
    return ToolProbe(
        path=str(path),
        present=True,
        version=version,
        version_ok=completed.returncode == 0 and version is not None,
        return_code=completed.returncode,
        detail=output[-800:] if output else f"Process exited with {completed.returncode}.",
    )


def _self_test(
    ffmpeg: Path | None,
    *,
    operation: str,
    temp_root: Path | None,
    allow_fixture: bool,
) -> ToolProbe:
    if ffmpeg is None:
        return _run_probe(None, (), allow_fixture=allow_fixture)
    # Null output keeps the probe deterministic and avoids creating media in a
    # user project/export directory.  The two commands exercise video and
    # audio codec paths separately; fixture commands accept both probes.
    if operation == "encode":
        args = [
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=16x16:r=1",
            "-frames:v",
            "1",
            "-f",
            "null",
            "-",
        ]
    else:
        args = [
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=0.1",
            "-f",
            "null",
            "-",
        ]
    return _run_probe(ffmpeg, args, allow_fixture=allow_fixture)


def discover_ffmpeg(
    component_root: str | os.PathLike[str],
    *,
    temp_root: str | os.PathLike[str] | None = None,
    allow_fixture: bool = False,
) -> FFmpegProbeResult:
    """Probe only the supplied activated component root.

    ``allow_fixture`` is intentionally explicit and is only for deterministic
    tests using command fixtures.  Production discovery requires the expected
    native executable names and never falls back to PATH.
    """

    root = Path(component_root).expanduser().resolve(strict=False)
    ffmpeg = _candidate(root, "ffmpeg", allow_fixture=allow_fixture)
    ffprobe = _candidate(root, "ffprobe", allow_fixture=allow_fixture)
    ffmpeg_probe = _run_probe(ffmpeg, ("-version",), allow_fixture=allow_fixture)
    ffprobe_probe = _run_probe(ffprobe, ("-version",), allow_fixture=allow_fixture)
    temp_path = Path(temp_root).resolve(strict=False) if temp_root else None
    encode = _self_test(
        ffmpeg,
        operation="encode",
        temp_root=temp_path,
        allow_fixture=allow_fixture,
    )
    decode = _self_test(
        ffmpeg,
        operation="decode",
        temp_root=temp_path,
        allow_fixture=allow_fixture,
    )
    remediation: list[str] = []
    if not ffmpeg_probe.present or not ffprobe_probe.present:
        remediation.append("FFMPEG_MISSING")
    if not ffmpeg_probe.version_ok or not ffprobe_probe.version_ok:
        remediation.append("FFMPEG_MISSING")
    if encode.return_code != 0 or decode.return_code != 0:
        remediation.append("FFMPEG_MISSING")
    return FFmpegProbeResult(
        component_root=str(root),
        ffmpeg=ffmpeg_probe,
        ffprobe=ffprobe_probe,
        encode_self_test=encode,
        decode_self_test=decode,
        ready=not remediation,
        remediation_codes=list(dict.fromkeys(remediation)),
    )
