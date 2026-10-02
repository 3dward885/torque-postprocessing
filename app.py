"""Small Tk/ttk desktop application. Scientific calculations live in pipeline.py."""
from __future__ import annotations
import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
import os
from pathlib import Path
import queue
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from io_profiles import InputError, PROFILES, read_raw, profile_from, sha256
from pipeline import default_config, molar_settings, select_background, validate_config
from cli import run_entry
from presets import PRESET_LABELS, apply_preset
from storage import atomic_json, export_run, load_config, load_session, save_session, json_text
from plots import make_figure, export_figure, font_status
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from validate import compare, read_treated

ROOT = Path(__file__).resolve().parent


def configure_tk():
    """Find Tcl/Tk scripts in Python distributions whose default lookup omits tcl/."""
    for key, subfolder, required in (("TCL_LIBRARY", "tcl8.6", "init.tcl"), ("TK_LIBRARY", "tk8.6", "tk.tcl")):
        candidate = Path(sys.base_prefix) / "tcl" / subfolder
        if not os.environ.get(key) and (candidate / required).is_file():
            os.environ[key] = candidate.as_posix()


configure_tk()


class App:
    def __init__(self, root):
        self.root = root
        root.title("Torque Postprocessing 1.0")
        root.geometry("1240x750")
        root.minsize(1000, 680)
        self.records = {}
        self.counter = 0
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="torque")
        self.events = queue.Queue()
        self.busy = False
        self.closed = False
        self.pulse_count = 0
        self.canvas = None
        self.last_error = ""
        self.output = tk.StringVar(value=str(ROOT / "runs"))
        self.status = tk.StringVar(value="Add raw files. Each new input starts with Midrange and Torque only.")
        self.case = tk.StringVar(value="Select an input to inspect its angular passes.")
        self.details = tk.StringVar(value="")
        self.view = tk.StringVar(value="stages")
        self.buttons = {}
        self.build_ui()
        self.refresh_buttons()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Control-o>", lambda e: self.add_files())
        root.bind("<Control-s>", lambda e: self.save_configuration())
        root.bind("<Control-l>", lambda e: self.load_configuration())
        root.bind("<F5>", lambda e: self.process_all())
        root.after(40, self.poll)

    def build_ui(self):
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Treeview", rowheight=25)
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)
        toolbar = ttk.Frame(outer)
        toolbar.pack(fill="x")
        for text, command in [
            ("Add raw files...", self.add_files), ("Remove selected", self.remove_selected),
            ("File settings...", self.file_settings), ("Save configuration...", self.save_configuration),
            ("Load configuration...", self.load_configuration),
        ]:
            self.buttons[text] = ttk.Button(toolbar, text=text, command=command)
            self.buttons[text].pack(side="left", padx=(0, 6))
        self.files = ttk.Treeview(outer, columns=("name", "schema", "profile", "center", "molar", "state"),
                                  show="headings", height=3, selectmode="extended")
        for key, label, width in [
            ("name", "Raw file", 230), ("schema", "Detected schema", 190), ("profile", "Profile", 90),
            ("center", "Centering", 90), ("molar", "Molar output", 165), ("state", "Import / result", 280),
        ]:
            self.files.heading(key, text=label)
            self.files.column(key, width=width, minwidth=65)
        self.files.pack(fill="x", pady=(8, 6))
        self.files.bind("<<TreeviewSelect>>", self.refresh_selected)
        self.files.bind("<Double-1>", lambda e: self.file_settings())
        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(0, 8))
        ttk.Label(actions, text="Output folder").pack(side="left")
        ttk.Entry(actions, textvariable=self.output).pack(side="left", fill="x", expand=True, padx=6)
        self.buttons["Browse..."] = ttk.Button(actions, text="Browse...", command=self.choose_output)
        self.buttons["Browse..."].pack(side="left", padx=4)
        for text, command in [("Process all", self.process_all), ("Export ready", self.export_all)]:
            self.buttons[text] = ttk.Button(actions, text=text, command=command)
            self.buttons[text].pack(side="left", padx=4)
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=80)
        self.progress.pack(side="left", padx=4)
        ttk.Label(outer, textvariable=self.case, wraplength=1190).pack(fill="x", pady=(0, 6))
        panes = ttk.Panedwindow(outer, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = ttk.Frame(panes)
        right = ttk.Frame(panes)
        panes.add(left, weight=4)
        panes.add(right, weight=6)
        ttk.Label(left, text="Angular passes", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tree_area = ttk.Frame(left)
        tree_area.pack(fill="both", expand=True, pady=4)
        self.passes = ttk.Treeview(tree_area, columns=("T", "B", "n", "role", "center"), show="tree headings", selectmode="browse")
        self.passes.heading("#0", text="Pass")
        self.passes.column("#0", width=62, minwidth=55, stretch=False)
        for key, label, width in [("T", "T (K)", 58), ("B", "B (T)", 110), ("n", "Rows", 45),
                                   ("role", "Role", 80), ("center", "Centering", 90)]:
            self.passes.heading(key, text=label)
            self.passes.column(key, width=width, minwidth=40)
        self.passes.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(tree_area, orient="vertical", command=self.passes.yview)
        scroll.pack(side="right", fill="y")
        self.passes.configure(yscrollcommand=scroll.set)
        self.passes.bind("<<TreeviewSelect>>", self.select_pass)
        self.passes.bind("<Double-1>", lambda e: self.pass_settings())
        self.buttons["Pass settings / Background..."] = ttk.Button(left, text="Pass settings / Background...", command=self.pass_settings)
        self.buttons["Pass settings / Background..."].pack(fill="x", pady=3)
        ttk.Label(left, textvariable=self.details, wraplength=420, justify="left").pack(fill="x", pady=6)
        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill="both", expand=True, padx=(8, 0))
        preview = ttk.Frame(self.tabs)
        advanced = ttk.Frame(self.tabs)
        validation = ttk.Frame(self.tabs)
        self.tabs.add(preview, text="Preview")
        self.tabs.add(advanced, text="Provenance")
        self.tabs.add(validation, text="Validation")
        choices = ttk.Frame(preview)
        choices.pack(fill="x", padx=4, pady=4)
        ttk.Label(choices, text="View").pack(side="left")
        combo = ttk.Combobox(choices, textvariable=self.view, state="readonly", width=16,
                             values=("stages", "background", "centered", "comparison", "residual"))
        combo.pack(side="left", padx=6)
        combo.bind("<<ComboboxSelected>>", self.select_pass)
        ttk.Button(choices, text="Export PDF + PNG...", command=self.save_plot).pack(side="left", padx=4)
        self.plot_area = ttk.Frame(preview)
        self.plot_area.pack(fill="both", expand=True)
        self.plot_message = ttk.Label(self.plot_area, text="Process the selected input to preview its results.", anchor="center")
        self.plot_message.pack(fill="both", expand=True)
        ttk.Label(preview, text=font_status(), wraplength=650).pack(fill="x", padx=4)
        self.advanced = tk.Text(advanced, wrap="word", font=("Consolas", 10), state="disabled")
        self.advanced.pack(fill="both", expand=True)
        ttk.Button(validation, text="Compare saved output with reference...", command=self.validate_saved).pack(anchor="w", padx=8, pady=8)
        ttk.Label(validation, text="Available after export. Comparison cannot change processing settings or output.", wraplength=600).pack(fill="x", padx=8)
        self.validation_text = tk.Text(validation, height=12, wrap="word", font=("Consolas", 10), state="disabled")
        self.validation_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.status_label = ttk.Label(outer, textvariable=self.status, wraplength=1190, foreground="#203e58")
        self.status_label.pack(side="bottom", fill="x", pady=(7, 0), before=panes)

    def selected(self):
        ids = self.files.selection()
        return self.records.get(ids[0]) if ids else None

    def selected_pass(self):
        record = self.selected()
        ids = self.passes.selection()
        if record and record.get("obj") and ids:
            return next((p for p in record["obj"].passes if p.id == ids[0]), None)
        return None

    def set_text(self, widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def show_error(self, error):
        self.last_error = str(error)
        self.status.set(str(error))
        messagebox.showerror("Torque Postprocessing", str(error), parent=self.root)

    def submit(self, message, job, callback):
        if self.busy:
            return
        self.busy = True
        self.status.set(message)
        self.progress.start(12)
        for button in self.buttons.values():
            button.configure(state="disabled")
        future = self.executor.submit(job)
        future.add_done_callback(lambda f: self.events.put((f, callback)))

    def poll(self):
        if self.closed:
            return
        self.pulse_count += 1
        try:
            future, callback = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.progress.stop()
            for button in self.buttons.values():
                button.configure(state="normal")
            try:
                callback(future.result())
            except Exception as exc:
                self.show_error(exc)
            self.refresh_buttons()
        self.root.after(40, self.poll)

    def refresh_buttons(self):
        if not self.busy:
            self.buttons["Export ready"].configure(state="normal" if any(r.get("result") for r in self.records.values()) else "disabled")

    def add_record(self, path, obj=None, cfg=None, error=""):
        self.counter += 1
        key = f"F{self.counter}"
        record = {"key": key, "path": str(Path(path).resolve()), "obj": obj, "cfg": cfg,
                  "result": None, "saved": None, "reference": None, "validation": None,
                  "state": error or "Ready to process", "error": error}
        self.records[key] = record
        self.files.insert("", "end", iid=key)
        self.update_file(record)
        return key

    def update_file(self, record):
        obj, cfg = record.get("obj"), record.get("cfg")
        molar = (cfg or {}).get("molar", {"mode": "torque"})
        label = {"torque": "Torque only", "multiplier": f"k = {molar.get('factor', '')}",
                 "amount": f"n = {molar.get('amount_mol', '')} mol",
                 "mass": f"{molar.get('mass', '')} {molar.get('mass_unit', '')}"}.get(molar["mode"], molar["mode"])
        self.files.item(record["key"], values=(Path(record["path"]).name, obj.schema if obj else "Import failed",
                        obj.profile.name if obj else "unresolved", (cfg or {}).get("centering", "midrange"), label, record["state"]))

    def add_files(self, paths=None):
        if self.busy:
            return
        paths = paths or filedialog.askopenfilenames(parent=self.root, title="Add raw DAT files",
                                                     filetypes=[("DAT text", "*.dat"), ("All files", "*.*")])
        if not paths:
            return
        def job():
            imports = []
            for path in paths:
                try:
                    obj = read_raw(path, "fractional")
                    imports.append((path, obj, default_config(obj), ""))
                except (ValueError, OSError) as exc:
                    imports.append((path, None, None, str(exc)))
            return imports
        def done(imports):
            keys = [self.add_record(*item) for item in imports]
            self.files.selection_set(keys[0])
            self.refresh_selected()
            self.status.set(f"Imported {sum(not i[3] for i in imports)}/{len(imports)} files. New inputs have independent torque-only settings.")
        self.submit("Reading raw files...", job, done)

    def remove_selected(self):
        if self.busy:
            return
        for key in self.files.selection():
            del self.records[key]
            self.files.delete(key)
        self.refresh_selected()

    def choose_output(self):
        path = filedialog.askdirectory(parent=self.root, title="Output parent folder")
        if path:
            self.output.set(path)

    def clear_plot(self, text="Process this input to preview current results."):
        if self.canvas:
            self.canvas.get_tk_widget().destroy()
            self.canvas = None
        self.plot_message.configure(text=text)
        self.plot_message.pack(fill="both", expand=True)

    def invalidate(self, record):
        record.update(result=None, saved=None, reference=None, validation=None, state="Settings changed: process again", error="")
        self.update_file(record)
        if record is self.selected():
            self.clear_plot()
            self.set_text(self.validation_text, "")
        self.refresh_buttons()

    def refresh_selected(self, event=None):
        old_pass = self.passes.selection()
        self.passes.delete(*self.passes.get_children())
        self.clear_plot()
        record = self.selected()
        if not record:
            self.case.set("Select an input to inspect its angular passes.")
            self.details.set("")
            self.set_text(self.advanced, "")
            self.set_text(self.validation_text, "")
            self.refresh_buttons()
            return
        obj = record.get("obj")
        if not obj:
            self.case.set(record["state"])
            self.details.set("Open File settings to select an explicit compatible profile.")
            self.set_text(self.advanced, record["error"])
            return
        cfg = record["cfg"]
        self.case.set(f"{Path(record['path']).name}  |  {obj.schema}  |  Input: K, Oe, deg, N m  |  Profile: {obj.profile.name}  |  {len(obj.rows)} observed rows")
        for p in obj.passes:
            override = cfg.get("overrides", {}).get(p.id, {})
            mode = "" if p.zero else override.get("centering", cfg["centering"]) + (" *" if "centering" in override else "")
            self.passes.insert("", "end", iid=p.id, text=p.id, values=(str(p.T), p.field_label, len(p.rows), "background" if p.zero else "signal", mode))
        selected_id = old_pass[0] if old_pass and self.passes.exists(old_pass[0]) else obj.passes[0].id
        self.passes.selection_set(selected_id)
        self.passes.see(selected_id)
        advanced = {"input_sha256": obj.sha256, "detected_columns": obj.header, "units": obj.units,
                    "settings": cfg, "error": record["error"]}
        if record.get("result"):
            advanced["recipe"] = record["result"]["recipe"]
            advanced["fits"] = record["result"]["fits"]
        self.set_text(self.advanced, json_text(advanced))
        met = record.get("validation")
        self.set_text(self.validation_text, self.validation_summary(met) if met else "No current saved-output comparison.")
        self.select_pass()
        self.refresh_buttons()

    def select_pass(self, event=None):
        if self.busy:
            return
        record, p = self.selected(), self.selected_pass()
        if not record or not p:
            return
        text = f"Acquisition {p.order}; physical lines {p.rows[0].line}-{p.rows[-1].line}.\nMissing angles: {p.missing or 'none'}."
        if p.trajectory:
            text += "\nChanging field: one pass; row-specific B retained."
        if not p.zero:
            try:
                bg = select_background(record["obj"], p, record["cfg"])
                order = "before" if bg.rows[-1].line < p.rows[0].line else "after"
                text += f"\nBackground: {bg.id}, {order}; lines {bg.rows[0].line}-{bg.rows[-1].line}; {len(bg.rows)} samples."
            except InputError as exc:
                text += "\n" + str(exc)
            if record.get("result"):
                pred = next(x for x in record["result"]["passes"] if x["pass_id"] == p.id)
                text += f"\n{pred['centering'].capitalize()} constant: {pred['centering_constant_Nm']:.9g} N m."
        self.details.set(text)
        self.clear_plot()
        if p.zero:
            self.plot_message.configure(text="Background pass selected. Choose a signal pass and Background view to inspect its selected fit.")
        elif record.get("result"):
            try:
                fig = make_figure(record["result"], p.id, self.view.get(), record.get("reference"), preview=True)
                self.plot_message.pack_forget()
                self.canvas = FigureCanvasTkAgg(fig, master=self.plot_area)
                self.canvas.get_tk_widget().pack(fill="both", expand=True)
                self.canvas.draw_idle()
            except InputError as exc:
                self.plot_message.configure(text=str(exc))

    def process_all(self):
        if self.busy or not self.records:
            return
        snapshots = [(key, r["path"], copy.deepcopy(r["cfg"])) for key, r in self.records.items()]
        for r in self.records.values():
            self.invalidate(r)
            r["state"] = "Processing..."
            self.update_file(r)
        def job():
            results = []
            for key, path, cfg in snapshots:
                try:
                    if cfg is None:
                        raise InputError("Resolve the import error in File settings first.")
                    results.append((key, run_entry(path, cfg), ""))
                except Exception as exc:
                    results.append((key, None, str(exc)))
            return results
        def done(results):
            for key, result, error in results:
                r = self.records[key]
                r.update(result=result, error=error, state=f"Processed {result['rows']} rows" if result else "FAILED: " + error)
                self.update_file(r)
            self.refresh_selected()
            self.status.set(f"Processing complete: {sum(v is not None for _, v, _ in results)} succeeded; {sum(bool(e) for _, _, e in results)} failed. Select a file for details.")
        self.submit("Processing all inputs with one worker...", job, done)

    def export_all(self):
        if self.busy:
            return
        ready = [(key, r["result"]) for key, r in self.records.items() if r.get("result")]
        if not ready:
            self.show_error("Process current settings before export.")
            return
        output = self.output.get()
        if not output.strip():
            self.show_error("Choose an output folder.")
            return
        def job():
            exports = []
            for key, result in ready:
                try:
                    exports.append((key, export_run(result, output), ""))
                except Exception as exc:
                    exports.append((key, None, str(exc)))
            return exports
        def done(exports):
            for key, folder, error in exports:
                r = self.records[key]
                r.update(saved=folder, error=error, state="Exported " + Path(folder).name if folder else "EXPORT FAILED: " + error)
                self.update_file(r)
            failed_inputs = [{"input": r["path"], "status": "failed", "error": r["error"]}
                             for r in self.records.values() if not r.get("result")]
            report = {"exports": [{"input": self.records[k]["path"], "run": f, "error": e} for k, f, e in exports],
                      "not_exported": failed_inputs}
            import uuid
            atomic_json(Path(output) / f"batch_{uuid.uuid4().hex[:8]}.json", report)
            self.status.set(f"Exported {sum(bool(f) for _, f, _ in exports)} runs to {output}. {len(failed_inputs)} inputs unavailable; batch report saved.")
        self.submit("Writing complete run directories and verifying raw hashes...", job, done)

    def save_configuration(self, path=None):
        if self.busy or not self.records:
            return
        path = path or filedialog.asksaveasfilename(parent=self.root, title="Save session configuration", defaultextension=".json", filetypes=[("JSON", "*.json")])
        if path:
            try:
                if any(r["cfg"] is None for r in self.records.values()):
                    raise InputError("Resolve failed imports before saving their settings.")
                if Path(path).resolve() in [Path(r["path"]) for r in self.records.values()]:
                    raise InputError("Configuration cannot overwrite a raw input.")
                save_session(path, [(r["path"], r["cfg"]) for r in self.records.values()])
                self.status.set("Configuration saved: " + str(path))
            except (ValueError, OSError) as exc:
                self.show_error(exc)

    def load_configuration(self, path=None):
        if self.busy:
            return
        path = path or filedialog.askopenfilename(parent=self.root, title="Load session configuration", filetypes=[("JSON", "*.json")])
        if not path:
            return
        def job():
            imported = []
            for raw, cfg in load_session(path):
                obj = read_raw(raw, cfg["profile"])
                validate_config(obj, cfg)
                imported.append((raw, obj, cfg, ""))
            return imported
        def done(imported):
            self.records.clear()
            self.files.delete(*self.files.get_children())
            keys = [self.add_record(*item) for item in imported]
            if keys:
                self.files.selection_set(keys[0])
            self.refresh_selected()
            self.status.set("Loaded saved configuration. Process to calculate current results.")
        self.submit("Checking saved fingerprints and pass identities...", job, done)

    def validation_summary(self, met):
        if not met:
            return ""
        lines = [f"Exact rows: {met['exact_rows']} / {met['rows']}",
                 f"Exact passes: {met['exact_passes']} / {met['pass_count']}",
                 "Exact cells: " + ", ".join(f"{c}: {n}/{met['rows']}" for c, n in met["exact_cells"].items()),
                 f"Headers match: {met['header_equal']}; file bytes identical: {met['byte_identical']}", ""]
        for column, unit in (("D", "N m"), ("E", "N m/mol")):
            if column in met:
                metrics = met[column]
                lines.extend([f"{column} residual (saved output - reference), {unit}",
                              f"  Maximum absolute error: {metrics['max_abs']:.9g}",
                              f"  RMSE: {metrics['RMSE']:.9g}",
                              f"  Mean residual: {metrics['mean_residual']:.9g}",
                              f"  Largest error / own pass range: {metrics['max_error_over_own_pass_range']}", ""])
        lines.append("Pass       Exact rows")
        lines.extend(f"{p['id']:10s} {p['exact_rows']} / {p['rows']}" for p in met["passes"])
        return "\n".join(lines)

    def validate_saved(self, reference=None):
        record = self.selected()
        if self.busy:
            return
        if not record or not record.get("saved") or not record.get("result"):
            self.show_error("Export the current processed result before loading a treated reference.")
            return
        reference = reference or filedialog.askopenfilename(parent=self.root, title="Select treated reference", filetypes=[("DAT", "*.dat")])
        if not reference:
            return
        saved = record["saved"]
        def job():
            met = compare(Path(saved) / "treated.dat", reference)
            rows, _ = read_treated(reference)
            return met, rows
        def done(value):
            record["validation"], record["reference"] = value
            self.refresh_selected()
            self.tabs.select(2)
            met = value[0]
            self.status.set(f"Exact saved-output comparison: {met['exact_rows']}/{met['rows']} rows, {met['exact_passes']}/{met['pass_count']} passes. Residual view is available in Preview.")
        self.submit("Comparing saved values without changing processing...", job, done)

    def save_plot(self):
        record, p = self.selected(), self.selected_pass()
        if self.busy:
            return
        if not record or not record.get("result") or not p or p.zero:
            self.show_error("Select a processed signal pass.")
            return
        folder = filedialog.askdirectory(parent=self.root, title="Choose plot folder (existing filenames are protected)")
        if folder:
            view = self.view.get()
            def done(paths):
                self.status.set("Saved " + " and ".join(Path(x).name for x in paths))
            self.submit("Exporting scientific PDF and PNG...",
                        lambda: export_figure(record["result"], p.id, folder, view, record.get("reference")), done)

    def file_settings(self):
        record = self.selected()
        if self.busy or not record:
            return
        original = copy.deepcopy(record.get("cfg"))
        dialog = tk.Toplevel(self.root)
        dialog.title("Settings for " + Path(record["path"]).name)
        dialog.transient(self.root)
        dialog.grab_set()
        panel = ttk.Frame(dialog, padding=14)
        panel.pack(fill="both", expand=True)
        panel.columnconfigure(1, weight=1)
        cfg = original or {"profile": asdict(PROFILES["fractional"]), "centering": "midrange",
                           "molar": {"mode": "torque"}, "export_format": "canonical", "overrides": {},
                           "support_exceptions": [], "input_sha256": sha256(record["path"])}
        profile_doc = copy.deepcopy(cfg["profile"])
        profile_name = tk.StringVar(value=profile_doc["name"])
        center = tk.StringVar(value=cfg["centering"])
        format_name = tk.StringVar(value=cfg["export_format"])
        molar = cfg["molar"]
        values = {key: tk.StringVar(value=molar.get(key) or default) for key, default in [
            ("mode", "torque"), ("factor", ""), ("amount_mol", ""), ("mass", ""),
            ("mass_unit", "mg"), ("molar_mass_g_mol", ""), ("source", "")]}
        clear_overrides = tk.BooleanVar(value=False)
        chosen_preset = tk.StringVar(value="")
        preset_used = [None]

        def add_row(number, label, variable, options=None):
            ttk.Label(panel, text=label).grid(row=number, column=0, sticky="w", padx=(0, 12), pady=5)
            widget = ttk.Combobox(panel, textvariable=variable, values=options, state="readonly") if options else ttk.Entry(panel, textvariable=variable, width=48)
            widget.grid(row=number, column=1, sticky="ew", pady=5)
            return widget

        profile_combo = add_row(0, "Profile", profile_name, tuple(dict.fromkeys([*PROFILES, profile_doc["name"]])))
        def load_profile():
            nonlocal profile_doc
            path = filedialog.askopenfilename(parent=dialog, title="Load explicit profile", filetypes=[("JSON", "*.json")])
            if path:
                try:
                    profile_doc = asdict(profile_from(load_config(path)))
                    profile_combo.configure(values=tuple(dict.fromkeys([*PROFILES, profile_doc["name"]])))
                    profile_name.set(profile_doc["name"])
                except (ValueError, OSError) as exc:
                    messagebox.showerror("Profile", str(exc), parent=dialog)
        ttk.Button(panel, text="Load explicit profile JSON...", command=load_profile).grid(row=1, column=1, sticky="w")
        add_row(2, "Centering (file default)", center, ("midrange", "mean"))
        add_row(3, "Export formatting", format_name, ("canonical", "previous", "new_rot1", "new_rot2"))
        add_row(4, "Molar output", values["mode"], ("torque", "multiplier", "amount", "mass"))
        ttk.Label(panel, text="torque = A-D only; multiplier = documented k; amount/mass = sample metadata",
                  wraplength=570).grid(row=5, column=0, columnspan=2, sticky="w", pady=4)
        add_row(6, "Multiplier k (mol^-1)", values["factor"])
        add_row(7, "Amount n (mol)", values["amount_mol"])
        add_row(8, "Sample mass", values["mass"])
        add_row(9, "Mass unit", values["mass_unit"], ("mg", "g"))
        add_row(10, "Molar mass (g/mol)", values["molar_mass_g_mol"])
        add_row(11, "Metadata source / note", values["source"])
        calculation = tk.StringVar()
        ttk.Label(panel, textvariable=calculation, wraplength=570).grid(row=12, column=0, columnspan=2, sticky="w", pady=5)
        def update_amount(*unused):
            try:
                meta = molar_settings({k: v.get() for k, v in values.items()})
                calculation.set("Torque only: no molar factor." if meta["factor_mol_inverse"] is None else
                                f"k = {meta['factor_mol_inverse']} mol^-1\nAmount = {meta.get('amount_mol_calculated') or 'not established by documented multiplier'}")
            except InputError as exc:
                calculation.set(str(exc))
        for variable in values.values():
            variable.trace_add("write", update_amount)
        update_amount()
        add_row(13, "Reference preset (explicit)", chosen_preset, tuple(PRESET_LABELS))
        def set_preset():
            nonlocal cfg, profile_doc
            try:
                name = chosen_preset.get()
                cfg = apply_preset(cfg, name)
                profile_doc = copy.deepcopy(cfg["profile"])
                profile_name.set(profile_doc["name"])
                format_name.set(cfg["export_format"])
                for key in values:
                    values[key].set(cfg["molar"].get(key, "mg" if key == "mass_unit" else ""))
                preset_used[0] = name
            except InputError as exc:
                messagebox.showerror("Reference preset", str(exc), parent=dialog)
        ttk.Button(panel, text="Fill documented preset", command=set_preset).grid(row=14, column=1, sticky="w")
        ttk.Label(panel, text="Reference multipliers: 911.63 / 1575.45 mol^-1; physical basis unverified.", wraplength=570).grid(row=15, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Checkbutton(panel, text="Clear this file's deliberate per-pass overrides", variable=clear_overrides).grid(row=16, column=0, columnspan=2, sticky="w", pady=5)

        def apply():
            try:
                selected_profile = profile_doc if profile_name.get() == profile_doc["name"] else asdict(PROFILES[profile_name.get()])
                obj = read_raw(record["path"], selected_profile)
                new = copy.deepcopy(cfg) if original else default_config(obj)
                new.update(profile=asdict(obj.profile), centering=center.get(), centering_source="Explicit GUI file setting",
                           export_format=format_name.get(), molar={k: v.get() for k, v in values.items()})
                if preset_used[0]:
                    new["support_exceptions"] = cfg["support_exceptions"]
                    new["note"] = cfg["note"]
                if clear_overrides.get():
                    new["overrides"] = {}
                validate_config(obj, new)
                record.update(obj=obj, cfg=new)
                self.invalidate(record)
                dialog.destroy()
                self.refresh_selected()
                self.status.set("File settings applied. Previous results were invalidated; process again.")
            except (ValueError, OSError) as exc:
                messagebox.showerror("File settings", str(exc), parent=dialog)
        footer = ttk.Frame(panel)
        footer.grid(row=17, column=0, columnspan=2, sticky="e", pady=8)
        ttk.Button(footer, text="Apply settings", command=apply).pack(side="left", padx=5)
        ttk.Button(footer, text="Cancel", command=dialog.destroy).pack(side="left")

    def pass_settings(self):
        record, selected = self.selected(), self.selected_pass()
        if self.busy or not record or not selected:
            return
        if selected.zero:
            self.show_error("Select a signal pass to choose its centering and background.")
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Pass settings: " + selected.id)
        dialog.transient(self.root)
        dialog.grab_set()
        panel = ttk.Frame(dialog, padding=16)
        panel.pack(fill="both", expand=True)
        old = record["cfg"].get("overrides", {}).get(selected.id, {})
        mode = tk.StringVar(value=old.get("centering", "File default"))
        background = tk.StringVar(value=old.get("background", "Automatic (unique only)"))
        source = tk.StringVar(value=old.get("source", "Explicit GUI per-pass selection"))
        ttk.Label(panel, text=f"{selected.id}: {selected.T} K; {selected.field_label} T; {len(selected.rows)} observed rows").pack(anchor="w", pady=4)
        ttk.Label(panel, text="Centering").pack(anchor="w")
        ttk.Combobox(panel, textvariable=mode, state="readonly", values=("File default", "midrange", "mean"), width=42).pack(fill="x", pady=4)
        candidates = record["obj"].candidates(selected)
        ttk.Label(panel, text="Background: same input and nominal temperature only").pack(anchor="w", pady=4)
        ttk.Combobox(panel, textvariable=background, state="readonly", values=["Automatic (unique only)"] + [p.id for p in candidates], width=42).pack(fill="x")
        for p in candidates:
            order = "before" if p.rows[-1].line < selected.rows[0].line else "after"
            ttk.Label(panel, text=f"{p.id}: {len(p.rows)} samples, lines {p.rows[0].line}-{p.rows[-1].line}, {order}").pack(anchor="w")
        ttk.Label(panel, text="Selection source / note").pack(anchor="w", pady=(12, 2))
        ttk.Entry(panel, textvariable=source, width=65).pack(fill="x")
        def apply():
            new = copy.deepcopy(record["cfg"])
            override = {"identity": selected.identity, "source": source.get()}
            if mode.get() != "File default":
                override["centering"] = mode.get()
            if background.get() != "Automatic (unique only)":
                override["background"] = background.get()
            if len(override) == 2:
                new["overrides"].pop(selected.id, None)
            else:
                new["overrides"][selected.id] = override
            try:
                validate_config(record["obj"], new)
                record["cfg"] = new
                self.invalidate(record)
                dialog.destroy()
                self.refresh_selected()
                self.status.set("Pass settings applied and bound to this input fingerprint/acquisition identity.")
            except InputError as exc:
                messagebox.showerror("Pass settings", str(exc), parent=dialog)
        ttk.Button(panel, text="Apply pass settings", command=apply).pack(anchor="e", pady=(14, 0))

    def close(self):
        self.closed = True
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", help="Load an explicit saved session at startup")
    args = parser.parse_args()
    root = tk.Tk()
    app = App(root)
    if args.session:
        root.after(0, lambda: app.load_configuration(args.session))
    root.mainloop()


if __name__ == "__main__":
    main()

