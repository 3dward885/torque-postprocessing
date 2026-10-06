"""Real Tk/widget/event checks with every window withdrawn and no desktop input."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys
import time
import tkinter as tk
from unittest.mock import patch
from matplotlib.backend_bases import MouseEvent
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import App
from baseline import accepted_record
from storage import atomic_json, load_session
from io_profiles import sha256
from cli import run_entry


def main(raw, output):
    dest = Path(output)
    dest.mkdir(parents=True, exist_ok=False)
    report = {"windows_withdrawn": True, "desktop_input": False, "checks": [],
              "manual_testing": False, "whole_window_visual_inspection": "Not performed: windows remain withdrawn."}
    root = tk.Tk()
    root.withdraw()
    class HiddenToplevel(tk.Toplevel):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.withdraw()
    errors = []
    root.report_callback_exception = lambda typ, value, trace: errors.append(str(value))
    app = App(root)
    def wait():
        end = time.monotonic()+40
        while app.busy:
            root.update()
            assert time.monotonic() < end, "Worker timeout"
            time.sleep(.005)
        root.update()
        assert not errors, errors
    def check(label):
        report["checks"].append(label)
        print(label, flush=True)
    def choose(pid):
        app.passes.selection_set(pid)
        app.select_pass()
        root.update()
    def mouse(ed, event, x, y):
        e = MouseEvent(event, ed.canvas, x, y, button=1)
        ed.canvas.callbacks.process(event, e)
        root.update()
    try:
        with patch("app.tk.Toplevel", HiddenToplevel), patch("baseline_editor.tk.Toplevel", HiddenToplevel), patch(
                "app.messagebox.showerror", side_effect=lambda title, message, **kw: report.setdefault("messages", []).append(message)):
            app.add_files([str(raw)])
            wait()
            record = app.selected()
            assert len(record["obj"].rows) == 1754 and len(record["obj"].passes) == 34
            assert app.canvas is not None
            check("Actual raw import and immediate preview: 1754 rows, 34 scans")
            app.file_settings()
            dialog = app.settings_dialog
            dialog.values["setpoints"].set("2.5, 5, 10, 25, 50, 100, 150, 200, 250")
            dialog.values["field_limit"].set("0.5")  # Explicit test-only acquisition policy.
            dialog.apply()
            assert not any(s.issue for s in record["obj"].passes)
            app.process_all()
            wait()
            assert set(record["result"]["processing_errors"]) == {"P022", "P023", "P024"}
            assert not record["result"]["exportable"]
            choose("P001")
            assert app.canvas is not None
            check("GUI setpoint entry and partial processing; unresolved coverage does not hide other previews")
            for pid in ("P022", "P023", "P024"):
                choose(pid)
                app.extrapolation_check.invoke()
                app.apply_background()
                root.update()
            app.process_all()
            wait()
            assert record["result"]["exportable"] and record["result"]["rows"] == 1296
            check("Three explicit GUI extrapolation choices produce all 1296 signal rows")
            choose("P001")
            original = copy.deepcopy(record["result"]["passes"][0])
            app.review_baseline()
            root.update()
            ed = app.editor
            assert ed and not ed.dirty and not record["cfg"]["baseline_review"]["overrides"]
            ed.delta.set("nan")
            root.update()
            assert str(ed.buttons["Apply"]["state"]) == "disabled"
            app.save_configuration(dest/"must_not_save.json")
            assert not (dest/"must_not_save.json").exists()
            choose("P002")
            assert app.passes.selection()[0] == "P001"
            ed.cancel()
            ed.reset()
            assert ed.dirty
            ed.cancel()
            ed.delta.set("1e-8")
            ed.cancel()
            assert not record["cfg"]["baseline_review"]["overrides"]
            check("Invalid offset, dirty navigation/save guards, Reset and Cancel")
            ed.canvas.draw()
            x, y = ed.axes.transData.transform((100, ed.line.get_ydata()[0]))
            ed.toolbar.pan()
            mouse(ed, "button_press_event", x, y)
            mouse(ed, "motion_notify_event", x, y+10)
            mouse(ed, "button_release_event", x, y+10)
            assert not ed.dragging and float(ed.delta.get()) == 0
            ed.toolbar.pan()
            ed.toolbar.home()
            ed.toolbar.zoom()
            mouse(ed, "button_press_event", x, y)
            mouse(ed, "button_release_event", x, y)
            assert not ed.dragging
            ed.toolbar.zoom()
            ed.toolbar.home()
            ed.canvas.draw()
            x, y = ed.axes.transData.transform((100, ed.line.get_ydata()[0]))
            limits = ed.axes.get_ylim()
            mouse(ed, "button_press_event", x, y)
            mouse(ed, "motion_notify_event", x, y+15)
            mouse(ed, "button_release_event", x, y+15)
            assert float(ed.delta.get()) > 0 and ed.axes.get_ylim() == limits
            assert ed.dirty
            ed.apply()
            assert record["cfg"]["baseline_review"]["active_passes"] == ["P001"]
            before = copy.deepcopy(record["result"]["output_rows"])
            ed.apply()
            assert record["result"]["output_rows"] == before
            ed.view.set("Corrected")
            ed.draw_new()
            assert list(ed.line.get_ydata()) == [0, 0]
            ed.figure.savefig(dest/"corrected_canvas.png", dpi=150)
            check("Matplotlib drag events, fixed limits, pan/zoom protection and repeat Apply")
            # Retained inactive records must not activate when another scan is applied.
            pred2 = record["result"]["passes"][1]
            cfg = copy.deepcopy(record["cfg"])
            cfg["baseline_review"]["overrides"][pred2["pass_id"]] = accepted_record(
                pred2["baseline_binding"], pred2["subtracted_Nm"], -1e-8)
            app.commit_baseline(record, cfg)
            ed.delta.set("-2e-8")
            ed.apply()
            assert record["result"]["passes"][1]["baseline_review"]["status"] == "inactive"
            ed.reset()
            assert ed.dirty
            ed.apply()
            assert record["result"]["passes"][0]["D"] == original["D"]
            ed.remove()
            assert record["result"]["passes"][0]["D"] == original["D"]
            ed.delta.set("1e-9")
            ed.apply()
            ed.close()
            check("Independent scan settings, inactive retention, zero-delta equality and Remove")
            choose("P001")
            app.range_settings()
            dialog = app.settings_dialog
            dialog.values["range_min"].set("200")
            dialog.values["range_max"].set("0")
            dialog.apply()
            assert dialog.error.get()
            dialog.values["range_min"].set("0")
            dialog.values["range_max"].set("200")
            dialog.apply()
            assert record["cfg"]["acquisition"]["angle_range_deg"] == ["0", "200"]
            app.process_all()
            wait()
            assert record["result"]["rows"] == 1023 and not record["result"]["exportable"]
            choose("P001")
            app.review_baseline()
            root.update()
            assert app.editor.prediction()["baseline_review"]["status"] == "stale"
            app.editor.remove()
            app.editor.delta.set("1e-9")
            app.editor.apply()
            app.editor.close()
            assert record["result"]["exportable"]
            assert all(0 <= a <= 200 for p in record["result"]["passes"] for a in p["angles_deg"])
            check("GUI angular range applies before fit/centering/export and invalidates the previous baseline")
            settings = dest/"accepted_session.json"
            app.save_configuration(settings)
            app.export_all(dest/"gui_treated.dat")
            wait()
            assert (dest/"gui_treated.dat").is_file()
            before_hash = sha256(dest/"gui_treated.dat")
            app.load_configuration(settings)
            wait()
            app.process_all()
            wait()
            app.export_all(dest/"gui_reloaded.dat")
            wait()
            assert (dest/"gui_treated.dat").read_bytes() == (dest/"gui_reloaded.dat").read_bytes()
            done = subprocess.run([sys.executable, str(ROOT/"cli.py"), "process", "--session", str(settings),
                                   "--dat", str(dest/"cli_treated.dat")], cwd=ROOT, capture_output=True, text=True)
            assert done.returncode == 0, done.stdout+done.stderr
            assert (dest/"gui_treated.dat").read_bytes() == (dest/"cli_treated.dat").read_bytes()
            assert sha256(dest/"gui_treated.dat") == before_hash
            assert app.root.state() == "withdrawn"
            check("GUI save/load/reprocess and CLI replay produce byte-identical torque-only DATs")
            report.update(status="PASS", rows=1023, raw_rows=1754, gui_cli_byte_identical=True)
            atomic_json(dest/"report.json", report)
    finally:
        if app.editor:
            app.editor.close(force=True)
        app.closed = True
        app.executor.shutdown(wait=True, cancel_futures=True)
        root.destroy()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    main(Path(args.raw), Path(args.output))
