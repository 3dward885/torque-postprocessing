"""Command-line access to the same processing and export functions as the GUI."""
from __future__ import annotations
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from io_profiles import read_raw, profile_from
from pipeline import default_config, process
from presets import apply_preset, PRESET_LABELS
from storage import atomic_json, export_run, load_config, load_session


def run_entry(path, settings=None, profile="fractional", allow_stale_review=False):
    obj = read_raw(path, settings["profile"] if settings else profile)
    cfg = settings if settings else default_config(obj)
    return process(obj, cfg, allow_stale_review=allow_stale_review)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect", help="List passes without fitting")
    inspect.add_argument("raw")
    inspect.add_argument("--profile", default="fractional")
    p = sub.add_parser("process")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--raw", nargs="+")
    source.add_argument("--session", help="GUI session JSON; all settings are fingerprint-bound")
    p.add_argument("--settings", help="Per-file settings JSON (one raw input)")
    p.add_argument("--profile", default="fractional", help="previous, fractional, or a saved profile JSON")
    p.add_argument("--preset", choices=PRESET_LABELS)
    p.add_argument("--centering", choices=("midrange", "mean"), default=None)
    p.add_argument("--molar-mode", choices=("torque", "multiplier", "amount", "mass"), default=None)
    p.add_argument("--factor")
    p.add_argument("--amount-mol")
    p.add_argument("--mass")
    p.add_argument("--mass-unit", choices=("g", "mg"))
    p.add_argument("--molar-mass-g-mol")
    p.add_argument("--molar-source")
    p.add_argument("--output", required=True, help="Parent folder for collision-safe new run directories")
    p.add_argument("--run-name", help="Explicit new run name (one input only); collision is an error")
    v = sub.add_parser("validate", help="Read saved output/reference; processing is already complete")
    v.add_argument("--output", required=True)
    v.add_argument("--reference", required=True)
    v.add_argument("--report")
    args = parser.parse_args(argv)
    if args.command == "validate":
        from validate import compare
        report = compare(args.output, args.reference)
        if args.report:
            atomic_json(args.report, report)
        print(json.dumps({k: v for k, v in report.items() if k not in ("passes", "residuals")}, indent=2))
        return 0
    profile_arg = args.profile
    profile = profile_from(load_config(profile_arg) if Path(profile_arg).is_file() else profile_arg)
    if args.command == "inspect":
        obj = read_raw(args.raw, profile)
        print(json.dumps({"schema": obj.schema, "units": obj.units, "raw_rows": len(obj.rows),
                          "profile": asdict(profile),
                          "passes": [{"id": p.id, "T_K": str(p.T), "field_T": p.field_label, "rows": len(p.rows),
                                      "role": "background" if p.zero else "signal", "missing_deg": p.missing,
                                      "first_line": p.rows[0].line, "last_line": p.rows[-1].line}
                                     for p in obj.passes]}, indent=2))
        return 0
    if args.session:
        if any((args.settings, args.preset, args.centering, args.molar_mode, args.factor, args.amount_mol, args.mass, args.molar_mass_g_mol)):
            parser.error("--session uses its saved settings; do not combine it with setting overrides.")
        entries = load_session(args.session)
    else:
        if args.settings and len(args.raw) != 1:
            parser.error("--settings requires exactly one raw file.")
        entries = [(path, load_config(args.settings) if args.settings else None) for path in args.raw]
    if args.run_name and len(entries) != 1:
        parser.error("--run-name requires exactly one input.")
    summary = []
    for path, settings in entries:
        try:
            obj = read_raw(path, settings["profile"] if settings else profile)
            cfg = settings or default_config(obj)
            if args.preset:
                cfg = apply_preset(cfg, args.preset)
                obj = read_raw(path, cfg["profile"])
            if args.centering:
                cfg["centering"] = args.centering
                cfg["centering_source"] = "Explicit CLI selection"
            if args.molar_mode:
                cfg["molar"] = {"mode": args.molar_mode, "source": args.molar_source or "",
                                "factor": args.factor, "amount_mol": args.amount_mol,
                                "mass": args.mass, "mass_unit": args.mass_unit,
                                "molar_mass_g_mol": args.molar_mass_g_mol}
            result = process(obj, cfg)
            saved = export_run(result, args.output, args.run_name)
            summary.append({"input": path, "status": "success", "rows": result["rows"], "run": saved})
        except (ValueError, OSError, KeyError, TypeError) as exc:
            summary.append({"input": path, "status": "failed", "error": str(exc)})
    print(json.dumps(summary, indent=2))
    return 1 if any(r["status"] == "failed" for r in summary) else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)

