"""Run the real CLI with reference/data reads denied, then compare outside it."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from io_profiles import read_raw, sha256
from pipeline import default_config
from presets import apply_preset
from storage import atomic_json
from validate import compare
from regression import CASES, EVIDENCE


def child(folder):
    import cli
    folder = Path(folder).resolve()
    permitted = {folder/"raw.dat", folder/"settings.json"}
    reads, denied = [], []
    def guard(event, args):
        if event != "open" or isinstance(args[0], int):
            return
        path = Path(os.fsdecode(args[0])).resolve()
        mode = args[1] or ""
        reading = "r" in mode or not mode
        if reading and path.suffix.lower() in (".dat", ".csv", ".json", ".txt"):
            # Export integrity reads may access only files just written in this run.
            if path not in permitted and not path.is_relative_to(folder/"out"):
                denied.append(str(path))
                raise PermissionError("Reference/other data read denied during processing")
            reads.append(str(path.relative_to(folder)))
    sys.addaudithook(guard)
    status = cli.main(["process", "--raw", str(folder/"raw.dat"), "--settings", str(folder/"settings.json"),
                       "--output", str(folder/"out"), "--run-name", "isolated"])
    if status:
        raise RuntimeError("Isolated CLI processing failed")
    probe_denied = False
    try:
        (EVIDENCE/"inputs/Rot1treatedHo2thd4Pc.dat").read_bytes()
    except PermissionError:
        probe_denied = True
    atomic_json(folder/"access_log.json", {"data_reads": sorted(set(reads)), "denied_reads": denied,
                                          "reference_probe_denied": probe_denied})


def main():
    reports = []
    for name, raw, reference, profile, preset, *_ in CASES:
        modes = ["mean", "midrange"] if name == "previous_rot1" else ["midrange"]
        for mode in modes:
            with tempfile.TemporaryDirectory(prefix="torque_isolated_") as temp:
                folder = Path(temp)
                shutil.copyfile(EVIDENCE/raw, folder/"raw.dat")
                obj = read_raw(folder/"raw.dat", profile)
                cfg = apply_preset(default_config(obj), preset)
                cfg["centering"] = mode
                cfg["centering_source"] = "Explicit fixed mode in isolated software regression"
                atomic_json(folder/"settings.json", cfg)
                done = subprocess.run([sys.executable, str(Path(__file__)), "--child", str(folder)],
                                      cwd=folder, capture_output=True, text=True, check=True)
                log = json.loads((folder/"access_log.json").read_text())
                assert log["reference_probe_denied"] and len(log["denied_reads"]) == 1
                result = compare(folder/"out/isolated/treated.dat", EVIDENCE/reference)
                expected = (615 if mode == "mean" else 328) if name == "previous_rot1" else result["rows"]
                assert result["exact_rows"] == expected
                reports.append({"case": name, "mode": mode, "exact_rows": result["exact_rows"],
                                "rows": result["rows"], "output_sha256": sha256(folder/"out/isolated/treated.dat"),
                                "input_sha256_unchanged": sha256(folder/"raw.dat") == obj.sha256,
                                **log, "CLI_exit_code": done.returncode})
    atomic_json(ROOT/"validation/isolation_results.json", reports)
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        child(sys.argv[2])
    else:
        main()

