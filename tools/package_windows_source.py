"""Create a source/update ZIP; runtime binaries and research data stay separate."""
import argparse
import json
from pathlib import Path

from package_usability_release import ROOT, project_files, write_zip


def main(destination):
    files = project_files()
    # These are named project examples, not private user session files.
    for name in ("WINDOWS_APP.txt", "STARTUP_FIX_v1.3.txt", "UPDATE_v1.6.txt",
                 "WINDOWS_INSTALLER_REPORT_v1.6.txt", "V1.4_SCOPE_ADDITIONS.txt",
                 "FIXTURE_LOCATIONS_v1.6.json", "V1.6_AUTHORIZED_RULE.txt"):
        files[name] = (ROOT / name).read_bytes()
    for path in (ROOT / "windows").iterdir():
        if path.is_file() and path.suffix in (".txt", ".iss", ".spec", ".json"):
            files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    forbidden = {".git", ".venv", ".build-venv", "build_tools", "releases",
                 "build", "dist", "evidence", "validation", "runs", "__pycache__"}
    assert not any(set(Path(name).parts) & forbidden for name in files)
    assert all(not name.lower().endswith((".exe", ".dll", ".pyd", ".zip")) for name in files)
    assert all(not name.endswith(".dat") or name == "fixtures/SYNTHETIC_software_fixture.dat" for name in files)
    before = json.loads((ROOT / "validation/v16_before/before.json").read_text(encoding="utf-8"))
    metadata = {
        "app": "Torque Data Postprocessing", "version": "1.6",
        "kind": "Complete project source/update; no runtime binaries or research measurements",
        "comparison_basis": "Fresh v1.5 working snapshot validation/v16_before; not the older Git HEAD",
        "base_source_sha256": before["snapshot_files"],
        "required_removals": [],
        "fixtures": "FIXTURE_LOCATIONS_v1.6.json; original examples require field-policy migration",
    }
    print(json.dumps(write_zip(destination, files, metadata), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output.resolve())
