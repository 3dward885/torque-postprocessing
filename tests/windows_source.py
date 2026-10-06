"""Verify and replay the delivered source ZIP from an extracted copy."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from windows_bundle import diagnostic_session

ROOT = Path(__file__).resolve().parents[1]


def main(archive, output):
    output.mkdir(parents=True, exist_ok=False)
    source = output / "source"
    source.mkdir()
    with zipfile.ZipFile(archive) as zipped:
        assert not zipped.testzip()
        names = zipped.namelist()
        assert all((source / n).resolve().is_relative_to(source) for n in names)
        manifest = json.loads(zipped.read("PACKAGE_MANIFEST.json"))
        assert set(names) == set(manifest["entries"]) | {"PACKAGE_MANIFEST.json"}
        assert all(hashlib.sha256(zipped.read(n)).hexdigest() == h for n, h in manifest["entries"].items())
        assert all(not set(Path(n).parts) & {".git", ".venv", ".build-venv", "releases", "runs", "evidence", "validation"} for n in names)
        assert all(not n.endswith(".dat") or n == "fixtures/SYNTHETIC_software_fixture.dat" for n in names)
        zipped.extractall(source)
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    before = json.loads((ROOT / "validation/v16_before/before.json").read_text(encoding="utf-8"))
    def run(arguments, label):
        done = subprocess.run([sys.executable, *map(str, arguments)], cwd=output, env=env,
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              creationflags=subprocess.CREATE_NO_WINDOW, timeout=150)
        (output / (label + ".log")).write_text(done.stdout + done.stderr, encoding="utf-8")
        assert done.returncode == 0, (label, done.stdout, done.stderr)
    for name, expected in before["results"].items():
        target = output / (name + ".dat")
        session = diagnostic_session(ROOT / 'examples' / (name + '.json'),output/(name+'_diagnostic.json'))
        run([source / "cli.py", "process", "--session", session, "--dat", target], name)
        assert hashlib.sha256(target.read_bytes()).hexdigest() == expected["dat_sha256"]
    run([source / "desktop.py", "--check-installation", output / "hidden_gui",
         "--session", output / 'Ho2sq3_0_to_200_diagnostic.json'], "hidden_gui")
    check = json.loads((output / "hidden_gui/report.json").read_text(encoding="utf-8"))
    assert Path(check["module_directory"]).resolve() == source
    assert check["status"] == "PASS" and check["help_topics"] >= 74
    report = {"status": "PASS", "source": str(source), "package_entries": len(names),
              "three_DATs_byte_equal": True, "extracted_GUI_Help_plots_molar": True,
              "windows_withdrawn": True, "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("PASS: archive contents/hashes and extracted source replay, Help, plots and molar DAT")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.archive.resolve(), args.output.resolve())
