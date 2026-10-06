"""Windowed entry point for the installed application."""
from pathlib import Path
import os
import sys
import traceback
from datetime import datetime


def main():
    checking = "--check-installation" in sys.argv
    log_path = None
    try:
        if checking:
            import argparse
            parser = argparse.ArgumentParser(description="Check the installed app with withdrawn windows.")
            parser.add_argument("--check-installation", type=Path, required=True, metavar="OUTPUT")
            parser.add_argument("--session", type=Path)
            args = parser.parse_args()
            data_dir = args.check_installation.resolve() / "app_data"
        else:
            data_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Torque Data Postprocessing"
        data_dir.mkdir(parents=True, exist_ok=True)
        os.environ["MPLCONFIGDIR"] = str(data_dir / "matplotlib")
        logs = data_dir / "logs"
        logs.mkdir(exist_ok=True)
        log_path = logs / f"launch_{datetime.now():%Y%m%d_%H%M%S}_{os.getpid()}.log"
        # Windowed executables have no console streams; retain startup diagnostics.
        if sys.stdout is None or sys.stderr is None:
            log = log_path.open("a", encoding="utf-8", buffering=1)
            if sys.stdout is None:
                sys.stdout = log
            if sys.stderr is None:
                sys.stderr = log
        if checking:
            from installation_check import check_installation
            check_installation(args.check_installation.resolve(), args.session)
        else:
            from app import main as launch
            launch()
        return 0
    except Exception:
        detail = traceback.format_exc()
        if sys.stderr:
            print(detail, file=sys.stderr)
        if log_path:
            with log_path.open("a", encoding="utf-8") as log:
                log.write(detail)
        if not checking:
            import ctypes
            message = "Torque Data Postprocessing could not start."
            if log_path:
                message += f"\n\nDetails: {log_path}"
            ctypes.windll.user32.MessageBoxW(None, message, "Torque Data Postprocessing", 0x10)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
