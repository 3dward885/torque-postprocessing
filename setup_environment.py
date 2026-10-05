"""One-time local environment setup, launched by Setup_Windows.cmd."""
from pathlib import Path
import subprocess
import sys
import venv

if sys.version_info[:2] != (3, 12):
    raise SystemExit("Use Python 3.12 with Tkinter. The tested numerical baseline is Python 3.12.14.")
root = Path(__file__).resolve().parent
environment = root / ".venv"
python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
if not python.exists():
    venv.create(environment, with_pip=True)
subprocess.run([str(python), "-m", "pip", "--isolated", "install", "--index-url",
                "https://pypi.org/simple", "-r", str(root/"requirements.txt")], check=True)
subprocess.run([str(python), "-c",
                "import app,tkinter; r=tkinter.Tk(); r.withdraw(); "
                "a=app.App(r); a.show_help(); r.update(); "
                "assert r.state() == 'withdrawn'; a.close(); "
                "print('Application and local Help startup check passed (hidden windows).')"],
               cwd=root, check=True)
print("Setup complete. Double-click Launch_GUI.cmd.")

