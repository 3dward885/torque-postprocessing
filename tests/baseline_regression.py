"""Real-fixture A/B/C/H regression, using immutable v1.0 saved runs."""
import argparse
import copy
import json
from pathlib import Path
import sys
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from regression import CASES, EVIDENCE
from baseline import accepted_record, empty_review, preview_values
from pipeline import process
from io_profiles import read_raw, sha256
from storage import treated_text, export_run, atomic_json
from validate import compare
from test_baseline import bound


def main(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    reports = []
    maximum_bound_ratio = 0.
    for name, raw, ref, profile, preset, raw_count, rows, passes in CASES:
        obj = read_raw(EVIDENCE/raw, profile)
        for mode in (["midrange", "mean", "DIAGNOSTIC"] if name == "previous_rot1" else ["midrange"]):
            frozen = ROOT/"validation/regression"/(name+"_"+mode)
            cfg = json.loads((frozen/"settings.json").read_text())
            assert "baseline_review" not in cfg
            ordinary = process(obj, cfg)
            before = (frozen/"treated.dat").read_bytes()
            assert treated_text(ordinary).encode() == before
            cfg["baseline_review"] = empty_review()
            assert treated_text(process(obj, cfg)).encode() == before
            cfg["baseline_review"]["enabled"] = True
            assert treated_text(process(obj, cfg)).encode() == before
            first = ordinary["passes"][0]
            cfg["baseline_review"]["overrides"][first["pass_id"]] = accepted_record(
                first["baseline_binding"], first["subtracted_Nm"], 1e-9)
            cfg["baseline_review"]["enabled"] = False
            assert treated_text(process(obj, cfg)).encode() == before
            saved = Path(export_run(ordinary, destination, name+"_"+mode))
            metrics = compare(saved/"treated.dat", EVIDENCE/ref)
            expected = (615 if mode == "mean" else 328) if name == "previous_rot1" and mode != "DIAGNOSTIC" else rows
            assert metrics["exact_rows"] == expected and metrics["pass_count"] == passes
            assert ordinary["raw_rows"] == raw_count
            reports.append({"case":name,"mode":mode,"v1_0_DAT_byte_identical":True,
                "DAT_sha256":sha256(saved/"treated.dat"),"raw_rows":raw_count,
                **{k:v for k,v in metrics.items() if k not in ("residuals","passes")}})
            if mode != "midrange":
                continue
            zero_cfg = copy.deepcopy(cfg)
            zero_cfg["centering"] = "mean"
            zero_cfg["baseline_review"] = {"schema_version":1,"enabled":True,"overrides":{}}
            for pred in ordinary["passes"]:
                u = np.array(pred["subtracted_Nm"])
                zero_cfg["baseline_review"]["overrides"][pred["pass_id"]] = accepted_record(pred["baseline_binding"],u,0.)
                zero = preview_values(u,0)
                b = bound(u,zero["c_mid"],zero["c_final"],0)
                assert abs(zero["imbalance"]) <= b
                for delta in (1e-9,-1e-9):
                    manual = preview_values(u,delta)
                    b = bound(u,manual["c_mid"],manual["c_final"],delta)
                    errors = [max(abs(manual["corrected"]-zero["corrected"]+delta)),
                              abs(np.ptp(u)-np.ptp(manual["corrected"])),
                              abs(manual["imbalance"]+2*delta)]
                    assert max(errors) <= b
                    maximum_bound_ratio = max(maximum_bound_ratio,max(errors)/b)
            zero_result = process(obj,zero_cfg)
            assert treated_text(zero_result).encode() == before
            zero_saved = Path(export_run(zero_result,destination,name+"_accepted_zero"))
            equality = compare(zero_saved/"treated.dat",saved/"treated.dat")
            assert equality["exact_rows"] == rows
            assert all(a["angles_deg"] == b["angles_deg"] and a["rows"] == b["rows"]
                for a,b in zip(ordinary["passes"],zero_result["passes"]))
            reports[-1]["accepted_zero_exact_D"] = equality["exact_cells"]["D"]
            reports[-1]["accepted_zero_exact_E"] = equality["exact_cells"]["E"]
    summary = {"status":"PASS","cases":reports,"raw_rows_distinct":4869,"reference_rows_distinct":3519,
        "maximum_observed_arithmetic_error_over_fixed_bound":maximum_bound_ratio,
        "bound":"16*epsilon*S + 8*smallest_positive_subnormal; never applied to serialized equality"}
    atomic_json(destination/"baseline_regression.json",summary)
    print(json.dumps(summary,indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output",default=str(ROOT/"validation/baseline_v1.1/numerical"))
    main(parser.parse_args().output)

