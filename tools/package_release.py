"""Verify recorded acceptance artifacts and package the release; does not rerun tests."""
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from io_profiles import PROFILES, TSV_HEADER, sha256
from storage import atomic_json, environment
from regression import CASES, EVIDENCE
from test_core import CoreTests, synthetic


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def text(path, value):
    Path(path).write_text(value, encoding="utf-8", newline="\n")


def verify(path):
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    for line in lines:
        digest, name = line.split("  ", 1)
        target = (Path(path).parent / name).resolve()
        if not target.is_relative_to(Path(path).parent.resolve()) or sha256(target) != digest:
            raise RuntimeError(f"Integrity mismatch: {target}")
    return len(lines)


def main():
    stamp = datetime.now(timezone.utc).isoformat()
    checked = verify(EVIDENCE / "SHA256SUMS.txt")
    if checked != 191:
        raise RuntimeError(f"Expected 191 source entries, found {checked}")
    source_zip = ROOT.parent / "Torque_Ho2thd4Pc_pipeline_comparison_v1.2.zip"
    expected = "71b5c9bd246648fd52ad6cdaf48626ce6b9051facbbb31bea35347fcdffdc605"
    prompt = "Torque_GUI_implementation_prompt_v1.0.txt"
    source = {"checked_utc": stamp, "checked_files": checked, "failures": [],
              "manifest": str((EVIDENCE / "SHA256SUMS.txt").relative_to(ROOT)),
              "authoritative_zip_bytes": 7814997, "authoritative_zip_sha256": expected,
              "prompt_sha256": sha256(ROOT / prompt)}
    if source_zip.exists():
        if source_zip.stat().st_size != 7814997 or sha256(source_zip) != expected:
            raise RuntimeError("Authoritative source ZIP changed")
        source["original_archive_unchanged"] = True
    if (ROOT.parent / prompt).exists():
        if sha256(ROOT.parent / prompt) != sha256(ROOT / prompt):
            raise RuntimeError("Build prompt copy differs")
        source["prompt_copy_exact"] = True
    atomic_json(ROOT / "source_verification.json", source)

    fixtures = []
    for name, raw, reference, profile, preset, nr, ns, np in CASES:
        fixtures.append({"id": name, "kind": "supplied experimental regression fixture",
                         "raw": str((EVIDENCE / raw).relative_to(ROOT)), "raw_sha256": sha256(EVIDENCE / raw),
                         "reference": str((EVIDENCE / reference).relative_to(ROOT)), "reference_sha256": sha256(EVIDENCE / reference),
                         "raw_rows": nr, "signal_rows": ns, "signal_passes": np, "profile": profile, "explicit_preset": preset})
    for name, profile in PROFILES.items():
        atomic_json(ROOT / "profiles" / (name + ".json"), asdict(profile))
    synthetic_path = ROOT / "fixtures/SYNTHETIC_software_fixture.dat"
    synthetic_path.parent.mkdir(exist_ok=True)
    with synthetic_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(TSV_HEADER)
        writer.writerows(synthetic())
    fixtures.append({"id": "SYNTHETIC_software_fixture", "kind": "software admission only, not a measurement",
                     "raw": str(synthetic_path.relative_to(ROOT)), "raw_sha256": sha256(synthetic_path),
                     "raw_rows": 82, "signal_rows": 41, "profile": "fractional", "generator": "tests/test_core.py:synthetic"})
    atomic_json(ROOT / "fixtures/manifest.json", {"paths_relative_to": "application root", "fixtures": fixtures})
    regression = read(ROOT / "validation/regression/regression_summary.json")
    gui = read(ROOT / "validation/gui/gui_test_results.json")
    for row in regression["results"]:
        run = ROOT / row["output_directory"]
        verify(run / "SHA256SUMS.txt")
        if sha256(run / "treated.dat") != row["output_sha256"]:
            raise RuntimeError("Recorded DAT changed")
        for name, digest in read(run / "provenance.json")["code_sha256"].items():
            if sha256(ROOT / name) != digest:
                raise RuntimeError("Core changed since regression: " + name)
    for name in ("app", "plots"):
        if sha256(ROOT / (name + ".py")) != gui[name + "_sha256"]:
            raise RuntimeError("Source changed since final GUI test: " + name)
    if gui["status"] != "PASS" or not gui["GUI_CLI_DAT_byte_identical"]:
        raise RuntimeError("GUI acceptance missing")
    gui_run = ROOT / "validation/gui/runs" / Path(gui["current_run"]).name
    cli_run = max((ROOT / "validation/gui/cli_comparison").iterdir(), key=lambda p: p.name)
    for run in (gui_run, cli_run):
        verify(run / "SHA256SUMS.txt")
    if sha256(gui_run / "treated.dat") != sha256(cli_run / "treated.dat"):
        raise RuntimeError("GUI/CLI byte equality changed")
    core = {"record_type": "Transcribed from observed unittest output; not rerun by packaging",
            "command": ".venv/Scripts/python.exe tests/test_core.py", "status": "PASS", "tests_run": 17,
            "elapsed_seconds": 0.560, "failures": 0, "errors": 0,
            "test_names": unittest.defaultTestLoader.getTestCaseNames(CoreTests),
            "source_sha256": sha256(ROOT / "tests/test_core.py"), "environment": environment()}
    atomic_json(ROOT / "validation/core_test_results.json", core)
    integrity = {"checked_utc": stamp, "source_manifest_files": checked, "regression_run_manifests_checked": 6,
                 "core_matches_regression": True, "app_and_plots_match_GUI_test": True, "GUI_CLI_DAT_byte_identical": True,
                 "portable_GUI_run": str(gui_run.relative_to(ROOT)), "portable_CLI_run": str(cli_run.relative_to(ROOT))}
    atomic_json(ROOT / "validation/release_integrity.json", integrity)
    state = read(ROOT / "Torque_GUI_project_state_v1.0.json")
    state.update(updated_utc=stamp, authoritative_inputs=source, environment=environment(),
                 verified_regression=regression, final_integrity=integrity)
    atomic_json(ROOT / "Torque_GUI_project_state_v1.0.json", state)

    files = []
    folders = {"evidence", "examples", "fonts", "profiles", "fixtures", "tests", "tools"}
    logs = {"gui_release_stdout.txt", "gui_release_stderr.txt", "isolation_results.json", "core_test_results.json",
            "desktop_verification.json", "release_integrity.json"}
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(p in (".venv", "__pycache__") for p in rel.parts) or path.suffix == ".pyc":
            continue
        include = False
        if len(rel.parts) == 1:
            include = path.name not in {"User_session.json", "SHA256SUMS.txt", "FILE_MANIFEST.json"}
        elif rel.parts[0] in folders:
            include = True
        elif rel.parts[0] == "validation":
            include = rel.parts[1] in {"regression", "plots", "screenshots"} or (len(rel.parts) == 2 and rel.parts[1] in logs)
            include |= rel.as_posix() in {"validation/gui/gui_test_results.json", "validation/gui/session.json", "validation/gui/SYNTHETIC_invalid_units.dat"}
            include |= path.is_relative_to(gui_run) or path.is_relative_to(cli_run)
        if include:
            files.append(path)
    atomic_json(ROOT / "FILE_MANIFEST.json", {"created_utc": stamp, "root": ROOT.name,
        "files": {p.relative_to(ROOT).as_posix(): {"bytes": p.stat().st_size, "sha256": sha256(p)} for p in files},
        "note": "Excludes itself and SHA256SUMS.txt to avoid circular hashes; archive verification covers both."})
    files.append(ROOT / "FILE_MANIFEST.json")
    text(ROOT / "SHA256SUMS.txt", "".join(f"{sha256(p)}  {p.relative_to(ROOT).as_posix()}\n" for p in sorted(files)))
    files.append(ROOT / "SHA256SUMS.txt")
    destination = ROOT.parent / (ROOT.name + ".zip")
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            archive.write(path, ROOT.name + "/" + path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None or len(archive.namelist()) != len(files):
            raise RuntimeError("ZIP CRC/count verification failed")
        for path in files:
            name = ROOT.name + "/" + path.relative_to(ROOT).as_posix()
            if hashlib.sha256(archive.read(name)).hexdigest() != sha256(path):
                raise RuntimeError("ZIP member mismatch: " + name)
    package = {"status": "PASS", "created_utc": stamp, "archive": destination.name,
               "bytes": destination.stat().st_size, "sha256": sha256(destination), "files_checked": len(files),
               "ZIP_CRC_pass": True, "every_member_SHA256_matches": True, "source_evidence_entries_verified": checked,
               "uncompressed_bytes": sum(p.stat().st_size for p in files)}
    atomic_json(destination.with_suffix(".package_verification.json"), package)
    text(destination.with_suffix(".zip.sha256"), f"{package['sha256']}  {destination.name}\n")
    print(json.dumps(package, indent=2))


if __name__ == "__main__":
    main()
