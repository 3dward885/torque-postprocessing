"""Exercise the real CMD entry points without displaying the application."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(folder, command):
    return subprocess.run([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", command],
                          cwd=folder, stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, timeout=180)


def main(application, output):
    if sys.platform != "win32":
        raise SystemExit("This test requires Windows CMD and Tkinter.")
    output.mkdir(parents=True, exist_ok=False)
    report = {"application": str(application), "foreground_windows": False, "checks": []}
    done = run(application, "call Setup_Windows.cmd --no-pause")
    (output/"setup_output.txt").write_text(done.stdout+done.stderr, encoding="utf-8")
    shutil.copyfile(application/"setup.log", output/"setup.log")
    assert done.returncode == 0, done.stdout+done.stderr
    assert "Application and local Help startup check passed (hidden windows)." in done.stdout
    report["checks"].append("Setup uses this folder's environment; real App and Help initialize withdrawn")

    done = run(application, "call Launch_GUI.cmd --invalid-startup-test-option")
    shutil.copyfile(application/"launch.log", output/"launch_error.log")
    assert done.returncode != 0, "Launcher lost the Python failure exit code"
    assert "unrecognized arguments" in (output/"launch_error.log").read_text(encoding="utf-8")
    assert "Application failed" in done.stdout
    report["checks"].append("Launcher preserves Python errors, log and nonzero exit status")

    done = run(application, "call Launch_GUI.cmd --version")
    shutil.copyfile(application/"launch.log", output/"launch_success.log")
    assert done.returncode == 0, done.stdout+done.stderr
    assert "Torque Postprocessing 1.3" in (output/"launch_success.log").read_text(encoding="utf-8")
    report["checks"].append("Real pythonw CMD launch and argument forwarding return version 1.3")

    scratch = output/"missing environment (test)"
    scratch.mkdir()
    shutil.copyfile(ROOT/"Launch_GUI.cmd", scratch/"Launch_GUI.cmd")
    done = run(scratch, "call Launch_GUI.cmd")
    assert done.returncode == 1
    assert "same folder" in done.stdout and (scratch/"launch.log").is_file()
    report["checks"].append("Missing environment reports same-folder setup instead of silently exiting")

    scratch = output/"setup failure (test)"
    scratch.mkdir()
    shutil.copyfile(ROOT/"Setup_Windows.cmd", scratch/"Setup_Windows.cmd")
    (scratch/"setup_environment.py").write_text("print('Expected setup failure'); raise SystemExit(7)\n", encoding="utf-8")
    done = run(scratch, "call Setup_Windows.cmd --no-pause")
    assert done.returncode == 7, done.stdout+done.stderr
    assert "Setup failed" in done.stdout
    assert "Expected setup failure" in (scratch/"setup.log").read_text(encoding="utf-8")
    report["checks"].append("Setup retains the failure log and exact exit code, including bundled-Python route")
    report["status"] = "PASS"
    (output/"report.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--application", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.application.resolve(), args.output.resolve())
