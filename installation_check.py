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
            check_field_widgets(app, root, output)
            report["checks"].append("Fixed-field widgets: persistent alert, full raw evidence, cancel, explicit whole-scan rejection, per-file independence, blocked export, save/replay and stale decision")
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


def check_field_widgets(app, root, output):
    """Synthetic source and simulated decisions; runs inside the withdrawn-window guard."""
    import copy
    from io_profiles import TSV_HEADER
    from cli import load_entry, run_entry
    from pipeline import process, verify_export
    from storage import save_session, load_session, treated_text
    from field_quality import UNRESOLVED
    source = output / "SYNTHETIC_field_review.dat"
    with source.open('w', newline='') as stream:
        writer=csv.writer(stream,delimiter='\t',lineterminator='\n');writer.writerow(TSV_HEADER)
        for scan in range(3):
            for i,angle in enumerate(range(200,-1,-5)):
                field = Decimal('15000') - Decimal('125')*i if scan==0 else Decimal('10000') if scan==1 else Decimal(0)
                writer.writerow(['7.375',str(field),str(angle),str(Decimal(angle*angle+1)*Decimal('1e-12'))])
    obj,cfg=load_entry(source)
    cfg['acquisition']['temperature_setpoints_K']=['7.375']
    cfg['acquisition']['source']='Synthetic software fixture'
    key=app.add_record(source,obj,cfg)
    app.files.selection_set(key);app.refresh_selected();root.update()
    assert 'review required' in app.field_alert.get().lower()
    app.file_settings();dialog=app.settings_dialog
    assert dialog.field_condition.get()=='Fixed field'
    assert dialog.values['field_limit'].get()==''
    dialog.values['field_limit'].set('.5');dialog.apply();root.update()
    record=app.selected()
    assert record['obj'].field_review['P001']['status']=='Review required'
    assert record['obj'].field_review['P002']['status']=='Check passed'
    app.passes.selection_set('P001');app.select_pass();app.review_field();root.update()
    review=app.field_dialog
    assert review.window.state()=='withdrawn'
    assert '15000' in review.raw_text.get('1.0','end')
    assert len(review.canvas.figure.axes[0].lines[0].get_xdata())==41
    review.close()
    assert not record['cfg']['field_quality']['decisions']
    result=process(record['raw'],record['cfg'],partial=True)
    assert not result['exportable'] and result['rows']==41
    try: verify_export(result)
    except ValueError: pass
    else: raise AssertionError('Unresolved scan was exportable')
    app.review_field();review=app.field_dialog
    unchanged=copy.deepcopy(record['cfg'])
    edited=copy.deepcopy(unchanged);edited['field_quality']['source']='Changed while review is open (test)'
    app.apply_settings(record,edited)
    review.reason.set('SIMULATED stale-panel test');review.commit('exclude')
    assert 'changed' in review.error.get()
    assert not record['cfg']['field_quality']['decisions']
    app.apply_settings(record,unchanged);review.close()
    app.review_field();review=app.field_dialog
    review.commit('exclude');assert 'Enter a reason' in review.error.get()
    assert not record['cfg']['field_quality']['decisions']
    review.reason.set('SIMULATED widget-test rejection, not experimental approval')
    review.commit('exclude');root.update()
    assert record['obj'].passes[0].excluded
    assert 'Excluded: P001' in app.field_alert.get()
    result=process(record['raw'],record['cfg'])
    assert result['rows']==41 and sum(r['retention']=='explicitly excluded' for r in result['ledger'])==41
    session=output/'SYNTHETIC_field_session.json'
    save_session(session,[(str(source),record['cfg'])])
    raw,reloaded=load_session(session)[0]
    assert treated_text(run_entry(raw,reloaded))==treated_text(result)
    changed=copy.deepcopy(record['cfg']);changed['field_quality']['limit_T']='.6'
    app.apply_settings(record,changed)
    assert record['obj'].field_review['P001']['status']=='Review required'
    assert not record['obj'].passes[0].excluded
    app.review_field();app.field_dialog.remove();root.update()
    assert not record['cfg']['field_quality']['decisions']
    assert record['obj'].field_review['P001']['status']=='Check passed'
