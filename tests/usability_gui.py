"""v1.3 behavior checks using real withdrawn Tk widgets, never desktop input."""
import argparse
import copy
import json
from pathlib import Path
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import App
from io_profiles import APP_VERSION
from storage import atomic_json, load_session
from ui_help import help_tip


def main(raw, output):
    output.mkdir(parents=True, exist_ok=False)
    report = {"windows_withdrawn": True, "desktop_input": False, "checks": [],
              "visual_inspection": "Widget/event tests only; no whole-window screenshot or desktop capture."}
    root = tk.Tk()
    root.withdraw()
    errors = []
    root.report_callback_exception = lambda typ, value, trace: errors.append(str(value))
    app = App(root)
    OriginalToplevel = tk.Toplevel
    class HiddenToplevel(OriginalToplevel):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.withdraw()

    def pump(seconds=.03):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            root.update()
            time.sleep(.005)
        assert not errors, errors

    def wait():
        until = time.monotonic() + 40
        while app.busy:
            pump(.02)
            assert time.monotonic() < until, "Task timeout"
        pump()
        assert app.progress.winfo_manager() == ""
        assert float(app.progress["value"]) == 0

    def check(message):
        report["checks"].append(message)
        print(message, flush=True)

    def choose(pid):
        app.passes.selection_set(pid)
        app.passes.event_generate("<<TreeviewSelect>>")
        pump()

    def view(name):
        app.view.set(name)
        app.view_box.event_generate("<<ComboboxSelected>>")
        pump()

    def raw_plot():
        assert app.view.get() == "Raw"
        axes = app.canvas.figure.axes[0]
        assert axes.get_ylabel() == "Raw torque (N m)"
        np.testing.assert_array_equal(axes.lines[0].get_ydata(),
                                      [float(r.tokens[12]) for r in app.selected_pass().rows])

    def escape_binding(widget):
        # Unmapped windows cannot receive physical keyboard focus. Invoke the
        # registered Tcl event command with Tk's standard substitution arguments.
        command = widget.bind("<Escape>").split('"[')[1].split()[0]
        return root.tk.call(command, 1, "??", 0, 0, 9, 0, 0, 0, 0, 0,
                            "\x1b", 0, "Escape", 65307, str(widget), 2, 0, 0, 0)

    try:
        with patch("tkinter.Toplevel", HiddenToplevel), patch("app.messagebox.showerror"):
            assert root.title() == f"Torque Data Postprocessing {APP_VERSION}"
            assert app.progress.winfo_manager() == ""
            frame_size = app.progress.master.winfo_reqwidth(), app.progress.master.winfo_reqheight()
            release = threading.Event()
            completed = []
            app.submit("Test activity", lambda: release.wait(5), completed.append)
            assert app.progress.winfo_manager() == "pack"
            pump(.15)
            assert float(app.progress["value"]) > 0
            release.set()
            wait()
            assert completed == [True]
            assert frame_size == (app.progress.master.winfo_reqwidth(), app.progress.master.winfo_reqheight())
            def fail():
                raise ValueError("Expected worker failure")
            app.submit("Test failure", fail, completed.append)
            wait()
            assert "Expected worker failure" in app.last_error
            with patch.object(app.executor, "submit", side_effect=RuntimeError("Executor unavailable")):
                try:
                    app.submit("Test submit failure", lambda: None, completed.append)
                    raise AssertionError("Submission should fail")
                except RuntimeError:
                    pass
            assert not app.busy and app.progress.winfo_manager() == ""
            check("Activity: hidden idle, animated during task, stable toolbar, success/error/submission cleanup")

            app.add_files([str(raw)])
            assert app.progress.winfo_manager() == "pack"
            wait()
            record = app.selected()
            assert len(record["obj"].rows) == 1754
            raw_plot()
            assert tuple(app.view_box["values"]) == ("Raw",)
            app.file_settings()
            dialog = app.settings_dialog
            assert dialog.labels["setpoints"]["text"] == "Temperatures in this file (K)"
            assert dialog.labels["scan_temperature"]["text"] == "Override selected scan temperature (K)"
            dialog.values["setpoints"].set("2.5 5, 10 25,50 100 150,200 250")
            dialog.values["scan_temperature"].set("2.5")
            dialog.apply()
            assert not dialog.window.winfo_exists(), dialog.error.get()
            acquisition = record["cfg"]["acquisition"]
            assert acquisition["temperature_setpoints_K"] == ["2.5", "5", "10", "25", "50", "100", "150", "200", "250"]
            assert set(acquisition["scans"]) == {"P001"}
            saved_override = copy.deepcopy(acquisition["scans"]["P001"])
            app.file_settings()
            dialog = app.settings_dialog
            dialog.apply()
            assert record["cfg"]["acquisition"]["scans"]["P001"] == saved_override
            app.save_configuration(output/"entered_settings.json")
            reloaded = load_session(output/"entered_settings.json")[0][1]
            assert reloaded["acquisition"] == record["cfg"]["acquisition"]
            check("GUI labels, mixed temperature list, selected-only override, blank preservation and settings round-trip")

            app.process_all()
            wait()
            assert set(record["result"]["processing_errors"]) == {"P022", "P023", "P024"}
            choose("P001")
            assert app.view.get() == "Corrected"
            np.testing.assert_array_equal(app.canvas.figure.axes[0].lines[0].get_ydata(),
                                          record["result"]["passes"][0]["centered_internal_Nm"])
            view("Processing steps")
            assert len(app.canvas.figure.axes[0].lines) == 4
            choose("P006")
            raw_plot()
            assert str(app.buttons["Center zero…"]["state"]) == "disabled"
            choose("P022")
            raw_plot()
            choose("P001")
            assert app.view.get() == "Processing steps"
            view("Background fit")
            assert app.canvas.figure.axes[0].get_ylabel() == "Background torque (N m)"
            cfg = copy.deepcopy(record["cfg"])
            app.apply_settings(record, cfg)
            raw_plot()
            with patch("app.run_entry", side_effect=ValueError("Test process failure")):
                app.process_all()
                wait()
            raw_plot()
            assert record["result"] is None
            app.process_all()
            wait()
            assert app.view.get() == "Background fit"
            app.add_files([str(raw)])
            wait()
            second_key = app.selected()["key"]
            raw_plot()
            app.files.selection_set(record["key"])
            app.refresh_selected()
            assert app.view.get() == "Background fit"
            app.files.delete(second_key)
            del app.records[second_key]
            check("Views: raw import/background/unresolved scan, processed values/labels, failure/invalidation and file switching")

            app.load_configuration(ROOT/"examples/Ho2sq3_manual_demo.json")
            wait()
            app.process_all()
            wait()
            record = app.selected()
            choose("P001")
            original = copy.deepcopy(record["result"])
            record["result"]["passes"][0]["baseline_review"]["status"] = "stale"
            app.select_pass()
            assert tuple(app.view_box["values"]) == ("Background fit", "Raw")
            record["result"] = original
            view("Raw")
            app.export_all(output/"raw_view.dat")
            wait()
            view("Corrected")
            app.export_all(output/"corrected_view.dat")
            wait()
            assert (output/"corrected_view.dat").is_file(), app.last_error
            assert (output/"raw_view.dat").read_bytes() == (output/"corrected_view.dat").read_bytes()
            check("Stale adjusted previews unavailable; DAT bytes independent of selected plot view")

            hover = app.hover
            target = app.buttons["Center zero…"]
            target.configure(state="disabled")
            target.event_generate("<Enter>")
            pump(.1)
            assert hover.pending and not hover.popup
            target.event_generate("<Leave>")
            pump(.2)
            assert not hover.pending and not hover.popup
            target.event_generate("<Enter>")
            started = time.monotonic()
            pump(.85)
            assert hover.pending and not hover.popup
            pump(.25)
            elapsed = time.monotonic() - started
            assert hover.popup and hover.popup.state() == "withdrawn"
            text = hover.popup.winfo_children()[0]["text"]
            assert text == help_tip("center_zero")
            target.event_generate("<Leave>")
            hover.popup.event_generate("<Enter>")
            pump(.25)
            assert hover.popup and hover.over_popup
            popup = hover.popup
            pump(1.15)
            assert hover.popup is popup and not hover.pending
            popup.event_generate("<Leave>")
            target.event_generate("<Enter>")
            assert escape_binding(root) == "break"
            assert not hover.popup and root.winfo_exists()
            target.event_generate("<Enter>")
            pump(1.1)
            assert not hover.popup and not hover.pending
            target.event_generate("<Leave>")
            target.event_generate("<Enter>")
            pump(1.1)
            assert hover.popup
            target.event_generate("<ButtonPress-1>")
            pump()
            assert not hover.popup
            temporary = ttk.Button(root, text="Temporary")
            hover.attach(temporary, "open")
            temporary.event_generate("<Enter>")
            assert hover.pending
            temporary.destroy()
            pump()
            assert not hover.pending and hover.source is None
            report["tooltip_observation_seconds"] = elapsed
            check("Hover: real Enter/Leave/click events, 1000 ms delay, disabled control, persistent reading, pointer transfer, Tcl-bound Esc and cleanup")

            menu = root.nametowidget(root["menu"])
            help_menu = root.nametowidget(menu.entrycget("Help", "menu"))
            help_menu.invoke("User guide")
            pump()
            guide = app.help_window
            assert guide.window.state() == "withdrawn"
            guide.tree.item("options", open=True)
            guide.tree.selection_set("temperature_list")
            guide.tree.event_generate("<<TreeviewSelect>>")
            pump()
            assert "spaces or commas" in guide.text.get("1.0", "end")
            guide.tree.item("options", open=False)
            assert not guide.tree.item("options", "open")
            guide.close()
            app.file_settings()
            dialog = app.settings_dialog
            assert dialog.window.bind("<F1>")
            assert {"angle_step_deg", "field_step_T", "scan_starts", "ordinary_centering"} <= {key for _, key in dialog.hover.bindings}
            app.show_help(dialog.window)
            assert root.grab_current() == app.help_window.window
            app.help_window.close()
            assert root.grab_current() == dialog.window
            entry = dialog.entries["scan_temperature"]
            entry.event_generate("<Enter>")
            assert dialog.hover.pending
            assert escape_binding(dialog.window) == "break"
            assert dialog.window.winfo_exists() and not dialog.hover.pending
            dialog.window.destroy()
            app.refresh_buttons()
            app.review_baseline()
            pump()
            ed = app.editor
            assert {"baseline_delta", "baseline_apply", "baseline_plot", "baseline_pan", "baseline_zoom"} <= {key for _, key in ed.hover.bindings}
            ed.entry.event_generate("<Enter>")
            assert ed.hover.pending
            ed.close()
            assert not ed.hover.pending
            check("Help menu/tree selection, expand/collapse, modal F1 access, advanced settings and zero-editor help coverage")

            target.event_generate("<Leave>")
            target.event_generate("<Enter>")
            app.set_activity(True)
            app.close()
            assert app.closed and app.poll_id is None and not hover.pending
            assert not root.tk.call("after", "info"), root.tk.call("after", "info")
            assert not errors, errors
            check("Application closure cancels activity, polling and tooltip callbacks")
            report["status"] = "PASS"
            atomic_json(output/"report.json", report)
    finally:
        app.executor.shutdown(wait=True, cancel_futures=True)
        if not app.closed:
            if app.editor:
                app.editor.close(force=True)
            app.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.raw, args.output)
