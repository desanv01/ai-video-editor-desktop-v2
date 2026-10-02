#!/usr/bin/env python3
"""Assemble an evidence-gated delivery from explicit approved inputs, offline.

No acquisition, execution, extraction, Git inspection, signing or publication.
Main owns installed acceptance and the final Desktop copy. All paths must be
below AIVE_REBUILD_ROOT, using the existing rebuild packer root contract.
Identical inputs and Python/zlib versions produce identical ZIP bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import struct
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from build_engine import AUTHORIZED_ROOT, validate_output
from package_engine import regular

REPOSITORY = "desanv01/ai-video-editor-desktop-v2"
COMPONENTS = frozenset(("aive-engine", "ffmpeg", "documents", "whisper-small"))
GATES = frozenset(("frozenEngine", "managedMediaExport", "managedDocumentConversion",
    "managedWhisperCpu", "installedSixStages", "installedExport", "installedReopen",
    "installedRecovery", "installedRestart", "installedShutdown", "installedUninstall"))
QUALIFICATIONS = frozenset(("liveProviders", "otherLaptop", "GPU", "signing"))
PROBES = frozenset(("engine-self-test", "ffmpeg-version", "ffprobe-version",
    "filter-codec-check", "whisper-runtime", "whisper-model", "document-tool-version"))
VERSION = re.compile(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?")
COMMIT = re.compile(r"[a-fA-F0-9]{40}")
SHA256 = re.compile(r"[a-f0-9]{64}")
METADATA_LIMIT = 4 * 1024 * 1024
MAX_ENTRIES = 100000
CHUNK = 1024 * 1024


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not any(ord(c) < 32 for c in value)


def integer(value: object) -> bool:
    return type(value) is int and 0 < value <= 9007199254740991


def safe_name(value: object, *, basename: bool = False) -> str:
    require(isinstance(value, str) and 0 < len(value) < 512, "Invalid archive name")
    parts = value.split("/")
    require(not basename or len(parts) == 1, f"Expected single filename: {value}")
    for part in parts:
        require(bool(part) and part not in (".", "..") and not part.endswith((".", " "))
            and not any(c in part for c in '\\:<>"|?*')
            and not any(ord(c) < 32 or ord(c) == 127 for c in part), f"Unsafe archive path: {value}")
        require(not re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", part.split(".")[0]),
            f"Reserved Windows path: {value}")
    return value


def reject_private(parts: tuple[str, ...] | list[str], *, component_id: str | None = None) -> None:
    folded = [part.casefold() for part in parts]
    for part in folded:
        require(part not in {".git", ".aws", ".ssh", "profiles", "user-data", "userdata"},
            f"Private path rejected: {'/'.join(parts)}")
        require(not (part == ".env" or part.startswith(".env.")) or part == ".env.example",
            f"Private environment input rejected: {'/'.join(parts)}")
    leaf = folded[-1]
    # Engine packer prefixes the onedir runtime with bin/. No input/source exception.
    engine_ca_bundle = component_id == 'aive-engine' and tuple(parts) in (
        ('bin', '_internal', 'certifi', 'cacert.pem'),
        ('bin', '_internal', 'grpc', '_cython', '_credentials', 'roots.pem'))
    documents_ca_bundle = component_id == 'documents' and tuple(parts) == (
        'program', 'python-core-3.12.14', 'lib', 'pip', '_vendor', 'certifi', 'cacert.pem')
    require(not (leaf in {"settings.json", "credentials.json", "credentials.yaml", "credentials.yml",
        "secrets.json", "secrets.yaml", "secrets.yml", "id_rsa", "id_ed25519"}
        or ".sqlite" in leaf or leaf.endswith((".key", ".log")) or (leaf.endswith(".pem") and not (engine_ca_bundle or documents_ca_bundle))
        or re.fullmatch(r"(?:[\w.-]+[-_.])?(?:tokens?|credentials?|secrets?)[-_.]?(?:store|vault)?\.(?:json|ya?ml|txt|ini|cfg|toml|db)", leaf)),
        f"Private file rejected: {'/'.join(parts)}")


def input_path(path: Path, *, directory: bool = False) -> Path:
    selected = path.absolute()
    validate_output(selected)
    if directory:
        for candidate in (selected, *selected.parents):
            info = candidate.lstat()
            require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
                f"Reparse/symlink input rejected: {candidate}")
        require(selected.is_dir(), f"Expected directory: {selected}")
    else:
        regular(selected)
    resolved = selected.resolve()
    require(resolved != AUTHORIZED_ROOT and resolved.is_relative_to(AUTHORIZED_ROOT),
        f"Input outside rebuild root: {selected}")
    reject_private(resolved.relative_to(AUTHORIZED_ROOT).parts)
    return resolved


def stamp(info: os.stat_result) -> tuple[int, ...]:
    # Windows 3.12+ path and descriptor ctime have different meanings. Birth
    # time is comparable across APIs; keep ctime on other OSes/older Windows.
    comparable_time = getattr(info, "st_birthtime_ns", info.st_ctime_ns) if os.name == "nt" else info.st_ctime_ns
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, comparable_time)


def handle_stamp(info: os.stat_result) -> tuple[int, ...]:
    # A single open descriptor always compares its own change-time semantics.
    return (*stamp(info), info.st_ctime_ns)


def identity(path: Path) -> dict:
    before_info = regular(path)
    before = stamp(before_info)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        opened_info = os.fstat(stream.fileno())
        require(os.path.samestat(before_info, opened_info) and stamp(opened_info) == before, f'Input replaced: {path}')
        opened_stamp = handle_stamp(opened_info)
        for block in iter(lambda: stream.read(CHUNK), b""):
            size += len(block)
            digest.update(block)
        require(handle_stamp(os.fstat(stream.fileno())) == opened_stamp, f"Input changed while hashing: {path}")
    require(stamp(regular(path)) == before and size == before[2], f"Input changed: {path}")
    return {"fileName": path.name, "sizeBytes": size, "sha256": digest.hexdigest(), "stamp": before}


def public_identity(value: dict) -> dict:
    return {key: value[key] for key in ("fileName", "sizeBytes", "sha256")}


def no_duplicates(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json(data: bytes, label: str) -> dict:
    require(0 < len(data) <= METADATA_LIMIT, f"Empty/oversized metadata: {label}")
    result = json.loads(data.decode("utf-8-sig"), object_pairs_hook=no_duplicates,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"Invalid JSON constant: {value}")))
    require(isinstance(result, dict), f"Expected JSON object: {label}")
    return result


def read_metadata(path: Path, expected: dict) -> dict:
    require(expected["sizeBytes"] <= METADATA_LIMIT, f"Metadata exceeds limit: {path}")
    with path.open("rb") as stream:
        data = stream.read(METADATA_LIMIT + 1)
    require(hashlib.sha256(data).hexdigest() == expected["sha256"], f"Metadata changed: {path}")
    return parse_json(data, str(path))


def validate_release(record: dict, installer: dict, source: dict) -> None:
    require(record.get("schemaVersion") == "aive.delivery-inputs.v1", "Release schema mismatch")
    require(isinstance(record.get("releaseVersion"), str) and bool(VERSION.fullmatch(record["releaseVersion"])),
        "Explicit controller-compatible releaseVersion required")
    require(record.get("platform") == "win32" and record.get("architecture") == "x64", "Release platform mismatch")
    commit = record.get("sourceCommit")
    require(isinstance(commit, str) and bool(COMMIT.fullmatch(commit)), "Invalid release sourceCommit")
    require(record.get("githubRepository") == REPOSITORY, "Repository mismatch")
    require(record.get("githubReleaseTag") == "v" + record["releaseVersion"], "Release tag mismatch")
    ci = record.get("ci")
    require(isinstance(ci, dict), "CI identity required")
    run = ci.get("runId")
    require((type(run) is int and run > 0) or (isinstance(run, str) and bool(re.fullmatch(r"[0-9]+", run)) and int(run) > 0),
        "CI runId must be a positive numeric identity")
    require(ci.get("runUrl") == f"https://github.com/{REPOSITORY}/actions/runs/{run}", "CI run URL mismatch")
    require(ci.get("commit") == commit and ci.get("status") == "success", "CI/source identity or success mismatch")
    for key, actual in (("installer", installer), ("sourceArchive", source)):
        supplied = record.get(key)
        require(isinstance(supplied, dict) and all(supplied.get(k) == v for k, v in public_identity(actual).items())
            and integer(supplied.get("sizeBytes")), f"Actual {key} filename/size/hash mismatch")
    qualification = record.get("qualification")
    require(isinstance(qualification, dict) and set(qualification) == QUALIFICATIONS
        and all(text(value) for value in qualification.values()), "Explicit qualification evidence/limitations required")
    commits = record.get("componentSourceCommits")
    require(isinstance(commits, dict) and set(commits) == COMPONENTS
        and all(isinstance(c, str) and bool(COMMIT.fullmatch(c)) for c in commits.values()),
        "Exact source commits for all four components required")


def validate_acceptance(record: dict, release: dict, installer: dict) -> None:
    require(record.get("schemaVersion") == "aive.delivery-acceptance.v1", "Acceptance schema mismatch")
    require(record.get("releaseVersion") == release["releaseVersion"]
        and record.get("sourceCommit") == release["sourceCommit"]
        and record.get("installerSha256") == installer["sha256"], "Acceptance identity mismatch")
    require(record.get("status") == "passed", "Final installed acceptance has not passed")
    gates = record.get("gates")
    require(isinstance(gates, dict) and set(gates) == GATES, "Acceptance requires exactly all eleven installed gates")
    for name in sorted(GATES):
        gate = gates[name]
        require(isinstance(gate, dict) and gate.get("status") == "passed" and text(gate.get("evidence")),
            f"Missing/unpassed gate or evidence: {name}")


def inspect_zip(path: Path, *, expanded_limit: int | None = None,
    component_id: str | None = None) -> dict[str, zipfile.ZipInfo]:
    entries = {}
    files = set()
    directories = set()
    expanded = 0
    spellings = {}
    with zipfile.ZipFile(path) as archive:
        require(0 < len(archive.infolist()) <= MAX_ENTRIES, f"ZIP entry count invalid: {path}")
        for entry in archive.infolist():
            name = entry.filename[:-1] if entry.is_dir() else entry.filename
            safe_name(name)
            reject_private(name.split("/"), component_id=component_id)
            require(entry.orig_filename == entry.filename, f"NUL/truncated ZIP name: {path}")
            folded = name.casefold()
            for length in range(1, len(name.split('/')) + 1):
                prefix = '/'.join(name.split('/')[:length])
                previous = spellings.setdefault(prefix.casefold(), prefix)
                require(previous == prefix, f'Case-colliding ZIP ancestor: {name}')
            require(folded not in entries, f"Duplicate/case-colliding ZIP entry: {name}")
            mode = stat.S_IFMT(entry.external_attr >> 16)
            require(mode in (0, stat.S_IFDIR if entry.is_dir() else stat.S_IFREG), f"Nonregular/symlink ZIP entry: {name}")
            require(not entry.flag_bits & 1 and entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                f"Encrypted/unsupported ZIP entry: {name}")
            require(entry.file_size >= 0 and entry.compress_size >= 0 and (not entry.is_dir() or entry.file_size == 0),
                f"Invalid ZIP entry size: {name}")
            ancestors = {"/".join(folded.split("/")[:i]) for i in range(1, len(folded.split("/")))}
            require(not ancestors & files and (entry.is_dir() or folded not in directories), f"ZIP file/directory collision: {name}")
            directories.update(ancestors)
            (directories if entry.is_dir() else files).add(folded)
            entries[folded] = entry
            expanded += entry.file_size
            require(expanded_limit is None or expanded <= expanded_limit, f"ZIP expandedBytes exceeds manifest: {path}")
    return entries


def validate_component(component: dict) -> None:
    require(isinstance(component, dict), "Invalid component object")
    require(isinstance(component.get("id"), str) and component["id"] in COMPONENTS, "Unexpected component ID")
    require(isinstance(component.get("version"), str) and bool(VERSION.fullmatch(component["version"])), "Invalid component version")
    name = safe_name(component.get("archive"), basename=True)
    require(name.endswith(".zip"), "Component archive must be ZIP")
    require(isinstance(component.get("sha256"), str) and bool(SHA256.fullmatch(component["sha256"])), "Invalid component hash")
    require(integer(component.get("sizeBytes")) and integer(component.get("expandedBytes"))
        and component.get("required") is True, "Required component size/expansion/required mismatch")
    entrypoints = component.get("entrypoints")
    require(isinstance(entrypoints, dict) and 0 < len(entrypoints) <= 100, "Component entrypoints required")
    for key, value in entrypoints.items():
        require(text(key), "Invalid entrypoint key")
        safe_name(value)
    probes = component.get("probes")
    require(isinstance(probes, list) and 0 < len(probes) <= 100, "Component probes required")
    for probe in probes:
        require(isinstance(probe, dict) and isinstance(probe.get("kind"), str) and probe["kind"] in PROBES
            and isinstance(probe.get("entrypoint"), str) and probe["entrypoint"] in entrypoints, "Invalid component probe")
        if "args" in probe:
            require(isinstance(probe["args"], list) and all(isinstance(a, str) and len(a) <= 512 and "\0" not in a for a in probe["args"]),
                "Invalid probe args")
        if probe["kind"] == "whisper-model":
            require(isinstance(probe.get("runtimeEntrypoint"), str) and probe["runtimeEntrypoint"] in entrypoints
                and isinstance(probe.get("audioEntrypoint"), str) and probe["audioEntrypoint"] in entrypoints
                and isinstance(probe.get("expectedText"), str) and 5 <= len(probe["expectedText"]) <= 200,
                "Whisper joint probe incomplete")
    if component.get("url"):
        require(isinstance(component["url"], str), "Invalid component URL")
        url = urlsplit(component["url"])
        require(url.scheme == "https" and bool(url.hostname) and not url.username and not url.password and not url.fragment,
            "Invalid component HTTPS URL")


def require_installer_pe(path: Path, size: int) -> None:
    require(size >= 64, "Installer too small for Windows PE")
    with path.open("rb") as stream:
        header = stream.read(64)
        require(header[:2] == b"MZ", "Installer lacks MZ header")
        offset = struct.unpack_from("<I", header, 60)[0]
        require(64 <= offset <= size - 24, "Installer PE header outside file bounds")
        stream.seek(offset)
        require(stream.read(4) == b"PE\0\0", "Installer lacks PE signature")
    # NSIS bootstrap machine may be x86; payload architecture is recorded separately.


def encode(value: object) -> bytes:
    data = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    require(len(data) <= METADATA_LIMIT, "Generated delivery metadata too large")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("installer", "component-manifest", "component-directory", "source-archive",
        "release-record", "acceptance-record", "guide", "notice", "output-dir"):
        parser.add_argument("--" + flag, required=True, type=Path)
    args = parser.parse_args()
    paths = {name: input_path(getattr(args, name)) for name in ("installer", "component_manifest",
        "source_archive", "release_record", "acceptance_record", "guide", "notice")}
    component_directory = input_path(args.component_directory, directory=True)
    output = validate_output(args.output_dir.absolute())
    reject_private(output.relative_to(AUTHORIZED_ROOT).parts)
    require(not output.exists(), "Output directory must be fresh and absent")
    require(not output.is_relative_to(component_directory) and not component_directory.is_relative_to(output),
        "Component directory and output overlap")
    require(len(set(paths.values())) == len(paths), "Each explicit input must be a distinct file")
    for path in paths.values():
        require(not path.is_relative_to(output), f"Input overlaps output: {path}")
        safe_name(path.name, basename=True)
    identities = {name: identity(path) for name, path in paths.items()}
    require(all(value["sizeBytes"] > 0 for value in identities.values()), "Empty delivery input rejected")
    release = read_metadata(paths["release_record"], identities["release_record"])
    acceptance = read_metadata(paths["acceptance_record"], identities["acceptance_record"])
    manifest = read_metadata(paths["component_manifest"], identities["component_manifest"])
    validate_release(release, identities["installer"], identities["source_archive"])
    validate_acceptance(acceptance, release, identities["installer"])
    require_installer_pe(paths["installer"], identities["installer"]["sizeBytes"])
    inspect_zip(paths["source_archive"])
    require(manifest.get("schemaVersion") == "aive.components.v1"
        and all(manifest.get(k) == release[k] for k in ("releaseVersion", "platform", "architecture")), "Component manifest release mismatch")
    components = manifest.get("components")
    require(isinstance(components, list) and len(components) == 4, "Exactly four components required")
    files = {"installer/" + paths["installer"].name: paths["installer"],
        "offline-components/" + paths["component_manifest"].name: paths["component_manifest"],
        "source/" + paths["source_archive"].name: paths["source_archive"],
        "README.txt": paths["guide"], "NOTICE.txt": paths["notice"],
        "evidence/release-record.json": paths["release_record"],
        "evidence/acceptance-record.json": paths["acceptance_record"]}
    known = {path: identities[name] for name, path in paths.items()}
    ids = set()
    archives = {paths["component_manifest"].name.casefold()}
    component_details = []
    for component in components:
        validate_component(component)
        cid = component["id"]
        require(cid.casefold() not in ids and component["archive"].casefold() not in archives, "Duplicate component ID/filename")
        ids.add(cid.casefold())
        archives.add(component["archive"].casefold())
        path = input_path(component_directory / component["archive"])
        actual = identity(path)
        require(actual["sizeBytes"] == component["sizeBytes"] and actual["sha256"] == component["sha256"],
            f"Actual component size/hash mismatch: {cid}")
        # Actual archive hash/size matched above before granting engine CA allowance.
        entries = inspect_zip(path, expanded_limit=component['expandedBytes'], component_id=cid)
        for entry in component["entrypoints"].values():
            item = entries.get(entry.casefold())
            require(item is not None and not item.is_dir() and item.filename == entry and item.file_size > 0,
                f"Missing actual entrypoint: {cid}/{entry}")
        item = entries.get("source-identity.json")
        require(item is not None and not item.is_dir() and 0 < item.file_size <= METADATA_LIMIT,
            f"Component source-identity.json required: {cid}")
        with zipfile.ZipFile(path) as archive:
            with archive.open(item) as stream:
                embedded = parse_json(stream.read(METADATA_LIMIT + 1), f"{cid}/source-identity.json")
        require(embedded.get("component") == cid and embedded.get("version") == component["version"],
            f"Embedded component identity mismatch: {cid}")
        if "releaseVersion" in embedded:
            require(embedded["releaseVersion"] == release["releaseVersion"], f"Embedded component release mismatch: {cid}")
        metadata = embedded.get("metadata", {})
        require(isinstance(metadata, dict), f"Invalid component metadata: {cid}")
        declared_commit = release["componentSourceCommits"][cid]
        embedded_commits = [obj['sourceCommit'] for obj in (embedded, metadata) if 'sourceCommit' in obj]
        if cid == 'whisper-small' and 'runtimeSourceCommit' in metadata:
            embedded_commits.append(metadata['runtimeSourceCommit'])
        require(bool(embedded_commits) and all(commit == declared_commit for commit in embedded_commits),
            f"Component source commit absent/unmatched (Whisper also permits metadata.runtimeSourceCommit): {cid}")
        component_details.append({"manifest": component, "sourceCommit": declared_commit, "sourceIdentity": embedded})
        files["offline-components/" + component["archive"]] = path
        known[path] = actual
    require(ids == COMPONENTS, "Missing required component ID")
    require(len({name.casefold() for name in files}) == len(files), "Delivery archive entry collision")
    hashes = {name: known[path]["sha256"] for name, path in files.items()}
    delivery = {"schemaVersion": "aive.delivery.v1", "releaseVersion": release["releaseVersion"],
        "platform": "win32", "architecture": "x64", "sourceCommit": release["sourceCommit"],
        "githubRepository": REPOSITORY, "githubReleaseTag": release["githubReleaseTag"], "ci": release["ci"],
        "qualification": release["qualification"], "componentSourceCommits": release["componentSourceCommits"],
        "components": sorted(component_details, key=lambda c: c["manifest"]["id"]),
        "acceptance": acceptance, "releaseInputs": release,
        "files": {name: public_identity(known[path]) for name, path in sorted(files.items())}}
    data = {"DELIVERY.json": encode(delivery)}
    hashes["DELIVERY.json"] = hashlib.sha256(data["DELIVERY.json"]).hexdigest()
    data["SHA256SUMS.txt"] = "".join(f"{hashes[name]}  {name}\n" for name in sorted(hashes)).encode("utf-8")
    final = output / f"AIVE-Desktop-{release['releaseVersion']}-win32-x64-delivery.zip"
    partial = output / (final.name + "." + uuid.uuid4().hex + ".part")
    validate_output(final)
    validate_output(partial)
    output.mkdir(parents=True, exist_ok=False)
    created = False
    try:
        with partial.open("xb") as raw:
            created = True
            with zipfile.ZipFile(raw, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True) as archive:
                for name in sorted(set(files) | set(data)):
                    info = zipfile.ZipInfo(safe_name(name), date_time=(1980, 1, 1, 0, 0, 0))
                    info.create_system = 3
                    info.external_attr = (stat.S_IFREG | 0o644) << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info._compresslevel = 9
                    with archive.open(info, "w", force_zip64=True) as destination:
                        if name in data:
                            destination.write(data[name])
                            continue
                        path = input_path(files[name])
                        expected = known[path]
                        before_info = regular(path)
                        require(stamp(before_info) == expected['stamp'], f'Input changed before copy: {path}')
                        digest = hashlib.sha256()
                        size = 0
                        with path.open("rb") as source:
                            opened_info = os.fstat(source.fileno())
                            require(os.path.samestat(before_info, opened_info) and stamp(opened_info) == expected['stamp'],
                                f'Input replaced before copy: {path}')
                            opened_stamp = handle_stamp(opened_info)
                            for block in iter(lambda: source.read(CHUNK), b""):
                                destination.write(block)
                                digest.update(block)
                                size += len(block)
                            require(handle_stamp(os.fstat(source.fileno())) == opened_stamp, f"Input changed during copy: {path}")
                        require(size == expected["sizeBytes"] and digest.hexdigest() == expected["sha256"], f"Input changed during copy: {path}")
            raw.flush()
            os.fsync(raw.fileno())
        for path, expected in known.items():
            input_path(path)
            actual = identity(path)
            require(actual == expected, f"Input changed during assembly: {path}")
        validate_output(final)
        require(not final.exists(), f"Refusing existing delivery: {final}")
        os.link(partial, final)  # Atomic same-directory publication; never overwrites.
        partial.unlink()
        created = False
    except BaseException:
        if created:
            validate_output(partial)
            partial.unlink(missing_ok=True)  # Only this invocation's unique temporary file.
        raise
    print(json.dumps({"archive": str(final), **public_identity(identity(final))}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, UnicodeError) as error:
        raise SystemExit(f"package_delivery.py: error: {error}")
