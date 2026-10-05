"""Compare v1.3 with the actual saved pre-patch v1.2 contents, not Git HEAD."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cli import run_entry
from io_profiles import sha256
from pipeline import UPSTREAM_IMPLEMENTATION
from storage import atomic_json, load_session, treated_text


def main(before, output):
    if output.exists():
        raise ValueError("Choose an unused report filename.")
    snapshot = json.loads(before.read_text(encoding="utf-8"))
    assert UPSTREAM_IMPLEMENTATION == snapshot["upstream_implementation"]
    for name in ("pipeline.py", "plots.py", "storage.py"):
        assert sha256(ROOT/name) == snapshot["source_sha256"][name], name
    protected = snapshot["protected_files"]
    for filename, expected in protected.items():
        assert sha256(filename) == expected, filename
    results = {}
    for name, prior in snapshot["results"].items():
        raw, cfg = load_session(ROOT/"examples"/(name+".json"))[0]
        result = run_entry(raw, cfg)
        actual = treated_text(result).encode("utf-8")
        assert hashlib.sha256(actual).hexdigest() == prior["dat_sha256"], name
        assert result["rows"] == prior["rows"]
        assert {p["pass_id"]: p["baseline_binding"] for p in result["passes"]} == prior["bindings"]
        results[name] = {"rows": result["rows"], "DAT_sha256": prior["dat_sha256"],
                         "DAT_byte_equal": True, "all_bindings_equal": True,
                         "accepted_baseline_status": {p["pass_id"]: p["baseline_review"]["status"]
                                                     for p in result["passes"]}}
    atomic_json(output, {"status": "PASS", "protected_files_unchanged": len(protected),
                         "upstream_implementation": UPSTREAM_IMPLEMENTATION,
                         "unchanged_files": ["pipeline.py", "plots.py", "storage.py"],
                         "results": results})
    print(f"PASS: {len(protected)} protected files, three byte-identical DATs and all saved bindings")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.before, args.output)
