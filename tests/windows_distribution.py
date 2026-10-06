"""Check a release's files against build metadata without executing the installer."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from io_profiles import sha256
from pipeline import UPSTREAM_IMPLEMENTATION


def main(release, output):
    info = json.loads((release / "build_info.json").read_text(encoding="utf-8"))
    manifest = json.loads((release / "bundle_manifest.json").read_text(encoding="utf-8"))
    bundle = release / "portable/Torque Data Postprocessing"
    for name, value in info["source_sha256"].items():
        assert sha256(ROOT / name) == value, name
    for name, value in manifest.items():
        assert sha256(bundle / name) == value, name
        parts = Path(name).parts
        assert not set(parts) & {".git", ".venv", "examples", "evidence", "validation", "runs"}, name
        assert "arial" not in name.lower(), name
        if Path(name).suffix.lower() == ".dat":
            assert name.startswith("_internal/matplotlib/mpl-data/sample_data/"), name
        if Path(name).suffix.lower() == ".zip":
            assert name == "_internal/base_library.zip", name
    assert any("licenses/Python_LICENSE.txt" in n for n in manifest)
    assert any("licenses/Tcl_Tk" in n for n in manifest)
    assert any("help_content.json" in n for n in manifest)
    assert info["numerical_implementation_sha256"] == UPSTREAM_IMPLEMENTATION
    report = {"status": "PASS", "files": len(manifest),
              "bytes": sum((bundle / n).stat().st_size for n in manifest),
              "no_project_research_data_environments_or_Arial": True,
              "standard_library_zip_and_Matplotlib_generic_sample_data": "Included runtime-package resources",
              "source_matches_build": True, "licenses_included": True,
              "numerical_implementation_sha256": UPSTREAM_IMPLEMENTATION,
              "max_install_directory_characters": info["maximum_install_directory_characters"]}
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("PASS: payload/source hashes, required resources/licenses and no project research data")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.release.resolve(), args.output.resolve())
