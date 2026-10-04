"""Frozen A-D regression and the user-confirmed Ho2sq3 configuration."""
import argparse
import copy
from decimal import Decimal, localcontext
import json
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from io_profiles import read_raw, configure_acquisition, sha256
from pipeline import default_config, process, migrate_config, select_background, support_permission
from storage import atomic_json, save_session, export_run
from validate import read_treated

EVIDENCE = ROOT/"evidence/Torque_Ho2thd4Pc_pipeline_comparison_v1.2"
CASES = {
    "new_rot1": ("inputs/Rot1rawHo2thd4Pc.dat", "inputs/Rot1treatedHo2thd4Pc.dat"),
    "new_rot2": ("inputs/Rot2rawHo2thd4Pc_1.dat", "inputs/Rot2treatedHo2thd4Pc.dat"),
    "previous_rot1": ("previous/inputs/Rot1raw.dat", "previous/inputs/Rot1treated.dat"),
    "previous_rot2": ("previous/inputs/Rot2raw.dat", "previous/inputs/Rot2treated.dat"),
}
RAW_HASH = "04edb7daae1c04a4330cb49a2cd46de5111ee00c643cef8e6e510b1be258e04c"


def main(raw, output):
    output.mkdir(parents=True, exist_ok=False)
    report = {"historical_cases": [], "new_sample": {}, "reference_columns_compared": "A-D only; E conversion removed"}
    raw_rows = {}
    for folder in sorted((ROOT/"validation/regression").iterdir()):
        if not (folder/"settings.json").is_file():
            continue
        key = next(k for k in CASES if folder.name.startswith(k))
        cfg = migrate_config(json.loads((folder/"settings.json").read_text()))
        prior = json.loads((folder/"provenance.json").read_text())
        cfg["acquisition"]["temperature_setpoints_K"] = sorted({p["T_K"] for p in prior["inventory"]}, key=Decimal)
        cfg["acquisition"]["source"] = "Frozen prior-run inventory; sha256 " + sha256(folder/"provenance.json")
        obj = read_raw(EVIDENCE/CASES[key][0], cfg["profile"])
        result = process(obj, cfg)
        run = Path(export_run(result, output, folder.name))
        actual, _ = read_treated(run/"treated.dat")
        before, _ = read_treated(folder/"treated.dat")
        reference, _ = read_treated(EVIDENCE/CASES[key][1])
        assert len(actual) == len(before) == len(reference)
        assert all(a == b[:4] for a, b in zip(actual, before)), folder.name
        assert all(a[:3] == b[:3] for a,b in zip(actual,reference)), folder.name
        exact = sum(a[3] == b[3] for a,b in zip(actual,reference))
        expected = 615 if folder.name == "previous_rot1_mean" else 328 if folder.name == "previous_rot1_midrange" else len(actual)
        assert exact == expected
        with localcontext() as context:
            context.prec = 100
            residual = [a[3]-b[3] for a,b in zip(actual,reference)]
        report["historical_cases"].append({"case": folder.name, "rows": len(actual),
            "A_D_equal_to_prechange": len(actual), "D_exact_reference_rows": exact,
            "D_max_abs_error_Nm": str(max(map(abs,residual))),
            "raw_rows": len(obj.rows), "raw_sha256": obj.sha256})
        raw_rows[key] = len(obj.rows)
    assert sum(raw_rows.values()) == 4869
    report["historical_distinct_raw_rows"] = sum(raw_rows.values())
    report["historical_distinct_reference_rows"] = 3519
    assert sha256(raw) == RAW_HASH, "Reproducer differs from the inspected raw file"
    obj = read_raw(raw)
    assert len(obj.rows) == 1754 and len(obj.passes) == 34
    cfg = default_config(obj)
    # These are user-confirmed experiment settings, never production defaults.
    cfg["acquisition"]["temperature_setpoints_K"] = ["2.5", "5", "10", "25", "50", "100", "150", "200", "250"]
    cfg["acquisition"]["source"] = "User confirmed experimental setpoints and nine near-zero backgrounds on 4 October 2026"
    for p in obj.passes:
        if p.zero:
            cfg["acquisition"]["scans"][p.id] = {"identity": p.identity, "role": "background",
                "source": "User confirmed near-zero-field background assignment on 4 October 2026"}
    configured = configure_acquisition(obj, cfg["acquisition"])
    initial = process(obj, cfg, partial=True)
    assert set(initial["processing_errors"]) == {"P022", "P023", "P024"}
    for pid in ("P022", "P023", "P024"):
        signal = next(p for p in configured.passes if p.id == pid)
        background = select_background(configured, signal, cfg)
        cfg["support_exceptions"].append(support_permission(configured, signal, background,
            "User explicitly authorized extrapolation of the approximately 100 K background on 4 October 2026"))
    result = process(obj, cfg)
    assert result["rows"] == 1296 and len(result["ledger"]) == 1754
    full = Path(export_run(result, output, "Ho2sq3_full_range"))
    save_session(output/"Ho2sq3_full_range.json", [(str(raw), cfg)])
    cropped_cfg = copy.deepcopy(cfg)
    cropped_cfg["acquisition"]["angle_range_deg"] = ["0", "200"]
    cropped_cfg["support_exceptions"] = []
    cropped_cfg["note"] = "Example angular range requested by the user; endpoints outside 0–200 degrees excluded before background fitting and centering."
    cropped = process(obj, cropped_cfg)
    assert cropped["rows"] == 1023 and len(cropped["ledger"]) == 1754
    assert not any(p["support"]["extrapolation_angles_deg"] for p in cropped["passes"])
    trimmed = Path(export_run(cropped, output, "Ho2sq3_0_to_200"))
    save_session(output/"Ho2sq3_0_to_200.json", [(str(raw), cropped_cfg)])
    assert sha256(raw) == RAW_HASH
    report["new_sample"] = {"raw_sha256": RAW_HASH, "raw_rows": 1754, "scans": 34,
        "background_rows": 458, "full_signal_rows": 1296, "range_0_to_200_signal_rows": 1023,
        "range_retained_background_rows": sum(v["retention"] == "background fit only" for v in cropped["ledger"]),
        "outside_selected_range_rows": sum(v["retention"] == "outside selected angle range" for v in cropped["ledger"]),
        "full_range_extrapolation_scans": ["P022", "P023", "P024"], "cropped_extrapolation_scans": [],
        "background_role_basis": "User confirmed", "temperature_basis": "User supplied",
        "reference_comparison": "Unavailable: no treated reference supplied for this sample"}
    atomic_json(output/"report.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.raw.resolve(), args.output.resolve())
