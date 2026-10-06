"""Evidence and explicit decisions for complete acquired sweeps."""
import copy
from decimal import Decimal
import tkinter as tk
from tkinter import ttk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from baseline_editor import dispose_canvas
import field_quality


class FieldReviewDialog:
    def __init__(self, app, record, scan_id):
        self.app, self.record, self.scan_id = app, record, scan_id
        self.window = tk.Toplevel(app.root)
        self.window.title("Torque Data Postprocessing — Field review")
        self.window.transient(app.root)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.hover = app.help_for(self.window)
        panel = ttk.Frame(self.window, padding=12)
        panel.pack(fill="both", expand=True)
        review = record["obj"].field_review[scan_id]
        self.displayed_review = copy.deepcopy(review)
        e, policy = review["evidence"], review["policy"]
        self.message = tk.StringVar(value=f"{scan_id} — {review['status']}\nSource rows {e['source_lines'][0]}–{e['source_lines'][-1]} ({len(e['source_lines'])} measurements)\n"
            f"Measured field: {e['minimum_T']} to {e['maximum_T']} T; span {e['span_T']} T\n"
            f"Review span: {e['review_span_T']} T; limit: {policy['limit_T'] or 'not configured'} T; condition: {policy['condition']}\n"
            f"{review['reason']}\nRecorded field values are evidence from the instrument file, not independent magnet verification.")
        ttk.Label(panel, textvariable=self.message, wraplength=750).pack(fill="x")
        fig = Figure(figsize=(7, 2.4), dpi=100)
        ax = fig.add_subplot(111)
        ax.plot(range(1, len(e["source_lines"]) + 1), [float(Decimal(v) / 10000) for v in e["field_Oe_tokens"]], "o", markersize=3)
        ax.set(xlabel="Acquisition order within scan", ylabel="Measured field (T)")
        fig.tight_layout()
        self.canvas = FigureCanvasTkAgg(fig, master=panel)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.canvas.draw_idle()
        rows = ttk.Frame(panel)
        rows.pack(fill="both", expand=True)
        self.raw_text = tk.Text(rows, height=5, width=95, wrap="none")
        scroll = ttk.Scrollbar(rows, command=self.raw_text.yview)
        self.raw_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.raw_text.pack(fill="both", expand=True)
        scan = next(p for p in record["obj"].passes if p.id == scan_id)
        self.raw_text.insert("end", "Original source rows (unchanged)\n" + "\n".join(f"{r.line}: {r.source_text}" for r in scan.acquired_rows))
        self.raw_text.configure(state="disabled")
        ttk.Label(panel, text="Decision reason (required for exclusion or permission)").pack(anchor="w")
        self.reason = tk.StringVar()
        self.hover.attach(ttk.Entry(panel, textvariable=self.reason), "field_review").pack(fill="x")
        self.error = tk.StringVar()
        ttk.Label(panel, textvariable=self.error, foreground="#963a24").pack(fill="x")
        buttons = ttk.Frame(panel)
        buttons.pack(fill="x", pady=8)
        for label, action in [("Exclude entire scan", lambda: self.commit("exclude")),
                              ("Permit changing field", lambda: self.commit("permit_changing")),
                              ("Remove saved decision", self.remove), ("Close", self.close)]:
            self.hover.attach(ttk.Button(buttons, text=label, command=action), "field_review").pack(side="left", padx=3)
        ttk.Label(panel, text="To correct the file policy or limit, close this panel and open Acquisition settings.").pack(anchor="w")

    def commit(self, action):
        try:
            current = self.record["obj"].field_review.get(self.scan_id)
            if current != self.displayed_review:
                raise ValueError("Acquisition or policy changed. Close and reopen this review before deciding.")
            if not self.reason.get().strip():
                raise ValueError("Enter a reason. Closing this panel makes no decision.")
            cfg = field_quality.decide(self.record["raw"], self.record["cfg"], self.scan_id, action,
                                       "Explicit GUI field review: " + self.reason.get().strip())
            # Remove a legacy flag so the scoped decision is the only active decision.
            cfg["acquisition"]["scans"].get(self.scan_id, {}).pop("exclude", None)
            if self.app.apply_settings(self.record, cfg):
                self.close()
        except (ValueError, OSError) as exc:
            self.error.set(str(exc))

    def remove(self):
        cfg = copy.deepcopy(self.record["cfg"])
        cfg["field_quality"]["decisions"].pop(self.scan_id, None)
        cfg["acquisition"]["scans"].get(self.scan_id, {}).pop("exclude", None)
        if self.app.apply_settings(self.record, cfg):
            self.close()

    def close(self):
        self.hover.dismiss()
        dispose_canvas(self.canvas)
        self.window.destroy()
