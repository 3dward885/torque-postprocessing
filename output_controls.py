"""Compact per-file output controls; drafts never change scientific results."""
from copy import deepcopy
from decimal import Decimal
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from tkinter import filedialog

from io_profiles import InputError
from output_settings import accepted_output, validate_output
from treated_plots import normalization

METHODS = {"Sample mass and molar mass": "mass", "Amount in moles": "amount"}
EDITABLE = ("mass_mg", "molar_mass_g_mol", "amount_mol")


class OutputControls:
    def __init__(self, app, parent):
        self.app, self.record, self.dirty, self.loading = app, None, False, True
        self.frame = ttk.LabelFrame(parent, text="Output", padding=8)
        self.frame.pack(fill="x", pady=5)
        self.file_label = ttk.Label(self.frame, text="Output for: no file", wraplength=460)
        self.file_label.pack(anchor="w")
        self.quantity = tk.StringVar(value="torque")
        self.mode = "torque"
        row = ttk.Frame(self.frame)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="Quantity:").pack(side="left")
        self.radios = []
        for text, value in (("Torque (N m)", "torque"), ("Molar torque (N m/mol)", "molar")):
            b = ttk.Radiobutton(row, text=text, value=value, variable=self.quantity, command=self.choose_quantity)
            b.pack(side="left", padx=4)
            app.hover.attach(b, "output_quantity")
            self.radios.append(b)
        self.sample = ttk.Frame(self.frame)
        self.method = tk.StringVar(value="Sample mass and molar mass")
        ttk.Label(self.sample, text="Amount from:").grid(row=0, column=0, sticky="w")
        self.method_box = ttk.Combobox(self.sample, textvariable=self.method, values=tuple(METHODS),
                                      state="readonly", width=28)
        self.method_box.grid(row=0, column=1, sticky="w", pady=2)
        app.hover.attach(self.method_box, "output_amount")
        self.values, self.entries, self.labels = {}, {}, {}
        for index, (key, label) in enumerate((("mass_mg", "Sample mass (mg)"),
                ("molar_mass_g_mol", "Molar mass (g/mol)"), ("amount_mol", "Amount (mol)")), 1):
            self.values[key] = tk.StringVar()
            self.labels[key] = ttk.Label(self.sample, text=label)
            self.entries[key] = ttk.Entry(self.sample, textvariable=self.values[key], width=28)
            self.labels[key].grid(row=index, column=0, sticky="w", padx=(0, 7), pady=2)
            self.entries[key].grid(row=index, column=1, sticky="w", pady=2)
            app.hover.attach(self.entries[key], "output_amount")
            app.hover.attach(self.labels[key], "output_amount")
            self.values[key].trace_add("write", self.edited)
        self.amount = tk.StringVar(value="Calculated amount: — mol")
        ttk.Label(self.sample, textvariable=self.amount).grid(row=4, column=0, columnspan=2, sticky="w")
        actions = ttk.Frame(self.sample)
        actions.grid(row=5, column=0, columnspan=2, sticky="e", pady=3)
        self.apply_button = ttk.Button(actions, text="Apply", command=self.apply)
        self.apply_button.pack(side="left", padx=3)
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self.cancel)
        self.cancel_button.pack(side="left")
        app.hover.attach(self.apply_button, "output_apply")
        app.hover.attach(self.cancel_button, "output_cancel")
        self.note = tk.StringVar()
        ttk.Label(self.frame, textvariable=self.note, wraplength=440).pack(anchor="w", pady=2)
        self.saving = tk.StringVar()
        ttk.Label(self.frame, textvariable=self.saving).pack(anchor="w")
        save = ttk.Frame(self.frame)
        save.pack(fill="x", pady=3)
        self.save_button = ttk.Button(save, text="Save torque data…", command=app.export_all)
        self.save_button.pack(side="left", padx=(0, 5))
        self.plots_button = ttk.Button(save, text="Save torque plots…", command=app.export_plots)
        self.plots_button.pack(side="left")
        app.hover.attach(self.save_button, "save_dat", text=self.save_help)
        app.hover.attach(self.plots_button, "export_treated_plots", text=self.save_help)
        self.method.trace_add("write", self.edited)
        self.loading = False
        self.refresh()

    def save_help(self):
        return (self.note.get() + " " if self.note.get() else "") + (
            "Save both ordinary N m and separate N m/mol data, or grouped JPEGs in N m/mol."
            if self.mode == "molar" else "Save treated N m data or grouped JPEGs. Requires complete valid processing.")

    def gather(self):
        block = deepcopy(self.record["output"])
        block.update(quantity=self.quantity.get(), method=METHODS.get(self.method.get(), ""))
        block.update({k: v.get().strip() for k, v in self.values.items()})
        return block

    def bind_record(self, record, force=False):
        if self.record is record and not force:
            return
        self.loading = True
        self.record = record
        block = record["output"] if record else {"quantity": "torque", "method": "mass"}
        self.quantity.set(block["quantity"])
        self.mode = block["quantity"]
        self.method.set(next(k for k, v in METHODS.items() if v == block["method"]))
        for k, v in self.values.items():
            v.set(block.get(k, ""))
        self.file_label.configure(text="Output for: " + (Path(record["path"]).name if record else "no file"))
        self.dirty = False
        self.note.set("")
        self.loading = False
        self.refresh()

    def edited(self, *args):
        if self.loading or not self.record:
            return
        block = self.gather()
        keys = (*EDITABLE, "quantity", "method")
        self.dirty = any(block[k] != self.record["output"][k] for k in keys)
        self.refresh()
        self.app.select_pass()

    def choose_quantity(self):
        if not self.record or self.app.busy:
            self.quantity.set(self.mode)
            return
        if self.dirty or not self.app.guard_baseline(close=True):
            self.quantity.set(self.mode)
            self.note.set("Apply or cancel sample changes.")
            return
        self.mode = self.quantity.get()
        block = self.gather()
        try:
            block = validate_output(block, self.record["cfg"]["input_sha256"])
        except InputError:
            self.dirty = True
        else:
            self.record["output"] = block
            self.record["saved"] = None
        self.refresh()
        self.app.select_pass()

    def require_clean(self):
        if self.dirty:
            self.note.set("Apply or cancel sample changes.")
            return False
        return True

    def apply(self):
        if not self.record or self.app.busy:
            return
        try:
            block = accepted_output(self.gather(), self.record["cfg"]["input_sha256"], self.record.get("result"))
        except (ValueError, OSError) as exc:
            self.note.set(str(exc))
            return
        self.record.update(output=block, saved=None)
        self.bind_record(self.record, force=True)
        self.app.select_pass()
        self.app.refresh_buttons()

    def cancel(self):
        if self.app.busy:
            return
        self.bind_record(self.record, force=True)
        self.app.select_pass()
        self.app.refresh_buttons()

    def refresh(self):
        ready_file = bool(self.record and self.record.get("cfg"))
        enabled = ready_file and not self.app.busy
        for b in self.radios:
            b.configure(state="normal" if enabled else "disabled")
        molar = self.mode == "molar"
        if molar:
            self.sample.pack(fill="x", before=self.frame.winfo_children()[3])
        else:
            self.sample.pack_forget()
        method = METHODS.get(self.method.get(), "mass")
        for k in EDITABLE:
            visible = (k == "amount_mol") == (method == "amount")
            for w in (self.labels[k], self.entries[k]):
                w.grid() if visible else w.grid_remove()
            self.entries[k].configure(state="normal" if enabled else "disabled")
        self.method_box.configure(state="readonly" if enabled else "disabled")
        self.apply_button.configure(state="normal" if enabled and self.dirty else "disabled")
        self.cancel_button.configure(state="normal" if enabled and self.dirty else "disabled")
        error = ""
        if molar and ready_file:
            try:
                n = normalization(self.gather())
                self.amount.set(f"Calculated amount: {Decimal(n['derived_amount_mol']):.6E} mol")
            except (ValueError, ArithmeticError) as exc:
                self.amount.set("Calculated amount: — mol")
                error = str(exc)
        if self.dirty:
            self.note.set(error or "Apply or cancel sample changes.")
        else:
            self.note.set("A task is running." if self.app.busy else (
                "" if self.record and self.record.get("result") and self.record["result"]["exportable"]
                else "Subtract background and resolve pending scans before saving."))
        ready = enabled and not self.dirty and self.record.get("result") and self.record["result"]["exportable"]
        self.save_button.configure(text="Save both data files…" if molar else "Save torque data…",
                                   state="normal" if ready else "disabled")
        self.plots_button.configure(text="Save molar plots…" if molar else "Save torque plots…",
                                    state="normal" if ready else "disabled")
        self.saving.set("Data: N m + N m/mol     Plots: N m/mol" if molar else "")
        if hasattr(self.app, "file_menu"):
            self.app.file_menu.entryconfigure(1, label=self.save_button.cget("text"))


