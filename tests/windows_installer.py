"""Silent install/update/uninstall in one isolated directory; no desktop input."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid
import winreg

from windows_bundle import check, ROOT
from io_profiles import sha256

REGKEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{7192D918-D36B-4D0E-9F83-F90C3C68A6F1}_is1"


def registration():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGKEY, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            return {name: winreg.QueryValueEx(key, name)[0] for name in
                    ("InstallLocation", "DisplayName", "DisplayVersion", "UninstallString")}
    except FileNotFoundError:
        return None


def main(setup, bundle_manifest, output, before):
    setup, output = Path(setup).resolve(), Path(output).resolve()
    if registration():
        raise RuntimeError("An existing app registration is present; installer test stopped without modifying it.")
    output.mkdir(parents=True, exist_ok=False)
    installed = output / "app é"
    assert installed.is_relative_to(output) and not installed.exists()
    group = "Torque Data Postprocessing test " + uuid.uuid4().hex[:10]
    shortcut_dir = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs" / group
    assert not shortcut_dir.exists()
    report = {"setup_sha256": sha256(setup), "visible_UI": False, "test_directory": str(installed),
              "shortcut_test_group": str(shortcut_dir), "checks": [], "exit_codes": {}}
    def install(target, label, success):
        command = [str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/SP-", "/NORESTART",
                   "/NOCLOSEAPPLICATIONS", "/NORESTARTAPPLICATIONS", "/TASKS=",
                   f"/DIR={target}", f"/GROUP={group}", f"/LOG={output / (label + '.log')}"]
        done = subprocess.run(command, cwd=output, creationflags=subprocess.CREATE_NO_WINDOW, timeout=150)
        report["exit_codes"][label] = done.returncode
        assert (done.returncode == 0) == success, (label, done.returncode)
    occupied = output / "unrelated directory"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("Unrelated user data")
    install(occupied, "reject_unrelated", False)
    assert list(occupied.iterdir()) == [occupied / "keep.txt"]
    assert registration() is None
    report["checks"].append("Unrelated nonempty destination refused before writing app files")
    too_long = output / ("long_path_" * 12)
    install(too_long, "reject_long_path", False)
    assert registration() is None and not (too_long / "Torque Data Postprocessing.exe").exists()
    report["checks"].append("Overlong installation path rejected before copying libraries")
    try:
        install(installed, "install", True)
        reg = registration()
        assert Path(reg["InstallLocation"]).resolve() == installed
        assert reg["DisplayName"].startswith("Torque Data Postprocessing") and reg["DisplayVersion"] == "1.5"
        manifest = json.loads(Path(bundle_manifest).read_text())
        assert all(sha256(installed / p) == h for p, h in manifest.items())
        links = sorted(shortcut_dir.glob("*.lnk"))
        assert len(links) == 2
        shortcut = shortcut_dir / "Torque Data Postprocessing.lnk"
        escaped = str(shortcut).replace("'", "''")
        script = f"[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); $s=(New-Object -ComObject WScript.Shell).CreateShortcut('{escaped}'); $s.TargetPath"
        shell_env = os.environ.copy()
        shell_env.pop("PSModulePath", None)
        resolved = subprocess.check_output([shutil.which("pwsh.exe") or "powershell.exe", "-NoProfile",
                    "-NonInteractive", "-Command", script], env=shell_env,
                    creationflags=subprocess.CREATE_NO_WINDOW, text=True, encoding="utf-8").strip()
        assert Path(resolved).resolve() == installed / "Torque Data Postprocessing.exe"
        report["checks"].append("Per-user registration, complete payload and Start-menu shortcut target")
        marker = installed / "user_saved_data.txt"
        marker.write_text("Uninstaller must preserve this unrelated user file.")
        install(installed, "repeat_update", True)
        assert marker.exists() and all(sha256(installed / p) == h for p, h in manifest.items())
        report["checks"].append("Repeat install/update preserves user files and payload")
        # Hold only this test installation's EXE open without sharing; no live app is closed.
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                      ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.CreateFileW(str(installed / "Torque Data Postprocessing.exe"), 0x80000000, 0, None, 3, 0x80, None)
        assert handle not in (None, ctypes.c_void_p(-1).value), ctypes.get_last_error()
        try:
            install(installed, "locked_update", False)
        finally:
            kernel.CloseHandle(handle)
        assert all(sha256(installed / p) == h for p, h in manifest.items()) and marker.exists()
        report["checks"].append("Locked-file update aborts and rolls back without closing an application")
        check(installed, output / "installed_checks", before, historical=False)
        report["checks"].append("Installed GUI and CLI run from Unicode/spaced paths with system-only PATH")
    finally:
        reg = registration()
        if reg:
            if Path(reg["InstallLocation"]).resolve() != installed:
                raise RuntimeError("Registration target changed; no uninstaller was run.")
            uninstall = installed / "unins000.exe"
            assert uninstall.is_file() and uninstall.resolve().is_relative_to(output)
            done = subprocess.run([str(uninstall), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                                   f"/LOG={output / 'uninstall.log'}"], cwd=output,
                                  creationflags=subprocess.CREATE_NO_WINDOW, timeout=150)
            report["exit_codes"]["uninstall"] = done.returncode
            assert done.returncode == 0
            end = time.monotonic() + 15
            while registration() and time.monotonic() < end:
                time.sleep(.1)
            assert registration() is None
    assert marker.exists() and not (installed / "Torque Data Postprocessing.exe").exists()
    assert not shortcut_dir.exists()
    assert (output / "installed_checks/gui_cli.dat").is_file()
    assert (output / "installed_checks/hidden_gui/accepted_session.json").is_file()
    report["checks"].append("Uninstall removed app/registration/test shortcuts and preserved user data/settings")
    report["status"] = "PASS"
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("PASS: silent install, shortcuts, update, locked-file rollback and uninstall preservation")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--before", type=Path, required=True)
    args = parser.parse_args()
    main(args.setup, args.manifest, args.output, args.before)
