"""Package v1.3 against the saved v1.2 working tree, preserving older releases."""
import argparse
import hashlib
import json
from pathlib import Path
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def project_files():
    files = {}
    patterns = ("*.py", "*.cmd", "*requirements*.txt", "README.*", "CHANGELOG.txt",
                "NOTICE.txt", "UPDATE_v1.3.txt", "*prompt*.txt", "*plan*.txt", "*REPORT*.txt",
                "Torque_GUI_project_state_v1.0.json", "help_content.json", ".gitignore", ".gitattributes")
    for pattern in patterns:
        for path in ROOT.glob(pattern):
            files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    for folder in ("tests", "tools", "examples", "profiles", "fixtures"):
        for path in (ROOT/folder).iterdir():
            if path.is_file() and (path.suffix in (".py", ".json", ".txt") or path.name == "SYNTHETIC_software_fixture.dat"):
                files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    return files


def write_zip(path, files, metadata):
    if path.exists() or path.suffix.lower() != ".zip":
        raise ValueError("Choose an unused .zip output path.")
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = dict(metadata, entries={name: digest(data) for name, data in sorted(files.items())})
    members = dict(files)
    members["PACKAGE_MANIFEST.json"] = (json.dumps(manifest, indent=2)+"\n").encode()
    stage = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with zipfile.ZipFile(stage, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name, data in sorted(members.items()):
                archive.writestr(name, data)
        with zipfile.ZipFile(stage) as archive:
            assert archive.testzip() is None
            assert len(archive.namelist()) == len(set(archive.namelist()))
            for name, expected in manifest["entries"].items():
                assert digest(archive.read(name)) == expected, name
        stage.rename(path)
    finally:
        stage.unlink(missing_ok=True)
    result = {"path": str(path), "bytes": path.stat().st_size, "sha256": digest(path.read_bytes()),
              "entries": len(members), "CRC_and_member_hashes_verified": True}
    path.with_suffix(".zip.sha256").write_text(result["sha256"]+"  "+path.name+"\n", encoding="ascii")
    path.with_suffix(".package_verification.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    return result


def main(destination):
    base = ROOT/"validation/usability_v1.3"
    before = json.loads((base/"before.json").read_text(encoding="utf-8"))
    current = project_files()
    removals = sorted(name for name in before["source_sha256"] if not (ROOT/name).is_file())
    update = {name: data for name, data in current.items()
              if before["source_sha256"].get(name) != digest(data)}
    # The revised prompt predates the source snapshot but is required delivery.
    update["Torque_GUI_v1.3_execution_prompt_v1.1.txt"] = current["Torque_GUI_v1.3_execution_prompt_v1.1.txt"]
    metadata = {"version": "1.3", "comparison_basis": "Actual pre-patch v1.2 working contents, not Git HEAD",
                "base_git_head": before["git_head"], "base_source_sha256": before["source_sha256"],
                "required_removals": removals}
    full = dict(current)
    state = json.loads(current["Torque_GUI_project_state_v1.0.json"])
    raw = state["authoritative_inputs"]["Ho2sq3_raw"]
    data = Path(raw["path"]).read_bytes()
    assert digest(data) == raw["sha256"]
    full["fixtures/Ho2sq3_Rot1_00001.dat"] = data
    for name in ("Ho2sq3_full_range", "Ho2sq3_0_to_200", "Ho2sq3_manual_demo"):
        filename = "examples/"+name+".json"
        document = json.loads(full[filename])
        for entry in document["files"]:
            entry["path"] = "../fixtures/Ho2sq3_Rot1_00001.dat"
        full[filename] = (json.dumps(document, indent=2, ensure_ascii=False)+"\n").encode()
    def add(path):
        if path.is_file():
            full[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    evidence = ROOT/"evidence/Torque_Ho2thd4Pc_pipeline_comparison_v1.2"
    for folder in (evidence/"inputs", evidence/"previous/inputs"):
        for path in folder.glob("*.dat"):
            add(path)
    for folder in (ROOT/"validation/regression").iterdir():
        for name in ("settings.json", "provenance.json", "treated.dat"):
            add(folder/name)
    for name in ("before.json", "before_unit_tests.txt", "unit_tests_final.txt", "preservation_final.json", "package_preflight.json",
                 "usability_gui_final.txt", "workflow_gui_final.txt", "isolation_verified.txt"):
        add(base/name)
    for path in (base/"before").rglob("*"):
        add(path)
    for directory in ("usability_gui_final", "workflow_gui_final", "regression_final", "isolation_verified", "figures_final"):
        folder = base/directory
        for filename in ("report.json", "figure_checks.json"):
            add(folder/filename)
        for pattern in ("*.png", "*.pdf"):
            for path in folder.glob(pattern):
                add(path)
    example = ROOT/"runs/Ho2sq3_0_to_200_v1.3.dat"
    add(example)
    for path in example.with_name(example.name+".details").iterdir():
        add(path)
    results = [write_zip(destination/"Torque_Postprocessing_v1.3_source.zip", full,
                         dict(metadata, kind="source/tests/help/fixtures", portable_paths="Current example paths rebased to included raw fixture only")),
               write_zip(destination/"Torque_Postprocessing_v1.3_GitHub_update.zip", update,
                         dict(metadata, kind="v1.2 update; no raw/evidence/runs", supplemental_files=["Torque_GUI_v1.3_execution_prompt_v1.1.txt"]))]
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, default=ROOT)
    main(parser.parse_args().destination.resolve())
