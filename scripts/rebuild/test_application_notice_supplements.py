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
    return cases
