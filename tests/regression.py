"""Replay saved real-data regression; old Rot1 diagnostic choices stay here."""
import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from io_profiles import read_raw, sha256
from pipeline import default_config, process
from presets import apply_preset
from storage import export_run, atomic_json, save_session
from validate import compare

EVIDENCE = ROOT / "evidence/Torque_Ho2thd4Pc_pipeline_comparison_v1.2"
CASES = [
    ("new_rot1", "inputs/Rot1rawHo2thd4Pc.dat", "inputs/Rot1treatedHo2thd4Pc.dat", "fractional", "new_rot1", 1146, 818, 20),
    ("new_rot2", "inputs/Rot2rawHo2thd4Pc_1.dat", "inputs/Rot2treatedHo2thd4Pc.dat", "fractional", "new_rot2", 1306, 938, 23),
    ("previous_rot2", "previous/inputs/Rot2raw.dat", "previous/inputs/Rot2treated.dat", "previous", "previous", 1105, 820, 20),
    ("previous_rot1", "previous/inputs/Rot1raw.dat", "previous/inputs/Rot1treated.dat", "previous", "previous", 1312, 943, 23),
]


def main(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    results = []
    raw_total = 0
    for name, raw, ref, profile, preset, nraw, nsignal, npasses in CASES:
        obj = read_raw(EVIDENCE / raw, profile)
        assert len(obj.rows) == nraw
        assert sum(len(p.rows) for p in obj.passes if not p.zero) == nsignal
        raw_total += len(obj.rows)
        cfg = apply_preset(default_config(obj), preset)
        modes = ["midrange", "mean", "DIAGNOSTIC"] if name == "previous_rot1" else ["midrange"]
        for mode in modes:
            current = json.loads(json.dumps(cfg))
            current["centering"] = "midrange" if mode == "DIAGNOSTIC" else mode
            current["centering_source"] = "Explicit regression test setting"
            if mode == "DIAGNOSTIC":
                table = EVIDENCE / "previous/validation/centering_choices_DIAGNOSTIC.csv"
                choices = [r for r in csv.DictReader(table.open()) if r["rotation"] == "Rot1"]
                current["note"] = "DIAGNOSTIC ONLY: reference-selected 15 mean/8 midrange choices; autonomous selector unresolved."
                for row in choices:
                    number = int(row["sweep_id"].split("_S")[1])
                    p = obj.passes[number-1]
                    current["overrides"][p.id] = {
                        "identity": p.identity, "centering": row["mode"],
                        "source": f"DIAGNOSTIC reference-selected table {table.name}; sha256 {sha256(table)}",
                    }
                assert sum(v["centering"] == "mean" for v in current["overrides"].values()) == 15
            result = process(obj, current)
            saved = Path(export_run(result, output, name + "_" + mode))
            met = compare(saved / "treated.dat", EVIDENCE / ref)
            expected = (615 if mode == "mean" else 328) if name == "previous_rot1" and mode != "DIAGNOSTIC" else nsignal
            assert met["exact_rows"] == expected, (name, mode, met["exact_rows"], expected, met["D"])
            assert met["pass_count"] == npasses
            assert met["header_equal"]
            atomic_json(saved / "validation.json", met)
            if mode == "midrange" or mode == "DIAGNOSTIC":
                sample = ROOT / "examples" / f"{name}_{mode}.json"
                save_session(sample, [(obj.path, current)])
            results.append({"case": name, "mode": mode, "raw_rows": nraw,
                            **{k: v for k, v in met.items() if k not in ("residuals", "passes")},
                            "output_directory": str(saved.relative_to(ROOT)) if saved.is_relative_to(ROOT) else str(saved)})
        if name == "new_rot1":
            transition = obj.passes[2]
            assert transition.rows[0].line == 85 and transition.rows[-1].line == 125
            assert transition.trajectory and len(transition.rows) == 41
            assert sum(len(p.missing) for p in obj.passes if not p.zero) == 2
        if name == "new_rot2":
            assert sum(len(p.missing) for p in obj.passes if not p.zero) == 5
        if name == "previous_rot2":
            assert [len(p.rows) for p in obj.passes if p.zero and p.T == 100] == [39]
        assert sha256(obj.path) == obj.sha256
    assert raw_total == 4869
    report = {"raw_rows": raw_total, "unique_reference_rows": 3519, "results": results}
    atomic_json(output / "regression_summary.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "validation/regression"))
    main(parser.parse_args().output)

