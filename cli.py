"""Headless processing using the same settings and numerical core as the GUI."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from io_profiles import read_raw, configure_acquisition, InputError
from pipeline import default_config, migrate_config, process, select_background, support_permission
from storage import atomic_json, export_run, save_dat, load_config, load_session


def load_entry(path, settings=None):
    cfg = migrate_config(settings) if settings else None
    obj = read_raw(path, cfg["profile"] if cfg else "fractional")
    return obj, cfg or default_config(obj)


def run_entry(path, settings=None, profile="fractional", allow_stale_review=False, partial=False):
    obj, cfg = load_entry(path, settings)
    return process(obj, cfg, allow_stale_review=allow_stale_review, partial=partial)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    arguments = sys.argv[1:] if argv is None else argv
    obsolete = ("--molar-", "--factor", "--amount-mol", "--mass", "--preset")
    if any(a.startswith(obsolete) for a in arguments):
        parser.error("Molar conversion and reference presets were removed. This processor saves torque in N m.")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect", help="Load raw measurements and list scans")
    inspect.add_argument("raw")
    inspect.add_argument("--settings")
    p = sub.add_parser("process", help="Subtract background, center and save torque data")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--raw", nargs="+")
    source.add_argument("--session")
    p.add_argument("--settings", help="Saved per-file settings (one raw file)")
    p.add_argument("--setpoints", help="Comma-separated experimental temperature setpoints in K")
    p.add_argument("--temperature-tolerance", help="Allowed temperature deviation in K")
    p.add_argument("--angle-range", nargs=2, metavar=("MIN_DEG", "MAX_DEG"), help="Range for background fit, centering and export; default all samples")
    p.add_argument("--allow-extrapolation", nargs="+", metavar="SCAN", help="Explicitly allow background extrapolation for these scan IDs")
    p.add_argument("--centering", choices=("midrange", "mean"))
    out = p.add_mutually_exclusive_group(required=True)
    out.add_argument("--output", help="Parent folder for a new complete run")
    out.add_argument("--dat", help="Treated .dat filename (one input)")
    p.add_argument("--run-name")
    v = sub.add_parser("validate", help="Compare already saved data with a reference")
    v.add_argument("--output", required=True)
    v.add_argument("--reference", required=True)
    v.add_argument("--report")
    args = parser.parse_args(arguments)
    if args.command == "validate":
        from validate import compare
        report = compare(args.output, args.reference)
        if args.report:
            atomic_json(args.report, report)
        print(json.dumps({k: v for k, v in report.items() if k not in ("passes", "residuals")}, indent=2))
        return 0
    if args.command == "inspect":
        obj, cfg = load_entry(args.raw, load_config(args.settings) if args.settings else None)
        obj = configure_acquisition(obj, cfg["acquisition"])
        print(json.dumps({"raw_rows": len(obj.rows), "scans": [
            {"id": p.id, "measured_T_K": p.measured_temperature, "setpoint_K": str(p.T),
             "field_T": p.field_label, "rows": len(p.rows), "issue": p.issue,
             "first_line": p.acquired_rows[0].line, "last_line": p.acquired_rows[-1].line}
            for p in obj.passes]}, indent=2))
        return 0
    if args.session:
        if any((args.settings, args.setpoints, args.temperature_tolerance, args.angle_range,
                args.allow_extrapolation, args.centering)):
            parser.error("--session replays its saved settings; edit the session in the GUI to change them.")
        entries = load_session(args.session)
    else:
        if args.settings and len(args.raw) != 1:
            parser.error("--settings requires one raw file.")
        entries = [(path, load_config(args.settings) if args.settings else None) for path in args.raw]
    if (args.dat or args.run_name) and len(entries) != 1:
        parser.error("--dat and --run-name require one input.")
    summary = []
    for path, settings in entries:
        try:
            obj, cfg = load_entry(path, settings)
            if args.setpoints is not None:
                cfg["acquisition"]["temperature_setpoints_K"] = [v.strip() for v in args.setpoints.split(",")]
                cfg["acquisition"]["source"] = "Explicit CLI experimental setpoints"
            if args.temperature_tolerance is not None:
                cfg["profile"]["temperature_tolerance_K"] = args.temperature_tolerance
                obj = read_raw(path, cfg["profile"])
            if args.angle_range:
                cfg["acquisition"]["angle_range_deg"] = args.angle_range
            if args.centering:
                cfg.update(centering=args.centering, centering_source="Explicit CLI selection")
            if args.allow_extrapolation:
                configured = configure_acquisition(obj, cfg["acquisition"])
                scans = {s.id: s for s in configured.passes}
                for pid in args.allow_extrapolation:
                    if pid not in scans or scans[pid].zero or scans[pid].issue:
                        raise InputError(f"{pid}: choose a valid signal scan before allowing extrapolation.")
                    bg = select_background(configured, scans[pid], cfg)
                    cfg["support_exceptions"].append(support_permission(configured, scans[pid], bg,
                                                       "Explicit CLI extrapolation permission"))
            result = process(obj, cfg)
            saved = save_dat(result, args.dat) if args.dat else export_run(result, args.output, args.run_name)
            summary.append({"input": path, "status": "success", "rows": result["rows"],
                            "saved": saved, "migration_notes": result["config"].get("migration_notes", [])})
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
