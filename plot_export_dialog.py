"""Grouped plot selection uses the main window's committed output settings."""
import copy
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk
from io_profiles import InputError
from treated_plots import export_treated_plots, grouped_samples, normalization
from output_settings import validate_output


class PlotExportDialog:
    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title("Save treated plots")
        self.window.transient(app.root)
        self.window.grab_set()
        self.hover = app.help_for(self.window)
        frame = ttk.Frame(self.window, padding=14)
        frame.pack(fill="both", expand=True)
        for i, title in enumerate(("File", "Rotation", "Quantity", "Amount (mol)")):
            ttk.Label(frame, text=title).grid(row=0, column=i+1, sticky="w", padx=6)
        self.rows = {}
        for row, (key, record) in enumerate(app.records.items(), 1):
            ready = bool(record.get("result") and record["result"]["exportable"])
            choice = record["output"]
            norm = normalization(choice)
            selected = tk.BooleanVar(value=ready and record is app.selected())
            rotation = tk.StringVar(value=choice["rotation"])
            check = ttk.Checkbutton(frame, variable=selected, state="normal" if ready else "disabled")
            check.grid(row=row, column=0)
            app.hover.attach(check, "plot_files")
            ttk.Label(frame, text=Path(record["path"]).name + ("" if ready else " - process first")).grid(
                row=row, column=1, sticky="w", padx=6)
            entry = ttk.Entry(frame, textvariable=rotation, width=7)
            entry.grid(row=row, column=2, padx=6)
            app.hover.attach(entry, "plot_rotation")
            ttk.Label(frame, text=norm["units"]).grid(row=row, column=3, padx=6)
            ttk.Label(frame, text=norm.get("derived_amount_mol", "-")).grid(row=row, column=4, padx=6)
            self.rows[key] = record, selected, rotation
        self.error = tk.StringVar()
        ttk.Label(frame, text="Quantity and sample amount are set in the main Output section.").grid(
            row=len(self.rows)+1, column=0, columnspan=5, sticky="w", pady=8)
        ttk.Label(frame, textvariable=self.error, foreground="#a00000", wraplength=680).grid(
            row=len(self.rows)+2, column=0, columnspan=5, sticky="w")
        buttons = ttk.Frame(frame)
        buttons.grid(row=len(self.rows)+3, column=0, columnspan=5, sticky="e", pady=6)
        self.hover.attach(ttk.Button(buttons, text="Cancel", command=self.window.destroy), "settings_cancel").pack(side="left")
        self.export_button = ttk.Button(buttons, text="Save plots...", command=self.export)
        self.export_button.pack(side="left", padx=6)
        self.hover.attach(self.export_button, "export_treated_plots")

    def export(self, folder=None):
        try:
            entries, updates = [], []
            for record, selected, rotation in self.rows.values():
                if not selected.get():
                    continue
                choice = {**record["output"], "rotation": rotation.get().strip()}
                choice = validate_output(choice, record["cfg"]["input_sha256"])
                grouped_samples(record["result"], choice)
                entries.append((copy.deepcopy(record["result"]), choice))
                updates.append((record, choice))
            if not entries:
                raise InputError("Select a processed file.")
            folder = folder or filedialog.askdirectory(parent=self.window, title="Save treated plots")
            if not folder:
                return
            def done(path):
                for record, choice in updates:
                    record["output"] = choice
                self.app.status.set("Treated plots saved: " + path)
            self.window.destroy()
            self.app.submit("Saving treated plots...", lambda: export_treated_plots(entries, folder), done)
        except (ValueError, OSError) as exc:
            self.error.set(str(exc))
