"""Opt-in installed-app checks; no foreground windows or desktop input."""
from pathlib import Path
import csv
from decimal import Decimal
import json
import sys
import time


def check_installation(output, session=None):
    import tkinter as tk
    from unittest.mock import patch
    import numpy as np
    import matplotlib
    from app import App
    from io_profiles import APP_VERSION, sha256
    from pipeline import UPSTREAM_IMPLEMENTATION
    from storage import atomic_json, environment, treated_text
    from plots import font_status, export_figure

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if (output / "report.json").exists():
        raise ValueError("Choose an unused installation-check output folder.")
    report = {"version": APP_VERSION, "frozen": bool(getattr(sys, "frozen", False)),
              "environment": environment(), "executable": sys.executable,
              "numpy_path": np.__file__, "matplotlib_path": matplotlib.__file__,
              "module_directory": str(Path(__file__).resolve().parent),
              "matplotlib_cache": matplotlib.get_configdir(),
              "implementation_sha256": UPSTREAM_IMPLEMENTATION,
              "windows_withdrawn": True, "desktop_input": False, "checks": []}
    root = tk.Tk()
    root.withdraw()
    original_toplevel = tk.Toplevel
    class HiddenToplevel(original_toplevel):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.withdraw()
        def deiconify(self):
            self.withdraw()
    errors = []
    root.report_callback_exception = lambda kind, error, trace: errors.append(str(error))
    app = None
    try:
        with patch("tkinter.Toplevel", HiddenToplevel), patch("app.messagebox.showerror",
                side_effect=lambda title, message, **kwargs: errors.append(str(message))):
            app = App(root)
            assert root.title() == f"Torque Data Postprocessing {APP_VERSION}"
            def wait():
                deadline = time.monotonic() + 90
                while app.busy:
                    root.update()
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Background task did not complete.")
                    time.sleep(.01)
                root.update()
                if errors:
                    raise AssertionError(errors)
            root.update()
            app.show_help()
            root.update()
            guide = app.help_window
            assert guide.topics and guide.window.state() == "withdrawn"
            for topic in guide.topics:
                guide.tree.selection_set(topic)
                guide.select()
                assert guide.text.get("1.0", "end").strip()
            report["help_topics"] = len(guide.topics)
            guide.close()
            report["tcl_library"] = root.tk.eval("info library")
            report["tk_version"] = root.tk.eval("package require Tk")
            report["font"] = font_status()
            report["checks"].append("Application, Tcl/Tk, local Help and font lookup")
            if session:
                app.load_configuration(str(Path(session).resolve()))
                wait()
                assert len(app.records) == 1, "Use a single-input session for this check."
                app.process_all()
                wait()
                record = app.selected()
                # Exercise the settings widgets without changing the supplied experiment.
                app.file_settings()
                root.update()
                app.settings_dialog.apply()
                app.process_all()
                wait()
                result = record["result"]
                assert result["exportable"], record["state"]
                report["raw_sha256"] = sha256(record["path"])
                report["rows"] = result["rows"]
                report["bindings"] = {p["pass_id"]: p["baseline_binding"] for p in result["passes"]}
                report["baseline_status"] = {p["pass_id"]: p["baseline_review"]["status"] for p in result["passes"]}
                app.export_all(output / "session_treated.dat")
                wait()
                pred = result["passes"][0]
                app.passes.selection_set(pred["pass_id"])
                app.select_pass()
                assert app.background.get()
                report["background_selector"] = app.background.get()
                app.review_baseline()
                root.update()
                editor = app.editor
                assert editor.window.state() == "withdrawn"
                editor.delta.set("1e-9")  # Software test only, never an experimental default.
                editor.apply()
                expected = treated_text(record["result"])
                editor.apply()
                assert treated_text(record["result"]) == expected
                editor.close()
                app.save_configuration(output / "accepted_session.json")
                app.export_all(output / "gui_treated.dat")
                wait()
                app.load_configuration(output / "accepted_session.json")
                wait()
                app.process_all()
                wait()
                assert treated_text(app.selected()["result"]) == expected
                report["checks"].append("Load, process, zero Apply, repeat Apply, settings save/reload and DAT save")
                if report["font"].startswith("Arial Regular verified:"):
                    export_figure(app.selected()["result"], pred["pass_id"], output / "figures", "background")
                    report["checks"].append("Bundled PDF and PNG figure export")
                    from treated_plots import molar_text, normalization
                    from output_settings import output_paths
                    from PIL import Image
                    saved = treated_text(app.selected()["result"])
                    panel = app.output
                    record = app.selected()
                    assert panel.mode == "torque" and not panel.sample.winfo_manager()
                    assert panel.frame.winfo_manager() == "pack"
                    app.export_plots()
                    dialog = app.plot_dialog
                    assert dialog.window.state() == "withdrawn" and not hasattr(dialog, "quantity")
                    with patch("plot_export_dialog.filedialog.askdirectory", return_value=str(output / "torque_plots")):
                        dialog.export_button.invoke()
                    wait()
                    torque_folder = next((output / "torque_plots").glob("treated_plots_*"))
                    assert not list(torque_folder.glob("*.dat"))
                    original_result = record["result"]
                    original_binding = json.dumps(report["bindings"], sort_keys=True)
                    record["output"]["source"] = "Synthetic software-test normalization; not this sample's measured mass"
                    panel.radios[1].invoke()
                    assert panel.dirty and panel.sample.winfo_manager() == "pack"
                    assert panel.save_button.instate(["disabled"])
                    panel.values["mass_mg"].set("0")
                    panel.values["molar_mass_g_mol"].set("400")
                    panel.apply_button.invoke()
                    assert "positive finite" in panel.note.get()
                    panel.values["mass_mg"].set("2")
                    with patch("app.run_entry", side_effect=AssertionError("Output change refitted data")):
                        panel.apply_button.invoke()
                    assert not panel.dirty and record["output"]["quantity"] == "molar"
                    assert "5.000000E-6" in panel.amount.get()
                    assert app.canvas.figure.axes[0].get_ylabel() == "Molar torque (N m/mol)"
                    assert record["result"] is original_result
                    assert treated_text(record["result"]) == saved
                    # Dirty settings cannot silently cross files, save, or change quantity.
                    panel.values["mass_mg"].set("3")
                    app.save_configuration(output / "must_not_save.json")
                    assert not (output / "must_not_save.json").exists()
                    panel.radios[0].invoke()
                    assert panel.quantity.get() == "molar"
                    key = app.add_record(record["path"], record["raw"], record["cfg"])
                    app.files.selection_set(key)
                    app.refresh_selected()
                    assert app.selected() is record
                    panel.cancel_button.invoke()
                    app.files.selection_set(key)
                    app.refresh_selected()
                    assert app.output.quantity.get() == "torque" and app.output.values["mass_mg"].get() == ""
                    app.remove_selected()
                    app.files.selection_set(record["key"])
                    app.refresh_selected()
                    root.update()
                    assert app.output.values["mass_mg"].get() == "2"
                    # The paired save dialog exposes both actual paths before writing.
                    app.export_all()
                    pair = app.output_save_dialog
                    assert pair.window.state() == "withdrawn"
                    pair.path.set(str(output / "selected_treated.dat"))
                    assert str(output / "selected_molar.dat") in pair.companion.get()
                    pair.save_button.invoke()
                    wait()
                    assert (output / "selected_treated.dat").read_text() == saved
                    assert (output / "selected_molar.dat").read_text() == molar_text(record["result"], normalization(record["output"]))
                    app.save_configuration(output / "molar_session.json")
                    app.load_configuration(output / "molar_session.json")
                    wait()
                    assert app.output.mode == "molar" and app.output.values["mass_mg"].get() == "2"
                    app.process_all()
                    wait()
                    record = app.selected()
                    assert treated_text(record["result"]) == saved
                    app.export_plots()
                    dialog = app.plot_dialog
                    dialog.export(folder=output / "molar_plots")
                    wait()
                    molar_folder = next((output / "molar_plots").glob("treated_plots_*"))
                    assert not list(molar_folder.glob("*.dat"))
                    info = json.loads((molar_folder / "plots.details/plots.json").read_text(encoding="utf-8"))
                    item = info["files"][0]
                    assert Decimal(item["normalization"]["factor_mol_inverse"]) == Decimal(200000)
                    rows = record["result"]["output_rows"]
                    assert sum(p["points"] for p in item["plots"]) == len(rows)
                    for picture in item["plots"]:
                        with Image.open(molar_folder / picture["filename"]) as image:
                            assert image.size == (2400, 1800) and image.info["dpi"] == (300, 300)
                    export_figure(record["result"], pred["pass_id"], output / "molar_figures",
                                  "centered", output=record["output"])
                    panel = app.output
                    panel.method.set("Amount in moles")
                    panel.values["amount_mol"].set("5e-6")
                    panel.apply_button.invoke()
                    assert record["output"]["method"] == "amount"
                    panel.radios[0].invoke()
                    assert panel.mode == "torque" and not panel.sample.winfo_manager()
                    assert "N m/mol" not in app.canvas.figure.axes[0].get_ylabel()
                    panel.radios[1].invoke()
                    assert not panel.dirty and panel.mode == "molar"
                    assert treated_text(record["result"]) == saved
                    app.export_all()
                    app.output_save_dialog.window.destroy()
                    app.export_plots()
                    app.plot_dialog.window.destroy()
                    assert not app.busy
                    report["plot_export"] = {"torque": str(torque_folder), "molar": str(molar_folder),
                        "temperature_groups": len(item["plots"]), "treated_rows": len(rows),
                        "normalization": "Software fixture: 2 mg, 400 g/mol, or 5e-6 mol; not experimental"}
                    report["checks"].append("Visible per-file Output, invalid entries, Apply/Cancel, dirty guards, file independence, amount mode, paired filenames/DAT, saved normalization, matching preview/PDF/PNG/JPEG, no plot DAT or refit")
                assert sha256(record["path"]) == report["raw_sha256"]
            assert root.state() == "withdrawn" and not app.busy
            report["status"] = "PASS"
            atomic_json(output / "report.json", report)
    finally:
        if app:
            if app.editor:
                app.editor.close(force=True)
            app.closed = True
            app.executor.shutdown(wait=True, cancel_futures=True)
        root.destroy()
