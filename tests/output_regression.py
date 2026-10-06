"""Compare current numerical output with a fresh pre-patch working snapshot."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cli import run_entry
from io_profiles import sha256
from pipeline import UPSTREAM_IMPLEMENTATION
from storage import load_session, treated_text
from treated_plots import molar_text, normalization


def main(before, output):
    prior = json.loads(before.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=False)
    assert UPSTREAM_IMPLEMENTATION == prior["upstream_implementation"]
    report = {"status": "PASS", "cases": {}, "implementation": UPSTREAM_IMPLEMENTATION,
              "molar_inputs": "Synthetic software normalization from snapshot, not experimental"}
    for name, expected in prior["results"].items():
        raw, cfg = load_session(ROOT / "examples" / (name + ".json"))[0]
        result = run_entry(raw, cfg)
        dat = output / (name + ".dat")
        dat.write_text(treated_text(result), encoding="utf-8", newline="")
        molar = output / (name + "_molar.dat")
        molar.write_text(molar_text(result, normalization(prior["synthetic_normalization"])), encoding="utf-8", newline="")
        assert sha256(dat) == expected["dat_sha256"]
        assert sha256(molar) == expected["molar_sha256"]
        assert {p["pass_id"]: p["baseline_binding"] for p in result["passes"]} == expected["bindings"]
        counts = Counter((row["role"], row["retention"]) for row in result["ledger"])
        assert len(result["ledger"]) == 1754
        report["cases"][name] = {"rows": result["rows"], "ordinary_byte_equal": True,
            "molar_byte_equal": True, "baseline_bindings_equal": True,
            "counts": {str(k): v for k, v in counts.items()}}
    for path, expected in prior["protected_files"].items():
        assert sha256(path) == expected, path
    for name, expected in prior["archive_sha256"].items():
        assert sha256(ROOT/name) == expected, name
    report["protected_files"] = len(prior["protected_files"])
    report["protected_archives"] = len(prior["archive_sha256"])
    (output/"report.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print("PASS: three exact ordinary/molar pairs, bindings, accounting, protected files/archives")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--before",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    main(args.before.resolve(),args.output.resolve())
