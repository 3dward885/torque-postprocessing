"""Small presentation-export dialog; normalization never changes processing settings."""
import copy
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk
from io_profiles import InputError
from treated_plots import export_treated_plots, grouped_samples, suggested_rotation


class PlotExportDialog:
    def __init__(self, app):
        self.app = app
        self.source = "User-entered sample normalization"
        self.window = tk.Toplevel(app.root)
        self.window.title("Export treated plots")
        self.window.transient(app.root)
        self.window.grab_set()
        self.hover = app.help_for(self.window)
        frame = ttk.Frame(self.window, padding=14)
        frame.pack(fill="both", expand=True)
        self.quantity = tk.StringVar(value="Torque (N m)")
        self.method = tk.StringVar(value="Sample mass and molar mass")
        ttk.Label(frame, text="Plot quantity").grid(row=0, column=0, sticky="w")
        quantity = ttk.Combobox(frame, textvariable=self.quantity, state="readonly", width=30,
                               values=("Torque (N m)", "Molar torque (N m/mol)"))
        quantity.grid(row=0, column=1, columnspan=3, sticky="w", pady=4)
        self.hover.attach(quantity, "plot_quantity")
        self.method_label = ttk.Label(frame, text="Calculate amount from")
        self.method_label.grid(row=1, column=0, sticky="w")
        self.method_box = ttk.Combobox(frame, textvariable=self.method, state="readonly", width=30,
                                      values=("Sample mass and molar mass", "Amount in moles"))
        self.method_box.grid(row=1, column=1, columnspan=3, sticky="w", pady=4)
        self.hover.attach(self.method_box, "plot_normalization")
        self.rows, self.numeric = {}, []
        self.heading1, self.heading2 = ttk.Label(frame), ttk.Label(frame)
        ttk.Label(frame, text="File").grid(row=2, column=0, columnspan=2, sticky="w", pady=8)
        ttk.Label(frame, text="Rotation").grid(row=2, column=2, padx=5)
        self.heading1.grid(row=2, column=3, padx=5)
        self.heading2.grid(row=2, column=4, padx=5)
        for row_number, (key, record) in enumerate(app.records.items(), 3):
            ready = bool(record.get("result") and record["result"]["exportable"])
            identity = (record["path"], (record.get("cfg") or {}).get("input_sha256"))
            prior = app.plot_choices.get(identity, {})
            values = {name: tk.StringVar(value=prior.get(name, "")) for name in
                      ("rotation", "mass_mg", "molar_mass_g_mol", "amount_mol")}
            values["rotation"].set(prior.get("rotation", suggested_rotation(record["path"])))
            selected = tk.BooleanVar(value=ready)
            check = ttk.Checkbutton(frame, variable=selected, state="normal" if ready else "disabled")
            check.grid(row=row_number, column=0)
            label = Path(record["path"]).name + ("" if ready else " — process first")
            ttk.Label(frame, text=label).grid(row=row_number, column=1, sticky="w", padx=(0, 12))
            rotation = ttk.Entry(frame, textvariable=values["rotation"], width=7)
            rotation.grid(row=row_number, column=2, padx=5, pady=4)
            self.hover.attach(rotation, "plot_rotation")
            self.hover.attach(check, "plot_files")
            mass = ttk.Entry(frame, textvariable=values["mass_mg"], width=12)
            molar_mass = ttk.Entry(frame, textvariable=values["molar_mass_g_mol"], width=12)
            amount = ttk.Entry(frame, textvariable=values["amount_mol"], width=12)
            for widget, column in ((mass, 3), (molar_mass, 4), (amount, 3)):
                widget.grid(row=row_number, column=column, padx=5, pady=4)
                self.hover.attach(widget, "plot_normalization")
            self.numeric.append((mass, molar_mass, amount))
            self.rows[key] = (record, identity, selected, values)
        last = len(app.records) + 3
        self.note = ttk.Label(frame, text="Molar output also saves a separate molar DAT. The ordinary DAT stays in N m.")
        self.note.grid(row=last, column=0, columnspan=5, sticky="w", pady=(10, 0))
        self.error = tk.StringVar()
        ttk.Label(frame, textvariable=self.error, foreground="#a00000", wraplength=680).grid(
            row=last + 1, column=0, columnspan=5, sticky="w", pady=5)
        buttons = ttk.Frame(frame)
        buttons.grid(row=last + 2, column=0, columnspan=5, sticky="e")
        self.hover.attach(ttk.Button(buttons, text="Cancel", command=self.window.destroy), "settings_cancel").pack(side="left", padx=6)
        self.export_button = ttk.Button(buttons, text="Export…", command=self.export)
        self.export_button.pack(side="left")
        self.hover.attach(self.export_button, "export_treated_plots")
        quantity.bind("<<ComboboxSelected>>", self.update_fields)
        self.method_box.bind("<<ComboboxSelected>>", self.update_fields)
        self.update_fields()

    def update_fields(self, event=None):
        molar = self.quantity.get() == "Molar torque (N m/mol)"
        mass = self.method.get() == "Sample mass and molar mass"
        for widget in (self.method_label, self.method_box, self.heading1, self.note):
            widget.grid() if molar else widget.grid_remove()
        self.heading1.configure(text="Sample mass (mg)" if mass else "Amount (mol)")
        self.heading2.configure(text="Molar mass (g/mol)")
        self.heading2.grid() if molar and mass else self.heading2.grid_remove()
        for a, b, c in self.numeric:
            a.grid() if molar and mass else a.grid_remove()
            b.grid() if molar and mass else b.grid_remove()
            c.grid() if molar and not mass else c.grid_remove()

    def export(self, folder=None):
        try:
            entries = []
            for record, identity, selected, values in self.rows.values():
                if not selected.get():
                    continue
                choice = {name: value.get().strip() for name, value in values.items()}
                choice.update(quantity="molar" if self.quantity.get() == "Molar torque (N m/mol)" else "torque",
                              method="mass" if self.method.get() == "Sample mass and molar mass" else "amount",
                              source=self.source)
                grouped_samples(record["result"], choice)
                entries.append((copy.deepcopy(record["result"]), choice))
            if not entries:
                raise InputError("Select a processed file.")
            folder = folder or filedialog.askdirectory(parent=self.window, title="Save treated plots")
            if not folder:
                return
            for record, identity, selected, values in self.rows.values():
                if selected.get():
                    self.app.plot_choices[identity] = {name: value.get() for name, value in values.items()}
            self.window.destroy()
            self.app.submit("Saving treated plots…", lambda: export_treated_plots(entries, folder),
                            lambda path: self.app.status.set("Treated plots saved: " + path))
        except (ValueError, OSError) as exc:
            self.error.set(str(exc))
