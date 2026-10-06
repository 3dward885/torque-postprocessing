"""Two entry points sharing one directory of bundled runtime files."""
from pathlib import Path
import os
from PyInstaller.utils.hooks import copy_metadata

root = Path(SPECPATH).parent
stage = Path(os.environ["TORQUE_BUILD_STAGE"])
data = [(str(root / name), ".") for name in (
    "app.py", "baseline.py", "baseline_editor.py", "cli.py", "input_fields.py",
    "io_profiles.py", "pipeline.py", "plots.py", "presets.py", "storage.py",
    "ui_help.py", "validate.py", "desktop.py", "installation_check.py", "help_content.json",
    "treated_plots.py", "plot_export_dialog.py")]
# Source is required by inspect.getsource for scientific baseline bindings.
data += [(str(stage / "licenses"), "licenses"),
         (str(stage / "build_info.json"), ".")]
data += copy_metadata("numpy") + copy_metadata("matplotlib")

options = dict(pathex=[str(root)], datas=data,
               hookspath=[], runtime_hooks=[], hiddenimports=[],
               excludes=["IPython", "pytest", "scipy", "pandas"],
               hooksconfig={"matplotlib": {"backends": ["TkAgg", "Agg", "pdf"]}},
               noarchive=False, optimize=0)
a = Analysis([str(root / "desktop.py")], **options)
gui = EXE(PYZ(a.pure), a.scripts, [], exclude_binaries=True,
          name="Torque Data Postprocessing", console=False, upx=False,
          version=str(root / "windows/version_info.txt"))
b = Analysis([str(root / "cli.py")], **options)
cli = EXE(PYZ(b.pure), b.scripts, [], exclude_binaries=True,
          name="TorqueDataCLI", console=True, upx=False,
          version=str(root / "windows/version_info.txt"))
bundle = COLLECT(gui, cli, a.binaries, a.datas, b.binaries, b.datas,
                 strip=False, upx=False, name="Torque Data Postprocessing")
