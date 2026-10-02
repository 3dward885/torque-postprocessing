"""Verify recorded v1.1 gates and package source plus immutable replay fixtures."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import zipfile
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from storage import atomic_json
from io_profiles import sha256


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def main(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise RuntimeError("Release ZIP exists; choose a new destination.")
    evidence = ROOT/"evidence/Torque_Ho2thd4Pc_pipeline_comparison_v1.2"
    checked = 0
    for line in (evidence/"SHA256SUMS.txt").read_text(encoding="utf-8-sig").splitlines():
        digest, relative = line.split("  ", 1)
        path = (evidence/relative).resolve()
        assert path.is_relative_to(evidence.resolve()) and sha256(path) == digest, path
        checked += 1
    assert checked == 191
    validation = ROOT/"validation/baseline_v1.1"
    gui = read(validation/"gui_background/gui_baseline_results.json")
    numerical = read(validation/"numerical_final/baseline_regression.json")
    assert gui["status"] == numerical["status"] == "PASS"
    assert gui["GUI_CLI_DAT_byte_identical"] and gui["isolation"]["reference_probe_denied"]
    endings = read(validation/"line_endings.json")
    for name, digest in gui["source_sha256"].items():
        actual = sha256(ROOT/name)
        assert actual == digest or (
            endings.get(name,{}).get("before_sha256") == digest and
            endings[name]["after_sha256"] == actual), name
    assert len(read(validation/"figures/figure_checks.json")) == 3
    assert "Ran 26 tests" in (validation/"unit_tests_final.txt").read_text(encoding="utf-8-sig")
    assert sha256(ROOT/"Torque_GUI_optional_baseline_implementation_plan_v1.0.txt") == "983481f23a0945564e6d2b06f247d4373157c53dd8f1a23a16c7e3d4cb0c437f"
    assert sha256(ROOT/"Torque_GUI_implementation_prompt_v1.0.txt") == "2e46c9549ecd7efb435db00d64f9ea897ee7ef65785b7f6a79703a01ead98598"

    files = []
    source_folders = {"examples","profiles","fixtures","tests","tools","fonts","evidence"}
    root_exclusions = {"User_session.json","FILE_MANIFEST.json","SHA256SUMS.txt","source_verification.json"}
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if any(part in (".git",".venv","__pycache__") for part in rel.parts) or p.suffix == ".pyc":
            continue
        include = len(rel.parts) == 1 and p.name not in root_exclusions and p.suffix not in (".zip",)
        include |= rel.parts[0] in source_folders
        if rel.parts[0] == "validation":
            include = False
            if len(rel.parts) >= 3 and rel.parts[1] == "regression":
                include = p.name in ("settings.json","treated.dat") or p.name == "regression_summary.json"
            if p.is_relative_to(validation):
                # Initial I1 results remain local; final numerical results supersede them.
                include = "numerical" not in rel.parts and p.name != "numerical_final_stdout.txt"
        if include:
            files.append(p)
    prefix = "Torque_Postprocessing_GUI_v1.1/"
    manifest = {p.relative_to(ROOT).as_posix(): {"bytes":p.stat().st_size,"sha256":sha256(p)} for p in files}
    assert len([p for p in files if p.name == "treated.dat" and "regression" in p.parts]) == 6
    assert any(p.name == "baseline_review_accepted.json" for p in files)
    data = (json.dumps({"created_utc":datetime.now(timezone.utc).isoformat(),"files":manifest},
                       indent=2,sort_keys=True)+"\n").encode()
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,"x",zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for p in files:
            archive.write(p,prefix+p.relative_to(ROOT).as_posix())
        archive.writestr(prefix+"FILE_MANIFEST.json",data)
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(files)+1
        for relative, info in manifest.items():
            assert hashlib.sha256(archive.read(prefix+relative)).hexdigest() == info["sha256"],relative
        assert archive.read(prefix+"FILE_MANIFEST.json") == data
    report = {"status":"PASS","archive":str(destination),"bytes":destination.stat().st_size,
              "sha256":sha256(destination),"member_count":len(files)+1,"every_member_verified":True,
              "ZIP_CRC_pass":True,"immutable_manifest_entries_verified":checked}
    atomic_json(destination.with_suffix(".package_verification.json"),report)
    destination.with_suffix(".zip.sha256").write_text(report["sha256"]+"  "+destination.name+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2))


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",default=str(ROOT.parent/"Torque_Postprocessing_GUI_v1.1.zip"))
    main(parser.parse_args().output)

