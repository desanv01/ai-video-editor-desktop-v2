"""Verify matched upstream inputs without erasing actual ASAR capture gaps."""
import copy
import hashlib
import json
import os
import subprocess


def verify_supplements(node, script, out, captured_inventory):
    folder = out / "supplement-input"
    folder.mkdir()
    inventory_file = folder / "inventory.json"
    manifest_file = folder / "supplements.json"
    # Keep the existing capture files and add a second unresolved package.
    inventory = copy.deepcopy(captured_inventory)
    inventory["inventory"][-1]["license"] = "Apache-2.0"
    second = copy.deepcopy(inventory["inventory"][-1])
    second.update(name="still-unresolved", packagePath="node_modules/still-unresolved",
                  packageJsonPath="node_modules/still-unresolved/package.json")
    inventory["inventory"].append(second)
    inventory["packageRecords"] += 1
    inventory["missingCapturedNotices"].append({
        "name": second["name"], "version": second["version"],
        "packageJsonPath": second["packageJsonPath"]})
    # Captured references remain relative to this independent fixture inventory.
    (folder / "notices").mkdir()
    for source in (out / "input/notices").iterdir():
        (folder / "notices" / source.name).write_bytes(source.read_bytes())
    inventory_file.write_text(json.dumps(inventory), encoding="utf-8")
    license_bytes = b"Synthetic full terms\nRaw UTF-8: \xc3\xa9\n"
    attribution_bytes = b"Synthetic exact-version attribution\nCopyright Fixture Owner\n"
    (folder / "terms.txt").write_bytes(license_bytes)
    (folder / "attribution.txt").write_bytes(attribution_bytes)
    pkg = inventory["inventory"][-2]
    item = {key: pkg[key] for key in ["name", "version", "packageJsonPath",
                                     "packageJsonSha256", "packageJsonSizeBytes"]}
    item["declaredLicense"] = pkg["license"]
    item["provenance"] = {
        "packageGitHead": "c" * 40, "fullTermsGitBlob": "d" * 40,
        "tarballSha256": "e" * 64,
        "fullTermsUrl": "https://github.com/fixture/repo/blob/revision/LICENSE",
        "sourceNoticesUrl": "https://github.com/fixture/repo/tree/revision/src",
        "maintainerExplanationUrl": "https://github.com/fixture/repo/issues/1",
        "association": "Synthetic exact-version fixture only."}
    item["files"] = [{"kind": kind, "file": name, "sizeBytes": len(raw),
                       "sha256": hashlib.sha256(raw).hexdigest()}
                      for kind, name, raw in [("full-license", "terms.txt", license_bytes),
                                              ("attribution", "attribution.txt", attribution_bytes)]]
    manifest = {"schema": "aive.application-notice-supplements.v1", "packages": [item]}
    cases = []

    def run(name, value=manifest, expected=True, target=None):
        manifest_file.write_text(json.dumps(value), encoding="utf-8")
        target = target or out / ("supplement-" + name)
        result = subprocess.run([node, str(script), "--inventory", str(inventory_file),
                                 "--output-dir", str(target), "--supplements", str(manifest_file)],
                                capture_output=True, text=True)
        assert (result.returncode == 0) == expected, (name, result.stderr)
        if not expected:
            assert not target.exists(), (name, "output created before rejection")
        cases.append({"name": name, "status": "PASS"})
        return target

    first = run("matched-raw-notices")
    second_output = run("deterministic")
    for name in ["THIRD_PARTY_APPLICATION_NOTICES.txt", "notice-assembly.json"]:
        assert (first / name).read_bytes() == (second_output / name).read_bytes()
    record = json.loads((first / "notice-assembly.json").read_text())
    assert record["schema"] == "aive.application-notices-assembly.v2"
    assert record["releaseApproved"] is False
    assert record["missingCapturedNotices"] == sorted(inventory["missingCapturedNotices"],
                                                     key=lambda p: p["packageJsonPath"])
    assert record["unresolvedNoticeInputs"] == [inventory["missingCapturedNotices"][-1]]
    assert record["capturedNoticeBlobs"] == inventory["capturedNoticeBlobs"]
    assert len(record["supplementedPackages"]) == 1 and record["supplementalNoticeBlobs"] == 2
    raw_output = (first / "THIRD_PARTY_APPLICATION_NOTICES.txt").read_bytes()
    assert raw_output.count(license_bytes) == 1 and raw_output.count(attribution_bytes) == 1
    for source in (folder / "notices").iterdir():
        assert raw_output.count(source.read_bytes()) == 1
    assert record["outputs"]["thirdPartyApplicationNotices"]["sha256"] == hashlib.sha256(raw_output).hexdigest()
    assert inventory_file.read_bytes() == json.dumps(inventory).encode()

    for key, wrong in [("name", "other"), ("version", "2.0.0"),
                       ("declaredLicense", "MIT"), ("packageJsonSha256", "f" * 64),
                       ("packageJsonSizeBytes", 11), ("packageJsonPath", "node_modules/unknown/package.json")]:
        bad = copy.deepcopy(manifest)
        bad["packages"][0][key] = wrong
        run("reject-identity-" + key, bad, False)
    bad = copy.deepcopy(manifest)
    bad["packages"].append(copy.deepcopy(item))
    run("reject-duplicate-owner", bad, False)
    bad = copy.deepcopy(manifest)
    captured = inventory["inventory"][0]
    for key in ["name", "version", "packageJsonPath", "packageJsonSha256", "packageJsonSizeBytes"]:
        bad["packages"][0][key] = captured[key]
    bad["packages"][0]["declaredLicense"] = captured["license"]
    run("reject-substitution-for-actual-captured-notice", bad, False)
    for kind in ["full-license", "attribution"]:
        bad = copy.deepcopy(manifest)
        bad["packages"][0]["files"] = [f for f in item["files"] if f["kind"] != kind]
        run("reject-missing-" + kind, bad, False)
    bad = copy.deepcopy(manifest)
    bad["packages"][0]["provenance"]["packageGitHead"] = "moving-branch"
    run("reject-unpinned-provenance", bad, False)
    for index, unsafe in enumerate(["../terms.txt", "/terms.txt", "x//terms.txt", "./terms.txt", "C:/terms.txt"]):
        bad = copy.deepcopy(manifest)
        bad["packages"][0]["files"][0]["file"] = unsafe
        run("reject-path-" + str(index), bad, False)
    (folder / "terms.txt").write_bytes(license_bytes + b"tamper")
    run("reject-tampered-terms", manifest, False)
    (folder / "terms.txt").write_bytes(license_bytes)
    bad = copy.deepcopy(manifest)
    bad["packages"][0]["files"][0]["sizeBytes"] = 16 * 1024 * 1024 + 1
    run("reject-oversize-input", bad, False)
    run("reject-output-overlap", manifest, False, folder / "output")
    # A directory alias must fail even when its bytes match the supplied hashes.
    alias = folder / "alias"
    if os.name == "nt":
        result = subprocess.run([node, "-e", "require('node:fs').symlinkSync(process.argv[1],process.argv[2],'junction')",
                                 str(folder), str(alias)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    else:
        alias.symlink_to(folder, target_is_directory=True)
    bad = copy.deepcopy(manifest)
    bad["packages"][0]["files"][0]["file"] = "alias/terms.txt"
    run("reject-symlink-junction-input", bad, False)
    before = {p.name: p.read_bytes() for p in first.iterdir()}
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    result = subprocess.run([node, str(script), "--inventory", str(inventory_file),
                             "--output-dir", str(first), "--supplements", str(manifest_file)],
                            capture_output=True, text=True)
    assert result.returncode != 0 and before == {p.name: p.read_bytes() for p in first.iterdir()}
    cases.append({"name": "supplement-existing-output-preserved", "status": "PASS"})
    cases.extend(verify_typed_supplements(node, script, out, captured_inventory))
    return cases


def verify_typed_supplements(node, script, out, captured_inventory):
    """Exercise recorded identity linkage, raw preservation and typed rejection."""
    from pathlib import Path
    library = script.parents[2] / "docs/rebuild/licenses"
    manifest = json.loads((library / "application-notice-supplements.v2.json").read_text())
    folder = out / "typed-supplement-input"
    folder.mkdir()
    inventory = copy.deepcopy(captured_inventory)
    inventory["inventory"] = [p for p in inventory["inventory"] if p["notices"]]
    (folder / "notices").mkdir()
    for source in (out / "input/notices").iterdir():
        (folder / "notices" / source.name).write_bytes(source.read_bytes())
    for item in manifest["packages"]:
        inventory["inventory"].append({
            "name": item["name"], "version": item["version"], "license": item["declaredLicense"],
            "packagePath": item["packageJsonPath"].removesuffix("/package.json"),
            "packageJsonPath": item["packageJsonPath"], "packageJsonSha256": item["packageJsonSha256"],
            "packageJsonSizeBytes": item["packageJsonSizeBytes"], "notices": [], "missingCapturedNotices": True})
        for notice in item["files"]:
            destination = folder / notice["file"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            raw = (library / notice["file"]).read_bytes()
            assert len(raw) == notice["sizeBytes"] and hashlib.sha256(raw).hexdigest() == notice["sha256"]
            if destination.exists():
                assert destination.read_bytes() == raw
            else:
                destination.write_bytes(raw)
    # Common Apache terms can occur inside a different captured notice. Verify
    # exact framed blobs rather than counting unlabelled substrings globally.
    pair_item = next(p for p in manifest["packages"] if p["name"] == "mj-context-menu")
    terms_file = next(f for f in pair_item["files"] if f["kind"] == "complete-license-text")
    common_terms = (folder / terms_file["file"]).read_bytes()
    captured_raw = b"Synthetic captured attribution\n" + common_terms
    captured_digest = hashlib.sha256(captured_raw).hexdigest()
    (folder / "notices" / (captured_digest + ".txt")).write_bytes(captured_raw)
    inventory["inventory"].append({"name": "captured-apache", "version": "fixture", "license": "Apache-2.0",
        "packagePath": "node_modules/captured-apache", "packageJsonPath": "node_modules/captured-apache/package.json",
        "packageJsonSha256": "c" * 64, "packageJsonSizeBytes": 10,
        "notices": [{"archivePath": "node_modules/captured-apache/LICENSE", "sizeBytes": len(captured_raw),
                     "sha256": captured_digest, "captured": "notices/" + captured_digest + ".txt"}],
        "missingCapturedNotices": False})
    inventory["capturedNoticeBlobs"] += 1
    for name in ["lazy-val", "load-script"]:
        raw = json.dumps({"name": name, "version": "fixture"}).encode()
        inventory["inventory"].append({"name": name, "version": "fixture", "license": "MIT",
            "packagePath": "node_modules/" + name, "packageJsonPath": "node_modules/" + name + "/package.json",
            "packageJsonSha256": hashlib.sha256(raw).hexdigest(), "packageJsonSizeBytes": len(raw),
            "notices": [], "missingCapturedNotices": True})
    inventory["packageRecords"] = len(inventory["inventory"])
    inventory["missingCapturedNotices"] = [{"name": p["name"], "version": p["version"], "packageJsonPath": p["packageJsonPath"]}
        for p in inventory["inventory"] if p["missingCapturedNotices"]]
    inventory_file = folder / "inventory.json"
    inventory_file.write_text(json.dumps(inventory), encoding="utf-8")
    manifest_file = folder / "supplements.json"
    cases = []

    def run(name, value=None, expected=True, target=None):
        manifest_file.write_text(json.dumps(value if value is not None else manifest), encoding="utf-8")
        target = target or out / ("typed-" + name)
        result = subprocess.run([node, str(script), "--inventory", str(inventory_file),
            "--output-dir", str(target), "--supplements", str(manifest_file)], capture_output=True, text=True)
        assert (result.returncode == 0) == expected, (name, result.stderr)
        if not expected:
            assert not target.exists(), (name, "output created before rejection")
        cases.append({"name": "typed-" + name, "status": "PASS"})
        return target, result

    first, result = run("nine-owner-integration")
    second, _ = run("deterministic")
    for name in ["THIRD_PARTY_APPLICATION_NOTICES.txt", "notice-assembly.json"]:
        assert (first / name).read_bytes() == (second / name).read_bytes()
    record = json.loads((first / "notice-assembly.json").read_text())
    summary = json.loads(result.stdout)
    assert record["schema"] == "aive.application-notices-assembly.v3" and record["releaseApproved"] is False
    assert record["inputs"]["upstreamSupplements"]["schema"] == manifest["schema"]
    assert record["capturedNoticeBlobs"] == inventory["capturedNoticeBlobs"]
    assert len(record["missingCapturedNotices"]) == summary["rawCaptureGaps"] == 11
    assert len(record["supplementedPackages"]) == summary["supplementedPackages"] == 9
    assert record["supplementalNoticeBlobs"] == summary["supplementalNoticeBlobs"] == 8
    assert {p["name"] for p in record["unresolvedNoticeInputs"]} == {"lazy-val", "load-script"}
    assert summary["unresolved"] == 2
    raw_output = (first / "THIRD_PARTY_APPLICATION_NOTICES.txt").read_bytes()
    unique = {n["sha256"]: folder / n["file"] for p in manifest["packages"] for n in p["files"]}
    assert len(unique) == 8
    for source in unique.values():
        raw = source.read_bytes()
        marker = ("=== UPSTREAM SUPPLEMENT " + hashlib.sha256(raw).hexdigest() +
                  " (" + str(len(raw)) + " raw bytes) ===\nBEGIN EXACT UPSTREAM BYTES\n").encode()
        assert raw_output.count(marker) == 1
        start = raw_output.index(marker) + len(marker)
        assert raw_output[start:start + len(raw)] == raw
        assert raw_output[start + len(raw):].startswith(b"\nEND EXACT UPSTREAM BYTES\n")
    assert raw_output.count(common_terms) == 2
    assert raw_output.count(captured_raw) == 1
    cases.append({"name": "typed-common-terms-in-captured-and-upstream-sections", "status": "PASS"})
    assert record["outputs"]["thirdPartyApplicationNotices"]["sha256"] == hashlib.sha256(raw_output).hexdigest()
    assert inventory_file.read_bytes() == json.dumps(inventory).encode()
    shared = manifest["packages"][0]["files"][0]["sha256"]
    assert sum(any(n["sha256"] == shared for n in p["notices"]) for p in record["supplementedPackages"]) == 3
    tag_index = next(i for i, p in enumerate(manifest["packages"]) if p["name"] == "degenerator")
    pair_index = next(i for i, p in enumerate(manifest["packages"]) if p["name"] == "mj-context-menu")
    readme_index = next(i for i, p in enumerate(manifest["packages"]) if p["name"] == "agent-base")
    actual_tag = record["supplementedPackages"][tag_index] if record["supplementedPackages"][tag_index]["name"] == "degenerator" else next(p for p in record["supplementedPackages"] if p["name"] == "degenerator")
    assert actual_tag["provenance"]["revisionBinding"]["publishedGitHead"] is None
    assert actual_tag["provenance"]["revisionBinding"]["kind"] == "version-tag"
    pair = next(p for p in record["supplementedPackages"] if p["name"] == "mj-context-menu")
    assert pair["provenance"]["evidenceSources"]["terms"]["commit"] != pair["provenance"]["revisionBinding"]["commit"]

    def reject(name, mutate):
        bad = copy.deepcopy(manifest)
        mutate(bad)
        run("reject-" + name, bad, False)

    reject("schema", lambda b: b.update(schema="aive.application-notice-supplements.v0"))
    reject("unknown-fields", lambda b: b.update(approved=True))
    reject("unknown-evidence", lambda b: b["packages"][0].update(evidenceType="declaration-only"))
    reject("duplicate-owner", lambda b: b["packages"].append(copy.deepcopy(b["packages"][0])))
    for key, wrong in [("name", "other"), ("version", "fixture"), ("declaredLicense", "MIT"),
            ("packageJsonSha256", "f" * 64), ("packageJsonSizeBytes", 11), ("packageJsonPath", "node_modules/unknown/package.json")]:
        reject("owner-" + key, lambda b, k=key, v=wrong: b["packages"][0].update({k: v}))
    reject("missing-role", lambda b: b["packages"][0].update(files=[]))
    reject("extra-role", lambda b: b["packages"][0]["files"].append(copy.deepcopy(b["packages"][0]["files"][0])))
    reject("wrong-role", lambda b: b["packages"][0]["files"][0].update(kind="source-readme-full-text"))
    reject("missing-pair-attribution", lambda b: b["packages"][pair_index]["files"].pop())
    reject("readme-as-root-license", lambda b: b["packages"][readme_index].update(evidenceType="source-license-file", files=[{**b["packages"][readme_index]["files"][0], "kind": "source-license-file"}]))
    reject("unpinned-source-url", lambda b: b["packages"][0]["provenance"]["evidenceSources"]["notice"].update(url="https://raw.githubusercontent.com/puppeteer/puppeteer/main/LICENSE"))
    reject("source-commit-mismatch", lambda b: b["packages"][0]["provenance"]["evidenceSources"]["notice"].update(commit="a" * 40))
    reject("published-head-mismatch", lambda b: b["packages"][0]["provenance"]["revisionBinding"].update(publishedGitHead="a" * 40))
    reject("tag-forged-published-head", lambda b: b["packages"][tag_index]["provenance"]["revisionBinding"].update(publishedGitHead="a" * 40))
    reject("tag-missing-object", lambda b: b["packages"][tag_index]["provenance"]["revisionBinding"].pop("tagObjectSha"))
    reject("tag-object-url-mismatch", lambda b: b["packages"][tag_index]["provenance"]["revisionBinding"].update(tagObjectUrl="https://api.github.com/repos/TooTallNate/proxy-agents/git/tags/" + "a" * 40))
    reject("tag-version-witness-mismatch", lambda b: b["packages"][tag_index]["provenance"]["revisionBinding"]["versionWitness"].update(version="wrong"))
    reject("malformed-archive-integrity", lambda b: b["packages"][0]["provenance"]["package"]["tarball"].update(distIntegrity="sha512-invalid"))
    for i, unsafe in enumerate(["../notice.txt", "/notice.txt", "C:/notice.txt", "a//b.txt", "./notice.txt"]):
        reject("unsafe-path-" + str(i), lambda b, p=unsafe: b["packages"][0]["files"][0].update(file=p))
    reject("notice-size", lambda b: b["packages"][0]["files"][0].update(sizeBytes=16 * 1024 * 1024 + 1))
    notice = folder / manifest["packages"][readme_index]["files"][0]["file"]
    saved = notice.read_bytes()
    raw = b"README: this package declares MIT. Copyright Fixture.\n"
    notice.write_bytes(raw)
    bad = copy.deepcopy(manifest)
    bad["packages"][readme_index]["files"][0].update(sizeBytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    run("reject-declaration-even-with-matching-byte-hash", bad, False)
    notice.write_bytes(saved + b"tamper")
    run("reject-notice-tamper", expected=False)
    notice.write_bytes(saved)
    run("reject-output-overlap", expected=False, target=folder / "output")
    return cases
