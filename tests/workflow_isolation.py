"""CLI replay with all other data/reference reads denied by a Python audit hook."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cli import main as cli_main, run_entry
from storage import atomic_json, load_session, treated_text
from io_profiles import sha256


def child(folder):
    folder = folder.resolve()
    allowed = {folder/"raw.dat", folder/"settings.json"}
    reads, denied = [], []
    def guard(event, args):
        if event != "open" or isinstance(args[0], int):
            return
        path = Path(os.fsdecode(args[0])).resolve()
        mode = args[1] or ""
        if ("r" in mode or not mode) and path.suffix.lower() in (".dat", ".csv", ".json", ".txt"):
            if path not in allowed and not path.is_relative_to(folder/"out"):
                denied.append(str(path))
                raise PermissionError("Reference or unrelated data read denied")
            reads.append(str(path))
    sys.addaudithook(guard)
    status = cli_main(["process", "--raw", str(folder/"raw.dat"), "--settings", str(folder/"settings.json"),
                       "--output", str(folder/"out"), "--run-name", "isolated"])
    assert status == 0 and not denied
    reference = ROOT/"evidence/Torque_Ho2thd4Pc_pipeline_comparison_v1.2/inputs/Rot1treatedHo2thd4Pc.dat"
    try:
        reference.read_bytes()
    except PermissionError:
        pass
    else:
        raise AssertionError("Reference access was not denied")
    atomic_json(folder/"access_log.json", {"processing_reference_reads": 0, "reference_probe_denied": True,
                                          "data_reads": sorted(set(reads)), "denied": denied, "status": "PASS"})


def main(session, folder):
    folder.mkdir(parents=True, exist_ok=False)
    entries = load_session(session)
    assert len(entries) == 1
    raw, cfg = entries[0]
    before = sha256(raw)
    shutil.copyfile(raw, folder/"raw.dat")
    atomic_json(folder/"settings.json", cfg)
    done = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child", str(folder)],
                          cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout+done.stderr
    expected = treated_text(run_entry(raw, cfg)).encode()
    assert (folder/"out/isolated/treated.dat").read_bytes() == expected
    assert sha256(raw) == before
    report = json.loads((folder/"access_log.json").read_text())
    report["byte_equal_to_normal_replay"] = True
    atomic_json(folder/"report.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", type=Path)
    parser.add_argument("--session", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.child:
        child(args.child)
    else:
        main(args.session, args.output.resolve())
