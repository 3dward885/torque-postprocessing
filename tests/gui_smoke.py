"""Real Tk event-loop smoke test using widgets/callbacks; no OS-input simulation.

Native file dialogs are supplied deterministic paths by mocks. Their visible
desktop behavior is inspected separately with the computer-use tool.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import App
from io_profiles import sha256
from storage import atomic_json
from regression import EVIDENCE


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def button(parent, label):
    matches = [w for w in descendants(parent) if isinstance(w, ttk.Button) and w.cget("text") == label]
    if len(matches) != 1:
        raise AssertionError((label, len(matches)))
    return matches[0]


def combo(parent, first_value):
    return next(w for w in descendants(parent) if isinstance(w, ttk.Combobox) and w.cget("values")[0] == first_value)


def main(hold):
    root = tk.Tk()
    app = App(root)
    root.title("Torque Postprocessing 1.0 - GUI smoke test")
    report = {"test_type": "Actual Tk widgets, worker and event loop on Windows desktop",
              "native_dialog_paths_mocked": True, "checks": []}
    errors = []
    root.report_callback_exception = lambda kind, value, traceback: errors.append(str(value))
    destination = ROOT / "validation/gui"
    destination.mkdir(exist_ok=True)
    app.output.set(str(destination / "runs"))
    raw = EVIDENCE / "inputs/Rot1rawHo2thd4Pc.dat"
    reference = EVIDENCE / "inputs/Rot1treatedHo2thd4Pc.dat"

    def wait():
        deadline = time.monotonic() + 30
        while app.busy:
            root.update()
            if time.monotonic() > deadline:
                raise AssertionError("GUI worker timeout")
            time.sleep(.005)
        root.update()
        if errors:
            raise AssertionError(errors)

    def dialog():
        root.update()
        return next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))

    with patch("app.messagebox.showerror", side_effect=lambda title, message, **kw: report.setdefault("displayed_errors", []).append(message)):
        with patch("app.filedialog.askopenfilenames", return_value=(str(raw),)):
            app.buttons["Add raw files..."].invoke()
        wait()
        record = app.selected()
        assert record["obj"].schema == "four-column TSV"
        assert record["cfg"]["centering"] == "midrange" and record["cfg"]["molar"]["mode"] == "torque"
        assert len(app.passes.get_children()) == 28
        report["checks"].append("Added actual raw file; 28 passes; independent torque-only defaults")

        app.buttons["File settings..."].invoke()
        d = dialog()
        # Choose by complete preset values, distinct from profile/format choices.
        preset = next(w for w in descendants(d) if isinstance(w, ttk.Combobox) and tuple(w.cget("values")) == ("previous", "new_rot1", "new_rot2"))
        preset.set("new_rot1")
        button(d, "Fill documented preset").invoke()
        button(d, "Apply settings").invoke()
        root.update()
        assert record["cfg"]["molar"]["factor"] == "1575.45"
        app.passes.selection_set("P003")
        app.select_pass()
        assert "Changing field" in app.details.get()
        report["checks"].append("Selected explicit reference preset and inspected changing-field pass")

        # Instrument the real processing call with a short delay to measure event-loop responsiveness.
        import app as app_module
        original = app_module.run_entry
        def delayed(*args, **kwargs):
            time.sleep(.25)
            return original(*args, **kwargs)
        ticks = app.pulse_count
        with patch("app.run_entry", side_effect=delayed):
            app.buttons["Process all"].invoke()
            wait()
        report["event_loop_ticks_while_processing"] = app.pulse_count - ticks
        assert report["event_loop_ticks_while_processing"] >= 3
        assert record["result"]["rows"] == 818 and app.canvas is not None
        app.buttons["Export ready"].invoke()
        wait()
        saved = Path(record["saved"])
        assert (saved/"treated.dat").exists()
        report["checks"].append("Processed, previewed and atomically exported 818 rows with a responsive GUI")

        session = destination/"session.json"
        with patch("app.filedialog.asksaveasfilename", return_value=str(session)):
            app.buttons["Save configuration..."].invoke()
        with patch("app.filedialog.askopenfilename", return_value=str(session)):
            app.buttons["Load configuration..."].invoke()
        wait()
        record = app.selected()
        assert record["result"] is None and record["saved"] is None
        app.buttons["Process all"].invoke()
        wait()
        app.buttons["Export ready"].invoke()
        wait()
        with patch("app.filedialog.askopenfilename", return_value=str(reference)):
            app.validate_saved()
        wait()
        assert record["validation"]["exact_rows"] == 818
        report["checks"].append("Saved/reloaded configuration; processed again; validated 818/818 saved rows")

        gui_bytes = (Path(record["saved"])/"treated.dat").read_bytes()
        cli_output = destination/"cli_comparison"
        done = subprocess.run([sys.executable, str(ROOT/"cli.py"), "process", "--session", str(session),
                               "--output", str(cli_output)], capture_output=True, text=True, check=True)
        cli_run = Path(json.loads(done.stdout)[0]["run"])
        assert (cli_run/"treated.dat").read_bytes() == gui_bytes
        report["GUI_CLI_DAT_byte_identical"] = True

        app.passes.selection_set("P003")
        app.select_pass()
        app.buttons["Pass settings / Background..."].invoke()
        d = dialog()
        combo(d, "File default").set("mean")
        combo(d, "Automatic (unique only)").set("P005")
        button(d, "Apply pass settings").invoke()
        root.update()
        assert record["result"] is None and record["saved"] is None
        assert record["validation"] is None and record["reference"] is None and app.canvas is None
        assert app.buttons["Export ready"].instate(["disabled"])
        app.buttons["Process all"].invoke()
        wait()
        assert record["result"]["passes"][2]["centering"] == "mean"
        assert record["result"]["passes"][2]["background_id"] == "P005"
        report["checks"].append("Per-pass mean/background selection invalidated results, plots, exports and validation")

        # Reload the unchanged explicit midrange configuration, then exercise a useful import error.
        app.load_configuration(session)
        wait()
        bad = destination/"SYNTHETIC_invalid_units.dat"
        bad.write_text("Temperature (K)\tMagnetic Field (T)\tSample Position (deg)\tTorque (Nm)\n5\t1\t200\t1e-8\n")
        app.add_files((str(bad),))
        wait()
        assert "schema/units" in app.selected()["error"]
        app.buttons["Process all"].invoke()
        wait()
        assert sum(r["result"] is not None for r in app.records.values()) == 1
        assert sum(bool(r["error"]) for r in app.records.values()) == 1
        report["checks"].append("Useful wrong-unit import error and individual batch success/failure")
        app.buttons["Remove selected"].invoke()
        key = next(iter(app.records))
        app.files.selection_set(key)
        app.refresh_selected()
        record = app.selected()
        app.buttons["Export ready"].invoke()
        wait()
        app.validate_saved(str(reference))
        wait()
        app.tabs.select(0)
        app.passes.selection_set("P003")
        app.view.set("stages")
        app.select_pass()
        root.update()
        assert sha256(raw) == record["obj"].sha256
        assert app.status_label.winfo_ismapped()
        assert app.status_label.winfo_y() + app.status_label.winfo_height() <= root.winfo_height()
        assert "Exact rows: 818 / 818" in app.validation_summary(record["validation"])
        report["raw_input_unchanged"] = True
        report["status_message_visible"] = True
        report["app_sha256"] = sha256(ROOT/"app.py")
        report["plots_sha256"] = sha256(ROOT/"plots.py")
        report["rows_validated"] = record["validation"]["exact_rows"]
        report["current_run"] = record["saved"]
        report["errors"] = errors
        report["status"] = "PASS"
        atomic_json(destination/"gui_test_results.json", report)
        print(json.dumps(report, indent=2), flush=True)
    if hold:
        app.status.set("GUI smoke test PASS. 818/818 saved rows exact; test window available for screenshots.")
        root.mainloop()
    else:
        app.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hold", action="store_true")
    main(parser.parse_args().hold)

