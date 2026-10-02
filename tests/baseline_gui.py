"""D/F/G: actual Tk widgets + Matplotlib events; native dialogs get fixed paths."""
import argparse
import copy
from decimal import Decimal, localcontext
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tkinter as tk
from unittest.mock import patch
import numpy as np
from matplotlib.backend_bases import MouseEvent
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import App
from baseline import preview_values
from io_profiles import sha256
from pipeline import process
from presets import apply_preset
from storage import atomic_json, treated_text, load_session
from regression import EVIDENCE
from validate import compare


def main(output, hold=False, background=False):
    dest = Path(output)
    dest.mkdir(parents=True,exist_ok=True)
    report = {"status":"RUNNING", "type":"Real Tk widgets, worker event loop and Matplotlib mouse events on Windows",
              "native_file_dialog_paths_mocked":True,"human_manual_testing":False,"checks":[]}
    root = tk.Tk()
    if background:
        root.withdraw()
        class HiddenToplevel(tk.Toplevel):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.withdraw()
        tk.Toplevel = HiddenToplevel
        report["windows_withdrawn"] = True
    app = App(root)
    errors = []
    root.report_callback_exception = lambda kind,value,tb: errors.append(str(value))
    app.output.set(str(dest/"gui_runs"))
    def wait():
        end = time.monotonic()+60
        while app.busy:
            root.update()
            assert time.monotonic()<end,"Worker timed out"
            time.sleep(.005)
        root.update()
        assert not errors,errors
    def check(text):
        report["checks"].append(text)
        print(text,flush=True)
    def open_editor():
        app.passes.selection_set("P003")
        app.select_pass()
        app.buttons["Review baseline..."].invoke()
        root.update()
        return app.editor
    def mouse(editor,name,x,y,button=1):
        event = MouseEvent(name,editor.canvas,x,y,button=button)
        editor.canvas.callbacks.process(name,event)
        root.update()
    raw = EVIDENCE/"inputs/Rot1rawHo2thd4Pc.dat"
    with patch("app.messagebox.showerror",side_effect=lambda title,message,**kw: report.setdefault("displayed_errors",[]).append(message)):
        with patch("app.filedialog.askopenfilenames",return_value=(str(raw),)):
            app.buttons["Add raw files..."].invoke()
        wait()
        r = app.selected()
        assert not app.baseline_enabled.get()
        r["cfg"] = apply_preset(r["cfg"],"new_rot1")
        r["cfg"]["centering"] = "mean"
        r["cfg"]["centering_source"] = "Explicit GUI software acceptance test"
        original_run_entry = __import__("app").run_entry
        def delayed(*args,**kwargs):
            time.sleep(.2)
            return original_run_entry(*args,**kwargs)
        ticks = app.pulse_count
        with patch("app.run_entry",side_effect=delayed):
            app.buttons["Process all"].invoke()
            wait()
        assert app.pulse_count-ticks>=2
        ordinary = treated_text(r["result"])
        app.baseline_check.invoke()
        wait()
        ed = open_editor()
        assert ed and not ed.dirty and float(ed.delta.get()) == 0.
        assert not r["cfg"]["baseline_review"]["overrides"]
        assert treated_text(r["result"]) == ordinary
        check("Load/process/default-off; viewing midrange draft does not commit or change ordinary mean")

        ed.entry.delete(0,"end")
        ed.entry.insert(0,"nan")
        root.update()
        assert ed.dirty and ed.buttons["Apply"].instate(["disabled"])
        assert "finite" in ed.notice.get()
        ed.pass_var.set("P001")
        ed.pass_box.event_generate("<<ComboboxSelected>>")
        root.update()
        assert ed.pid == "P003" and ed.pass_var.get() == "P003"
        app.passes.selection_set("P002")
        app.select_pass()
        root.update()
        assert app.passes.selection() == ("P003",)
        forbidden = dest/"must_not_save.json"
        app.save_configuration(str(forbidden))
        app.load_configuration(str(forbidden))
        app.export_all()
        app.process_all()
        app.close()
        assert not forbidden.exists() and not app.closed and not app.busy
        app.baseline_enabled.set(False)
        app.toggle_baseline()
        assert app.baseline_enabled.get() and r["cfg"]["baseline_review"]["enabled"]
        ed.buttons["Cancel"].invoke()
        assert not ed.dirty
        check("Invalid numeric entry and dirty guards: navigation, disable, save/load, process, export and close")

        ed.buttons["Reset"].invoke()
        assert ed.dirty and not r["cfg"]["baseline_review"]["overrides"]
        ed.buttons["Apply"].invoke()
        root.update()
        accepted = copy.deepcopy(r["cfg"]["baseline_review"]["overrides"]["P003"])
        for _ in range(3):
            ed.buttons["Apply"].invoke()
            root.update()
        assert accepted == r["cfg"]["baseline_review"]["overrides"]["P003"]
        mid_cfg = copy.deepcopy(r["cfg"])
        mid_cfg["baseline_review"]["enabled"] = False
        mid_cfg["overrides"]["P003"] = {"identity":r["obj"].passes[2].identity,"centering":"midrange","source":"Software test"}
        assert treated_text(r["result"]) == treated_text(process(r["obj"],mid_cfg))
        check("Reset requires Apply; accepted zero equals midrange; repeated Apply preserves offset and timestamp")

        ed.canvas.draw()
        x,y = ed.axes.transData.transform((100,ed.line.get_ydata()[0]))
        limits = ed.axes.get_ylim()
        with patch("pipeline.fit_background",side_effect=AssertionError("unexpected refit")), patch("app.run_entry",side_effect=AssertionError("unexpected reread")):
            ed.toolbar.pan()
            mouse(ed,"button_press_event",x,y)
            mouse(ed,"motion_notify_event",x,y+12)
            mouse(ed,"button_release_event",x,y+12)
            assert float(ed.delta.get()) == 0.
            ed.toolbar.pan()
            ed.toolbar.home()
            ed.canvas.draw()
            x,y = ed.axes.transData.transform((100,ed.line.get_ydata()[0]))
            mouse(ed,"button_press_event",x,y)
            mouse(ed,"motion_notify_event",x,y+12)
            mouse(ed,"button_release_event",x,y+12)
        assert float(ed.delta.get())>0 and ed.dirty
        assert ed.axes.get_ylim() == limits
        stats = preview_values(ed.cache.u,ed.delta.get())
        assert stats["maximum"] < preview_values(ed.cache.u,0)["maximum"]
        assert float(ed.line.get_ydata()[0]) == stats["c_final"]
        ed.buttons["Cancel"].invoke()
        ed.toolbar.zoom()
        ed.canvas.draw()
        x1,y1 = ed.axes.transAxes.transform((.2,.2))
        x2,y2 = ed.axes.transAxes.transform((.8,.8))
        mouse(ed,"button_press_event",x1,y1)
        mouse(ed,"motion_notify_event",x2,y2)
        mouse(ed,"button_release_event",x2,y2)
        assert ed.axes.get_xlim() != (-5.,205.)
        assert not ed.dirty and float(ed.delta.get()) == 0.
        ed.toolbar.zoom()
        check("Actual Matplotlib drag has correct sign and fixed limits; pan/zoom never changes the baseline; no reread/refit")

        ed.delta.set("1.2345678901234567e-9")
        ed.buttons["Apply"].invoke()
        root.update()
        committed = treated_text(r["result"])
        ed.view.set("Corrected")
        ed.view_box.event_generate("<<ComboboxSelected>>")
        root.update()
        assert ed.line.get_ydata() == [0.,0.]
        assert np.array_equal(ed.points.get_ydata(),ed.cache.u-float(r["cfg"]["baseline_review"]["overrides"]["P003"]["c_final_Nm"]))
        ed.delta.set("-1e-9")
        ed.buttons["Cancel"].invoke()
        assert treated_text(r["result"]) == committed
        ed.pass_var.set("P001")
        ed.pass_box.event_generate("<<ComboboxSelected>>")
        root.update()
        assert ed.pid == "P001" and float(ed.delta.get()) == 0
        assert "mean" in ed.effective.get()
        ed.close()
        app.baseline_check.invoke()
        assert treated_text(r["result"]) == ordinary
        assert "P003" in r["cfg"]["baseline_review"]["overrides"]
        app.baseline_check.invoke()
        assert treated_text(r["result"]) == committed
        ed = open_editor()
        ed.buttons["Remove override"].invoke()
        assert treated_text(r["result"]) == ordinary
        ed.delta.set("1.2345678901234567e-9")
        ed.buttons["Apply"].invoke()
        ed.close()
        check("Corrected view fixed zero; Cancel, pass isolation, retained off/on settings and Remove restore ordinary policy")

        session = dest/"accepted_session.json"
        app.save_configuration(str(session))
        app.export_all()
        wait()
        gui_bytes = (Path(r["saved"])/"treated.dat").read_bytes()
        first_saved = r["saved"]
        app.load_configuration(str(session))
        wait()
        r = app.selected()
        app.process_all()
        wait()
        app.export_all()
        wait()
        assert (Path(r["saved"])/"treated.dat").read_bytes() == gui_bytes
        cli = subprocess.run([sys.executable,str(ROOT/"cli.py"),"process","--session",str(session),
                              "--output",str(dest/"cli_runs")],capture_output=True,text=True,check=True)
        cli_saved = Path(json.loads(cli.stdout)[0]["run"])
        assert (cli_saved/"treated.dat").read_bytes() == gui_bytes
        report["GUI_CLI_DAT_byte_identical"] = True
        report["representative_GUI_export"] = first_saved
        report["accepted_session"] = str(session)
        check("GUI save/load/reprocess/export and actual CLI replay are byte-identical without accumulated shifts")

        isolated = dest/"isolated"
        isolated.mkdir()
        shutil.copyfile(raw,isolated/"raw.dat")
        atomic_json(isolated/"settings.json",r["cfg"])
        isolated_run = subprocess.run([sys.executable,str(ROOT/"tests/isolation.py"),"--child",str(isolated)],
                                      capture_output=True,text=True,check=True)
        access = json.loads((isolated/"access_log.json").read_text())
        assert access["reference_probe_denied"] and len(access["denied_reads"]) == 1
        assert (isolated/"out/isolated/treated.dat").read_bytes() == gui_bytes
        # Independent comparison occurs only after the guarded child has exited.
        equality = compare(isolated/"out/isolated/treated.dat",Path(first_saved)/"treated.dat")
        assert equality["exact_rows"] == 818
        with localcontext() as ctx:
            ctx.prec = 50
            assert all(Decimal(row[4]) == Decimal(row[3])*Decimal("1575.45") for row in r["result"]["output_rows"])
        report["isolation"] = access
        report["separate_comparison_exact_rows"] = equality["exact_rows"]
        check("Reference-denied CLI succeeds; separate comparison gives 818/818 exact committed rows; E uses exported D")

        # Stale active settings remain reviewable but block export.
        stale = copy.deepcopy(r["cfg"])
        stale["baseline_review"]["overrides"]["P003"]["u_sha256"] = "stale"
        app.commit_baseline(r,stale)
        assert not r["result"]["exportable"]
        app.export_all()
        assert "Stale active" in report["displayed_errors"][-1]
        ed = open_editor()
        assert "Stale" in ed.notice.get()
        ed.delta.set("1.2345678901234567e-9")
        ed.buttons["Apply"].invoke()
        assert r["result"]["exportable"]
        ed.close()
        assert sha256(raw) == r["obj"].sha256
        assert not errors
        report.update(status="PASS",errors=errors,source_sha256={p:sha256(ROOT/p) for p in ("app.py","baseline.py","baseline_editor.py","pipeline.py","plots.py")})
        check("Stale settings block export and can be explicitly reaccepted; original raw bytes unchanged")
        atomic_json(dest/"gui_baseline_results.json",report)
    if hold:
        ed = open_editor()
        app.status.set("Baseline gates PASS. Review window available for native interaction and screenshots.")
        root.mainloop()
    else:
        app.close()


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",default=str(ROOT/"validation/baseline_v1.1/gui"))
    parser.add_argument("--hold",action="store_true")
    parser.add_argument("--background",action="store_true",help="Keep all Tk windows withdrawn; no desktop input")
    args=parser.parse_args()
    main(args.output,args.hold,args.background)