class MolarSaveDialog:
    """Show both final paths before publishing a paired data export."""
    def __init__(self, app, record):
        self.app, self.record = app, record
        self.window = tk.Toplevel(app.root)
        self.window.title("Save both data files")
        self.window.transient(app.root)
        self.window.grab_set()
        self.hover = app.help_for(self.window)
        frame = ttk.Frame(self.window, padding=14)
        frame.pack(fill="both", expand=True)
        self.path = tk.StringVar(value=str(Path(record["path"]).with_name(Path(record["path"]).stem + "_treated.dat")))
        ttk.Label(frame, text="Torque data (N m)").pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(fill="x")
        entry = ttk.Entry(row, textvariable=self.path, width=85)
        entry.pack(side="left", fill="x", expand=True)
        self.hover.attach(entry, "output_save_paths")
        self.hover.attach(ttk.Button(row, text="Browse...", command=self.browse), "output_save_paths").pack(side="left", padx=5)
        self.companion = tk.StringVar()
        ttk.Label(frame, textvariable=self.companion, wraplength=720).pack(anchor="w", pady=7)
        self.error = tk.StringVar()
        ttk.Label(frame, textvariable=self.error, foreground="#a00000", wraplength=720).pack(anchor="w")
        buttons = ttk.Frame(frame)
        buttons.pack(anchor="e", pady=4)
        self.hover.attach(ttk.Button(buttons, text="Cancel", command=self.window.destroy), "settings_cancel").pack(side="left")
        self.save_button = ttk.Button(buttons, text="Save both data files", command=self.save)
        self.save_button.pack(side="left", padx=5)
        self.hover.attach(self.save_button, "save_dat")
        self.path.trace_add("write", self.update_paths)
        self.update_paths()

    def update_paths(self, *args):
        from output_settings import output_paths
        try:
            paths = output_paths(self.path.get(), self.record["output"])
            self.companion.set("Molar data (N m/mol): " + str(paths[1]))
            self.error.set("")
            self.save_button.configure(state="normal")
        except ValueError as exc:
            self.error.set(str(exc))
            self.save_button.configure(state="disabled")

    def browse(self):
        value = filedialog.asksaveasfilename(parent=self.window, title="Choose torque data filename (N m)",
            initialfile=Path(self.path.get()).name, defaultextension=".dat", filetypes=[("DAT", "*.dat")])
        if value:
            self.path.set(value)

    def save(self):
        self.app.export_all(self.path.get())
        if self.app.busy:
            self.window.destroy()
