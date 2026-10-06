"""Tk desktop workflow; all scientific processing is shared with the CLI."""
from __future__ import annotations
import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import os
from pathlib import Path
import queue
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from io_profiles import APP_VERSION, InputError, read_raw, configure_acquisition, profile_from
from input_fields import temperature_list
from ui_help import HoverHelp, HelpWindow, help_tip
from pipeline import (default_config, select_background, refinalize, support_permission,
                      validate_config)
from baseline import empty_review
from baseline_editor import BaselineEditor, dispose_canvas
from cli import load_entry, run_entry
from storage import save_dat, load_session, save_session, json_text
from plots import make_figure, raw_figure, export_figure, font_status
from output_settings import default_output, save_output_dat, output_paths
from output_controls import OutputControls, MolarSaveDialog
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import field_quality

ROOT = Path(__file__).resolve().parent


def configure_tk():
    for key, subfolder, required in (("TCL_LIBRARY", "tcl8.6", "init.tcl"), ("TK_LIBRARY", "tk8.6", "tk.tcl")):
        candidate = Path(sys.base_prefix) / "tcl" / subfolder
        if not os.environ.get(key) and (candidate / required).is_file():
            os.environ[key] = candidate.as_posix()


configure_tk()


class App:
    def __init__(self, root):
        self.root = root
        root.title(f"Torque Data Postprocessing {APP_VERSION}")
        root.geometry("1220x780")
        root.minsize(1000, 660)
        self.records, self.counter = {}, 0
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="torque")
        self.events = queue.Queue()
        self.busy = self.closed = False
        self.pulse_count = 0
        self.canvas = self.editor = None
        self.last_error = ""
        self.status = tk.StringVar(value="Open a raw DAT file.")
        self.details = tk.StringVar()
        self.field_alert = tk.StringVar()
        self.range_label = tk.StringVar(value="All angles")
        self.view = tk.StringVar(value="Raw")
        self.view_preference = "Corrected"
        self.background = tk.StringVar()
        self.extrapolate = tk.BooleanVar(value=False)
        self.buttons = {}
        self.help_window = None
        self.hover = self.help_for(root)
        self.build_ui()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Control-o>", lambda e: self.add_files())
        root.bind("<Control-s>", lambda e: self.export_all())
        root.bind("<F5>", lambda e: self.process_all())
        self.poll_id = root.after(40, self.poll)

    def help_for(self, window):
        window.hover_help = HoverHelp(window)
        window.bind("<F1>", lambda event: self.show_help(window))
        return window.hover_help

    def show_help(self, parent=None):
        parent = parent or self.root
        self.hover.dismiss()
        if hasattr(parent, "hover_help"):
            parent.hover_help.dismiss()
        if self.help_window and self.help_window.window.winfo_exists():
            self.help_window.close()
        self.help_window = HelpWindow(parent)

    def build_ui(self):
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Treeview", rowheight=26)
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=False)
        self.file_menu = file_menu
        for label, action in [("Open data…", self.add_files), ("Save treated data…", self.export_all),
                              ("Save settings…", self.save_configuration), ("Load settings…", self.load_configuration),
                              ("Remove selected file", self.remove_selected), ("Close", self.close)]:
            file_menu.add_command(label=label, command=action)
        menu.add_cascade(label="File", menu=file_menu)
        tools_menu = tk.Menu(menu, tearoff=False)
        for label, action in [("Acquisition settings…", self.file_settings), ("Export figure…", self.save_plot),
                              ("Export treated plots…", self.export_plots),
                              ("Details…", self.show_details)]:
            tools_menu.add_command(label=label, command=action)
        menu.add_cascade(label="Tools", menu=tools_menu)
        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="User guide", accelerator="F1", command=self.show_help)
        menu.add_cascade(label="Help", menu=help_menu, underline=0)
        self.root.config(menu=menu)
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)
        toolbar = ttk.Frame(outer)
        toolbar.pack(fill="x")
        for label, command in [("Open data…", self.add_files), ("Subtract background", self.process_all),
                               ("Center zero…", self.review_baseline)]:
            button = ttk.Button(toolbar, text=label, command=command)
            button.pack(side="left", padx=(0, 8))
            self.buttons[label] = button
            key = {"Open data…": "open", "Subtract background": "process", "Center zero…": "center_zero",
                   "Save treated data…": "save_dat"}[label]
            self.hover.attach(button, key, text=lambda key=key: ("A task is running; wait for it to finish. " if self.busy else "") + help_tip(key))
        slot = ttk.Frame(toolbar, width=70, height=24)
        slot.pack(side="right")
        slot.pack_propagate(False)
        self.progress = ttk.Progressbar(slot, mode="indeterminate", length=70)
        self.hover.attach(self.progress, "activity")
        self.files = ttk.Treeview(outer, columns=("name", "state"), show="headings", height=2)
        for key, title, width in [("name", "Raw file", 380), ("state", "Status", 700)]:
            self.files.heading(key, text=title)
            self.files.column(key, width=width)
        self.files.pack(fill="x", pady=8)
        self.files.bind("<<TreeviewSelect>>", self.refresh_selected)
        self.hover.attach(self.files, "files")
        settings = ttk.Frame(outer)
        settings.pack(fill="x", pady=(0, 8))
        self.hover.attach(ttk.Button(settings, text="Acquisition settings…", command=self.file_settings), "settings").pack(side="left")
        self.hover.attach(ttk.Button(settings, text="Angle range…", command=self.range_settings), "range").pack(side="left", padx=8)
        ttk.Label(settings, textvariable=self.range_label).pack(side="left")
        alert = ttk.Frame(outer)
        alert.pack(fill="x", pady=(0, 5))
        ttk.Label(alert, textvariable=self.field_alert, wraplength=940, foreground="#963a24").pack(side="left")
        self.hover.attach(ttk.Button(alert, text="Review scan…", command=self.review_field), "field_review").pack(side="right")
        panes = ttk.Panedwindow(outer, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left, right = ttk.Frame(panes), ttk.Frame(panes)
        panes.add(left, weight=4)
        panes.add(right, weight=6)
        scan_area = ttk.Frame(left)
        scan_area.pack(fill="both", expand=True)
        self.passes = ttk.Treeview(scan_area, columns=("T", "B", "n", "role", "quality"), show="tree headings", selectmode="extended")
        self.passes.heading("#0", text="Scan")
        self.passes.column("#0", width=65, stretch=False)
        for key, label, width in [("T", "T (K)", 130), ("B", "B (T)", 110),
                                   ("n", "Points", 55), ("role", "Role", 90), ("quality", "Field review", 130)]:
            self.passes.heading(key, text=label)
            self.passes.column(key, width=width, minwidth=45)
        scroll = ttk.Scrollbar(scan_area, orient="vertical", command=self.passes.yview)
        self.passes.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.passes.pack(fill="both", expand=True)
        self.passes.bind("<<TreeviewSelect>>", self.select_pass)
        self.hover.attach(self.passes, "scans")
        association = ttk.Frame(left, padding=(0, 8))
        association.pack(fill="x")
        ttk.Label(association, text="Background").pack(anchor="w")
        self.background_box = ttk.Combobox(association, textvariable=self.background, state="readonly")
        self.background_box.pack(fill="x", pady=3)
        self.hover.attach(self.background_box, "background")
        self.extrapolation_check = ttk.Checkbutton(association, text="Allow background extrapolation",
                                                 variable=self.extrapolate)
        self.extrapolation_check.pack(anchor="w")
        self.hover.attach(self.extrapolation_check, "extrapolation")
        self.hover.attach(ttk.Button(association, text="Apply background", command=self.apply_background), "apply_background").pack(anchor="e", pady=3)
        details_label = ttk.Label(left, textvariable=self.details, wraplength=420)
        details_label.pack(fill="x", pady=6)
        self.output = OutputControls(self, left)
        self.output.frame.pack_configure(side="bottom", before=scan_area)
        details_label.pack_configure(side="bottom", before=scan_area)
        association.pack_configure(side="bottom", before=scan_area)
        self.buttons["Save treated data…"] = self.output.save_button
        controls = ttk.Frame(right)
        controls.pack(fill="x", padx=10)
        ttk.Label(controls, text="View").pack(side="left")
        self.view_box = ttk.Combobox(controls, textvariable=self.view, state="readonly", width=20, values=("Raw",))
        self.view_box.pack(side="left", padx=6)
        self.view_box.bind("<<ComboboxSelected>>", self.change_view)
        self.hover.attach(self.view_box, "view")
        self.plot_area = ttk.Frame(right, padding=5)
        self.plot_area.pack(fill="both", expand=True)
        self.plot_message = ttk.Label(self.plot_area, text="", anchor="center")
        self.plot_message.pack(fill="both", expand=True)
        ttk.Label(outer, textvariable=self.status, wraplength=1160).pack(fill="x", pady=(8, 0))

    def selected(self):
        ids = self.files.selection()
        return self.records.get(ids[0]) if ids else None

    def selected_pass(self):
        record, ids = self.selected(), self.passes.selection()
        return next((p for p in record["obj"].passes if p.id == ids[0]), None) if record and record.get("obj") and ids else None

    def show_error(self, error):
        self.last_error = str(error)
        self.status.set(str(error))
        messagebox.showerror("Torque Data Postprocessing", str(error), parent=self.root)

    def submit(self, message, job, callback):
        if self.busy or self.closed:
            return
        self.busy = True
        self.status.set(message)
        self.set_activity(True)
        self.refresh_buttons()
        try:
            future = self.executor.submit(job)
        except Exception:
            self.busy = False
            self.set_activity(False)
            self.refresh_buttons()
            raise
        future.add_done_callback(lambda f: self.events.put((f, callback)))

    def set_activity(self, active):
        self.progress.stop()
        self.progress.configure(value=0)
        if active:
            self.progress.pack(fill="x", pady=3)
            self.progress.start(12)
        else:
            self.progress.pack_forget()

    def poll(self):
        self.poll_id = None
        if self.closed:
            return
        self.pulse_count += 1
        try:
            future, callback = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.set_activity(False)
            try:
                callback(future.result())
            except Exception as exc:
                self.show_error(exc)
            self.refresh_buttons()
        self.poll_id = self.root.after(40, self.poll)

    def refresh_buttons(self):
        r = self.selected()
        for button in self.buttons.values():
            button.configure(state="disabled" if self.busy else "normal")
        if not self.busy:
            self.buttons["Save treated data…"].configure(state="normal" if r and r.get("result", {}) and r["result"]["exportable"] else "disabled")
            p = self.selected_pass()
            processed = p and any(v["pass_id"] == p.id for v in ((r or {}).get("result") or {}).get("passes", []))
            self.buttons["Center zero…"].configure(state="normal" if processed else "disabled")
        self.output.refresh()

    def add_record(self, path, obj=None, cfg=None, error="", output=None):
        self.counter += 1
        key = f"F{self.counter}"
        record = {"key": key, "path": str(Path(path).resolve()), "raw": obj, "cfg": cfg, "obj": None,
                  "result": None, "saved": None, "state": error, "error": error}
        record["output"] = output or default_output((cfg or {}).get("input_sha256", ""), path)
        if obj:
            record["obj"] = field_quality.configure(obj, cfg)
            record["state"] = f"{len(obj.rows)} measurements; {len(record['obj'].passes)} scans"
        self.records[key] = record
        self.files.insert("", "end", iid=key)
        self.update_file(record)
        return key

    def update_file(self, record):
        self.files.item(record["key"], values=(Path(record["path"]).name, record["state"]))

    def add_files(self, paths=None):
        if self.busy or not self.guard_baseline(close=True):
            return
        paths = paths or filedialog.askopenfilenames(parent=self.root, title="Open raw data", filetypes=[("DAT", "*.dat")])
        if not paths:
            return
        def job():
            imports = []
            for path in paths:
                try:
                    obj, cfg = load_entry(path)
                    imports.append((path, obj, cfg, ""))
                except (ValueError, OSError) as exc:
                    imports.append((path, None, None, str(exc)))
            return imports
        def done(imports):
            keys = [self.add_record(*item) for item in imports]
            self.files.selection_set(keys[0])
            self.refresh_selected()
            self.status.set("Data loaded. Set experimental temperatures in Acquisition settings.")
        self.submit("Reading data…", job, done)

    def remove_selected(self):
        if self.busy or not self.guard_baseline(close=True):
            return
        for key in self.files.selection():
            self.records.pop(key)
            self.files.delete(key)
        self.refresh_selected()

    def clear_plot(self):
        if self.canvas:
            dispose_canvas(self.canvas)
            self.canvas = None
        self.plot_message.pack(fill="both", expand=True)

    def refresh_selected(self, event=None):
        if self.output.record is not self.selected() and not self.output.require_clean():
            self.files.selection_set(self.output.record["key"])
            return
        if self.editor and self.selected() is not self.editor.record:
            if not self.guard_baseline(close=True):
                self.files.selection_set(self.editor.record["key"])
                return
        old = self.passes.selection()
        self.passes.delete(*self.passes.get_children())
        self.clear_plot()
        r = self.selected()
        self.field_alert.set("")
        self.output.bind_record(r)
        if not r or not r.get("obj"):
            self.update_view()
            self.details.set(r["error"] if r else "")
            self.refresh_buttons()
            return
        limits = r["cfg"]["acquisition"]["angle_range_deg"]
        reviews = r["obj"].field_review
        pending = [pid for pid, v in reviews.items() if v["status"] in field_quality.UNRESOLVED]
        excluded = [pid for pid, v in reviews.items() if v["status"] == "Excluded by decision"]
        self.field_alert.set(("Field review required: " + ", ".join(pending) + ". Select a scan and Review scan; final exports are blocked.")
                             if pending else "Field review resolved." + (" Excluded: " + ", ".join(excluded) if excluded else ""))
        self.range_label.set(f"{limits[0]} to {limits[1]}° — fit, center and export" if limits else "All angles")
        for p in r["obj"].passes:
            self.passes.insert("", "end", iid=p.id, text=p.id, values=(
                str(p.T) if p.T is not None else p.measured_temperature,
                p.field_label, f"{len(p.rows)}/{len(p.acquired_rows)}",
                "Excluded" if p.excluded else "Background" if p.zero else "Signal", reviews[p.id]["status"]))
        selected = [pid for pid in old if self.passes.exists(pid)] or [r["obj"].passes[0].id]
        self.passes.selection_set(selected)
        self.select_pass()
        self.refresh_buttons()

    def select_pass(self, event=None):
        if self.busy:
            return
        r, p = self.selected(), self.selected_pass()
        if not r or not p:
            return
        if self.editor and p.id != self.editor.main_pass_id and not self.guard_baseline(close=True):
            self.passes.selection_set(self.editor.main_pass_id)
            return
        candidates = r["obj"].candidates(p) if not p.zero else []
        labels = [f"{b.id}: {b.T} K; {min(x.angle for x in b.rows):g}–{max(x.angle for x in b.rows):g}°"
                  for b in candidates if b.rows]
        self.background_box.configure(values=labels)
        selected = r["cfg"]["overrides"].get(p.id, {}).get("background")
        if not selected and len(candidates) == 1:
            selected = candidates[0].id
        self.background.set(next((v for v in labels if v.startswith(str(selected) + ":")), ""))
        self.extrapolate.set(any(e.get("signal_id") == p.id for e in r["cfg"]["support_exceptions"]))
        self.extrapolation_check.configure(state="normal" if candidates and not p.zero else "disabled")
        pred = next((x for x in (r.get("result") or {}).get("passes", []) if x["pass_id"] == p.id), None)
        issue = (r.get("result") or {}).get("processing_errors", {}).get(p.id) or p.issue
        text = issue or f"Measured T: {p.measured_temperature} K"
        if pred:
            text += f"\nZero offset: {pred['centering_constant_Nm']:.8g} N m ({pred['centering']})"
            if pred["baseline_review"]["status"] == "stale":
                text += "\nSaved zero adjustment is stale; review or remove it."
        self.details.set(text)
        self.update_view(pred)
        self.refresh_buttons()
        self.clear_plot()
        try:
            if pred and self.view.get() != "Raw":
                if self.view.get() == "Corrected" and self.output.dirty:
                    raise InputError("Apply or cancel sample changes to view corrected output.")
                fig = make_figure(r["result"], p.id, self.view_key(), preview=True, output=r["output"])
            else:
                fig = raw_figure(p, preview=True)
            self.plot_message.pack_forget()
            self.canvas = FigureCanvasTkAgg(fig, master=self.plot_area)
            self.canvas.get_tk_widget().pack(fill="both", expand=True)
            self.canvas.draw_idle()
        except InputError as exc:
            self.plot_message.configure(text=str(exc))

    def change_view(self, event=None):
        if self.view.get() in self.view_box["values"]:
            self.view_preference = self.view.get()
        self.select_pass()

    def update_view(self, prediction=None):
        values = ("Raw",)
        if prediction:
            values = ("Corrected", "Background fit", "Processing steps", "Raw")
            if prediction["baseline_review"]["status"] == "stale":
                values = ("Background fit", "Raw")
        self.view_box.configure(values=values)
        self.view.set(self.view_preference if self.view_preference in values else "Raw")

    def view_key(self):
        return {"Corrected": "centered", "Background fit": "background",
                "Processing steps": "stages", "Raw": "raw"}[self.view.get()]

    def apply_settings(self, record, cfg):
        if not self.guard_baseline(close=True):
            return False
        obj = read_raw(record["path"], cfg["profile"])
        configured = field_quality.configure(obj, cfg)
        record.update(raw=obj, obj=configured, cfg=cfg, result=None, saved=None,
                      state="Settings changed; subtract background again", error="")
        self.update_file(record)
        self.refresh_selected()
        return True

    def file_settings(self):
        r = self.selected()
        if self.busy or not r or not r.get("raw") or not self.guard_baseline(close=True):
            return
        self.settings_dialog = AcquisitionDialog(self, r, list(self.passes.selection()))

    def review_field(self):
        r, p = self.selected(), self.selected_pass()
        if self.busy or not r or not p or not self.guard_baseline(close=True):
            return
        from field_review_dialog import FieldReviewDialog
        self.field_dialog = FieldReviewDialog(self, r, p.id)

    def range_settings(self):
        self.file_settings()
        if hasattr(self, "settings_dialog"):
            self.settings_dialog.entries["range_min"].focus_set()

    def apply_background(self):
        r, p = self.selected(), self.selected_pass()
        if self.busy or not r or not p or p.zero or not self.guard_baseline(close=True):
            return
        try:
            pid = self.background.get().split(":")[0]
            bg = next((b for b in r["obj"].candidates(p) if b.id == pid), None)
            if bg is None or bg.issue or p.issue:
                raise InputError((bg.issue if bg else "") or p.issue or "Select a background at the same experimental temperature.")
            cfg = copy.deepcopy(r["cfg"])
            cfg["overrides"].setdefault(p.id, {}).update(identity=p.identity, background=bg.id, source="Explicit GUI background selection")
            cfg["support_exceptions"] = [e for e in cfg["support_exceptions"] if e.get("signal_id") != p.id]
            if self.extrapolate.get():
                cfg["support_exceptions"].append(support_permission(r["obj"], p, bg, "Explicit GUI extrapolation permission"))
            self.apply_settings(r, cfg)
        except (ValueError, OSError) as exc:
            self.show_error(exc)

    def process_all(self):
        if self.busy or not self.records or not self.guard_baseline(close=True):
            return
        snapshots = [(k, r["path"], copy.deepcopy(r["cfg"])) for k, r in self.records.items()]
        def job():
            results = []
            for key, path, cfg in snapshots:
                try:
                    if cfg is None:
                        raise InputError("Resolve the import error first.")
                    results.append((key, run_entry(path, cfg, allow_stale_review=True, partial=True), ""))
                except Exception as exc:
                    results.append((key, None, str(exc)))
            return results
        def done(results):
            for key, result, error in results:
                r = self.records[key]
                r.update(result=result, error=error, saved=None,
                         state=f"{result['rows']} treated points" + (f"; {len(result['export_blockers'])} unresolved scans" if not result["exportable"] else "") if result else error)
                self.update_file(r)
            self.refresh_selected()
            self.status.set("Background subtraction complete.")
        self.submit("Subtracting background…", job, done)

    def export_all(self, path=None):
        if self.busy or not self.guard_baseline(close=True):
            return
        r = self.selected()
        if not r or not r.get("result"):
            return self.show_error("Subtract the background before saving.")
        if not r["result"]["exportable"]:
            return self.show_error("Resolve the listed scans or explicitly exclude them in Acquisition settings before saving.")
        if path is None and r["output"]["quantity"] == "molar":
            self.output_save_dialog = MolarSaveDialog(self, r)
            return
        path = path or filedialog.asksaveasfilename(parent=self.root, title="Save treated data",
            initialfile=Path(r["path"]).stem + "_treated.dat", defaultextension=".dat", filetypes=[("DAT", "*.dat")])
        if path:
            try:
                paths = output_paths(path, r["output"])
            except InputError as exc:
                return self.show_error(exc)
            def done(saved):
                r["saved"] = saved
                self.status.set("Saved " + " and ".join(str(p) for p in paths))
            result, output = copy.deepcopy(r["result"]), copy.deepcopy(r["output"])
            self.submit("Saving treated data…", lambda: save_output_dat(result, path, output), done)

    def save_configuration(self, path=None):
        if self.busy or not self.guard_baseline(close=True):
            return
        path = path or filedialog.asksaveasfilename(parent=self.root, title="Save settings", defaultextension=".json", filetypes=[("JSON", "*.json")])
        if path:
            try:
                if any(r["cfg"] is None for r in self.records.values()):
                    raise InputError("Resolve failed imports before saving settings.")
                save_session(path, [(r["path"], r["cfg"], r["output"]) for r in self.records.values()])
                self.status.set("Settings saved.")
            except (ValueError, OSError) as exc:
                self.show_error(exc)

    def load_configuration(self, path=None):
        if self.busy or not self.guard_baseline(close=True):
            return
        path = path or filedialog.askopenfilename(parent=self.root, title="Load settings", filetypes=[("JSON", "*.json")])
        if not path:
            return
        def job():
            imports = []
            for raw, cfg, output in load_session(path, include_output=True):
                obj, cfg = load_entry(raw, cfg)
                if cfg["input_sha256"] != obj.sha256:
                    raise InputError("Settings do not match this raw file.")
                imports.append((raw, obj, cfg, "", output))
            return imports
        def done(imports):
            self.records.clear()
            self.files.delete(*self.files.get_children())
            keys = [self.add_record(*item) for item in imports]
            if keys:
                self.files.selection_set(keys[0])
            self.refresh_selected()
            notes = [n for r in self.records.values() for n in r["cfg"].get("migration_notes", [])]
            self.status.set(" ".join(notes) if notes else "Settings loaded. Subtract background to calculate results.")
        self.submit("Loading settings…", job, done)

    def show_details(self):
        r = self.selected()
        if not r:
            return
        win = tk.Toplevel(self.root)
        win.title("Processing details")
        text = tk.Text(win, width=100, height=32, wrap="word")
        text.pack(fill="both", expand=True)
        text.insert("1.0", font_status() + "\n\n" + json_text(r.get("result") or r.get("cfg")))
        text.configure(state="disabled")

    def save_plot(self):
        if self.busy or not self.guard_baseline(close=True):
            return
        r, p = self.selected(), self.selected_pass()
        if not r or not p or not r.get("result"):
            return
        folder = filedialog.askdirectory(parent=self.root, title="Save figure")
        if folder:
            try:
                from pipeline import verify_export
                verify_export(r["result"])
                if self.view.get() == "Raw":
                    raise InputError("Choose Corrected, Background fit or Processing steps for figure export.")
                export_figure(r["result"], p.id, folder, self.view_key(), output=r["output"])
                self.status.set("Figure saved as PDF and PNG.")
            except (ValueError, OSError) as exc:
                self.show_error(exc)

    def export_plots(self):
        if self.busy or not self.guard_baseline(close=True):
            return
        if not any(r.get("result") and r["result"]["exportable"] for r in self.records.values()):
            return self.show_error("Subtract the background and resolve pending scans before exporting treated plots.")
        from plot_export_dialog import PlotExportDialog
        self.plot_dialog = PlotExportDialog(self)

    def guard_baseline(self, close=False):
        if hasattr(self, "output") and not self.output.require_clean():
            return False
        if self.editor:
            if not self.editor.require_clean():
                return False
            if close:
                self.editor.close(force=True)
        return True

    def commit_baseline(self, record, cfg):
        result = refinalize(record["result"], cfg, allow_stale_review=True)
        record.update(cfg=cfg, result=result, saved=None)
        self.refresh_selected()

    def review_baseline(self):
        r, p = self.selected(), self.selected_pass()
        if self.busy or not r or not p or not self.guard_baseline(close=True):
            return
        if not any(v["pass_id"] == p.id for v in (r.get("result") or {}).get("passes", [])):
            return self.show_error("Choose a signal scan with a processed background.")
        # Opening an editor does not activate retained settings or commit a draft.
        self.editor = BaselineEditor(self, r, p.id)

    def close(self):
        if not self.guard_baseline(close=True):
            return
        self.closed = True
        self.set_activity(False)
        self.hover.dismiss()
        if self.poll_id:
            self.root.after_cancel(self.poll_id)
            self.poll_id = None
        self.clear_plot()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


class AcquisitionDialog:
    def __init__(self, app, record, selected):
        self.app, self.record, self.selected = app, record, selected
        self.window = tk.Toplevel(app.root)
        self.window.title("Acquisition settings")
        self.window.transient(app.root)
        self.window.grab_set()
        self.hover = app.help_for(self.window)
        panel = ttk.Frame(self.window, padding=16)
        panel.pack(fill="both", expand=True)
        self.values, self.entries, self.labels = {}, {}, {}
        cfg = record["cfg"]
        def entry(key, label, value, parent=panel):
            frame = ttk.Frame(parent)
            frame.pack(fill="x", pady=3)
            self.labels[key] = ttk.Label(frame, text=label, width=39, wraplength=320)
            self.labels[key].pack(side="left")
            self.values[key] = tk.StringVar(value=str(value))
            self.entries[key] = ttk.Entry(frame, textvariable=self.values[key], width=40)
            self.entries[key].pack(side="right", fill="x", expand=True)
            help_key = "temperature_list" if key == "setpoints" else key
            self.hover.attach(self.labels[key], help_key)
            self.hover.attach(self.entries[key], help_key)
        entry("setpoints", "Temperatures in this file (K)", ", ".join(cfg["acquisition"]["temperature_setpoints_K"]))
        ttk.Label(panel, text="Separate values with spaces or commas").pack(anchor="e")
        entry("temperature_tolerance_K", "Allowed deviation (K)", cfg["profile"]["temperature_tolerance_K"])
        quality = cfg.get("field_quality", field_quality.defaults())
        self.field_condition = tk.StringVar(value="Fixed field" if quality["condition"] == "fixed" else "Changing field permitted")
        ttk.Label(panel, text="Field condition").pack(anchor="w")
        self.hover.attach(ttk.Combobox(panel, textvariable=self.field_condition, state="readonly",
            values=("Fixed field", "Changing field permitted")), "field_condition").pack(anchor="w")
        entry("field_limit", "Review at field change (T)", quality["limit_T"])
        ttk.Label(panel, text="Span rounded to 0.01 T; review at or above the limit. Blank = unconfigured.").pack(anchor="w")
        limits = cfg["acquisition"]["angle_range_deg"]
        ttk.Label(panel, text="Angle range for fit, centering and export (blank = all angles)").pack(anchor="w", pady=(12, 3))
        entry("range_min", "Lower angle (deg)", limits[0] if limits else "")
        entry("range_max", "Upper angle (deg)", limits[1] if limits else "")
        scan_panel = ttk.LabelFrame(panel, text="Selected scans: " + ", ".join(selected), padding=8)
        scan_panel.pack(fill="x", pady=10)
        entry("scan_temperature", "Override selected scan temperature (K)", "", scan_panel)
        entry("scan_field", "Stable field setpoint (T)", "", scan_panel)
        self.role = tk.StringVar(value="Keep current")
        ttk.Label(scan_panel, text="Role").pack(anchor="w")
        self.hover.attach(ttk.Combobox(scan_panel, textvariable=self.role, state="readonly",
                     values=("Keep current", "Signal", "Background"), width=25), "role").pack(anchor="w", pady=3)
        self.include = tk.StringVar(value="Keep current")
        ttk.Label(scan_panel, text="Processing").pack(anchor="w")
        self.hover.attach(ttk.Combobox(scan_panel, textvariable=self.include, state="readonly",
                     values=("Keep current", "Include", "Exclude"), width=25), "include").pack(anchor="w", pady=3)
        advanced = ttk.Frame(panel)
        self.advanced_visible = False
        def show_advanced():
            self.advanced_visible = not self.advanced_visible
            advanced.pack(fill="x", before=footer) if self.advanced_visible else advanced.pack_forget()
        self.hover.attach(ttk.Button(panel, text="More acquisition settings", command=show_advanced), "more_settings").pack(anchor="w")
        for key, label in [("angle_step_deg", "Angle step (deg)"), ("angle_origin_deg", "Angle grid origin (deg)"),
                           ("angle_tolerance_deg", "Allowed angle deviation (deg)"), ("field_step_T", "Field grid step (T)"),
                           ("stable_field_tolerance_Oe", "Allowed field deviation (Oe)"),
                           ("background_threshold_Oe", "Near-zero field limit (Oe)")]:
            entry(key, label, cfg["profile"][key], advanced)
        entry("scan_starts", "Scan starts (source row numbers)", ", ".join(map(str, cfg["acquisition"]["scan_starts"] or [])), advanced)
        self.center = tk.StringVar(value=cfg["centering"])
        ttk.Label(advanced, text="Automatic centering").pack(anchor="w")
        self.hover.attach(ttk.Combobox(advanced, textvariable=self.center, values=("midrange", "mean"), state="readonly"), "ordinary_centering").pack(anchor="w")
        footer = ttk.Frame(panel)
        footer.pack(fill="x", pady=(12, 0))
        self.hover.attach(ttk.Button(footer, text="Apply", command=self.apply), "settings_apply").pack(side="right")
        self.hover.attach(ttk.Button(footer, text="Cancel", command=self.window.destroy), "settings_cancel").pack(side="right", padx=6)
        self.error = tk.StringVar()
        ttk.Label(panel, textvariable=self.error, wraplength=540, foreground="#963a24").pack(fill="x")

    def apply(self):
        try:
            cfg = copy.deepcopy(self.record["cfg"])
            quality = cfg.setdefault("field_quality", field_quality.defaults())
            condition = "fixed" if self.field_condition.get() == "Fixed field" else "changing"
            limit = self.values["field_limit"].get().strip()
            if (condition, limit) != (quality["condition"], quality["limit_T"]):
                quality.update(condition=condition, limit_T=limit, source="Explicit GUI field-condition setting")
            field_quality.validate(quality)
            for key in cfg["profile"]:
                if key in self.values:
                    cfg["profile"][key] = self.values[key].get().strip()
            cfg["profile"] = asdict(profile_from(cfg["profile"]))
            values = self.values["setpoints"].get().strip()
            cfg["acquisition"]["temperature_setpoints_K"] = temperature_list(values)
            cfg["acquisition"]["source"] = "Explicit GUI experimental setpoints"
            lo, hi = self.values["range_min"].get().strip(), self.values["range_max"].get().strip()
            cfg["acquisition"]["angle_range_deg"] = [lo, hi] if lo or hi else None
            starts = self.values["scan_starts"].get().strip()
            cfg["acquisition"]["scan_starts"] = [int(v.strip()) for v in starts.split(",")] if starts else None
            cfg.update(centering=self.center.get(), centering_source="Explicit GUI acquisition setting")
            for pid in self.selected:
                scan = next(s for s in self.record["obj"].passes if s.id == pid)
                updates = {}
                if self.values["scan_temperature"].get().strip():
                    updates["temperature_K"] = self.values["scan_temperature"].get().strip()
                if self.values["scan_field"].get().strip():
                    updates["field_T"] = self.values["scan_field"].get().strip()
                if self.role.get() != "Keep current":
                    updates["role"] = self.role.get().lower()
                if self.include.get() != "Keep current":
                    updates["exclude"] = self.include.get() == "Exclude"
                    if self.include.get() == "Include":
                        quality["decisions"].pop(pid, None)
                if updates:
                    cfg["acquisition"]["scans"].setdefault(pid, {}).update(
                        identity=scan.identity, source="Explicit GUI scan setting", **updates)
                if self.include.get() == "Exclude":
                    cfg = field_quality.decide(self.record["raw"], cfg, pid, "exclude", "Explicit GUI acquisition setting: exclude entire scan")
            if self.app.apply_settings(self.record, cfg):
                self.window.destroy()
        except (ValueError, OSError) as exc:
            self.error.set(str(exc))


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"Torque Data Postprocessing {APP_VERSION}")
    parser.add_argument("--session")
    args = parser.parse_args()
    root = tk.Tk()
    app = App(root)
    if args.session:
        root.after(0, lambda: app.load_configuration(args.session))
    root.mainloop()


if __name__ == "__main__":
    main()
