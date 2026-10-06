"""Black-box tests of the built Windows executables; no desktop interaction."""
import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from storage import load_session, save_session
from io_profiles import sha256
from io_profiles import APP_VERSION
from pipeline import migrate_config


def diagnostic_session(original, destination):
    entries=[]
    for raw,cfg,choice in load_session(original,include_output=True):
        cfg=migrate_config(cfg)
        cfg['field_quality'].update(condition='changing',source='Diagnostic numerical regression policy; not experimental permission')
        entries.append((raw,cfg,choice) if choice else (raw,cfg))
    save_session(destination,entries)
    return destination


def clean_environment():
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("PYTHON", "PYI_", "_PYI_"))
           and k.upper() not in {"VIRTUAL_ENV", "TCL_LIBRARY", "TK_LIBRARY", "MPLCONFIGDIR"}}
    env["PATH"] = str(Path(os.environ["SYSTEMROOT"]) / "System32")
    return env


def check(bundle, output, before, historical=True):
    bundle, output = Path(bundle).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    cwd = output / "working directory é"
    cwd.mkdir()
    env = clean_environment()
    env["LOCALAPPDATA"] = str(output / "local app data")
    report = {"checks": [], "bundle": str(bundle), "PATH": env["PATH"],
              "clean_machine": False, "desktop_input": False}
    def run(executable, args, label, success=True):
        done = subprocess.run([str(bundle / executable), *map(str, args)], cwd=cwd, env=env,
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              creationflags=subprocess.CREATE_NO_WINDOW, timeout=150)
        (output / (label + ".log")).write_text(done.stdout + done.stderr, encoding="utf-8")
        assert (done.returncode == 0) == success, (label, done.returncode, done.stdout, done.stderr)
        return done
    cli = "TorqueDataCLI.exe"
    version = run(cli, ["--version"], "version")
    assert f"Torque Data Postprocessing {APP_VERSION}" in version.stdout
    prior = json.loads(Path(before).read_text(encoding="utf-8"))
    report["examples"] = {}
    for name, expected in prior["results"].items():
        session = diagnostic_session(ROOT / "examples" / (name + ".json"),output / (name + '_diagnostic.json'))
        dat = output / (name + ".dat")
        run(cli, ["process", "--session", session, "--dat", dat], name)
        assert sha256(dat) == expected["dat_sha256"], name
        details = dat.with_name(dat.name + ".details")
        prov = json.loads((details / "provenance.json").read_text(encoding="utf-8"))
        ledger = json.loads((details / "row_ledger.json").read_text(encoding="utf-8"))
        assert {p["pass_id"]: p["baseline_binding"] for p in prov["passes"]} == expected["bindings"]
        assert len(ledger) == 1754 and len({p["pass_id"] for p in ledger}) == 34
        assert len(dat.read_text().splitlines()) == expected["rows"] + 1
        assert all(len(line.split("\t")) == 4 for line in dat.read_text().splitlines())
        counts = Counter((r["role"], r["retention"]) for r in ledger)
        assert sum(r["role"] == "background" for r in ledger) == 458
        assert sum(r["role"] == "signal" and r["retention"] == "retained in treated DAT" for r in ledger) == expected["rows"]
        assert all(Decimal(line.split("\t")[1]) != 0 for line in dat.read_text().splitlines()[1:])
        assert prov["environment"]["numpy"] == prior["environment"]["numpy"]
        assert prov["environment"]["matplotlib"] == prior["environment"]["matplotlib"]
        for module in ("pipeline.py", "io_profiles.py", "storage.py", "baseline.py", "plots.py"):
            expected_hash = sha256(ROOT / module)
            assert prov["code_sha256"][module] == expected_hash
        report["examples"][name] = {"rows": expected["rows"], "DAT_byte_equal": True,
              "bindings_equal": True, "counts": {str(k): v for k, v in counts.items()}}
    report["checks"].append("Three exact DAT replays, original accepted offsets, row accounting and source provenance")
    session = output / 'Ho2sq3_0_to_200_diagnostic.json'
    collision = output / "Ho2sq3_0_to_200.dat"
    original = sha256(collision)
    run(cli, ["process", "--session", session, "--dat", collision], "collision", False)
    assert sha256(collision) == original
    raw, settings = load_session(ROOT / "examples/Ho2sq3_manual_demo.json")[0]
    settings["profile"]["angle_tolerance_deg"] = "0.9"
    stale = output / "stale_session.json"
    save_session(stale, [(raw, settings)])
    run(cli, ["process", "--session", stale, "--dat", output / "stale.dat"], "stale", False)
    assert not (output / "stale.dat").exists()
    report["checks"].append("Collision and stale-baseline rejection")
    gui_output = output / "hidden_gui"
    run("Torque Data Postprocessing.exe", ["--check-installation", gui_output, "--session", session], "gui")
    gui = json.loads((gui_output / "report.json").read_text(encoding="utf-8"))
    assert gui["status"] == "PASS" and gui["frozen"] and gui["windows_withdrawn"]
    for key in ("numpy_path", "matplotlib_path", "module_directory", "tcl_library", "executable"):
        assert Path(gui[key]).resolve().is_relative_to(bundle), (key, gui[key])
    assert Path(gui["matplotlib_cache"]).is_relative_to(gui_output)
    assert gui["implementation_sha256"] == prior["upstream_implementation"]
    assert sha256(gui_output / "session_treated.dat") == prior["results"]["Ho2sq3_0_to_200"]["dat_sha256"]
    run(cli, ["process", "--session", gui_output / "accepted_session.json", "--dat", output / "gui_cli.dat"], "gui_cli")
    assert (output / "gui_cli.dat").read_bytes() == (gui_output / "gui_treated.dat").read_bytes()
    run(cli, ["process", "--session", gui_output / "molar_session.json", "--dat", output / "selected.dat"], "molar_cli")
    assert (output / "selected.dat").read_bytes() == (gui_output / "selected_treated.dat").read_bytes()
    assert (output / "selected_molar.dat").read_bytes() == (gui_output / "selected_molar.dat").read_bytes()
    report["checks"].append("Committed per-file molar settings replay: GUI/CLI ordinary and molar DAT bytes equal")
    report["checks"].append("Hidden real GUI workflow, bundled dependencies/Help/figures and GUI/CLI equality")
    failure = output / "startup_failure"
    run("Torque Data Postprocessing.exe", ["--check-installation", failure, "--session", output / "absent.json"], "startup_failure", False)
    logs = list((failure / "app_data/logs").glob("*.log"))
    assert logs and any("absent.json" in p.read_text(encoding="utf-8") for p in logs)
    report["checks"].append("Startup failure recorded in writable log without foreground dialogs")
    if historical:
        from workflow_regression import CASES, EVIDENCE
        from pipeline import migrate_config
        from validate import read_treated
        cases = []
        for folder in sorted((ROOT / "validation/regression").iterdir()):
            if not (folder / "settings.json").is_file():
                continue
            key = next(k for k in CASES if folder.name.startswith(k))
            cfg = migrate_config(json.loads((folder / "settings.json").read_text(encoding="utf-8")))
            cfg['field_quality'].update(condition='changing',source='Diagnostic historical comparison; not experimental permission')
            frozen = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
            cfg["acquisition"]["temperature_setpoints_K"] = sorted({p["T_K"] for p in frozen["inventory"]}, key=Decimal)
            cfg["acquisition"]["source"] = "Frozen prior-run inventory; sha256 " + sha256(folder / "provenance.json")
            replay = output / (folder.name + "_session.json")
            save_session(replay, [(EVIDENCE / CASES[key][0], cfg)])
            dat = output / (folder.name + ".dat")
            run(cli, ["process", "--session", replay, "--dat", dat], folder.name)
            actual, _ = read_treated(dat)
            old, _ = read_treated(folder / "treated.dat")
            ref, _ = read_treated(EVIDENCE / CASES[key][1])
            assert len(actual) == len(old) and all(a == b[:4] for a, b in zip(actual, old))
            exact = sum(a[3] == b[3] for a, b in zip(actual, ref))
            target = 615 if folder.name == "previous_rot1_mean" else 328 if folder.name == "previous_rot1_midrange" else len(actual)
            assert exact == target
            cases.append({"case": folder.name, "rows": len(actual), "D_reference_exact": exact})
        assert len(cases) == 6 and sum(c["rows"] for c in cases) == 5405
        report["historical"] = cases
        report["checks"].append("Six historical cases: exact pre-change A-D across 5405 case rows")
    for path, expected in prior["protected_files"].items():
        assert sha256(path) == expected, path
    for path, expected in prior["archive_sha256"].items():
        assert sha256(ROOT / path) == expected, path
    report.update(status="PASS", protected_files=len(prior["protected_files"]),
                  gui=gui_output.as_posix(), frozen_runtime=gui["environment"],
                  font=gui["font"], help_topics=gui["help_topics"])
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("PASS: bundled runtime, exact numerical replay, hidden GUI/CLI, safeguards and preservation")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--skip-historical", action="store_true")
    args = parser.parse_args()
    check(args.bundle, args.output, args.before, not args.skip_historical)
