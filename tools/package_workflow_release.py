"""Build a portable source/evidence ZIP without altering inputs or prior releases."""
import argparse
import hashlib
import json
from pathlib import Path
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main(output):
    output = output.resolve()
    if output.exists() or output.suffix.lower() != ".zip":
        raise ValueError("Choose an unused .zip output path.")
    files = {}
    def add(path):
        if path.is_file():
            files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    for pattern in ("*.py", "*.cmd", "*requirements*.txt", "README.*", "CHANGELOG.txt",
                    "*prompt*.txt", "*plan*.txt", "*REPORT*.txt", "Torque_GUI_project_state_v1.0.json", ".gitignore"):
        for path in ROOT.glob(pattern):
            add(path)
    for directory in ("tests", "tools"):
        for path in (ROOT/directory).glob("*.py"):
            add(path)
    add(ROOT/"examples/README.txt")
    for name in ("Ho2sq3_full_range", "Ho2sq3_0_to_200", "Ho2sq3_manual_demo"):
        path = ROOT/"examples"/(name+".json")
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        for entry in document["files"]:
            entry["path"] = "../fixtures/Ho2sq3_Rot1_00001.dat"
        files[path.relative_to(ROOT).as_posix()] = (json.dumps(document,indent=2,ensure_ascii=False)+"\n").encode()
    state = json.loads((ROOT/"Torque_GUI_project_state_v1.0.json").read_text(encoding="utf-8"))
    raw = state["authoritative_inputs"]["Ho2sq3_raw"]
    blob = Path(raw["path"]).read_bytes()
    assert hashlib.sha256(blob).hexdigest() == raw["sha256"]
    files["fixtures/Ho2sq3_Rot1_00001.dat"] = blob
    evidence = ROOT/"evidence/Torque_Ho2thd4Pc_pipeline_comparison_v1.2"
    for directory in (evidence/"inputs", evidence/"previous/inputs"):
        for path in directory.glob("*.dat"):
            add(path)
    for folder in (ROOT/"validation/regression").iterdir():
        for name in ("settings.json", "provenance.json", "treated.dat"):
            add(folder/name)
    base = ROOT/"validation/import_workflow_v1.2"
    for name in ("before.json", "before_tests.txt", "unit_tests_final.txt", "source_hashes.json",
                 "preservation_before.json", "preservation_final.json", "gui_final.txt"):
        add(base/name)
    for directory in ("gui_final", "isolation_final", "figures_final"):
        for path in (base/directory).iterdir():
            if path.suffix.lower() in (".json", ".png", ".pdf"):
                add(path)
    add(base/"regression_final/report.json")
    for path in (base/"regression_final/Ho2sq3_full_range").iterdir():
        add(path)
    treated = ROOT/"runs/Ho2sq3_0_to_200_v1.2.dat"
    add(treated)
    for path in treated.with_name(treated.name+".details").iterdir():
        add(path)
    manifest = {"version": "1.2", "source_base_commit": "b9517f489a35dcf3984ea48356fc3d12956e7c5c",
                "portable_example_paths": "Only example session file paths are rebased to the included raw fixture.",
                "entries": {name: hashlib.sha256(data).hexdigest() for name,data in sorted(files.items())}}
    files["PACKAGE_MANIFEST.json"] = (json.dumps(manifest,indent=2)+"\n").encode()
    output.parent.mkdir(parents=True,exist_ok=True)
    stage = output.with_name("."+output.name+"."+uuid.uuid4().hex+".tmp")
    try:
        with zipfile.ZipFile(stage, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name,data in sorted(files.items()):
                archive.writestr(name,data)
        with zipfile.ZipFile(stage) as archive:
            assert archive.testzip() is None
            for name,digest in manifest["entries"].items():
                assert hashlib.sha256(archive.read(name)).hexdigest() == digest, name
        stage.rename(output)
    finally:
        stage.unlink(missing_ok=True)
    result = {"path":str(output),"bytes":output.stat().st_size,
              "sha256":hashlib.sha256(output.read_bytes()).hexdigest(),"entries":len(files),
              "CRC_and_member_hashes_verified":True}
    output.with_suffix(".zip.sha256").write_text(result["sha256"]+"  "+output.name+"\n",encoding="ascii")
    output.with_suffix(".package_verification.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=ROOT/"Torque_Postprocessing_v1.2_source.zip")
    main(parser.parse_args().output)

