"""Build a local, offline Windows installer. Run with requirements-build.txt installed."""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata as metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
COMPILER_URL = "https://github.com/jrsoftware/issrc/releases/download/is-7_1_0/innosetup-7.1.0-x64.exe"
COMPILER_SHA256 = "0362a383ed217d4c4239b5933866dd96d3eb2102737da92f80f6057a4b40df2f"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, log=None, **kwargs):
    if log:
        with Path(log).open("w", encoding="utf-8") as stream:
            result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                                    creationflags=subprocess.CREATE_NO_WINDOW, **kwargs)
        if result.returncode:
            raise RuntimeError(f"Command failed ({result.returncode}); see {log}")
    else:
        subprocess.run(command, check=True, creationflags=subprocess.CREATE_NO_WINDOW, **kwargs)


def compiler():
    tools = ROOT / "build_tools"
    tools.mkdir(exist_ok=True)
    setup = tools / "innosetup-7.1.0-x64.exe"
    if not setup.exists():
        urllib.request.urlretrieve(COMPILER_URL, setup)
    if digest(setup) != COMPILER_SHA256:
        raise ValueError("Compiler download hash mismatch; no downloaded program was run.")
    quoted = str(setup).replace("'", "''")
    shell_env = os.environ.copy()
    shell_env.pop("PSModulePath", None)
    run([shutil.which("pwsh.exe") or "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         f"$s=Get-AuthenticodeSignature -LiteralPath '{quoted}'; "
         "if ($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notlike '*Pyrsys B.V.*') {exit 1}"], env=shell_env)
    folder = tools / "innosetup"
    if not (folder / "ISCC.exe").exists():
        run([str(setup), "/PORTABLE=1", "/CURRENTUSER", "/VERYSILENT", "/SUPPRESSMSGBOXES",
             "/NORESTART", "/NOCLOSEAPPLICATIONS", "/NOICONS", "/SP-", "/TASKS=",
             f"/DIR={folder}", f"/LOG={tools / 'compiler_setup.log'}"])
    for filename in ("ISCC.exe", "ISCmplr.dll"):
        quoted = str(folder / filename).replace("'", "''")
        run([shutil.which("pwsh.exe") or "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             f"$s=Get-AuthenticodeSignature -LiteralPath '{quoted}'; "
             "if ($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notlike '*Pyrsys B.V.*') {exit 1}"], env=shell_env)
    return folder / "ISCC.exe"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New directory for this build")
    args = parser.parse_args()
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        parser.error("Build with 64-bit Python on Windows.")
    if platform.python_version() != "3.12.14":
        parser.error("This release uses Python 3.12.14; a different runtime needs separate baseline replay validation.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    versions = {}
    for req in (ROOT / "requirements.txt", ROOT / "requirements-build.txt"):
        for line in req.read_text().splitlines():
            if "==" not in line or line.startswith("#"):
                continue
            package, expected = line.split("==")
            actual = metadata.version(package)
            if actual != expected:
                raise ValueError(f"Build requires {package}=={expected}; found {actual}.")
            versions[package] = actual
    stage = output / "build"
    stage.mkdir()
    licenses = stage / "licenses"
    licenses.mkdir(exist_ok=True)
    for name in versions:
        dist = metadata.distribution(name)
        for item in dist.files or []:
            if any(word in item.name.lower() for word in ("license", "copying", "copyright", "notice")):
                source = Path(dist.locate_file(item))
                if source.is_file():
                    target = licenses / name / str(item).replace("../", "")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
    shutil.copyfile(Path(sys.base_prefix) / "LICENSE.txt", licenses / "Python_LICENSE.txt")
    for source in (Path(sys.base_prefix) / "tcl").rglob("*"):
        if source.is_file() and source.name.lower() in ("license.terms", "license.txt", "license"):
            target = licenses / "Tcl_Tk" / source.relative_to(Path(sys.base_prefix) / "tcl")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    sys.path.insert(0, str(ROOT))
    from pipeline import UPSTREAM_IMPLEMENTATION
    from io_profiles import APP_VERSION
    info = {"app_name": "Torque Data Postprocessing", "app_version": APP_VERSION,
            "installer_build": 1, "built_utc": datetime.now(timezone.utc).isoformat(),
            "python": platform.python_version(), "platform": platform.platform(), "packages": versions,
            "numerical_implementation_sha256": UPSTREAM_IMPLEMENTATION,
            "source_sha256": {p.name: digest(p) for p in ROOT.glob("*.py")},
            "compiler_download": COMPILER_URL, "compiler_download_sha256": COMPILER_SHA256,
            "code_signing": "Unsigned; no publisher certificate configured"}
    wheel_manifest = ROOT / "windows/dependency_wheels.json"
    if wheel_manifest.exists():
        info["dependency_wheels"] = json.loads(wheel_manifest.read_text())
    (stage / "build_info.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    (licenses / "README.txt").write_text(
        "Third-party notices for the bundled runtime and build tools.\n"
        "The app does not distribute Microsoft Arial; it uses the installed Windows font.\n",
        encoding="utf-8")
    iscc = compiler()
    info["compiler_sha256"] = digest(iscc)
    (stage / "build_info.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(iscc.parent / "license.txt", licenses / "Inno_Setup_LICENSE.txt")
    build_env = os.environ.copy()
    build_env["TORQUE_BUILD_STAGE"] = str(stage)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", str(output / "portable"), "--workpath", str(stage / "pyinstaller"),
         str(ROOT / "windows/Torque.spec")], output / "pyinstaller.log", cwd=ROOT, env=build_env)
    bundle = output / "portable/Torque Data Postprocessing"
    shutil.copyfile(ROOT / "WINDOWS_APP.txt", bundle / "Read me.txt")
    (bundle / "install_identity.txt").write_text("7192D918-D36B-4D0E-9F83-F90C3C68A6F1\n")
    manifest = {p.relative_to(bundle).as_posix(): digest(p) for p in bundle.rglob("*") if p.is_file()}
    library_names = [n for n in manifest if Path(n).suffix.lower() in (".dll", ".pyd", ".exe")]
    max_path = 258 - max(len(n.encode("utf-16-le")) // 2 for n in library_names)
    info["maximum_install_directory_characters"] = max_path
    (stage / "build_info.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(stage / "build_info.json", bundle / "_internal/build_info.json")
    manifest["_internal/build_info.json"] = digest(bundle / "_internal/build_info.json")
    (output / "bundle_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    run([str(iscc), f"/DBundleDir={bundle}", f"/DOutputPath={output}", f"/DMaxAppPath={max_path}",
         str(ROOT / "windows/installer.iss")], output / "inno.log", cwd=ROOT)
    portable = output / f"Torque_Data_Postprocessing_{APP_VERSION}_portable_x64.zip"
    with zipfile.ZipFile(portable, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for p in sorted(bundle.rglob("*")):
            if p.is_file():
                archive.write(p, str(Path(bundle.name) / p.relative_to(bundle)))
    hashes = {p.name: digest(p) for p in output.iterdir() if p.suffix in (".exe", ".zip")}
    (output / "SHA256SUMS.txt").write_text("".join(f"{h}  {n}\n" for n, h in hashes.items()))
    shutil.copyfile(stage / "build_info.json", output / "build_info.json")
    print(json.dumps({"output": str(output), "sha256": hashes}, indent=2))


if __name__ == "__main__":
    main()
